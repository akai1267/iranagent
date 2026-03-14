import argparse
import asyncio
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession


async def export_string_session(session_file: str, api_id: int, api_hash: str) -> str:
    client = TelegramClient(session_file, api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Session file is not authorized. Re-auth locally first.")
        return StringSession.save(client.session)
    finally:
        await client.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a Telethon StringSession from a local .session file")
    parser.add_argument(
        "--session-file",
        default=os.environ.get("TELEGRAM_SESSION_FILE", "memory/telegram_session"),
        help="Path prefix for Telethon file session (without .session suffix)",
    )
    parser.add_argument(
        "--api-id",
        type=int,
        default=int(os.environ.get("TELEGRAM_API_ID", "0") or "0"),
        help="Telegram API ID",
    )
    parser.add_argument(
        "--api-hash",
        default=os.environ.get("TELEGRAM_API_HASH", ""),
        help="Telegram API hash",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.api_id or not args.api_hash:
        print("Missing --api-id/--api-hash (or TELEGRAM_API_ID/TELEGRAM_API_HASH)", file=sys.stderr)
        return 1

    session_base = Path(args.session_file)
    if not session_base.with_suffix(".session").exists():
        print(f"Session file not found: {session_base}.session", file=sys.stderr)
        return 1

    try:
        token = asyncio.run(export_string_session(str(session_base), int(args.api_id), str(args.api_hash)))
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to export session string: {exc}", file=sys.stderr)
        return 1

    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
