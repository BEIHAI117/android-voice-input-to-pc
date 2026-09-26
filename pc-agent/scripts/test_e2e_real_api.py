"""Final acceptance: real ASR API -> Android app -> PC -> caret.

Opens a scratch Notepad window, long-presses the floating ball on the emulator,
and reads whatever comes back at the caret. Unlike test_e2e_emulator.py this
does not require a fixed phrase — the real recogniser sees whatever the
emulator's microphone picked up, so success just means "text arrived".
"""
from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def cls(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def kids(hwnd: int) -> list[int]:
    out: list[int] = []
    T = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(c, _):
        out.append(c)
        return True

    user32.EnumChildWindows(hwnd, T(cb), 0)
    return out


def read_edit(hwnd: int) -> str:
    n = user32.SendMessageW(hwnd, 0x000E, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, 0x000D, n + 1, ctypes.byref(buf))
    return buf.value


def find_notepad():
    tops: list[int] = []
    T = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        if user32.IsWindowVisible(h) and cls(h) == "Notepad":
            tops.append(h)
        return True

    user32.EnumWindows(T(cb), 0)
    if not tops:
        return None, None
    hwnd = tops[0]
    return hwnd, next((c for c in kids(hwnd) if cls(c) == "Edit"), None)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--serial", default="emulator-5554")
    p.add_argument("--ball", nargs=2, type=int, default=[97, 650])
    p.add_argument("--hold-ms", type=int, default=1200)
    p.add_argument("--expect", default="", help="exact text to require; empty = any non-blank")
    args = p.parse_args()

    subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
    time.sleep(1.0)
    proc = subprocess.Popen(["notepad.exe"])

    deadline = time.time() + 15
    hwnd = edit = None
    while time.time() < deadline:
        hwnd, edit = find_notepad()
        if hwnd and edit:
            break
        time.sleep(0.3)
    if not hwnd or not edit:
        print("FAIL: Notepad not found")
        proc.kill()
        return 1
    print(f"notepad hwnd={hwnd} edit={edit}")

    fg = user32.GetForegroundWindow()
    tid_fg = user32.GetWindowThreadProcessId(fg, None)
    tid_cur = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(tid_cur, tid_fg, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(tid_cur, tid_fg, False)
    time.sleep(0.6)

    import pyautogui

    pyautogui.FAILSAFE = False
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT((rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    pyautogui.click(pt.x, pt.y)
    time.sleep(0.5)

    x, y = args.ball
    print(f"long-press ({x},{y}) {args.hold_ms}ms -> real ASR API")
    subprocess.run(
        ["adb", "-s", args.serial, "shell", "input", "swipe",
         str(x), str(y), str(x), str(y), str(args.hold_ms)],
        capture_output=True,
    )

    got = ""
    for _ in range(30):
        time.sleep(1.0)
        got = read_edit(edit)
        if got.strip():
            break

    print(f"read back: {got!r}")
    ok = bool(args.expect and args.expect in got) if args.expect else bool(got.strip())

    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    time.sleep(0.8)
    try:
        proc.kill()
    except Exception:
        pass

    print()
    print(f"RESULT: {'ALL PASS' if ok else 'FAILURE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
