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
import os
import uuid
from dataclasses import dataclass
from typing import Mapping

import httpx

from app.service.ephemeral.backends import EphemeralBackendError, WorkerResponse


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


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


async def _docker_stop(container_name: str) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "stop",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
    except Exception:
        # Best-effort; ignore failures
        return


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
        """
        For each incoming request:
          1. Start a fresh worker container running the same FastAPI app.
          2. Wait for its /health endpoint to be ready.
          3. Proxy the HTTP request to the worker via httpx (streaming).
          4. Stop the worker container when done.
        """
        container_name = f"paxs-eigent-worker-{uuid.uuid4().hex[:12]}"

        # Pass through a controlled set of env vars into the worker.
        allow = _env_allowlist()
        env_flags: list[str] = []
        for k in sorted(allow):
            v = os.environ.get(k)
            if v is not None:
                env_flags.extend(["-e", f"{k}={v}"])

        # Ensure workers do not recursively gateway.
        env_flags.extend(["-e", "EIGENT_EPHEMERAL_GATEWAY_ENABLED=false"])

        # Run worker container in detached mode; it will start /entrypoint.sh (uvicorn on port 5002).
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
        ]

        # Optional: use a specific Docker network if configured.
        network = os.environ.get("EIGENT_EPHEMERAL_DOCKER_NETWORK")
        if network:
            cmd.extend(["--network", network])

        cmd.extend(
            [
                *env_flags,
                self.image,
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

        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise EphemeralBackendError(
                "Failed to start docker worker container. "
                f"exit_code={proc.returncode} stderr={stderr.decode('utf-8', errors='replace')}"
            )

        # Wait for worker FastAPI app to be ready.
        base_url = f"http://{container_name}:5002"
        health_url = base_url + "/health"
        startup_timeout = float(os.environ.get("EIGENT_EPHEMERAL_STARTUP_TIMEOUT_S", "30"))
        start_time = asyncio.get_event_loop().time()

        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                try:
                    resp = await client.get(health_url)
                    if resp.status_code < 500:
                        break
                except Exception:
                    pass

                if asyncio.get_event_loop().time() - start_time > startup_timeout:
                    await _docker_stop(container_name)
                    raise EphemeralBackendError(
                        f"Docker worker did not become ready within {startup_timeout}s"
                    )
                await asyncio.sleep(0.3)

        # Proxy the original request to the worker using httpx streaming.
        url = path + (f"?{query_string}" if query_string else "")

        # Avoid propagating a Host header tied to the gateway; let httpx set it.
        filtered_headers = {k: v for k, v in headers.items() if k.lower() != "host"}

        client_timeout = httpx.Timeout(self.timeout_s, read=self.timeout_s)
        client = httpx.AsyncClient(base_url=base_url, timeout=client_timeout)

        try:
            request = client.build_request(
                method=method,
                url=url,
                headers=filtered_headers,
                content=body,
            )
            resp = await client.send(request, stream=True)
        except Exception as e:
            await client.aclose()
            await _docker_stop(container_name)
            raise EphemeralBackendError(f"Error proxying request to docker worker: {e!s}") from e

        async def stream_iter():
            try:
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
            finally:
                await resp.aclose()
                await client.aclose()
                await _docker_stop(container_name)

        return WorkerResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body_iter=stream_iter(),
            media_type=resp.headers.get("content-type"),
        )

