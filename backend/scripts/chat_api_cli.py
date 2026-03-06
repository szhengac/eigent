#!/usr/bin/env python3
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
Simple interactive CLI for Eigent backend chat API (port 5002 by default).

Features:
- Start chat (task starts automatically): POST /chat (SSE stream)
- Send follow-up message: POST /chat/{project_id}
- Answer agent question (human reply): POST /chat/{project_id}/human-reply
- Parse SSE chunks and render user-facing output
- Copy any returned files from `write_file` events into a local directory

Usage:
  python backend/scripts/chat_api_cli.py --help

Example:
  export OPENAI_API_KEY="..."
  python backend/scripts/chat_api_cli.py \
    --question "Build me a todo app" \
    --email "me@example.com" \
    --model-platform "openai-compatible-model" \
    --model-type "gpt-4o-mini" \
    --download-dir "./downloads"
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _print(msg: str) -> None:
    print(msg, file=sys.stdout, flush=True)


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _safe_relativize(path: Path, root: Path) -> Optional[Path]:
    try:
        return path.resolve().relative_to(root.resolve())
    except Exception:
        return None


@dataclass
class PendingAsk:
    agent: str
    question: str


class EigentChatCli:
    def __init__(
        self,
        base_url: str,
        download_dir: Path,
        verbose: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.download_dir = download_dir
        self.verbose = verbose

        self._client = httpx.Client(timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=None))
        self._stop_event = threading.Event()
        self._sse_thread: Optional[threading.Thread] = None
        self._events: "queue.Queue[dict[str, Any]]" = queue.Queue()

        self.project_id: Optional[str] = None
        self.task_id: Optional[str] = None
        self.pending_ask: Optional[PendingAsk] = None

    # ------------- HTTP helpers -------------
    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def post_followup(self, project_id: str, message: str, new_task_id: Optional[str] = None) -> None:
        payload: dict[str, Any] = {"question": message, "task_id": new_task_id}
        r = self._client.post(self._url(f"/chat/{project_id}"), json=payload)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"followup failed: {r.status_code} {r.text}")

    def post_human_reply(self, project_id: str, agent: str, reply: str) -> None:
        payload = {"agent": agent, "reply": reply}
        r = self._client.post(self._url(f"/chat/{project_id}/human-reply"), json=payload)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"human-reply failed: {r.status_code} {r.text}")

    def post_skip_task(self, project_id: str) -> None:
        r = self._client.post(self._url(f"/chat/{project_id}/skip-task"))
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"skip-task failed: {r.status_code} {r.text}")

    def delete_stop(self, project_id: str) -> None:
        r = self._client.delete(self._url(f"/chat/{project_id}"))
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"stop failed: {r.status_code} {r.text}")

    # ------------- SSE stream -------------
    def start_stream(self, chat_payload: dict[str, Any]) -> None:
        if self._sse_thread and self._sse_thread.is_alive():
            raise RuntimeError("SSE stream already running")

        self._stop_event.clear()
        self._sse_thread = threading.Thread(
            target=self._run_sse_stream,
            args=(chat_payload,),
            name="eigent-sse",
            daemon=True,
        )
        self._sse_thread.start()

    def stop_stream(self) -> None:
        self._stop_event.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=1.0)

    def _run_sse_stream(self, chat_payload: dict[str, Any]) -> None:
        try:
            with self._client.stream("POST", self._url("/chat"), json=chat_payload) as r:
                r.raise_for_status()

                data_lines: list[str] = []
                for raw_line in r.iter_lines():
                    if self._stop_event.is_set():
                        return
                    if raw_line is None:
                        continue

                    line = raw_line.strip()
                    if not line:
                        # End of SSE event
                        if data_lines:
                            payload_text = "\n".join(data_lines)
                            data_lines = []
                            evt = self._parse_sse_data(payload_text)
                            if evt is not None:
                                self._events.put(evt)
                        continue

                    # We only care about "data:" lines (backend uses sse_json -> "data: {...}\n\n")
                    if line.startswith("data:"):
                        data_lines.append(line[len("data:") :].lstrip())
        except Exception as e:
            self._events.put({"step": "error", "data": {"message": f"SSE stream error: {e}"}})

    @staticmethod
    def _parse_sse_data(payload_text: str) -> Optional[dict[str, Any]]:
        payload_text = payload_text.strip()
        if not payload_text:
            return None
        try:
            obj = json.loads(payload_text)
        except Exception:
            # Non-JSON payload - still surface it
            return {"step": "raw", "data": {"text": payload_text}}
        if isinstance(obj, dict) and "step" in obj and "data" in obj:
            return obj
        return {"step": "raw", "data": obj}

    # ------------- Event rendering & file saving -------------
    def _copy_returned_file(self, file_path_str: str) -> Optional[Path]:
        src = Path(file_path_str).expanduser()
        if not src.exists() or not src.is_file():
            return None

        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Try to preserve a useful relative structure under ~/eigent/...
        home = Path.home()
        eigent_root = home / "eigent"
        rel = _safe_relativize(src, eigent_root)
        if rel is None:
            rel = Path(src.name)

        dest = (self.download_dir / rel).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Avoid overwriting if repeated
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            for i in range(1, 1000):
                candidate = dest.with_name(f"{stem}__{i}{suffix}")
                if not candidate.exists():
                    dest = candidate
                    break

        shutil.copy2(src, dest)
        return dest

    def handle_event(self, evt: dict[str, Any]) -> bool:
        """
        Returns True if the session should end.
        """
        step = evt.get("step")
        data = evt.get("data")

        if step in ("confirmed",):
            _print(f"[{_now()}] assistant: confirmed. starting task for: {data.get('question') if isinstance(data, dict) else data}")
            return False

        if step in ("wait_confirm",):
            # Simple-question answer
            if isinstance(data, dict):
                content = data.get("content", "")
            else:
                content = str(data)
            _print(f"[{_now()}] assistant:\n{content}\n")
            return False

        if step in ("ask",):
            if isinstance(data, dict):
                agent = str(data.get("agent", "")).strip() or "unknown"
                question = str(data.get("question", "")).strip()
            else:
                agent, question = "unknown", str(data)
            self.pending_ask = PendingAsk(agent=agent, question=question)
            _print(f"[{_now()}] agent question from '{agent}': {question}")
            _print("Type: /reply <your answer>")
            return False

        if step in ("write_file",):
            if isinstance(data, dict):
                file_path = data.get("file_path")
            else:
                file_path = None
            if file_path:
                saved = self._copy_returned_file(str(file_path))
                if saved is None:
                    _print(f"[{_now()}] file: {file_path} (not found locally)")
                else:
                    _print(f"[{_now()}] file saved: {saved}")
            else:
                _print(f"[{_now()}] file: {data}")
            return False

        if step in ("task_state", "new_task_state"):
            if isinstance(data, dict):
                task_id = data.get("task_id")
                state = data.get("state")
                content = data.get("content")
                result = data.get("result")
                if self.verbose and result:
                    _print(f"[{_now()}] {step}: ({task_id}) {state} - {content}\n{result}\n")
                else:
                    _print(f"[{_now()}] {step}: ({task_id}) {state} - {content}")
            else:
                _print(f"[{_now()}] {step}: {data}")
            return False

        if step in ("notice", "terminal"):
            if isinstance(data, dict):
                msg = data.get("notice") if step == "notice" else data.get("output")
                pid = data.get("process_task_id")
                prefix = f"{step}({pid})" if pid else step
                _print(f"[{_now()}] {prefix}: {msg}")
            else:
                _print(f"[{_now()}] {step}: {data}")
            return False

        if step in ("to_sub_tasks", "decompose_text"):
            if self.verbose:
                _print(f"[{_now()}] {step}: {data}")
            return False

        if step in (
            "create_agent",
            "activate_agent",
            "deactivate_agent",
            "assign_task",
            "activate_toolkit",
            "deactivate_toolkit",
            "search_mcp",
        ):
            if self.verbose:
                _print(f"[{_now()}] {step}: {data}")
            return False

        if step in ("context_too_long",):
            _print(f"[{_now()}] error: {data}")
            return False

        if step in ("budget_not_enough",):
            _print(f"[{_now()}] error: budget not enough")
            return False

        if step in ("error",):
            if isinstance(data, dict):
                msg = data.get("message", data)
            else:
                msg = data
            _print(f"[{_now()}] error: {msg}")
            return False

        if step in ("end",):
            if isinstance(data, (dict, list)):
                _print(f"[{_now()}] end:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n")
            else:
                _print(f"[{_now()}] end:\n{data}\n")
            return True

        # Fallback
        if self.verbose:
            _print(f"[{_now()}] {step}: {data}")
        return False

    # ------------- Main loop -------------
    def run_interactive(self) -> None:
        _print("Commands: /followup <msg> | /followup --new-task-id <id> <msg> | /reply <msg> | /skip | /stop | /quit | /help")

        done = threading.Event()

        def _render_loop() -> None:
            while not done.is_set():
                try:
                    evt = self._events.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    if self.handle_event(evt):
                        done.set()
                except Exception as e:
                    _print(f"[{_now()}] render error: {e}")

        renderer = threading.Thread(target=_render_loop, name="eigent-render", daemon=True)
        renderer.start()

        try:
            while not done.is_set():
                try:
                    line = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    _print("\nExiting...")
                    return

                if not line:
                    continue

                if not line.startswith("/"):
                    _print("Commands must start with '/'. Try /help.")
                    continue

                try:
                    should_quit = self._handle_command(line)
                    if should_quit:
                        return
                except Exception as e:
                    _print(f"command error: {e}")
        finally:
            done.set()

    def _handle_command(self, line: str) -> bool:
        if self.project_id is None:
            raise RuntimeError("no active project_id (start_chat not called?)")

        parts = shlex.split(line)
        cmd = parts[0]

        if cmd in ("/help",):
            _print("Commands:")
            _print("  /followup <message>")
            _print("  /followup --new-task-id <task_id> <message>")
            _print("  /reply <message>              (answers last /ask)")
            _print("  /skip                         (stop current task but keep SSE for multi-turn)")
            _print("  /stop                         (stop chat/task)")
            _print("  /quit")
            return False

        if cmd in ("/quit",):
            return True

        if cmd == "/stop":
            self.delete_stop(self.project_id)
            _print("stop requested")
            return False

        if cmd == "/skip":
            self.post_skip_task(self.project_id)
            _print("skip requested")
            return False

        if cmd == "/followup":
            new_task_id: Optional[str] = None
            msg_parts: list[str] = []
            i = 1
            if i < len(parts) and parts[i] == "--new-task-id":
                if i + 1 >= len(parts):
                    raise RuntimeError("missing value for --new-task-id")
                new_task_id = parts[i + 1]
                i += 2
            msg_parts = parts[i:]
            if not msg_parts:
                raise RuntimeError("missing follow-up message")
            message = " ".join(msg_parts)
            self.post_followup(self.project_id, message, new_task_id=new_task_id)
            _print("followup queued")
            return False

        if cmd == "/reply":
            if len(parts) < 2:
                raise RuntimeError("missing reply text")
            reply = " ".join(parts[1:])
            if self.pending_ask is None:
                raise RuntimeError("no pending /ask; you can still reply by specifying agent in code if needed")
            self.post_human_reply(self.project_id, agent=self.pending_ask.agent, reply=reply)
            _print("reply sent")
            # keep last ask around in case multiple replies are needed
            return False

        raise RuntimeError(f"unknown command: {cmd}")


