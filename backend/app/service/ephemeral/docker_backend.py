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
import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping

from app.service.ephemeral.backends import EphemeralBackendError, WorkerResponse


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def _b64encode(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def _b64decode(s: str) -> bytes:
    return base64.b64decode(s.encode("utf-8"))


def _env_allowlist() -> set[str]:
    default = {
        "ENVIRONMENT",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "E2B_API_KEY",
        "E2B_DOMAIN",
    }
    extra = set(_split_csv(os.environ.get("EIGENT_EPHEMERAL_ENV_ALLOWLIST")))
    return default | extra


@dataclass(frozen=True)
class DockerEphemeralBackend:
    image: str
    timeout_s: float

    @classmethod
    def from_env(cls) -> "DockerEphemeralBackend":
        image = os.environ.get("EIGENT_EPHEMERAL_DOCKER_IMAGE", "").strip()
        if not image:
            raise EphemeralBackendError(
                "EIGENT_EPHEMERAL_DOCKER_IMAGE is required for docker backend "
                "(e.g. the image built from backend/Dockerfile)."
            )
        timeout_s = float(os.environ.get("EIGENT_EPHEMERAL_TIMEOUT_S", "120"))
        return cls(image=image, timeout_s=timeout_s)

    async def handle_http(
        self,
        *,
        method: str,
        path: str,
        query_string: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> WorkerResponse:
        req_obj = {
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": dict(headers),
            "body_b64": _b64encode(body),
        }
        req_b64 = _b64encode(json.dumps(req_obj).encode("utf-8"))

        # Pass through a controlled set of env vars into the worker.
        allow = _env_allowlist()
        env_flags: list[str] = []
        for k in sorted(allow):
            v = os.environ.get(k)
            if v is not None:
                env_flags.extend(["-e", f"{k}={v}"])

        # Disable gateway in worker. (Request payload is passed via stdin to avoid env size limits.)
        env_flags.extend(["-e", "EIGENT_EPHEMERAL_GATEWAY_ENABLED=false"])

        # Run the in-repo worker runner module.
        cmd = [
            "docker",
            "run",
            "--rm",
            *env_flags,
            self.image,
            "python",
            "-m",
            "app.service.ephemeral._worker_runner",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise EphemeralBackendError("docker CLI not found in PATH") from e

        if proc.stdout is None or proc.stderr is None or proc.stdin is None:
            proc.kill()
            raise EphemeralBackendError("Failed to capture docker worker stdout/stderr")

        # Send request payload then close stdin so worker can proceed.
        proc.stdin.write((req_b64 + "\n").encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        async def _readline_with_timeout() -> bytes:
            try:
                return await asyncio.wait_for(proc.stdout.readline(), timeout=self.timeout_s)
            except asyncio.TimeoutError as e:
                proc.kill()
                raise EphemeralBackendError(f"Docker worker timed out after {self.timeout_s}s") from e

        first = await _readline_with_timeout()
        if not first:
            stderr = await proc.stderr.read()
            proc.kill()
            raise EphemeralBackendError(
                "Docker worker produced no output. "
                f"stderr={stderr.decode('utf-8', errors='replace')}"
            )

        line = first.decode("utf-8", errors="replace").rstrip("\n")
        if not line.startswith("EIGENT_META "):
            stderr = await proc.stderr.read()
            proc.kill()
            raise EphemeralBackendError(
                "Docker worker returned unexpected protocol header. "
                f"stdout_first_line={line!r} stderr={stderr.decode('utf-8', errors='replace')}"
            )

        try:
            meta = json.loads(line.removeprefix("EIGENT_META ").strip())
            status_code = int(meta["status_code"])
            resp_headers = {str(k): str(v) for k, v in (meta.get("headers") or {}).items()}
            media_type = meta.get("media_type")
        except Exception as e:
            stderr = await proc.stderr.read()
            proc.kill()
            raise EphemeralBackendError(
                "Docker worker returned invalid META JSON. "
                f"stdout_first_line={line!r} stderr={stderr.decode('utf-8', errors='replace')}"
            ) from e

        async def stream_iter():
            try:
                while True:
                    raw = await _readline_with_timeout()
                    if not raw:
                        break
                    s = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if s == "EIGENT_DONE":
                        break
                    if not s.startswith("EIGENT_CHUNK "):
                        continue
                    b64 = s.removeprefix("EIGENT_CHUNK ").strip()
                    if not b64:
                        continue
                    yield _b64decode(b64)
            finally:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    proc.kill()

        return WorkerResponse(
            status_code=status_code,
            headers=resp_headers,
            body_iter=stream_iter(),
            media_type=media_type,
        )

