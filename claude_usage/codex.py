"""OpenAI Codex rate-limit collector (opt-in second provider).

Talks to the local ``codex`` CLI's ``app-server`` over stdio JSON-RPC:
``initialize`` -> ``initialized`` -> ``account/rateLimits/read``. The
response carries a ``rateLimits`` object with a ``primary`` (~5h) and
``secondary`` (weekly) window, each with ``usedPercent`` and ``resetsAt``
— the same shape as Claude's session/weekly pair, so the overlay can
render them with the exact same ring/bar primitives.

Spawning the app-server takes a couple of seconds, so results are cached
on disk (`~/.cache/claude-usage/codex_limits.json`) and only refreshed
every ``poll_seconds``. Between polls — and on RPC failure — the cache is
served, with expired windows clamped back to zero exactly like the Claude
sample-fallback path in ``collector.collect_all``.

Uses a background pipe reader and a bounded queue wait, which work on Windows,
Linux and macOS. A stalled or partial response cannot block widget refresh.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

RPC_TIMEOUT_SECONDS = 12
DEFAULT_POLL_SECONDS = 300
CACHE_PATH = Path.home() / ".cache" / "claude-usage" / "codex_limits.json"
STATUS_PATH = CACHE_PATH.with_name("codex_status.json")
_BIN_CANDIDATES = ("/opt/homebrew/bin/codex", "/usr/local/bin/codex")


def find_codex_bin() -> str | None:
    """Locate the ``codex`` CLI, preferring whatever is on PATH."""
    which = shutil.which("codex")
    if which:
        return which
    # Explorer-launched GUI apps can inherit a different PATH from terminal
    # sessions. Check the native Windows Codex installer location explicitly.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        candidate = os.path.join(
            local_app_data, "Programs", "OpenAI", "Codex", "bin", "codex.exe"
        )
        if os.path.isfile(candidate):
            return candidate
    for candidate in _BIN_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def _rate_limits_rpc(codex_bin: str, timeout: float = RPC_TIMEOUT_SECONDS) -> dict[str, Any] | None:
    """Query Codex with a single bounded deadline on every platform.

    A daemon reader consumes newline-delimited stdout in the background.
    Waiting on a queue (rather than select() on a pipe) works on Windows;
    killing the subprocess on timeout also unblocks a partial readline().
    """
    proc = subprocess.Popen(
        [codex_bin, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def send(obj: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        proc.stdin.flush()

    messages: queue.Queue[bytes | None] = queue.Queue()

    def read_lines() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                messages.put(line)
        except OSError:
            pass
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    result: dict[str, Any] | None = None
    try:
        send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {
                "name": "claude-usage-widget",
                "title": "Claude Usage Widget",
                "version": "0",
            }},
        })
        initialized = False
        while time.monotonic() < deadline:
            try:
                raw = messages.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                break
            if raw is None:
                break
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except (ValueError, AttributeError):
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == 1 and not initialized:
                initialized = True
                send({"jsonrpc": "2.0", "method": "initialized"})
                # Allow the app-server's handshake to settle, without
                # extending the overall RPC deadline.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.6, remaining))
                if time.monotonic() >= deadline:
                    break
                send({
                    "jsonrpc": "2.0", "id": 2,
                    "method": "account/rateLimits/read", "params": {},
                })
            elif msg.get("id") == 2 and initialized:
                value = msg.get("result")
                result = value if isinstance(value, dict) else None
                break
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for pipe in (proc.stdin, proc.stdout):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass
        reader.join(timeout=0.2)
    return result

def parse_rate_limits(payload: Any) -> dict[str, Any] | None:
    """Extract the two utilization windows from a rateLimits/read result.

    Returns ``{"session_pct", "session_reset", "weekly_pct", "weekly_reset"}``
    (pct 0..1, reset as unix seconds, 0 when absent), or None when the
    payload has no usable window data.
    """
    if not isinstance(payload, dict):
        return None
    limits = payload.get("rateLimits")
    if not isinstance(limits, dict):
        return None

    def window(block: Any) -> tuple[float, int] | None:
        if not isinstance(block, dict) or block.get("usedPercent") is None:
            return None
        try:
            pct = max(0.0, min(1.0, float(block["usedPercent"]) / 100.0))
        except (TypeError, ValueError):
            return None
        reset = block.get("resetsAt")
        try:
            reset_ts = int(reset) if reset is not None else 0
        except (TypeError, ValueError):
            reset_ts = 0
        if reset_ts > 10**12:  # milliseconds — normalise to seconds
            reset_ts //= 1000
        return pct, reset_ts

    # Window position is not a duration: weekly-only plans may put their
    # 10080-minute window in "primary" and leave "secondary" null.
    session = None
    weekly = None
    unknown = []
    for key in ("primary", "secondary"):
        block = limits.get(key)
        parsed = window(block)
        if parsed is None:
            continue
        duration = block.get("windowDurationMins")
        try:
            duration = int(duration)
        except (ValueError, TypeError):
            duration = None
        if duration == 300:
            session = parsed
        elif duration == 10080:
            weekly = parsed
        else:
            unknown.append(parsed)

    # Older app-server versions may omit durations; preserve their ordering.
    if unknown:
        if session is None:
            session = unknown.pop(0)
        if weekly is None and unknown:
            weekly = unknown.pop(0)
    if session is None and weekly is None:
        return None
    return {
        "session_pct": session[0] if session else 0.0,
        "session_reset": session[1] if session else 0,
        "weekly_pct": weekly[0] if weekly else 0.0,
        "weekly_reset": weekly[1] if weekly else 0,
    }


def _load_cache() -> dict[str, Any] | None:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _save_cache(payload: dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": time.time(), "payload": payload}, fh)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def _clamp_expired(parsed: dict[str, Any], now_ts: float) -> dict[str, Any]:
    """A window whose reset has passed has rolled over — show 0, not stale %."""
    out = dict(parsed)
    if out["session_reset"] and now_ts >= out["session_reset"]:
        out["session_pct"], out["session_reset"] = 0.0, 0
    if out["weekly_reset"] and now_ts >= out["weekly_reset"]:
        out["weekly_pct"], out["weekly_reset"] = 0.0, 0
    return out


def _report_status(status: dict[str, Any]) -> dict[str, Any]:
    """Write safe troubleshooting metadata, never tokens or raw RPC payloads."""
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps({
            "checked_at": time.time(),
            "available": status.get("available", False),
            "error": status.get("error", ""),
            "session_pct": status.get("session_pct", 0),
            "weekly_pct": status.get("weekly_pct", 0),
        }, indent=2), encoding="utf-8")
    except OSError:
        pass
    return status


def collect_codex(poll_seconds: int = DEFAULT_POLL_SECONDS) -> dict[str, Any]:
    """Return Codex utilization for the overlay; never raises.

    ``{"available": bool, "session_pct", "session_reset", "weekly_pct",
    "weekly_reset", "error": str}`` — available=False hides the Codex UI.
    """
    unavailable = {
        "available": False, "error": "",
        "session_pct": 0.0, "session_reset": 0,
        "weekly_pct": 0.0, "weekly_reset": 0,
    }
    codex_bin = find_codex_bin()
    if codex_bin is None:
        return _report_status({**unavailable, "error": "codex binary not found"})

    now_ts = time.time()
    cache = _load_cache()
    if cache is not None:
        age = now_ts - float(cache.get("fetched_at", 0) or 0)
        parsed = parse_rate_limits(cache.get("payload"))
        if parsed is not None and 0 <= age < poll_seconds:
            return _report_status({"available": True, "error": "", **_clamp_expired(parsed, now_ts)})

    payload = None
    try:
        payload = _rate_limits_rpc(codex_bin)
    except (OSError, ValueError, RuntimeError) as exc:
        return _report_status({**unavailable, "error": f"app-server failed: {type(exc).__name__}: {exc}"})
    parsed = parse_rate_limits(payload)
    if parsed is not None:
        assert isinstance(payload, dict)
        _save_cache(payload)
        return {"available": True, "error": "", **_clamp_expired(parsed, now_ts)}

    # RPC failed — fall back to any cache, however old, before giving up.
    if cache is not None:
        parsed = parse_rate_limits(cache.get("payload"))
        if parsed is not None:
            return _report_status({"available": True, "error": "rpc failed; serving cache",
                    **_clamp_expired(parsed, now_ts)})
    return _report_status({**unavailable, "error": "rateLimits/read returned no window data"})