def build_chat_payload(args: argparse.Namespace) -> dict[str, Any]:
    project_id = args.project_id or _make_id("project")
    task_id = args.task_id or _make_id("task")

    payload: dict[str, Any] = {
        "task_id": task_id,
        "project_id": project_id,
        "question": args.question,
        "email": args.email,
        "attaches": args.attach or [],
        "model_platform": args.model_platform,
        "model_type": args.model_type,
        "api_key": args.api_key,
        "api_url": args.api_url,
        "language": args.language,
        "browser_port": args.browser_port,
        "max_retries": args.max_retries,
        "allow_local_system": args.allow_local_system,
        "installed_mcp": {"mcpServers": {}},
        "bun_mirror": args.bun_mirror,
        "uvx_mirror": args.uvx_mirror,
        "env_path": args.env_path,
        "new_agents": [],
        "extra_params": None,
        "search_config": None,
    }

    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive CLI for Eigent backend /chat SSE API")
    parser.add_argument("--base-url", default="http://localhost:5002", help="Backend base URL (default: http://localhost:5002)")
    parser.add_argument("--download-dir", default="./eigent_downloads", help="Where to copy files from write_file events")
    parser.add_argument("--verbose", action="store_true", help="Print verbose SSE events")

    parser.add_argument("--project-id", default=None, help="Project ID (defaults to random)")
    parser.add_argument("--task-id", default=None, help="Task ID (defaults to random)")
    parser.add_argument("--question", required=True, help="Initial user question")
    parser.add_argument("--email", required=True, help="User email (used for file save path on backend)")

    parser.add_argument("--model-platform", default=os.getenv("EIGENT_MODEL_PLATFORM", "openai-compatible-model"))
    parser.add_argument("--model-type", default=os.getenv("EIGENT_MODEL_TYPE", "gpt-4o-mini"))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"), help="Model API key (defaults to OPENAI_API_KEY)")
    parser.add_argument("--api-url", default=os.getenv("OPENAI_API_BASE_URL"), help="Model API base URL")
    parser.add_argument("--language", default="en")
    parser.add_argument("--browser-port", type=int, default=9222)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--allow-local-system", action="store_true", default=False)
    parser.add_argument("--env-path", default=None, help="Optional env file path for backend thread")
    parser.add_argument("--attach", action="append", default=[], help="Local file path to attach (repeatable)")
    parser.add_argument("--bun-mirror", default="")
    parser.add_argument("--uvx-mirror", default="")

    args = parser.parse_args()

    if not args.api_key:
        _eprint("Missing --api-key (or OPENAI_API_KEY).")
        return 2

    download_dir = Path(args.download_dir).expanduser()
    cli = EigentChatCli(base_url=args.base_url, download_dir=download_dir, verbose=args.verbose)

    payload = build_chat_payload(args)
    cli.project_id = payload["project_id"]
    cli.task_id = payload["task_id"]

    _print(f"Starting chat. project_id={cli.project_id} task_id={cli.task_id}")
    _print(f"SSE: POST {args.base_url.rstrip('/')}/chat")

    cli.start_stream(payload)
    try:
        cli.run_interactive()
    finally:
        cli.stop_stream()
        try:
            cli._client.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

