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
import uuid
from dataclasses import dataclass
from pathlib import Path
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


def _shared_dir() -> Path:
    """
    Directory used to hand off large request payloads to worker containers.

    This path is on the gateway container filesystem and is bind-mounted into
    the worker container at the same path.
    """
    base = os.environ.get("EIGENT_EPHEMERAL_SHARED_DIR", "/tmp/paxs/shared/ephemeral")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


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
        # Serialize request to a shared file to avoid env size limits.
        shared_dir = _shared_dir()
        request_id = uuid.uuid4().hex
        request_path = shared_dir / f"req-{request_id}.json"
        request_path.write_text(json.dumps(req_obj), encoding="utf-8")

        # Pass through a controlled set of env vars into the worker.
        allow = _env_allowlist()
        env_flags: list[str] = []
        for k in sorted(allow):
            v = os.environ.get(k)
            if v is not None:
                env_flags.extend(["-e", f"{k}={v}"])

        # Disable gateway in worker and point it to the shared request file.
        env_flags.extend(
            [
                "-e",
                "EIGENT_EPHEMERAL_GATEWAY_ENABLED=false",
                "-e",
                f"EIGENT_EPHEMERAL_REQUEST_FILE={request_path}",
            ]
        )

        # Run the in-repo worker runner module.
        cmd = [
            "docker",
            "run",
            "--rm",
        ]

        # Optional: use a specific Docker network if configured.
        network = os.environ.get("EIGENT_EPHEMERAL_DOCKER_NETWORK")
        if network:
            cmd.extend(["--network", network])

        # Bind-mount the shared directory into the worker at the same path.
        cmd.extend(["-v", f"{shared_dir}:{shared_dir}"])

        cmd.extend(
            [
                *env_flags,
                self.image,
                "python",
                "-m",
                "app.service.ephemeral._worker_runner",
            ]
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise EphemeralBackendError("docker CLI not found in PATH") from e

        if proc.stdout is None or proc.stderr is None:
            try:
                proc.kill()
            except Exception:
                pass
            raise EphemeralBackendError("Failed to capture docker worker stdout/stderr")

        async def _readline_with_timeout() -> bytes:
            try:
                return await asyncio.wait_for(proc.stdout.readline(), timeout=self.timeout_s)
            except asyncio.TimeoutError as e:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise EphemeralBackendError(f"Docker worker timed out after {self.timeout_s}s") from e

        first = await _readline_with_timeout()
        if not first:
            stderr = await proc.stderr.read()
            try:
                proc.kill()
            except Exception:
                pass
            raise EphemeralBackendError(
                "Docker worker produced no output. "
                f"stderr={stderr.decode('utf-8', errors='replace')}"
            )

        line = first.decode("utf-8", errors="replace").rstrip("\n")
        if not line.startswith("EIGENT_META "):
            stderr = await proc.stderr.read()
            try:
                proc.kill()
            except Exception:
                pass
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
            try:
                proc.kill()
            except Exception:
                pass
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
                    try:
                        proc.kill()
                    except Exception:
                        pass
                # Best-effort cleanup of request file
                try:
                    if request_path.exists():
                        request_path.unlink()
                except Exception:
                    pass

        return WorkerResponse(
            status_code=status_code,
            headers=resp_headers,
            body_iter=stream_iter(),
            media_type=media_type,
        )

