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
Unified creds_params key names and mapping to env vars for toolkits.

Credentials and tokens come from Chat.creds_params (not extra_params), e.g.:
  creds_params["twitter"] = {"access_token": "...", "access_token_secret": "...", "consumer_key": "...", "consumer_secret": "..."}
  creds_params["google_gmail"] = {"credentials": "<base64>"}

extra_params_to_env(creds_params) builds env vars for base toolkits that read from os.environ.
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

# Map: tool key in creds_params -> { unified_key -> env_var_name }
# Base toolkits read these env vars; we set them from creds_params at call time.
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
