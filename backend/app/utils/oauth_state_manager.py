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
OAuth authorization state manager for background authorization flows
"""
import threading
from typing import Dict, Optional, Literal, Any
from datetime import datetime
import logging
logger = logging.getLogger("main")

AuthStatus = Literal["pending", "authorizing", "success", "failed", "cancelled"]


class OAuthState:
    """Represents the state of an OAuth authorization flow"""

    def __init__(self, provider: str):
        self.provider = provider
        self.status: AuthStatus = "pending"
        self.error: Optional[str] = None
        self.thread: Optional[threading.Thread] = None
        self.result: Optional[Any] = None
        self.started_at = datetime.now()
        self.completed_at: Optional[datetime] = None
        self._cancel_event = threading.Event()
        self.server = None  # Store the local server instance for forced shutdown
    
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested"""
        return self._cancel_event.is_set()
    
    def cancel(self):
        """Request cancellation of the authorization flow"""
        self._cancel_event.set()
        self.status = "cancelled"
        self.completed_at = datetime.now()
    
    def to_dict(self) -> Dict:
        """Convert state to dictionary for API response"""
        return {
            "provider": self.provider,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def _state_key(project_id: str, provider: str) -> str:
    """Key for per-project OAuth state."""
    return f"{project_id}:{provider}"


class OAuthStateManager:
    """Manager for tracking OAuth authorization flows. State is stored per project and cleared when chat ends."""

    def __init__(self):
        self._states: Dict[str, OAuthState] = {}
        self._lock = threading.Lock()

    def create_state(self, provider: str, project_id: str = "install") -> OAuthState:
        """Create a new OAuth state for a provider in a project. Use project_id='install' for tool install flow."""
        key = _state_key(project_id, provider)
        with self._lock:
            if key in self._states:
                old_state = self._states[key]
                if old_state.status in ["pending", "authorizing"]:
                    old_state.cancel()
                    logger.info(f"Cancelled previous {provider} authorization for project {project_id}")
            state = OAuthState(provider)
            self._states[key] = state
            return state

    def get_state(self, provider: str, project_id: str | None = None) -> Optional[OAuthState]:
        """Get the current state for a provider. If project_id is None, returns None (caller must pass project_id)."""
        if project_id is None:
            return None
        key = _state_key(project_id, provider)
        with self._lock:
            return self._states.get(key)

    def update_status(
        self,
        provider: str,
        status: AuthStatus,
        project_id: str = "install",
        error: Optional[str] = None,
        result: Optional[Any] = None,
    ):
        """Update the status of an authorization flow for a project."""
        key = _state_key(project_id, provider)
        with self._lock:
            if key in self._states:
                state = self._states[key]
                state.status = status
                state.error = error
                state.result = result
                if status in ["success", "failed", "cancelled"]:
                    state.completed_at = datetime.now()
                logger.info(f"Updated {provider} OAuth status to {status} for project {project_id}")

    def clear_project(self, project_id: str) -> None:
        """Remove all OAuth state for a project. Call when chat ends (e.g. after delete_task_lock)."""
        with self._lock:
            to_remove = [k for k in self._states if k.startswith(f"{project_id}:")]
            for key in to_remove:
                state = self._states[key]
                if state.status in ["pending", "authorizing"]:
                    state.cancel()
                del self._states[key]
                logger.info(f"Cleared OAuth state {key}")
    
# Global instance
oauth_state_manager = OAuthStateManager()

