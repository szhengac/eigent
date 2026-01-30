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

import os
import json
import asyncio
from textwrap import indent
from typing import Any, Dict, List
from camel.toolkits import FunctionTool
from app.service.task import get_task_lock_if_exists
from app.utils.toolkit.abstract_toolkit import AbstractToolkit
from camel.toolkits.mcp_toolkit import MCPToolkit
import logging

logger = logging.getLogger("notion_mcp_toolkit")

def _customize_function_parameters(schema: Dict[str, Any]) -> None:
        r"""Customize function parameters for specific functions.

        This method allows modifying parameter descriptions or other schema
        attributes for specific functions.
        """
        function_info = schema.get("function", {})
        function_name = function_info.get("name", "")
        parameters = function_info.get("parameters", {})
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        
        help_description = "If you need use parent, you can use `notion-search` for the information"
        # Modify the notion-create-pages function to make parent optional
        if function_name == "notion-create-pages" or function_name == "notion-create-database":
            required.remove("parent")
            parameters["required"] = required
            if "parent" in properties:
                # Update the parent parameter description
                properties["parent"]["description"] = "Optional. " + properties["parent"]["description"] + help_description

class NotionMCPToolkit(MCPToolkit, AbstractToolkit):

    def __init__(
        self,
        api_task_id: str,
        timeout: float | None = None,
        mcp_remote_config_dir: str | None = None,
    ):
        self.api_task_id = api_task_id
        if timeout is None:
            timeout = 120.0
        # Credentials/config only from Chat.extra_params["notion_mcp"] or default path (no env).
        config_dir = mcp_remote_config_dir or os.path.expanduser("~/.mcp-auth")
        config_dict={
            "mcpServers": {
                "notionMCP": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "mcp-remote",
                        "https://mcp.notion.com/mcp",
                    ],
                    "env": {
                        "MCP_REMOTE_CONFIG_DIR": config_dir,
                    },
                }
            }
        }
        super().__init__(config_dict=config_dict, timeout=timeout)    

    @classmethod
    async def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        # Config from Chat.extra_params["notion_mcp"]: user sends "config" (base64 of zipped entire folder); we unzip to project path and pass dir.
        from app.utils.extra_params_config import get_unified, write_config_folder_to_project
        task_lock = get_task_lock_if_exists(api_task_id)
        if not task_lock:
            return []
        notion_mcp = (getattr(task_lock, "extra_params", None) or {}).get("notion_mcp") or {}
        config_b64 = get_unified(notion_mcp, "config")
        if not config_b64:
            return []
        config_dir = write_config_folder_to_project(api_task_id, "notion_mcp", config_b64)
        # Retry mechanism for remote MCP connection
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            tools = []
            toolkit = None
            
            try:
                # Create a fresh toolkit instance for each retry
                toolkit = cls(api_task_id, mcp_remote_config_dir=config_dir)
                logger.info(f"Attempting to connect to Notion MCP server (attempt {attempt + 1}/{max_retries})")
                
                await toolkit.connect()
                
                # Get tools from the connected toolkit
                all_tools = toolkit.get_tools()
                tool_schema = [
                    item.get_openai_tool_schema() for item in all_tools
                ]
                
                # Adjust tool schema
                for item in tool_schema:
                    _customize_function_parameters(item)
                
                for item in all_tools:
                    setattr(item, "_toolkit_name", cls.__name__)
                    tools.append(item)
                
                # Check if we actually got tools
                if len(tools) == 0:
                    logger.warning(f"Connected to Notion MCP server but got 0 tools (attempt {attempt + 1}/{max_retries})")
                    raise Exception("No tools retrieved from Notion MCP server")
                
                # Success! Got tools
                logger.info(f"Successfully connected to Notion MCP server and loaded {len(tools)} tools")
                
                return tools
                
            except Exception as e:
                logger.warning(f"Failed to connect to Notion MCP server (attempt {attempt + 1}/{max_retries}): {e}")
                
                # If not the last attempt, wait and retry
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    # Last attempt failed
                    logger.error(f"All {max_retries} connection attempts to Notion MCP server failed. Notion tools will not be available for this task.")
        return []
