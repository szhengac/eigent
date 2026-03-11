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

from dataclasses import dataclass
from typing import AsyncIterable, Mapping, Protocol


class EphemeralBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes | None = None
    body_iter: AsyncIterable[bytes] | None = None
    media_type: str | None = None


class EphemeralBackend(Protocol):
    async def handle_http(
        self,
        *,
        method: str,
        path: str,
        query_string: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> WorkerResponse: ...

    async def stop_all(self) -> None:
        """
        Stop/cleanup all project-scoped workers managed by this backend.

        Implementations should be idempotent and best-effort.
        """
        ...


def build_ephemeral_backend_from_env(name: str) -> EphemeralBackend:
    name = (name or "").strip().lower()
    if name == "docker":
        from app.service.ephemeral.docker_backend import DockerEphemeralBackend

        return DockerEphemeralBackend.from_env()
    if name in {"e2b", "sandbox"}:
        from app.service.ephemeral.e2b_backend import E2BEphemeralBackend

        return E2BEphemeralBackend.from_env()
    raise EphemeralBackendError(f"Unknown ephemeral backend '{name}'. Expected 'docker' or 'e2b'.")

