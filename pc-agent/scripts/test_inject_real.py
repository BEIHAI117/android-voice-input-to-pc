"""Real (non-dry-run) injection acceptance test.

Opens a scratch Notepad window as the caret target, injects a marker string
through both modes, then reads the window text back via WM_GETTEXT to prove the
characters actually landed at the caret. Closes the window without saving.

Note: synthetic input is subject to Windows UIPI — the test must run at the
same or higher integrity level as the target window (i.e. not from a sandbox
that drops SendInput).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ctypes
from ctypes import wintypes

import pyautogui

pyautogui.FAILSAFE = False

from agent.inject import inject_text

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

_MARKER_A = "PhoneMic剪贴板注入测试123"
_MARKER_B = "PhoneMic逐字注入测试456"


def _cls(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _children(hwnd: int) -> list[int]:
    out: list[int] = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(child, _):
        out.append(child)
        return True

    user32.EnumChildWindows(hwnd, proc_t(cb), 0)
    return out


def _find_notepad() -> tuple[int | None, int | None]:
    top: list[int] = []
    enum_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _cls(hwnd) == "Notepad":
            top.append(hwnd)
        return True

    user32.EnumWindows(enum_t(cb), 0)
    if not top:
        return None, None
    hwnd = top[0]
    edit = next((c for c in _children(hwnd) if _cls(c) == "Edit"), None)
    return hwnd, edit


def _force_focus(hwnd: int) -> None:
    fg = user32.GetForegroundWindow()
    tid_fg = user32.GetWindowThreadProcessId(fg, None)
    tid_cur = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(tid_cur, tid_fg, True)
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        user32.AttachThreadInput(tid_cur, tid_fg, False)
    time.sleep(0.5)


def main() -> int:
    # Clear any Notepad left over from a previous run, otherwise we may lock
    # onto a stale window and inject into the wrong target.
    subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
    time.sleep(1.0)

    proc = subprocess.Popen(["notepad.exe"])
    deadline = time.time() + 15
    hwnd = edit = None
    while time.time() < deadline:
        hwnd, edit = _find_notepad()
        if hwnd and edit:
            break
        time.sleep(0.3)

    if not hwnd or not edit:
        print("FAIL: could not find the Notepad window + Edit child")
        proc.kill()
        return 1
    print(f"target: hwnd={hwnd} edit={edit} title={_title(hwnd)!r}")

    _force_focus(hwnd)

    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT((rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    pyautogui.click(pt.x, pt.y)  # seat the caret in the edit control
    time.sleep(0.5)
    print(f"focus check: foreground==target -> {user32.GetForegroundWindow() == hwnd}")

    inject_text(_MARKER_A, mode="clipboard", paste_delay_ms=250)
    time.sleep(1.2)
    got_a = _read(edit)
    ok_a = _MARKER_A in got_a
    print(f"clipboard mode -> {'PASS' if ok_a else 'FAIL'}  read back {got_a!r}")

    pyautogui.click(pt.x, pt.y)
    time.sleep(0.4)
    inject_text(_MARKER_B, mode="type", char_delay_ms=8)
    time.sleep(1.2)
    got_b = _read(edit)
    ok_b = _MARKER_B in got_b
    print(f"type mode      -> {'PASS' if ok_b else 'FAIL'}  read back {got_b!r}")

    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    time.sleep(1.0)
    try:
        proc.kill()
    except Exception:
        pass

    print()
    print(f"RESULT: {'ALL PASS' if (ok_a and ok_b) else 'FAILURE'}")
    return 0 if (ok_a and ok_b) else 1


def _read(hwnd: int) -> str:
    # GetWindowText does not work cross-process for controls (only captions),
    # so the text must be fetched with an explicit WM_GETTEXT SendMessage.
    n = user32.SendMessageW(hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, 0x000D, n + 1, ctypes.byref(buf))  # WM_GETTEXT
    return buf.value


if __name__ == "__main__":
    raise SystemExit(main())
