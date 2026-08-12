"""Thin async client for the funnel Apps Script endpoint.

The same spreadsheet backs `sheets_writer` (orders); this module talks to the
funnel actions (`users`, `events`, `content`). Every call is a POST carrying an
`action` field — Apps Script `doPost` branches on it and falls back to the
legacy order payload when the field is absent.

The shared secret travels in the POST body, never in the query string: URLs end
up in access logs, proxies and debug dumps, and this project has already leaked
a live token that way once.
"""

import asyncio
import os
from typing import Any

import aiohttp

from utils.logger import log_agent_action

_URL = os.getenv("SHEETS_SCRIPT_URL", "")
_SECRET = os.getenv("SHEETS_SECRET", "")

_TIMEOUT = aiohttp.ClientTimeout(total=20)
_RETRY_DELAYS = (1.0, 3.0)  # a third attempt is not worth the chat latency

_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()


def is_configured() -> bool:
    """True only when the endpoint can actually be authenticated against."""
    if not _URL:
        return False
    if not _SECRET:
        log_agent_action(
            "Sheets",
            "SHEETS_SCRIPT_URL is set but SHEETS_SECRET is empty — refusing to call "
            "the endpoint unauthenticated",
            level="ERROR",
        )
        return False
    return True


async def _get_session() -> aiohttp.ClientSession:
    """One pooled session for the process — TLS handshakes cost real latency."""
    global _session
    async with _session_lock:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return _session


async def close() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


async def call(action: str, payload: dict[str, Any] | None = None) -> Any:
    """POST an action and return the decoded JSON body, or None on failure.

    Never raises for network or protocol errors: the funnel must keep serving
    from cache when Sheets is down. `asyncio.CancelledError` deliberately
    propagates so callers can restore whatever they were flushing.
    """
    if not is_configured():
        return None

    body = {"action": action, "secret": _SECRET, **(payload or {})}

    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            session = await _get_session()
            async with session.post(_URL, json=body) as resp:
                if resp.status >= 500:
                    raise aiohttp.ClientError(f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
                if isinstance(data, dict) and data.get("error"):
                    log_agent_action(
                        "Sheets",
                        f"⚠️ {action} rejected: {str(data['error'])[:120]}",
                        level="WARNING",
                    )
                    return None
                return data
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            log_agent_action("Sheets", f"❌ {action} failed: {e}", level="ERROR")
            return None
    return None
