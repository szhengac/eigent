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

from camel.toolkits import BaseToolkit, FunctionTool, MCPToolkit
from app.component.command import bun
from app.service.task import Agents, get_task_lock_if_exists
from app.utils.toolkit.abstract_toolkit import AbstractToolkit


class GoogleGmailMCPToolkit(BaseToolkit, AbstractToolkit):
    agent_name: str = Agents.social_medium_agent

    def __init__(
        self,
        api_task_id: str,
        credentials_path: str | None = None,
        timeout: float | None = None,
        input_env: dict[str, str] | None = None,
    ):
        super().__init__(timeout)
        self.api_task_id = api_task_id
        self._mcp_toolkit = MCPToolkit(
            config_dict={
                "mcpServers": {
                    "gmail": {
                        "command": bun(),
                        "args": ["x", "-y", "@gongrzhe/server-gmail-autoauth-mcp"],
                        "env": {"GMAIL_CREDENTIALS_PATH": credentials_path or "", **(input_env or {})},
                    }
                }
            },
            timeout=timeout,
        )

    async def connect(self):
        await self._mcp_toolkit.connect()

    async def disconnect(self):
        await self._mcp_toolkit.disconnect()

    def get_tools(self) -> list[FunctionTool]:
        return self._mcp_toolkit.get_tools()

    @classmethod
    async def get_can_use_tools(cls, api_task_id: str, input_env: dict[str, str] | None = None) -> list[FunctionTool]:
        # Credentials from Chat.creds_params["google_gmail"]: user sends "credentials" (base64); we save to project path.
        from app.utils.extra_params_config import get_unified, write_content_to_project
        task_lock = get_task_lock_if_exists(api_task_id)
        if not task_lock:
            return []
        gmail = (getattr(task_lock, "creds_params", None) or {}).get("google_gmail") or {}
        credentials_b64 = get_unified(gmail, "credentials")
        if not credentials_b64:
            return []
        credentials_path = write_content_to_project(
            api_task_id, "google_gmail", credentials_b64, filename_suffix="credentials.json"
        )
        toolkit = cls(api_task_id, credentials_path=credentials_path, timeout=180, input_env=input_env)
        await toolkit.connect()
        tools = []
        for item in toolkit.get_tools():
            setattr(item, "_toolkit_name", cls.__name__)
            tools.append(item)
        return tools
