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

from typing import Any, Dict, List
from camel.toolkits import RedditToolkit as BaseRedditToolkit
from camel.toolkits.function_tool import FunctionTool
from app.service.task import Agents, get_task_lock_if_exists
from app.utils.listen.toolkit_listen import auto_listen_toolkit
from app.utils.toolkit.abstract_toolkit import AbstractToolkit


@auto_listen_toolkit(BaseRedditToolkit)
class RedditToolkit(BaseRedditToolkit, AbstractToolkit):
    agent_name: str = Agents.social_medium_agent

    def __init__(
        self,
        api_task_id: str,
        retries: int = 3,
        delay: float = 0,
        timeout: float | None = None,
    ):
        super().__init__(retries, delay, timeout)
        self.api_task_id = api_task_id

    @classmethod
    def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        # Credentials from Chat.creds_params["reddit"] (unified: client_id, client_secret, user_agent).
        from app.utils.extra_params_config import get_unified
        task_lock = get_task_lock_if_exists(api_task_id)
        if not task_lock:
            return []
        reddit = (getattr(task_lock, "creds_params", None) or {}).get("reddit") or {}
        if (
            get_unified(reddit, "client_id", "REDDIT_CLIENT_ID")
            and get_unified(reddit, "client_secret", "REDDIT_CLIENT_SECRET")
            and get_unified(reddit, "user_agent", "REDDIT_USER_AGENT")
        ):
            return RedditToolkit(api_task_id).get_tools()
        return []
