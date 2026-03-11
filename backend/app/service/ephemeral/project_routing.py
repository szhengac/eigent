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

from __future__ import annotations

import json
from typing import Mapping


def extract_project_key(
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
) -> str | None:
    """
    Derive a stable project key from the HTTP request so that related calls
    (e.g. POST /chat, POST /task/{id}/start) are routed to the same worker.

    Rules:
      - /chat (POST): use JSON body field `project_id`
      - /chat/{id}..., /task/{id}... : use the `{id}` path segment
      - otherwise: return None (non-project-scoped)
    """
    # Normalize path segments (ignore leading/trailing slashes).
    segments = [seg for seg in path.strip("/").split("/") if seg]
    if not segments:
        return None

    root = segments[0]
    if root in {"chat", "task"} and len(segments) >= 2:
        # /chat/{id}/..., /task/{id}/...
        return segments[1]

    if root == "chat" and method.upper() == "POST" and len(segments) == 1:
        # POST /chat with JSON body containing project_id
        content_type = headers.get("content-type", headers.get("Content-Type", ""))
        if "application/json" not in content_type:
            return None
        try:
            data = json.loads(body.decode("utf-8"))
            project_id = data.get("project_id")
            if isinstance(project_id, str) and project_id:
                return project_id
        except Exception:
            return None

    return None

