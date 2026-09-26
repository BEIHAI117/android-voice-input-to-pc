"""Full-loop acceptance test: emulator long-press -> PC caret injection.

Opens a scratch Notepad window as the caret target, triggers the floating ball
on the connected Android emulator via adb, and reads the injected text back
with WM_GETTEXT to prove the whole chain works end to end.

    python scripts/test_e2e_emulator.py --serial emulator-5554 --ball 97 650
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

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E


def cls(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def children(hwnd: int) -> list[int]:
    out: list[int] = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(child, _):
        out.append(child)
        return True

    user32.EnumChildWindows(hwnd, proc_t(cb), 0)
    return out


def read_edit(hwnd: int) -> str:
    n = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.byref(buf))
    return buf.value


def find_notepad():
    top: list[int] = []
    enum_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and cls(hwnd) == "Notepad":
            top.append(hwnd)
        return True

    user32.EnumWindows(enum_t(cb), 0)
    if not top:
        return None, None
    hwnd = top[0]
    return hwnd, next((c for c in children(hwnd) if cls(c) == "Edit"), None)


def force_focus(hwnd: int) -> None:
    fg = user32.GetForegroundWindow()
    tid_fg = user32.GetWindowThreadProcessId(fg, None)
    tid_cur = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(tid_cur, tid_fg, True)
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        user32.AttachThreadInput(tid_cur, tid_fg, False)
    time.sleep(0.6)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--serial", default="emulator-5554")
    p.add_argument("--ball", nargs=2, type=int, default=[97, 650])
    p.add_argument("--expect", default="你好这是来自模拟器的测试文本")
    p.add_argument("--hold-ms", type=int, default=800)
    args = p.parse_args()

    adb = ["adb", "-s", args.serial]

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
        print("FAIL: Notepad window not found")
        proc.kill()
        return 1

    print(f"target notepad hwnd={hwnd} edit={edit}")
    force_focus(hwnd)

    import pyautogui

    pyautogui.FAILSAFE = False
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT((rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    pyautogui.click(pt.x, pt.y)
    time.sleep(0.5)

    x, y = args.ball
    print(f"long-press floating ball at ({x},{y}) for {args.hold_ms} ms")
    subprocess.run(
        adb + ["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(args.hold_ms)],
        capture_output=True,
    )

    print("waiting for the round trip ...")
    got = ""
    for _ in range(20):
        time.sleep(1.0)
        got = read_edit(edit)
        if args.expect in got:
            break

    print(f"read back: {got!r}")
    ok = args.expect in got

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
