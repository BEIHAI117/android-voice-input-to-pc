"""``python -m agent`` — start the PhoneMic PC agent."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import MODE_CLIPBOARD, MODE_TYPE, Config, data_dir
from .server import run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phonemic-agent",
        description="PhoneMic PC agent — injects text received from the phone at the caret.",
    )
    p.add_argument("--host", help="bind address (default 0.0.0.0)")
    p.add_argument("--port", type=int, help="listen port (default 8765)")
    p.add_argument("--name", help="device name shown on the phone")
    p.add_argument(
        "--mode",
        choices=[MODE_CLIPBOARD, MODE_TYPE],
        help="text injection mode: clipboard (Ctrl+V) or type (real keystrokes)",
    )
    p.add_argument("--encrypt", action="store_true", help="enable NaCl payload encryption")
    p.add_argument("--no-encrypt", action="store_true", help="disable payload encryption")
    p.add_argument("--dry-run", action="store_true", help="do not touch the keyboard/clipboard")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    # Always keep a file log: after a crash or an unattended reboot it is the
    # only way to see what happened. Rotated so it cannot grow without bound.
    try:
        from logging.handlers import RotatingFileHandler

        logfile = data_dir() / "agent.log"
        filehandler = RotatingFileHandler(
            logfile, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        filehandler.setFormatter(fmt)
        root.addHandler(filehandler)
    except OSError:
        pass  # console logging still works

    cfg = Config.load()
    # Only durable preferences are written back to config.json. Debug switches
    # like --dry-run are per-run: persisting them silently turns every later
    # launch into a dry run.
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    if args.name:
        cfg.device_name = args.name
    if args.mode:
        cfg.inject_mode = args.mode
    if args.encrypt:
        cfg.encrypt = True
    if args.no_encrypt:
        cfg.encrypt = False
    cfg.dry_run = bool(args.dry_run)  # never persisted
    cfg.save()

    if cfg.encrypt:
        try:
            import nacl  # noqa: F401
        except ImportError:
            print("--encrypt needs pynacl:  pip install pynacl", file=sys.stderr)
            return 2

    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
