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
Code that runs INSIDE an ephemeral worker environment.

It executes a single HTTP request against the in-process FastAPI app using TestClient,
and writes a simple streaming protocol to stdout:

  EIGENT_META <json>\n
  EIGENT_CHUNK <base64>\n   (0..N times)
  EIGENT_DONE\n
"""

import base64
import json
import os
import sys
from typing import Any


def _b64decode(s: str) -> bytes:
    return base64.b64decode(s.encode("utf-8"))


def _b64encode(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def main() -> None:
    payload_b64 = os.environ.get("EIGENT_EPHEMERAL_REQUEST_B64", "").strip()
    if not payload_b64:
        payload_b64 = sys.stdin.read().strip()
    if not payload_b64:
        raise SystemExit("Missing EIGENT_EPHEMERAL_REQUEST_B64")

    req: dict[str, Any] = json.loads(_b64decode(payload_b64).decode("utf-8"))

    # IMPORTANT: ensure workers do not recursively gateway.
    os.environ["EIGENT_EPHEMERAL_GATEWAY_ENABLED"] = "false"

    from app import api  # local import so env is set first
    from starlette.testclient import TestClient

    method = str(req["method"]).upper()
    path = str(req["path"])
    query_string = str(req.get("query_string") or "")
    url = path + (f"?{query_string}" if query_string else "")
    headers = dict(req.get("headers") or {})
    body = _b64decode(str(req.get("body_b64") or ""))

    with TestClient(api) as client:
        with client.stream(method, url, headers=headers, content=body) as r:
            meta = {
                "status_code": r.status_code,
                "headers": dict(r.headers),
                "media_type": r.headers.get("content-type"),
            }
            sys.stdout.write("EIGENT_META " + json.dumps(meta) + "\n")
            sys.stdout.flush()

            for chunk in r.iter_bytes():
                if not chunk:
                    continue
                sys.stdout.write("EIGENT_CHUNK " + _b64encode(chunk) + "\n")
                sys.stdout.flush()

            sys.stdout.write("EIGENT_DONE\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

