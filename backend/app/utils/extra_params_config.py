# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""
Unified extra_params key names and mapping to env vars for toolkits.

Clients send credentials in Chat.extra_params with unified names, e.g.:
  extra_params["twitter"] = {"access_token": "...", "access_token_secret": "...", "consumer_key": "...", "consumer_secret": "..."}
  extra_params["linkedin"] = {"access_token": "..."}

For tools that need a credentials/token file path (e.g. google_gmail, google_drive), the user
serializes the file content into base64 and sends "credentials" (and "token" for Drive); we decode and save to
the project path (from Chat.file_save_path) and pass that path to the tool.
"""

from pathlib import Path
from typing import Any
import base64
import logging
import shutil
import zipfile
import io

from app.service.task import get_task_lock_if_exists

logger = logging.getLogger("main")

# Map: tool key in extra_params -> { unified_key -> env_var_name }
# Base toolkits read these env vars; we set them from extra_params at call time.
UNIFIED_TO_ENV: dict[str, dict[str, str]] = {
    "twitter": {
        "access_token": "TWITTER_ACCESS_TOKEN",
        "access_token_secret": "TWITTER_ACCESS_TOKEN_SECRET",
        "consumer_key": "TWITTER_CONSUMER_KEY",
        "consumer_secret": "TWITTER_CONSUMER_SECRET",
    },
    "linkedin": {
        "access_token": "LINKEDIN_ACCESS_TOKEN",
    },
    "slack": {
        "bot_token": "SLACK_BOT_TOKEN",
        "user_token": "SLACK_USER_TOKEN",
    },
    "reddit": {
        "client_id": "REDDIT_CLIENT_ID",
        "client_secret": "REDDIT_CLIENT_SECRET",
        "user_agent": "REDDIT_USER_AGENT",
    },
    "whatsapp": {
        "access_token": "WHATSAPP_ACCESS_TOKEN",
        "phone_number_id": "WHATSAPP_PHONE_NUMBER_ID",
    },
    "lark": {
        "app_id": "LARK_APP_ID",
        "app_secret": "LARK_APP_SECRET",
    },
}


def extra_params_to_env(extra_params: dict[str, Any] | None) -> dict[str, str]:
    """
    Convert extra_params (unified keys per tool) into a flat env var dict.
    Used to inject into os.environ during tool execution so base toolkits see credentials.
    """
    if not extra_params:
        return {}
    result: dict[str, str] = {}
    for tool_key, mapping in UNIFIED_TO_ENV.items():
        params = extra_params.get(tool_key)
        if not isinstance(params, dict):
            continue
        for unified_key, env_var in mapping.items():
            val = params.get(unified_key)
            if val is not None and str(val).strip():
                result[env_var] = str(val)
    return result


def get_unified(params: dict[str, Any], *keys: str) -> str | None:
    """Get first present value for unified or legacy key names. keys can be (unified_key, legacy_env_name)."""
    for k in keys:
        v = params.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return None


def _get_project_save_path(api_task_id: str) -> Path:
    """Project path from Chat.file_save_path (stored on task_lock when chat starts)."""
    task_lock = get_task_lock_if_exists(api_task_id)
    if not task_lock:
        raise ValueError("Task lock not available; cannot write credentials.")
    path = getattr(task_lock, "file_save_path", None)
    if not path:
        raise ValueError("Task lock has no file_save_path (from Chat.file_save_path); cannot write credentials.")
    return Path(path)


def write_content_to_project(
    api_task_id: str,
    tool_name: str,
    content_base64: str,
    filename_suffix: str = "credentials.json",
) -> str:
    """
    Decode base64-encoded file content and save to the project path (from Chat.file_save_path).
    User sends base64 string under key "credentials" or "token"; we decode and write to
    {project_path}/.eigent_credentials/{tool_name}_{filename_suffix}.
    """
    base_path = _get_project_save_path(api_task_id)
    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception as e:
        raise ValueError(f"Invalid base64 content: {e}") from e
    cred_dir = base_path / ".eigent_credentials"
    cred_dir.mkdir(parents=True, exist_ok=True)
    path = cred_dir / f"{tool_name}_{filename_suffix}"
    path.write_bytes(content)
    logger.debug("Wrote content to project dir", extra={"path": str(path), "tool": tool_name})
    return str(path)


def write_config_folder_to_project(api_task_id: str, tool_name: str, config_base64: str) -> str:
    """
    Decode base64-encoded zip of a folder and extract to project path (from Chat.file_save_path).
    User zips the entire config folder, base64-encodes it, and sends under key "config";
    we decode, unzip to {project_path}/.eigent_credentials/{tool_name}_config/, return that dir path.
    """
    base_path = _get_project_save_path(api_task_id)
    try:
        zip_bytes = base64.b64decode(config_base64, validate=True)
    except Exception as e:
        raise ValueError(f"Invalid base64 config: {e}") from e
    cred_dir = base_path / ".eigent_credentials"
    cred_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = cred_dir / f"{tool_name}_config"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            zf.extractall(extract_dir)
    except Exception as e:
        raise ValueError(f"Invalid zip config: {e}") from e
    logger.debug("Extracted config folder to project dir", extra={"path": str(extract_dir), "tool": tool_name})
    return str(extract_dir)


def cleanup_project_credentials(api_task_id: str) -> None:
    """Remove .eigent_credentials directory for the project. Call when chat/task ends."""
    task_lock = get_task_lock_if_exists(api_task_id)
    if not task_lock:
        return
    path = getattr(task_lock, "file_save_path", None)
    if not path:
        return
    cred_dir = Path(path) / ".eigent_credentials"
    if not cred_dir.is_dir():
        return
    try:
        shutil.rmtree(cred_dir)
        logger.debug("Cleaned up project credentials", extra={"project_id": api_task_id})
    except OSError as e:
        logger.warning("Failed to cleanup project credentials dir: %s", e)
