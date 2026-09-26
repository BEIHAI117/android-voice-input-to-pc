"""Text injection at the current caret position.

Two modes:

  clipboard  copy to the clipboard and press Ctrl+V.
             Reliable for every language including CJK — the default.

  type       real keystrokes via Win32 SendInput with KEYEVENTF_UNICODE.
             Needed where Ctrl+V is swallowed or means something else
             (terminals, SSH sessions, vim in insert mode, remote desktops).

The "type" mode is UTF-16 code-unit based so astral-plane characters
(emoji, rare CJK ext-B) are emitted as surrogate pairs instead of raising.
"""
from __future__ import annotations

import sys
import time

from .config import MODE_CLIPBOARD, MODE_TYPE

# ----------------------------------------------------------------- typing ---

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]

    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004
    _SendInput = ctypes.windll.user32.SendInput

    def _send_char(code_unit: int) -> None:
        for up in (False, True):
            ki = _KEYBDINPUT(
                0,
                code_unit,
                _KEYEVENTF_UNICODE | (_KEYEVENTF_KEYUP if up else 0),
                0,
                ULONG_PTR(0),
            )
            _SendInput(1, ctypes.byref(_INPUT(_INPUT_KEYBOARD, _INPUTUNION(ki))), ctypes.sizeof(_INPUT))

    def type_text(text: str, char_delay_ms: int = 0) -> None:
        delay = char_delay_ms / 1000.0
        for ch in text:
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                _send_char(units[i] | (units[i + 1] << 8))
            if delay:
                time.sleep(delay)

else:  # pragma: no cover - non-Windows fallback

    def type_text(text: str, char_delay_ms: int = 0) -> None:
        raise NotImplementedError("character-level typing is only implemented on Windows")


# -------------------------------------------------------------- clipboard ---

def paste_text(text: str, paste_delay_ms: int = 80) -> None:
    import pyautogui
    import pyperclip

    # PyAutoGUI's fail-safe aborts whenever the pointer sits in a screen corner.
    # This agent never moves the mouse on its own, so a corner-positioned cursor
    # must not be able to block an explicit paste request from the phone.
    pyautogui.FAILSAFE = False

    previous = None
    try:
        previous = pyperclip.paste()
    except Exception:
        pass

    pyperclip.copy(text)
    time.sleep(max(paste_delay_ms, 0) / 1000.0)
    pyautogui.hotkey("ctrl", "v")

    # Restore the user's clipboard shortly after so we do not hijack it.
    if previous is not None:
        def _restore() -> None:
            time.sleep(1.5)
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy(previous)
            except Exception:
                pass

        import threading

        threading.Thread(target=_restore, daemon=True).start()


# ------------------------------------------------------------- public API ---

def inject_text(
    text: str,
    mode: str = MODE_CLIPBOARD,
    char_delay_ms: int = 0,
    paste_delay_ms: int = 80,
    dry_run: bool = False,
) -> str:
    """Inject *text* at the caret. Returns the mode actually used."""
    if not text:
        return mode

    if mode not in (MODE_CLIPBOARD, MODE_TYPE):
        raise ValueError(f"unknown inject mode: {mode}")

    if dry_run:
        preview = text if len(text) <= 80 else text[:77] + "..."
        print(f"[dry-run] mode={mode} chars={len(text)} text={preview!r}")
        return mode

    if mode == MODE_TYPE:
        type_text(text, char_delay_ms=char_delay_ms)
    else:
        paste_text(text, paste_delay_ms=paste_delay_ms)
    return mode


def inject_hotkey(*keys: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] hotkey={'+'.join(keys)}")
        return
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.hotkey(*keys)
