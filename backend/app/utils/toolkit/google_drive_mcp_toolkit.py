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

from camel.toolkits import GoogleDriveMCPToolkit as BaseGoogleDriveMCPToolkit, MCPToolkit
from app.component.command import bun
from app.service.task import Agents, get_task_lock_if_exists
from app.utils.toolkit.abstract_toolkit import AbstractToolkit
from camel.toolkits.function_tool import FunctionTool


class GoogleDriveMCPToolkit(BaseGoogleDriveMCPToolkit, AbstractToolkit):
    agent_name: str = Agents.document_agent

    def __init__(
        self,
        api_task_id: str,
        timeout: float | None = None,
        credentials_path: str | None = None,
        tokens_path: str | None = None,
        input_env: dict[str, str] | None = None,
    ) -> None:
        self.api_task_id = api_task_id
        super().__init__(timeout, credentials_path)
        self._mcp_toolkit = MCPToolkit(
            config_dict={
                "mcpServers": {
                    "gdrive": {
                        "command": bun(),
                        "args": ["x", "-y", "@piotr-agier/google-drive-mcp"],
                        "env": {
                            "GOOGLE_DRIVE_OAUTH_CREDENTIALS": credentials_path or "",
                            "GOOGLE_DRIVE_MCP_TOKEN_PATH": tokens_path or "",
                            **(input_env or {}),
                        },
                    }
                }
            },
            timeout=timeout,
        )

    @classmethod
    async def get_can_use_tools(cls, api_task_id: str, input_env: dict[str, str] | None = None) -> list[FunctionTool]:
        # Credentials from Chat.creds_params["google_drive"]: user sends "credentials" and "token" (both base64); we save to project path.
        from app.utils.extra_params_config import get_unified, write_content_to_project

        task_lock = get_task_lock_if_exists(api_task_id)
        if not task_lock:
            return []
        gdrive = (getattr(task_lock, "creds_params", None) or {}).get("google_drive") or {}
        credentials_b64 = get_unified(gdrive, "credentials")
        tokens_b64 = get_unified(gdrive, "tokens")
        if not credentials_b64 or not tokens_b64:
            return []
        credentials_path = write_content_to_project(
            api_task_id, "google_drive", credentials_b64, filename_suffix="credentials.json"
        )
        tokens_path = write_content_to_project(
            api_task_id, "google_drive", tokens_b64, filename_suffix="tokens.json"
        )
        toolkit = cls(
            api_task_id,
            timeout=180,
            credentials_path=credentials_path,
            tokens_path=tokens_path,
            input_env=input_env,
        )
        await toolkit.connect()
        tools = []
        for item in toolkit.get_tools():
            setattr(item, "_toolkit_name", cls.__name__)
            tools.append(item)
        return tools
