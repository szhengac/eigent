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

from typing import Literal
from camel.toolkits import GithubToolkit as BaseGithubToolkit
from camel.toolkits.function_tool import FunctionTool
from app.service.task import Agents, get_task_lock_if_exists
from app.utils.listen.toolkit_listen import auto_listen_toolkit
from app.utils.toolkit.abstract_toolkit import AbstractToolkit


@auto_listen_toolkit(BaseGithubToolkit)
class GithubToolkit(BaseGithubToolkit, AbstractToolkit):
    agent_name: str = Agents.developer_agent

    def __init__(
        self,
        api_task_id: str,
        access_token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(access_token, timeout)
        self.api_task_id = api_task_id

    @classmethod
    def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        # Credentials from Chat.extra_params["github"] (unified: access_token).
        from app.utils.extra_params_config import get_unified
        task_lock = get_task_lock_if_exists(api_task_id)
        if not task_lock:
            return []
        github = (getattr(task_lock, "extra_params", None) or {}).get("github") or {}
        token = get_unified(github, "access_token", "GITHUB_ACCESS_TOKEN")
        if not token:
            return []
        return GithubToolkit(api_task_id, access_token=token).get_tools()
