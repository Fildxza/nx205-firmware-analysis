"""
ui.py
-----
Branding and dark-theme console rendering for FILDZA MOD ROUTER.

Palette: charcoal background tone, white text, amber accents.
No third-party libraries: colours use ANSI escape codes. On Windows 10/11 the
virtual-terminal processing mode is enabled via ctypes so the codes render in
the standard console as well as Windows Terminal.

This is cosmetic only. Nothing here changes any file, firmware, or router.
"""

from __future__ import annotations

import os
import sys
from typing import List

# ---- Palette (256-colour ANSI) -------------------------------------------
_CHARCOAL_BG = "\x1b[48;5;236m"   # dark grey panel background
_RESET = "\x1b[0m"
_AMBER = "\x1b[38;5;214m"         # amber accent
_AMBER_B = "\x1b[1;38;5;214m"     # bold amber
_WHITE = "\x1b[38;5;255m"
_DIM = "\x1b[38;5;245m"           # muted grey ("charcoal" text)
_GREEN = "\x1b[38;5;78m"
_RED = "\x1b[38;5;203m"
_YELLOW = "\x1b[38;5;221m"

_WIDTH = 78
_USE_COLOR = True


def enable_windows_vt() -> None:
    """Turn on ANSI processing in the Windows console (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        # If this fails we simply fall back to plain text below.
        global _USE_COLOR
        _USE_COLOR = False


def set_color(enabled: bool) -> None:
    global _USE_COLOR
    _USE_COLOR = enabled


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _USE_COLOR else text


def amber(text: str) -> str:
    return _c(text, _AMBER)


def _status_color(ok: bool) -> str:
    return _GREEN if ok else _RED


# ---- Layout helpers -------------------------------------------------------
def _line(char: str = "-") -> str:
    return _c(char * _WIDTH, _DIM)


def banner() -> str:
    """ASCII brand header. Amber on a charcoal band."""
    title = "FILDZA MOD ROUTER"
    subtitle = "NX205 Firmware Inspector  -  read-only analysis toolkit"
    pad_title = title.center(_WIDTH)
    pad_sub = subtitle.center(_WIDTH)
    bar = "=" * _WIDTH
    parts = [
        _c(bar, _AMBER_B),
        _c(pad_title, _AMBER_B),
        _c(pad_sub, _WHITE),
        _c(bar, _AMBER_B),
    ]
    return "\n".join(parts)


def section(title: str) -> str:
    return "\n" + _c(f">> {title}", _AMBER_B) + "\n" + _line()


def kv(key: str, value: str, ok: bool | None = None) -> str:
    label = _c(f"  {key:<22}", _DIM)
    if ok is None:
        val = _c(str(value), _WHITE)
    else:
        val = _c(str(value), _status_color(ok))
    return f"{label}{val}"


def note(text: str, kind: str = "info") -> str:
    palette = {"info": _DIM, "warn": _YELLOW, "bad": _RED, "good": _GREEN}
    mark = {"info": "-", "warn": "!", "bad": "x", "good": "+"}.get(kind, "-")
    return _c(f"  [{mark}] {text}", palette.get(kind, _DIM))


def tile(label: str, value: str, kind: str = "info") -> str:
    palette = {"info": _WHITE, "warn": _YELLOW, "bad": _RED, "good": _GREEN}
    return _c(f" {value} ", _AMBER_B) + _c(label, palette.get(kind, _WHITE))


def footer() -> str:
    text = (
        "Read-only tool. It does not flash, modify, downgrade, decrypt, or "
        "execute firmware, and does not change router settings or device IDs."
    )
    wrapped = []
    words = text.split()
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > _WIDTH - 4:
            wrapped.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        wrapped.append(cur)
    body = "\n".join(_c("  " + ln, _DIM) for ln in wrapped)
    return "\n" + _line("=") + "\n" + body + "\n" + _line("=")
