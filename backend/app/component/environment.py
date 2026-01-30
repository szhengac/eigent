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

import logging
import importlib.util
import os
from pathlib import Path
from fastapi import APIRouter, FastAPI
import importlib
from typing import Any, overload

logger = logging.getLogger("env")

"""
Environment helpers.

IMPORTANT:
- This backend is intended to run as a multi-user server process.
- Requests MUST NOT be able to mutate process-wide environment variables or load
  arbitrary user-provided .env files.

Configuration should be provided via process environment variables (preferred),
 or an operator-provided env file specified by `EIGENT_SERVER_ENV_PATH`.
"""



@overload
def env(key: str) -> str | None: ...


@overload
def env(key: str, default: str) -> str: ...


@overload
def env(key: str, default: Any) -> Any: ...


def env(key: str, default=None):
    """
    Get environment variable.
    Server mode: reads process environment only.
    """
    value = os.getenv(key, default)
    return value


def env_or_fail(key: str):
    value = env(key)
    if value is None:
        logger.warning(f"[ENVIRONMENT] can't get env config value for key: {key}")
        raise Exception(f"can't get env config value for key: {key}")
    return value

def env_not_empty(key: str):
    value = env(key)
    if not value:
        logger.warning(f"[ENVIRONMENT] env config value can't be empty for key: {key}")
        raise Exception(f"env config value can't be empty for key: {key}")
    return value


def base_path():
    return Path(__file__).parent.parent.parent


def to_path(path: str):
    return base_path() / path


def auto_import(package: str):
    """
    Automatically import all Python files in the specified directory
    """
    # Get all file names in the folder
    folder = package.replace(".", "/")
    files = os.listdir(folder)

    # Import all .py files in the folder
    for file in files:
        if file.endswith(".py") and not file.startswith("__"):
            module_name = file[:-3]  # Remove the .py extension from filename
            importlib.import_module(package + "." + module_name)


def auto_include_routers(api: FastAPI, prefix: str, directory: str):
    """
    Automatically scan all modules in the specified directory and register routes

    :param api: FastAPI instance
    :param prefix: Route prefix
    :param directory: Directory path to scan
    """
    # Convert directory to absolute path
    dir_path = Path(directory).resolve()

    # Traverse all .py files in the directory
    for root, _, files in os.walk(dir_path):
        for file_name in files:
            if file_name.endswith("_controller.py") and not file_name.startswith("__"):
                # Construct complete file path
                file_path = Path(root) / file_name

                # Generate module name
                module_name = file_path.stem

                # Load module using importlib
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Check if router attribute exists in module and is an APIRouter instance
                router = getattr(module, "router", None)
                if isinstance(router, APIRouter):
                    api.include_router(router, prefix=prefix)
