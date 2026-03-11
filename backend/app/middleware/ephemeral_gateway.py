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

import json
import os
from dataclasses import dataclass
from typing import Mapping

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.service.ephemeral.backends import (
    EphemeralBackend,
    EphemeralBackendError,
    build_ephemeral_backend_from_env,
)
from app.service.ephemeral.project_routing import extract_project_key


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


@dataclass(frozen=True)
class EphemeralGatewayConfig:
    enabled: bool
    backend: str
    exclude_path_prefixes: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "EphemeralGatewayConfig":
        enabled = os.environ.get("EIGENT_EPHEMERAL_GATEWAY_ENABLED", "").lower() in {"1", "true", "yes", "on"}
        backend = os.environ.get("EIGENT_EPHEMERAL_BACKEND", "docker").strip().lower()

        default_excludes = [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        excludes = tuple(_split_csv(os.environ.get("EIGENT_EPHEMERAL_EXCLUDE_PREFIXES")) or default_excludes)
        return cls(enabled=enabled, backend=backend, exclude_path_prefixes=excludes)


def _should_bypass(request: Request, config: EphemeralGatewayConfig) -> bool:
    # Prevent infinite recursion: workers must never gateway again.
    if request.headers.get("x-eigent-ephemeral-worker", "").lower() in {"1", "true", "yes"}:
        return True

    path = request.url.path
    return any(path.startswith(prefix) for prefix in config.exclude_path_prefixes)


def _headers_to_forward(headers: Mapping[str, str]) -> dict[str, str]:
    # Preserve user headers, but strip hop-by-hop / size-sensitive headers.
    blocked = {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
    return {k: v for k, v in headers.items() if k.lower() not in blocked}


def _sanitize_response_headers(headers: Mapping[str, str], *, streaming: bool) -> dict[str, str]:
    blocked = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
    out = {k: v for k, v in headers.items() if k.lower() not in blocked}
    if streaming:
        out.pop("content-length", None)
        out.pop("Content-Length", None)
    return out


class EphemeralGatewayMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, backend: EphemeralBackend, config: EphemeralGatewayConfig) -> None:
        super().__init__(app)
        self._backend = backend
        self._config = config

    async def dispatch(self, request: Request, call_next):
        if not self._config.enabled or _should_bypass(request, self._config):
            return await call_next(request)

        body = await request.body()
        project_key = extract_project_key(request.method, request.url.path, request.headers, body)

        # Special-case: DELETE /task/stop-all should also tear down all workers.
        if request.method.upper() == "DELETE" and request.url.path == "/task/stop-all":
            # Let the parent handle its own state first.
            parent_resp = await call_next(request)
            try:
                await self._backend.stop_all()
            except Exception as e:  # pragma: no cover
                # Surface as 502 if backend cleanup fails badly.
                return Response(
                    status_code=502,
                    content=json.dumps({"error": "ephemeral_backend_error", "detail": f"stop_all failed: {e}"}),
                    media_type="application/json",
                )
            return parent_resp

        # Non-project-scoped requests are handled by the parent container directly.
        if project_key is None:
            return await call_next(request)

        # Per-project stop semantics:
        # - DELETE /chat/{project_id}: stop chat and kill that project's worker.
        # - POST /chat/{project_id}/skip-task: stop current task and kill that project's worker.
        if request.method.upper() == "DELETE" and request.url.path.startswith("/chat/") and project_key:
            parent_resp = await call_next(request)
            await self._backend.stop_project(project_key)
            return parent_resp

        if (
            request.method.upper() == "POST"
            and request.url.path.startswith("/chat/")
            and request.url.path.endswith("/skip-task")
            and project_key
        ):
            parent_resp = await call_next(request)
            await self._backend.stop_project(project_key)
            return parent_resp

        headers = _headers_to_forward(dict(request.headers))
        headers["x-eigent-ephemeral-worker"] = "1"

        try:
            worker_resp = await self._backend.handle_http(
                method=request.method,
                path=request.url.path,
                query_string=request.url.query,
                headers=headers,
                body=body,
            )
        except EphemeralBackendError as e:
            return Response(
                status_code=502,
                content=json.dumps({"error": "ephemeral_backend_error", "detail": str(e)}),
                media_type="application/json",
            )

        if worker_resp.body_iter is not None:
            return StreamingResponse(
                worker_resp.body_iter,
                status_code=worker_resp.status_code,
                headers=_sanitize_response_headers(worker_resp.headers, streaming=True),
                media_type=worker_resp.media_type,
            )

        return Response(
            status_code=worker_resp.status_code,
            content=worker_resp.body or b"",
            headers=_sanitize_response_headers(worker_resp.headers, streaming=False),
            media_type=worker_resp.media_type,
        )


def maybe_install_ephemeral_gateway(app) -> None:
    """
    Installs the ephemeral gateway middleware if enabled via env.

    Env:
      - EIGENT_EPHEMERAL_GATEWAY_ENABLED=true|false
      - EIGENT_EPHEMERAL_BACKEND=docker|e2b
      - EIGENT_EPHEMERAL_EXCLUDE_PREFIXES=/health,/docs,...
    """
    config = EphemeralGatewayConfig.from_env()
    if not config.enabled:
        return

    backend = build_ephemeral_backend_from_env(config.backend)
    app.add_middleware(EphemeralGatewayMiddleware, backend=backend, config=config)

