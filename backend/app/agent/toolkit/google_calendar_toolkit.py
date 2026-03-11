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
import os
import threading

from app.service.task import Agents
from app.utils.listen.toolkit_listen import auto_listen_toolkit
from app.utils.toolkit.abstract_toolkit import AbstractToolkit
from app.utils.oauth_state_manager import oauth_state_manager
from app.service.task import get_task_lock_if_exists
import logging

from camel.toolkits import GoogleCalendarToolkit as BaseGoogleCalendarToolkit

logger = logging.getLogger("main")

SCOPES = ['https://www.googleapis.com/auth/calendar']

@auto_listen_toolkit(BaseGoogleCalendarToolkit)
class GoogleCalendarToolkit(BaseGoogleCalendarToolkit, AbstractToolkit):
    agent_name: str = Agents.social_medium_agent

    def __init__(self, api_task_id: str, timeout: float | None = None):
        self.api_task_id = api_task_id
        super().__init__(timeout)

    @classmethod
    def get_can_use_tools(cls, api_task_id: str):
        # Credentials only from Chat.creds_params or per-project OAuth state (no env).
        task_lock = get_task_lock_if_exists(api_task_id)
        if task_lock:
            creds = getattr(task_lock, "creds_params", None) or {}
            gc = creds.get("google_calendar") or {}
            if gc.get("access_token") or (gc.get("refresh_token") and gc.get("client_id") and gc.get("client_secret")):
                return cls(api_task_id).get_tools()
            state = oauth_state_manager.get_state("google_calendar", api_task_id)
            if state and state.status == "success" and state.result:
                return cls(api_task_id).get_tools()
        return []

    def _get_calendar_service(self):
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request

        creds = self._authenticate()

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        return build("calendar", "v3", credentials=creds)

    def _authenticate(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = None

        # First, try credentials from Chat.creds_params (stored on task_lock when request is received)
        task_lock = get_task_lock_if_exists(self.api_task_id)
        if task_lock:
            creds_params = getattr(task_lock, "creds_params", None) or {}
            gc = creds_params.get("google_calendar") or {}
            if gc:
                token_uri = gc.get("token_uri") or "https://oauth2.googleapis.com/token"
                if gc.get("access_token"):
                    creds = Credentials(token=gc["access_token"], scopes=SCOPES)
                    logger.info("Using Google Calendar credentials from Chat.creds_params (access_token)")
                elif gc.get("refresh_token") and gc.get("client_id") and gc.get("client_secret"):
                    creds = Credentials(
                        token=None,
                        refresh_token=gc["refresh_token"],
                        token_uri=token_uri,
                        client_id=gc["client_id"],
                        client_secret=gc["client_secret"],
                        scopes=SCOPES,
                    )
                    logger.info("Using Google Calendar credentials from Chat.creds_params (refresh_token)")

        # If still no creds, check per-project OAuth state (no env)
        if not creds:
            state = oauth_state_manager.get_state("google_calendar", self.api_task_id)
            if state and state.status == "success" and state.result:
                logger.info("Using credentials from per-project OAuth state")
                creds = state.result
            else:
                raise ValueError(
                    "No Google Calendar credentials. Include them in Chat.creds_params['google_calendar'] "
                    "(e.g. access_token or refresh_token+client_id+client_secret) or complete OAuth for this project."
                )

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Token expired, refreshing...")
                creds.refresh(Request())
                logger.info("Token refreshed successfully")
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                raise ValueError("Failed to refresh expired token. Please re-authorize.")

        return creds
    
    @staticmethod
    def start_background_auth(api_task_id: str = "install") -> str:
        """
        Start background OAuth authorization flow. State is stored per project_id.
        Use project_id='install' for the tool install flow (no active chat).
        Returns the status of the authorization.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        project_id = api_task_id

        # Check if there's an existing authorization for this project and force stop it
        old_state = oauth_state_manager.get_state("google_calendar", project_id)
        if old_state and old_state.status in ["pending", "authorizing"]:
            logger.info("Found existing authorization, forcing shutdown...")
            old_state.cancel()
            if hasattr(old_state, "server") and old_state.server:
                try:
                    old_state.server.shutdown()
                    logger.info("Old server shutdown successfully")
                except Exception as e:
                    logger.warning(f"Could not shutdown old server: {e}")

        state = oauth_state_manager.create_state("google_calendar", project_id)

        def auth_flow():
            try:
                state.status = "authorizing"
                oauth_state_manager.update_status("google_calendar", "authorizing", project_id=project_id)

                # Client credentials must come from Chat.creds_params for this project (no env).
                # For install flow (project_id='install'), client must have set them in a prior request or we fail.
                task_lock = get_task_lock_if_exists(project_id)
                creds_params = getattr(task_lock, "creds_params", None) or {} if task_lock else {}
                gc = creds_params.get("google_calendar") or {}
                client_id = gc.get("client_id")
                client_secret = gc.get("client_secret")
                token_uri = gc.get("token_uri") or "https://oauth2.googleapis.com/token"

                logger.info(f"Google Calendar auth - client_id present: {bool(client_id)}, client_secret present: {bool(client_secret)}")

                if not client_id or not client_secret:
                    error_msg = (
                        "Google Calendar OAuth requires client_id and client_secret in Chat.creds_params['google_calendar'] "
                        "for this project (or for project_id='install' when using the install flow)."
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": token_uri,
                        "redirect_uris": ["http://localhost"],
                    }
                }
                logger.debug(f"calendar client_config initialized with client_id: {client_id[:10]}...")
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

                # Check for cancellation before starting
                if state.is_cancelled():
                    logger.info("Authorization cancelled before starting")
                    return

                # This will automatically open browser and wait for user authorization
                logger.info("=" * 80)
                logger.info(f"[Thread {threading.current_thread().name}] Starting local server for Google Calendar authorization")
                logger.info("Browser should open automatically in a moment...")
                logger.info("=" * 80)

                # Run local server - this will block until authorization completes
                # Note: Each call uses a random port (port=0), so multiple concurrent attempts won't conflict
                try:
                    creds = flow.run_local_server(
                        port=0,
                        authorization_prompt_message="",
                        success_message="<h1>Authorization successful!</h1><p>You can close this window and return to Eigent.</p>",
                        open_browser=True
                    )
                    logger.info("Authorization flow completed successfully!")
                except Exception as server_error:
                    logger.error(f"Error during run_local_server: {server_error}")
                    raise

                # Check for cancellation after auth
                if state.is_cancelled():
                    logger.info("Authorization cancelled after completion")
                    return

                oauth_state_manager.update_status("google_calendar", "success", project_id=project_id, result=creds)
                logger.info("Google Calendar authorization successful!")

            except Exception as e:
                if state.is_cancelled():
                    logger.info("Authorization was cancelled")
                    oauth_state_manager.update_status("google_calendar", "cancelled", project_id=project_id)
                else:
                    error_msg = str(e)
                    logger.error(f"Google Calendar authorization failed: {error_msg}")
                    oauth_state_manager.update_status("google_calendar", "failed", project_id=project_id, error=error_msg)
            finally:
                # Clean up server reference
                state.server = None

        # Start authorization in background thread
        thread = threading.Thread(target=auth_flow, daemon=True, name=f"GoogleCalendar-OAuth-{state.started_at.timestamp()}")
        state.thread = thread
        thread.start()

        logger.info("Started background Google Calendar authorization")
        return "authorizing"
