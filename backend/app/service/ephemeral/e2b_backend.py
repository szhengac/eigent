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

import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping

from app.service.ephemeral.backends import EphemeralBackendError, WorkerResponse
from app.service.ephemeral.project_routing import extract_project_key


def _b64encode(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


_PROJECT_SANDBOXES: dict[str, object] = {}


@dataclass(frozen=True)
class E2BEphemeralBackend:
    timeout_s: float

    @classmethod
    def from_env(cls) -> "E2BEphemeralBackend":
        timeout_s = float(os.environ.get("EIGENT_EPHEMERAL_TIMEOUT_S", "120"))
        return cls(timeout_s=timeout_s)

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
        Reuses an E2B sandbox per project key, running the in-process request via TestClient.

        Requires env: E2B_API_KEY (and optionally E2B_DOMAIN).
        """
        try:
            from e2b_code_interpreter import Sandbox  # type: ignore
        except Exception as e:  # pragma: no cover
            raise EphemeralBackendError(
                "E2B backend requires 'e2b_code_interpreter' installed and E2B_API_KEY set."
            ) from e

        project_key = extract_project_key(method, path, headers, body)
        req_obj = {
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": dict(headers),
            "body_b64": _b64encode(body),
        }
        req_b64 = _b64encode(json.dumps(req_obj).encode("utf-8"))

        api_key = os.environ.get("E2B_API_KEY")
        if not api_key:
            raise EphemeralBackendError("E2B_API_KEY is required for e2b backend.")

        domain = os.environ.get("E2B_DOMAIN")
        sandbox_kwargs: dict[str, str] = {"api_key": api_key}
        if domain:
            sandbox_kwargs["domain"] = domain

        sandbox: "Sandbox"
        # For project-scoped calls, reuse sandbox; otherwise one-off.
        if project_key is not None:
            sandbox = _PROJECT_SANDBOXES.get(project_key) or Sandbox(**sandbox_kwargs)
            _PROJECT_SANDBOXES[project_key] = sandbox
        else:
            sandbox = Sandbox(**sandbox_kwargs)

        try:
            # Mirror only the env we need inside the sandbox.
            # (Workers must never enable the gateway again.)
            code = r"""
import base64, json, os
os.environ["EIGENT_EPHEMERAL_GATEWAY_ENABLED"] = "false"
payload_b64 = os.environ.get("EIGENT_EPHEMERAL_REQUEST_B64", "")
req = json.loads(base64.b64decode(payload_b64).decode("utf-8"))

from app import api
from app.component.environment import env
from app.router import register_routers
from starlette.testclient import TestClient

def b64decode(s: str) -> bytes:
    return base64.b64decode(s.encode("utf-8"))

def b64encode(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

method = str(req["method"]).upper()
path = str(req["path"])
qs = str(req.get("query_string") or "")
url = path + (f"?{qs}" if qs else "")
headers = dict(req.get("headers") or {})
body = b64decode(str(req.get("body_b64") or ""))

prefix = env("url_prefix", "")
register_routers(api, prefix)

with TestClient(api) as client:
    with client.stream(method, url, headers=headers, content=body) as r:
        meta = {
            "status_code": r.status_code,
            "headers": dict(r.headers),
            "media_type": r.headers.get("content-type"),
        }
        print("EIGENT_META " + json.dumps(meta))
        for chunk in r.iter_bytes():
            if not chunk:
                continue
            print("EIGENT_CHUNK " + b64encode(chunk))
        print("EIGENT_DONE")
"""
            # E2B runs code synchronously; keep this function async-compatible.
            # Also ensure the repository code exists in sandbox: assume you build an E2B template
            # with this backend package; otherwise this will fail with ImportError.
            sandbox.set_env("EIGENT_EPHEMERAL_REQUEST_B64", req_b64)
            execution = sandbox.run_code(code)

            text = (execution.text or "").strip()
            if not text:
                raise EphemeralBackendError(f"E2B worker produced no output. error={execution.error}")

            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            meta_line = next((ln for ln in lines if ln.startswith("EIGENT_META ")), None)
            if not meta_line:
                raise EphemeralBackendError(f"E2B worker missing META line. output={text[:5000]}")

            meta = json.loads(meta_line.removeprefix("EIGENT_META ").strip())
            status_code = int(meta["status_code"])
            resp_headers = {str(k): str(v) for k, v in (meta.get("headers") or {}).items()}
            media_type = meta.get("media_type")

            # E2B stdout is buffered, so we return a buffered body (not true streaming).
            chunks: list[bytes] = []
            for ln in lines:
                if ln.startswith("EIGENT_CHUNK "):
                    b64 = ln.removeprefix("EIGENT_CHUNK ").strip()
                    if b64:
                        chunks.append(base64.b64decode(b64.encode("utf-8")))
            body_bytes = b"".join(chunks)

            return WorkerResponse(status_code=status_code, headers=resp_headers, body=body_bytes, media_type=media_type)
        except Exception as e:
            raise EphemeralBackendError(f"E2B worker failed: {e!s}") from e
        finally:
            # Only auto-kill non-project sandboxes; project-scoped ones are reused
            if project_key is None:
                try:
                    sandbox.kill()
                except Exception:
                    pass

    async def stop_all(self) -> None:
        """
        Kill all project-scoped sandboxes.
        """
        global _PROJECT_SANDBOXES
        for sb in _PROJECT_SANDBOXES.values():
            try:
                sb.kill()
            except Exception:
                pass
        _PROJECT_SANDBOXES = {}

