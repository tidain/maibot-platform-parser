# -*- coding: utf-8 -*-
"""OneBot HTTP sender for the MaiBot multi-platform parser plugin."""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger("plugin.multi_platform_parser.sender")


class ApiSettings:
    host: str
    port: int
    token: str
    bot_uin: str


MessageSegment = dict[str, Any]


async def send_text(message: dict[str, Any], text: str, api: ApiSettings) -> bool:
    return await _send_message(message, [{"type": "text", "data": {"text": text}}], api, timeout=30)


async def send_image(message: dict[str, Any], path: Path, api: ApiSettings) -> bool:
    return await _send_message(message, [{"type": "image", "data": {"file": _file_uri(path)}}], api, timeout=120)


async def send_video(message: dict[str, Any], path: Path, api: ApiSettings) -> bool:
    return await _send_message(message, [{"type": "video", "data": {"file": _file_uri(path)}}], api, timeout=300)


async def send_group_forward(
    message: dict[str, Any],
    nodes: list[list[MessageSegment]],
    api: ApiSettings,
) -> bool:
    group_id = _get_group_id(message)
    if not group_id:
        return False
    if not nodes:
        return True

    forward_nodes = [
        {
            "type": "node",
            "data": {
                "name": "麦麦解析",
                "uin": api.bot_uin or "10000",
                "content": node,
            },
        }
        for node in nodes
    ]
    return await _post_onebot(
        f"http://{api.host}:{api.port}/send_group_forward_msg",
        {"group_id": group_id, "messages": forward_nodes},
        api,
        timeout=120,
    )


def text_segment(text: str) -> MessageSegment:
    return {"type": "text", "data": {"text": text}}


def image_segment(path: Path) -> MessageSegment:
    return {"type": "image", "data": {"file": _file_uri(path)}}


async def _send_message(
    message: dict[str, Any],
    segments: list[MessageSegment],
    api: ApiSettings,
    *,
    timeout: int,
) -> bool:
    if _is_private_message(message):
        user_id = _get_user_id(message)
        if not user_id:
            logger.error("Cannot send private message: missing user id")
            return False
        url = f"http://{api.host}:{api.port}/send_private_msg"
        payload = {"user_id": user_id, "message": segments}
    else:
        group_id = _get_group_id(message)
        if not group_id:
            logger.error("Cannot send group message: missing group id")
            return False
        url = f"http://{api.host}:{api.port}/send_group_msg"
        payload = {"group_id": group_id, "message": segments}

    return await _post_onebot(url, payload, api, timeout=timeout)


async def _post_onebot(url: str, payload: dict[str, Any], api: ApiSettings, *, timeout: int) -> bool:
    token = str(getattr(api, "token", "") or "").strip()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                if response.status == 200:
                    return True

                if response.status in (401, 403) and token:
                    retry_url = f"{url}?access_token={urllib.parse.quote(token)}"
                    async with session.post(retry_url, json=payload, headers=headers, timeout=timeout) as retry:
                        if retry.status == 200:
                            return True
                        logger.error("OneBot retry failed: HTTP %s %s", retry.status, await retry.text())
                        return False

                logger.error("OneBot request failed: HTTP %s %s", response.status, await response.text())
                return False
    except asyncio.TimeoutError:
        logger.error("OneBot request timed out: %s", url)
        return False
    except Exception as exc:
        logger.error("OneBot request error: %s", exc)
        return False


def _file_uri(path: Path) -> str:
    value = str(path)
    if value.startswith(("http://", "https://", "file://")):
        return value
    return "file:///" + urllib.request.pathname2url(value).lstrip("/")


def _is_private_message(message: dict[str, Any]) -> bool:
    message_info = message.get("message_info", {})
    return bool(message_info) and message_info.get("group_info") is None


def _get_user_id(message: dict[str, Any]) -> str | None:
    message_info = message.get("message_info", {})
    user_info = message_info.get("user_info", {}) if isinstance(message_info, dict) else {}
    user_id = user_info.get("user_id") if isinstance(user_info, dict) else None
    return str(user_id) if user_id else None


def _get_group_id(message: dict[str, Any]) -> str | None:
    message_info = message.get("message_info", {})
    group_info = message_info.get("group_info") if isinstance(message_info, dict) else None
    group_id = group_info.get("group_id") if isinstance(group_info, dict) else None
    return str(group_id) if group_id else None
