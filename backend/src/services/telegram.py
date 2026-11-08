"""Minimal Telegram Bot API client (stdlib only; calls run in a worker thread)."""

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from src.core.config import settings


class TelegramError(Exception):
    pass


def _call(method: str, payload: Dict[str, Any]) -> Any:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    url = f"{settings.TELEGRAM_API_BASE.rstrip('/')}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.load(response)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            raise TelegramError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise TelegramError(f"Telegram is unreachable: {e}") from e
    if not body.get("ok"):
        raise TelegramError(body.get("description", "Telegram API error"))
    return body["result"]


async def call(method: str, **payload) -> Any:
    return await asyncio.to_thread(_call, method, payload)


async def send_message(chat_id: str, text: str) -> None:
    # Telegram limits a message to 4096 characters; daily reports are far shorter.
    await call("sendMessage", chat_id=chat_id, text=text[:4096], parse_mode="HTML", disable_web_page_preview=True)


async def get_me() -> Dict[str, Any]:
    return await call("getMe")


async def recent_chats() -> List[Dict[str, str]]:
    """Chats that recently wrote to the bot — how an owner finds their chat id after pressing /start."""
    updates = await call("getUpdates", limit=100, allowed_updates=["message", "my_chat_member"])
    chats = {}
    for update in updates:
        message = update.get("message") or update.get("my_chat_member") or {}
        chat = message.get("chat")
        if not chat:
            continue
        title = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
        if chat.get("username"):
            title = f"{title} (@{chat['username']})" if title else f"@{chat['username']}"
        chats[str(chat["id"])] = {"chat_id": str(chat["id"]), "title": title or str(chat["id"]), "type": chat["type"]}
    return list(chats.values())
