"""QQ 空间原媒体接口与 SnowLuma 动态凭证支持。

这里只实现万能解析器需要的只读能力：
- 优先从 SnowLuma OneBot HTTP ``get_credentials`` 动态获取 qzone.qq.com 凭证；
- SnowLuma 不可用时自动回退插件手动 Cookie；
- 基于当前 p_skey / SnowLuma csrf_token 调用照片动态与 floatview 接口；
- 登录态疑似失效时强制向 SnowLuma 刷新一次并自动重试；
- 保存服务端刷新出的 qq_photo_key；
- 为 qpic / photo.qq.com 媒体下载构造必要请求头。

QQ 空间 CGI 协议行为按公开网页请求独立实现；SnowLuma 调用只使用其
OneBot HTTP action，不读取 SnowLuma 私有文件或进程内存。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time
from typing import Any

import json5
from aiohttp import ClientError, ClientSession
import logging

logger = logging.getLogger("plugin.multi_platform_parser.core")

from .cookie import CookieJar


@dataclass(slots=True, frozen=True)
class SnowLumaCredentials:
    """SnowLuma ``get_credentials`` 返回的 QQ Web 凭证。"""

    cookies: str
    token: int = 0
    csrf_token: int = 0


@dataclass(slots=True, frozen=True)
class QZoneAuth:
    """调用 QQ 空间 CGI 所需的登录态。"""

    uin_cookie: str
    uin: str
    p_skey: str
    gtk: int


@dataclass(slots=True)
class QZoneMediaDetail:
    """浮层接口返回的一项媒体详情。"""

    pic_key: str | None = None
    raw_url: str | None = None
    url: str | None = None
    preview_url: str | None = None
    is_video: bool = False
    video_download_url: str | None = None
    video_play_url: str | None = None
    video_cover_url: str | None = None
    video_duration: float = 0.0

    @property
    def best_image_url(self) -> str | None:
        return self.raw_url or self.url or self.preview_url

    @property
    def best_video_url(self) -> str | None:
        return self.video_download_url or self.video_play_url


def qzone_gtk(p_skey: str) -> int:
    """QQ 空间 hash33/g_tk。"""
    value = 5381
    for char in p_skey:
        value += (value << 5) + ord(char)
    return value & 0x7FFFFFFF


def _raw_uin(value: str) -> str:
    value = str(value or "").strip()
    return value[1:] if value.startswith("o") else value


def _first_string(mapping: dict[str, Any] | None, *keys: str) -> str | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_cookie_header(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in str(value or "").replace("\r", "").replace("\n", "").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, cookie_value = item.split("=", 1)
        name = name.strip()
        if name:
            result[name] = cookie_value.strip()
    return result


class SnowLumaCredentialProvider:
    """通过 SnowLuma OneBot HTTP API 动态获取 qzone.qq.com Cookie。

    Provider 只在内存中缓存短时间凭证。强制刷新时会重新请求 SnowLuma，
    由 SnowLuma 使用当前已登录 QQ 的 clientKey / PSKey 链路生成最新凭证。
    """

    def __init__(
        self,
        session: ClientSession,
        *,
        base_url: str,
        access_token: str = "",
        cache_seconds: int = 300,
    ) -> None:
        self.session = session
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.access_token = str(access_token or "").strip()
        self.cache_seconds = max(0, int(cache_seconds or 0))
        self._cached: SnowLumaCredentials | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()
        self.last_error = ""

    @property
    def enabled(self) -> bool:
        return self.base_url.startswith(("http://", "https://"))

    def invalidate(self) -> None:
        self._cached = None
        self._cached_at = 0.0

    def _cache_valid(self) -> bool:
        if self._cached is None:
            return False
        if self.cache_seconds <= 0:
            return False
        return (time.monotonic() - self._cached_at) < self.cache_seconds

    async def get(self, *, force: bool = False) -> SnowLumaCredentials | None:
        if not self.enabled:
            return None
        if not force and self._cache_valid():
            return self._cached

        async with self._lock:
            if not force and self._cache_valid():
                return self._cached
            credentials = await self._fetch()
            if credentials is not None:
                self._cached = credentials
                self._cached_at = time.monotonic()
                self.last_error = ""
            elif force:
                self.invalidate()
            return credentials

    async def _fetch(self) -> SnowLumaCredentials | None:
        url = f"{self.base_url}/get_credentials"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            # 本地 SnowLuma HTTP 不继承万能解析器的媒体代理设置。
            async with self.session.post(
                url,
                json={"domain": "qzone.qq.com"},
                headers=headers,
            ) as response:
                if response.status >= 400:
                    self.last_error = f"HTTP {response.status}"
                    return None
                payload = await response.json(content_type=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = type(exc).__name__
            return None

        if not isinstance(payload, dict):
            self.last_error = "响应不是对象"
            return None
        if str(payload.get("status") or "").lower() in {"failed", "error"}:
            self.last_error = str(payload.get("message") or payload.get("wording") or "调用失败")
            return None
        try:
            retcode = int(payload.get("retcode", 0) or 0)
        except (TypeError, ValueError):
            retcode = -1
        if retcode != 0:
            self.last_error = str(payload.get("message") or payload.get("wording") or f"retcode={retcode}")
            return None

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        cookies = str(data.get("cookies") or "").strip()
        cookie_map = _parse_cookie_header(cookies)
        if not cookie_map.get("p_skey") or not (cookie_map.get("uin") or cookie_map.get("p_uin")):
            self.last_error = "返回 Cookie 缺少 uin/p_uin 或 p_skey"
            return None

        def as_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError, OverflowError):
                return 0

        return SnowLumaCredentials(
            cookies=cookies,
            token=as_int(data.get("token")),
            csrf_token=as_int(data.get("csrf_token")),
        )


class QZoneApiClient:
    """只读 QQ 空间媒体详情客户端。"""

    FLOATVIEW_URL = (
        "https://user.qzone.qq.com/proxy/domain/photo.qzone.qq.com/"
        "fcgi-bin/cgi_floatview_photo_list_v2"
    )
    PICFEED_URL = (
        "https://user.qzone.qq.com/proxy/domain/ic2.qzone.qq.com/cgi-bin/feeds/"
        "feeds2_html_picfeed_qqtab"
    )

    def __init__(
        self,
        session: ClientSession,
        cookie_jar: CookieJar | None,
        *,
        proxy: str | None = None,
        credential_provider: SnowLumaCredentialProvider | None = None,
    ) -> None:
        self.session = session
        self.cookie_jar = cookie_jar
        self.proxy = proxy
        self.credential_provider = credential_provider
        self._runtime_cookies: dict[str, str] = {}
        self._runtime_gtk = 0
        self._credential_source = "manual"

    @property
    def credential_source(self) -> str:
        return self._credential_source

    async def ensure_auth(self, *, force_refresh: bool = False) -> bool:
        """确保存在可用登录态；SnowLuma 失败时保留手动 Cookie fallback。"""
        provider = self.credential_provider
        if provider is not None and provider.enabled:
            credentials = await provider.get(force=force_refresh)
            if credentials is not None:
                self._runtime_cookies = _parse_cookie_header(credentials.cookies)
                self._runtime_gtk = credentials.csrf_token or credentials.token
                self._credential_source = "snowluma"
                return self.auth() is not None
            if force_refresh:
                self._runtime_cookies = {}
                self._runtime_gtk = 0

        if self._manual_auth() is not None:
            self._credential_source = "manual"
            return True
        return False

    def _manual_auth(self) -> QZoneAuth | None:
        if self.cookie_jar is None:
            return None
        cookies = self.cookie_jar.get(domain="user.qzone.qq.com")
        p_skey = str(cookies.get("p_skey") or "").strip()
        uin_cookie = str(cookies.get("uin") or cookies.get("p_uin") or "").strip()
        uin = _raw_uin(uin_cookie)
        if not uin or not p_skey:
            return None
        return QZoneAuth(
            uin_cookie=uin_cookie,
            uin=uin,
            p_skey=p_skey,
            gtk=qzone_gtk(p_skey),
        )

    def auth(self) -> QZoneAuth | None:
        cookies = self._runtime_cookies
        p_skey = str(cookies.get("p_skey") or "").strip()
        uin_cookie = str(cookies.get("uin") or cookies.get("p_uin") or "").strip()
        uin = _raw_uin(uin_cookie)
        if uin and p_skey:
            return QZoneAuth(
                uin_cookie=uin_cookie,
                uin=uin,
                p_skey=p_skey,
                gtk=self._runtime_gtk or qzone_gtk(p_skey),
            )
        return self._manual_auth()

    @property
    def available(self) -> bool:
        return self.auth() is not None

    def _cookie_header(self) -> str:
        # 手动 Cookie / qq_photo_key 作为底层，SnowLuma 最新登录态覆盖同名项。
        merged: dict[str, str] = {}
        if self.cookie_jar is not None:
            merged.update(self.cookie_jar.get(domain="user.qzone.qq.com"))
        merged.update(self._runtime_cookies)
        return "; ".join(f"{key}={value}" for key, value in merged.items())

    def api_headers(self, referer: str = "https://user.qzone.qq.com/") -> dict[str, str]:
        headers = {
            "Referer": referer,
            "Origin": "https://user.qzone.qq.com",
            "Accept": "application/json,text/javascript,*/*;q=0.8",
        }
        if cookie := self._cookie_header():
            headers["Cookie"] = cookie
        return headers

    def media_headers(self, referer: str = "https://user.qzone.qq.com/") -> dict[str, str]:
        headers = {
            "Referer": referer,
            "Origin": "https://user.qzone.qq.com",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if cookie := self._cookie_header():
            headers["Cookie"] = cookie
        return headers

    def _update_cookies(self, response: Any) -> None:
        if self.cookie_jar is None:
            return
        try:
            values = response.headers.getall("Set-Cookie", [])
        except Exception:
            values = []
        if values:
            self.cookie_jar.update_from_response(list(values))

    @staticmethod
    def _normalize_duration(value: Any) -> float:
        try:
            duration = float(value or 0)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if duration < 0:
            return 0.0
        if duration > 24 * 60 * 60:
            duration /= 1000
        return duration

    @classmethod
    def _detail_from_photo(cls, photo: dict[str, Any]) -> QZoneMediaDetail:
        video_info = photo.get("video_info")
        if not isinstance(video_info, dict):
            video_info = {}

        is_video = bool(photo.get("is_video"))
        return QZoneMediaDetail(
            pic_key=_first_string(photo, "picKey", "pic_key", "lloc", "id"),
            raw_url=_first_string(photo, "raw", "raw_url", "origin", "origin_url"),
            url=_first_string(photo, "url", "big_url", "large_url"),
            preview_url=_first_string(photo, "pre", "preview", "thumb", "thumb_url"),
            is_video=is_video,
            video_download_url=_first_string(
                video_info, "download_url", "downloadUrl", "raw_url"
            ),
            video_play_url=_first_string(video_info, "video_url", "videoUrl", "url"),
            video_cover_url=(
                _first_string(video_info, "cover_url", "cover", "pic_url")
                or _first_string(photo, "pre", "url")
            ),
            video_duration=cls._normalize_duration(
                video_info.get("duration")
                or video_info.get("video_time")
                or photo.get("videotime")
            ),
        )

    @staticmethod
    async def _read_object_response(response: Any) -> dict[str, Any] | None:
        text = await response.text()
        stripped = text.strip()
        if not stripped:
            return None
        try:
            value = json.loads(stripped)
            return value if isinstance(value, dict) else None
        except (json.JSONDecodeError, TypeError):
            try:
                value = json5.loads(stripped)
                return value if isinstance(value, dict) else None
            except (ValueError, TypeError):
                pass

        left = stripped.find("(")
        right = stripped.rfind(")")
        if left >= 0 and right > left:
            inner = stripped[left + 1 : right].strip()
            try:
                value = json.loads(inner)
                return value if isinstance(value, dict) else None
            except (json.JSONDecodeError, TypeError):
                try:
                    value = json5.loads(inner)
                    return value if isinstance(value, dict) else None
                except (ValueError, TypeError):
                    return None
        return None

    @staticmethod
    def _looks_like_auth_failure(payload: dict[str, Any] | None, status: int = 200) -> bool:
        if status in {401, 403}:
            return True
        if not isinstance(payload, dict):
            return True
        message = " ".join(
            str(payload.get(key) or "")
            for key in ("message", "msg", "wording", "error", "em")
        ).lower()
        if any(
            token in message
            for token in (
                "login",
                "not logged",
                "skey",
                "p_skey",
                "cookie",
                "登录",
                "未登录",
                "登陆",
                "凭证",
                "鉴权",
            )
        ):
            return True
        try:
            code = int(payload.get("code", payload.get("ret", 0)) or 0)
        except (TypeError, ValueError):
            code = 0
        # QQ 空间 Web CGI 常见“需要登录/登录态失效”返回值。
        return code == -3000

    async def _maybe_refresh_after_failure(
        self, payload: dict[str, Any] | None, status: int
    ) -> bool:
        provider = self.credential_provider
        if provider is None or not provider.enabled:
            return False
        if not self._looks_like_auth_failure(payload, status):
            return False
        provider.invalidate()
        refreshed = await self.ensure_auth(force_refresh=True)
        if refreshed:
            logger.info("[QZone] SnowLuma 凭证已刷新，正在重试 QQ 空间媒体接口")
        return refreshed

    async def get_photo_feed(
        self,
        *,
        host_uin: str,
        begintime: int = 0,
    ) -> dict[str, Any] | None:
        """读取照片/视频动态流的一页。"""
        host_uin = _raw_uin(host_uin)
        if not host_uin:
            return None

        for attempt in range(2):
            if not await self.ensure_auth(force_refresh=False):
                return None
            auth = self.auth()
            if auth is None:
                return None
            params = {
                "g_tk": auth.gtk,
                "t": int(time.time() * 1000),
                "uin": auth.uin,
                "hostUin": host_uin,
                "fuin": host_uin,
                "appid": 4,
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "begintime": max(0, int(begintime or 0)),
            }
            try:
                async with self.session.get(
                    self.PICFEED_URL,
                    params=params,
                    headers=self.api_headers(f"https://user.qzone.qq.com/{host_uin}/main"),
                    proxy=self.proxy,
                ) as response:
                    self._update_cookies(response)
                    status = response.status
                    if status >= 400:
                        payload = None
                    else:
                        payload = await self._read_object_response(response)
            except asyncio.CancelledError:
                raise
            except (ClientError, ValueError, TypeError):
                return None

            if attempt == 0 and await self._maybe_refresh_after_failure(payload, status):
                continue
            return payload if status < 400 else None
        return None

    @staticmethod
    def find_feed(
        payload: dict[str, Any] | None,
        *,
        cell_id: str = "",
        timestamp: int | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        feeds = data.get("feeds") if isinstance(data, dict) else None
        if not isinstance(feeds, list):
            return None

        normalized_cell = str(cell_id or "").strip()
        target_time = int(timestamp or 0)
        if normalized_cell:
            for feed in feeds:
                if not isinstance(feed, dict):
                    continue
                keys = (feed.get("skey"), feed.get("cellid"), feed.get("tid"), feed.get("id"))
                if any(str(value or "") == normalized_cell for value in keys):
                    return feed
        if target_time:
            for feed in feeds:
                if not isinstance(feed, dict):
                    continue
                try:
                    feed_time = int(feed.get("time") or feed.get("abstime") or 0)
                except (TypeError, ValueError):
                    continue
                if feed_time == target_time:
                    return feed
        return None

    async def get_media_detail(
        self,
        *,
        host_uin: str,
        topic_id: str,
        pic_key: str,
    ) -> QZoneMediaDetail | None:
        """通过 floatview 精确读取单个照片/视频详情。"""
        if not host_uin or not topic_id or not pic_key:
            return None

        payload: dict[str, Any] | None = None
        for attempt in range(2):
            if not await self.ensure_auth(force_refresh=False):
                return None
            auth = self.auth()
            if auth is None:
                return None
            params = {
                "g_tk": auth.gtk,
                "topicId": topic_id,
                "picKey": pic_key,
                "cmtNum": 0,
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "uin": auth.uin,
                "hostUin": _raw_uin(host_uin),
                "appid": 4,
                "isFirst": 1,
                "postNum": 18,
            }
            try:
                async with self.session.get(
                    self.FLOATVIEW_URL,
                    params=params,
                    headers=self.api_headers(f"https://user.qzone.qq.com/{_raw_uin(host_uin)}"),
                    proxy=self.proxy,
                ) as response:
                    self._update_cookies(response)
                    status = response.status
                    if status >= 400:
                        payload = None
                    else:
                        payload = await self._read_object_response(response)
            except asyncio.CancelledError:
                raise
            except (ClientError, ValueError, TypeError):
                return None

            if attempt == 0 and await self._maybe_refresh_after_failure(payload, status):
                continue
            if status >= 400:
                return None
            break

        data = payload.get("data") if isinstance(payload, dict) else None
        photos = data.get("photos") if isinstance(data, dict) else None
        if not isinstance(photos, list) or not photos:
            return None

        matched: dict[str, Any] | None = None
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            candidate = _first_string(photo, "picKey", "pic_key", "lloc", "id")
            if candidate == pic_key:
                matched = photo
                break
        if matched is None:
            valid_photos = [p for p in photos if isinstance(p, dict)]
            if len(valid_photos) == 1:
                matched = valid_photos[0]
        return self._detail_from_photo(matched) if matched else None


__all__ = [
    "QZoneApiClient",
    "QZoneAuth",
    "QZoneMediaDetail",
    "SnowLumaCredentialProvider",
    "SnowLumaCredentials",
    "qzone_gtk",
]
