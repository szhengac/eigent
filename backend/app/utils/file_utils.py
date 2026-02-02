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

"""File system utilities."""

import base64
import os
import subprocess

from app.model.chat import Chat

# Max size for including file content as base64 (10 MiB)
DEFAULT_MAX_FILE_SIZE_FOR_BASE64 = 10 * 1024 * 1024


def _is_hidden_path(rel_path: str) -> bool:
    """True if the path contains any hidden segment (name starting with '.')."""
    parts = rel_path.replace("\\", "/").split("/")
    return any(p.startswith(".") for p in parts if p)


def get_working_directory(options: Chat, task_lock=None) -> str:
    """
    Get the correct working directory for file operations.
    First checks if there's an updated path from improve API call,
    then falls back to environment variable or default path.
    """
    if not task_lock:
        from app.service.task import get_task_lock_if_exists
        task_lock = get_task_lock_if_exists(options.project_id)
    
    if task_lock and hasattr(task_lock, 'new_folder_path') and task_lock.new_folder_path:
        return str(task_lock.new_folder_path)
    else:
        # Server mode: working directory is derived from server-owned data dir.
        return options.file_save_path()


def get_working_directory_from_task_lock(task_lock) -> str | None:
    """
    Get the working directory from task_lock when Chat/options is not available.
    Returns None if task_lock has no path information.
    """
    if not task_lock:
        return None
    if hasattr(task_lock, 'new_folder_path') and task_lock.new_folder_path:
        return str(task_lock.new_folder_path)
    if hasattr(task_lock, 'file_save_path') and task_lock.file_save_path:
        return str(task_lock.file_save_path)
    return None


def get_changed_files(
    working_directory: str,
    since_timestamp: float | None = None,
) -> list[str]:
    """
    Get new or changed files in the working directory.

    - If the directory is a git repo: uses git status (since_timestamp ignored).
    - If not a git repo and since_timestamp is given: returns files with
      mtime >= since_timestamp (relative to working_directory).
    - If not a git repo and since_timestamp is None: returns [].

    Returns a list of relative paths (relative to working_directory).
    """
    if not working_directory or not os.path.isdir(working_directory):
        return []

    working_dir_abs = os.path.abspath(working_directory)
    relative_paths: list[str] = []

    # Try git first
    try:
        root_result = subprocess.run(
            ["git", "-C", working_directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if root_result.returncode == 0:
            git_root = root_result.stdout.strip()
            status_result = subprocess.run(
                ["git", "-C", working_directory, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if status_result.returncode == 0:
                for line in status_result.stdout.strip().splitlines():
                    if not line or len(line) < 4:
                        continue
                    status = line[:2]
                    path_part = line[3:].strip()
                    if " -> " in path_part:
                        path_part = path_part.split(" -> ")[-1].strip()
                    if status[0] in "MADRC" or status[1] in "MADRC" or status == "??":
                        full_path = os.path.normpath(
                            os.path.join(git_root, path_part)
                        )
                        if os.path.exists(full_path) and os.path.isfile(
                            full_path
                        ):
                            try:
                                rel = os.path.relpath(
                                    os.path.abspath(full_path),
                                    working_dir_abs,
                                )
                                if not rel.startswith("..") and not _is_hidden_path(
                                    rel
                                ):
                                    relative_paths.append(rel)
                            except ValueError:
                                pass
                return sorted(set(relative_paths))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Not a git repo (or git failed): use mtime if since_timestamp given
    if since_timestamp is None:
        return []

    for root, dirs, files in os.walk(working_directory):
        # Skip hidden directories (do not descend into them)
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        root_abs = os.path.abspath(root)
        for name in files:
            if name.startswith("."):
                continue
            full_path = os.path.join(root_abs, name)
            try:
                if not os.path.isfile(full_path):
                    continue
                if os.path.getmtime(full_path) >= since_timestamp:
                    rel = os.path.relpath(full_path, working_dir_abs)
                    if not rel.startswith("..") and not _is_hidden_path(rel):
                        relative_paths.append(rel)
            except OSError:
                continue
    return sorted(set(relative_paths))


def get_changed_file_entries(
    working_directory: str,
    since_timestamp: float | None = None,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE_FOR_BASE64,
) -> list[dict[str, str]]:
    """
    Get new or changed files with base64-encoded content.

    Returns a list of dicts: [{"path": "<relative_path>", "content_base64": "<base64>"}, ...].
    Path is relative to working_directory. content_base64 is empty string if the file
    is over max_file_size or cannot be read (binary/skip).
    """
    paths = get_changed_files(working_directory, since_timestamp)
    if not paths:
        return []

    working_dir_abs = os.path.abspath(working_directory)
    result: list[dict[str, str]] = []

    for rel_path in paths:
        full_path = os.path.normpath(os.path.join(working_dir_abs, rel_path))
        if not full_path.startswith(working_dir_abs):
            continue
        if not os.path.isfile(full_path):
            continue
        try:
            size = os.path.getsize(full_path)
            if size > max_file_size:
                result.append({"path": rel_path, "content_base64": ""})
                continue
            with open(full_path, "rb") as f:
                raw = f.read()
            result.append(
                {
                    "path": rel_path,
                    "content_base64": base64.b64encode(raw).decode("ascii"),
                }
            )
        except OSError:
            result.append({"path": rel_path, "content_base64": ""})

    return result