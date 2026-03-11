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

import asyncio
import logging

from camel.toolkits import MCPToolkit

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.agent.toolkit.audio_analysis_toolkit import AudioAnalysisToolkit
from app.agent.toolkit.excel_toolkit import ExcelToolkit
from app.agent.toolkit.file_write_toolkit import FileToolkit
from app.agent.toolkit.github_toolkit import GithubToolkit
from app.agent.toolkit.google_calendar_toolkit import GoogleCalendarToolkit
from app.agent.toolkit.google_drive_mcp_toolkit import GoogleDriveMCPToolkit
from app.agent.toolkit.google_gmail_mcp_toolkit import GoogleGmailMCPToolkit
from app.agent.toolkit.lark_toolkit import LarkToolkit
from app.agent.toolkit.linkedin_toolkit import LinkedInToolkit
from app.agent.toolkit.mcp_search_toolkit import McpSearchToolkit
from app.agent.toolkit.notion_mcp_toolkit import NotionMCPToolkit
from app.agent.toolkit.openai_image_toolkit import OpenAIImageToolkit
from app.agent.toolkit.pptx_toolkit import PPTXToolkit
from app.agent.toolkit.rag_toolkit import RAGToolkit
from app.agent.toolkit.image_analysis_toolkit import ImageAnalysisToolkit
from app.agent.toolkit.reddit_toolkit import RedditToolkit
from app.agent.toolkit.search_toolkit import SearchToolkit
from app.agent.toolkit.slack_toolkit import SlackToolkit
from app.agent.toolkit.terminal_toolkit import TerminalToolkit
from app.agent.toolkit.twitter_toolkit import TwitterToolkit
from app.agent.toolkit.video_analysis_toolkit import VideoAnalysisToolkit
from app.agent.toolkit.video_download_toolkit import VideoDownloaderToolkit
from app.agent.toolkit.whatsapp_toolkit import WhatsAppToolkit
from app.component.environment import env
from app.model.chat import McpServers
from app.utils.extra_params_config import _get_project_save_path

logger = logging.getLogger(__name__)


async def get_toolkits(tools: list[str], agent_name: str, api_task_id: str):
    logger.info(f"Getting toolkits for agent: {agent_name}, task: {api_task_id}, tools: {tools}")
    toolkits = {
        "audio_analysis_toolkit": AudioAnalysisToolkit,
        "openai_image_toolkit": OpenAIImageToolkit,
        "excel_toolkit": ExcelToolkit,
        "file_write_toolkit": FileToolkit,
        "github_toolkit": GithubToolkit,
        "google_calendar_toolkit": GoogleCalendarToolkit,
        "google_drive_mcp_toolkit": GoogleDriveMCPToolkit,
        "google_gmail_mcp_toolkit": GoogleGmailMCPToolkit,
        "image_analysis_toolkit": ImageAnalysisToolkit,
        "linkedin_toolkit": LinkedInToolkit,
        "lark_toolkit": LarkToolkit,
        "mcp_search_toolkit": McpSearchToolkit,
        "notion_mcp_toolkit": NotionMCPToolkit,
        "pptx_toolkit": PPTXToolkit,
        "rag_toolkit": RAGToolkit,
        "reddit_toolkit": RedditToolkit,
        "search_toolkit": SearchToolkit,
        "slack_toolkit": SlackToolkit,
        "terminal_toolkit": TerminalToolkit,
        "twitter_toolkit": TwitterToolkit,
        "video_analysis_toolkit": VideoAnalysisToolkit,
        "video_download_toolkit": VideoDownloaderToolkit,
        "whatsapp_toolkit": WhatsAppToolkit,
    }
    res = []
    for item in tools:
        if item in toolkits:
            toolkit: AbstractToolkit = toolkits[item]
            toolkit.agent_name = agent_name
            toolkit_tools = toolkit.get_can_use_tools(api_task_id)
            toolkit_tools = await toolkit_tools if asyncio.iscoroutine(toolkit_tools) else toolkit_tools
            res.extend(toolkit_tools)
        else:
            logger.warning(f"Toolkit {item} not found for agent {agent_name}")
    return res


async def get_mcp_tools(api_task_id: str, mcp_server: McpServers):
    logger.info(f"Getting MCP tools for {len(mcp_server['mcpServers'])} servers")
    if len(mcp_server["mcpServers"]) == 0:
        return []

    # Ensure unified auth directory for all mcp-remote servers to avoid re-authentication on each task
    config_dict = {**mcp_server}
    for server_config in config_dict["mcpServers"].values():
        if "env" not in server_config:
            server_config["env"] = {}
        # Set global auth directory to persist authentication across tasks
        if "MCP_REMOTE_CONFIG_DIR" not in server_config["env"]:
            mcp_remote_config_dir = str(_get_project_save_path(api_task_id))
            server_config["env"]["MCP_REMOTE_CONFIG_DIR"] = env(
                "MCP_REMOTE_CONFIG_DIR", mcp_remote_config_dir
            )

    mcp_toolkit_cm = MCPToolkit(config_dict=config_dict, timeout=180)
    try:
        mcp_toolkit = await asyncio.shield(mcp_toolkit_cm.__aenter__())
        try:
            logger.info(f"Successfully connected to MCP toolkit with {len(mcp_server['mcpServers'])} servers")
            tools = mcp_toolkit.get_tools()
            if tools:
                tool_names = [
                    (tool.get_function_name() if hasattr(tool, "get_function_name") else str(tool)) for tool in tools
                ]
                logging.debug(f"MCP tool names: {tool_names}")
            return tools
        finally:
            await mcp_toolkit_cm.__aexit__(None, None, None)
    
    except asyncio.CancelledError:
        logger.info("MCP connection cancelled during get_mcp_tools")
        return []
    
    except Exception as e:
        logger.error(f"Failed to connect MCP toolkit: {e}", exc_info=True)
        return []
