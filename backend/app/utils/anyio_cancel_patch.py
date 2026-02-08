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
Optional monkey-patch for anyio's _deliver_cancellation to prevent CPU spin loops.

When request cancellation triggers anyio (e.g. via MCP/httpx), _deliver_cancellation
can reschedule itself indefinitely if tasks don't respond to CancelledError, causing
high CPU (see anyio#695, IBM/mcp-context-forge#2360). This patch caps the number of
delivery iterations so the loop exits after ~60ms instead of spinning forever.

Configuration (env):
- ANYIO_CANCEL_DELIVERY_PATCH_ENABLED: "true" to enable (default: "true")
- ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS: max iterations before giving up (default: 500)
"""
import logging
from typing import Any

from app.component.environment import env

logger = logging.getLogger(__name__)

_original_deliver_cancellation: Any = None
_patch_applied = False


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_int(value: str | None, default: int, min_val: int = 1, max_val: int = 10000) -> int:
    if value is None:
        return default
    try:
        n = int(value.strip())
        return max(min_val, min(max_val, n))
    except ValueError:
        return default


def apply_anyio_cancel_delivery_patch() -> bool:
    """
    Apply the anyio _deliver_cancellation monkey-patch if enabled.

    Idempotent. Safe to call at app startup. Uses env:
    ANYIO_CANCEL_DELIVERY_PATCH_ENABLED, ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS.

    Returns:
        True if patch was applied (or already applied), False if disabled or failed.
    """
    global _original_deliver_cancellation, _patch_applied  # noqa: PLW0603

    if _patch_applied:
        return True

    if not _parse_bool(env("ANYIO_CANCEL_DELIVERY_PATCH_ENABLED"), default=True):
        logger.debug(
            "anyio _deliver_cancellation patch disabled. "
            "Set ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=true to mitigate CPU spin on cancel."
        )
        return False

    try:
        from anyio._backends._asyncio import CancelScope

        _original_deliver_cancellation = CancelScope._deliver_cancellation
        max_iterations = _parse_int(env("ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS"), 500)

        def _patched_deliver_cancellation(self: Any, origin: Any) -> bool:
            if not hasattr(origin, "_delivery_iterations"):
                origin._delivery_iterations = 0  # type: ignore[attr-defined]
            origin._delivery_iterations += 1  # type: ignore[attr-defined]
            if origin._delivery_iterations > max_iterations:  # type: ignore[attr-defined]
                logger.warning(
                    "anyio cancel delivery exceeded %s iterations - giving up to prevent CPU spin. "
                    "Some tasks may not have been properly cancelled.",
                    max_iterations,
                )
                if hasattr(self, "_cancel_handle") and self._cancel_handle is not None:
                    self._cancel_handle = None  # type: ignore[attr-defined]
                return False
            return _original_deliver_cancellation(self, origin)

        CancelScope._deliver_cancellation = _patched_deliver_cancellation  # type: ignore[method-assign]
        _patch_applied = True
        logger.info(
            "anyio _deliver_cancellation patch enabled (max_iterations=%s). "
            "Mitigates CPU spin on request cancel (anyio#695).",
            max_iterations,
        )
        return True
    except Exception as e:
        logger.warning("Failed to apply anyio _deliver_cancellation patch: %s", e)
        return False
