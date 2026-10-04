"""QQ 空间公开分享页解析。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from html import unescape
from math import isfinite
from re import Match, findall, search, sub
from typing import ClassVar
from urllib.parse import parse_qs, urljoin, urlsplit

from aiohttp import ClientError
from bs4 import BeautifulSoup, Tag

from ..config import PluginConfig
from ..cookie import CookieJar
from ..data import MediaContent, Platform, SendGroup, TextContent
from ..download import Downloader
from ..exception import ParseException
from ..qzone_api import QZoneApiClient, SnowLumaCredentialProvider
from ..qzone_link import LinkPreview, inspect_link
from .base import BaseParser, handle


@dataclass(slots=True)
class _QZoneVideo:
    url: str | None = None
    cover_url: str | None = None
    duration: float = 0
    media_indices: set[str] = field(default_factory=set)
    unavailable: bool = False
    topic_id: str | None = None
    pic_key: str | None = None


@dataclass(slots=True)
class _QZoneImageRef:
    index: str
    url: str
    fallback_url: str | None = None
    topic_id: str | None = None
    pic_key: str | None = None


def _balanced_object(source: str, start: int) -> str | None:
    if start < 0 or start >= len(source) or source[start] != "{":
        return None

    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    for index in range(start, len(source)):
        character = source[index]
        next_character = source[index + 1 : index + 2]
        if line_comment:
            if character in "\r\n":
                line_comment = False
            continue
        if block_comment:
            if character == "*" and next_character == "/":
                block_comment = False
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue

        if character in {'"', "'", "`"}:
            quote = character
        elif character == "/" and next_character == "/":
            line_comment = True
        elif character == "/" and next_character == "*":
            block_comment = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
            if depth < 0:
                return None
    return None


def _frontpage_object_starts(source: str):
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(source):
        character = source[index]
        next_character = source[index + 1 : index + 2]
        if line_comment:
            if character in "\r\n":
                line_comment = False
        elif block_comment:
            if character == "*" and next_character == "/":
                block_comment = False
                index += 1
        elif quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character in {'"', "'", "`"}:
            quote = character
        elif character == "/" and next_character == "/":
            line_comment = True
            index += 1
        elif character == "/" and next_character == "*":
            block_comment = True
            index += 1
        elif source.startswith("FrontPage", index):
            before = source[index - 1] if index else ""
            end = index + len("FrontPage")
            if not before or not (before.isalnum() or before in "_$"):
                cursor = end
                while cursor < len(source) and source[cursor].isspace():
                    cursor += 1
                if cursor < len(source) and source[cursor] == "=":
                    cursor += 1
                    while cursor < len(source) and source[cursor].isspace():
                        cursor += 1
                    if cursor < len(source) and source[cursor] == "{":
                        yield cursor
        index += 1


def _extract_frontpage_data(html: str) -> dict[str, object] | None:
    scripts = BeautifulSoup(html, "html.parser").find_all("script")
    sources = [script.get_text() for script in scripts] if scripts else [html]
    for source in sources:
        if (data := _extract_frontpage_source(source)) is not None:
            return data
    return None


def _extract_frontpage_source(source: str) -> dict[str, object] | None:
    for outer_start in _frontpage_object_starts(source):
        outer = _balanced_object(source, outer_start)
        if outer is not None and (
            data := _extract_top_level_data(outer)
        ) is not None:
            return data
    return None


def _extract_top_level_data(outer: str) -> dict[str, object] | None:
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(outer):
        character = outer[index]
        next_character = outer[index + 1 : index + 2]
        if line_comment:
            if character in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if character == "*" and next_character == "/":
                block_comment = False
                index += 1
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue

        key_end: int | None = None
        if depth == 1 and outer.startswith(('"data"', "'data'"), index):
            key_end = index + len('"data"')
        elif depth == 1 and outer.startswith("data", index):
            before = outer[index - 1] if index else ""
            after = outer[index + 4 : index + 5]
            if not (before.isalnum() or before in "_$") and not (
                after.isalnum() or after in "_$"
            ):
                key_end = index + len("data")

        if key_end is not None:
            value_start = key_end
            while value_start < len(outer) and outer[value_start].isspace():
                value_start += 1
            if value_start < len(outer) and outer[value_start] == ":":
                value_start += 1
                while value_start < len(outer) and outer[value_start].isspace():
                    value_start += 1
                value = _balanced_object(outer, value_start)
                if value is None:
                    return None
                try:
                    decoded = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return None
                return decoded if isinstance(decoded, dict) else None

        if character in {'"', "'", "`"}:
            quote = character
        elif character == "/" and next_character == "/":
            line_comment = True
            index += 1
        elif character == "/" and next_character == "*":
            block_comment = True
            index += 1
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        index += 1
    return None


@dataclass(slots=True)
class QZonePost:
    author_name: str
    avatar_url: str | None
    text: str
    link_urls: list[str]
    timestamp: int | None
    image_urls: list[str]
    video_url: str | None
    video_cover_url: str | None
    video_unavailable: bool = False
    video_duration: float = 0.0
    image_refs: list[_QZoneImageRef] = field(default_factory=list)
    video_topic_id: str | None = None
    video_pic_key: str | None = None


class QZoneParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name="qzone", display_name="QQ空间")
    BLUE_LINK_CONCURRENCY_LIMIT: ClassVar[int] = 3

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.headers.update(
            {
                "user-agent": (
                    "Mozilla/5.0 (Linux; Android 13; Mobile) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
                ),
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
            }
        )
        self._qzone_cookie_jar: CookieJar | None = None
        self._qzone_credential_provider: SnowLumaCredentialProvider | None = None
        self._snowluma_provider_options: tuple[str, str, int] | None = None
        self._qzone_api: QZoneApiClient | None = None
        try:
            parser_cfg = self.cfg.parser.qzone
            # 正常 AstrBot 运行环境必定有 cookie_dir；测试桩可能没有。
            # 手动 Cookie 始终保留为 SnowLuma 不可用时的 fallback。
            if hasattr(self.cfg, "cookie_dir"):
                self._qzone_cookie_jar = CookieJar(
                    self.cfg, parser_cfg, "qzone.qq.com"
                )

            # Provider 延迟到真正解析时再创建，避免插件构造阶段提前创建
            # aiohttp ClientSession（此时 AstrBot 事件循环可能尚未启动）。
            if hasattr(parser_cfg, "qzone_credential_source"):
                credential_source = str(
                    getattr(parser_cfg, "qzone_credential_source", None)
                    or "snowluma"
                ).strip().lower()
                if credential_source != "manual":
                    base_url = str(
                        getattr(parser_cfg, "snowluma_http_url", None)
                        or "http://127.0.0.1:3000"
                    ).strip()
                    access_token = str(
                        getattr(parser_cfg, "snowluma_access_token", None) or ""
                    ).strip()
                    try:
                        cache_seconds = int(
                            getattr(parser_cfg, "snowluma_credential_cache_seconds", None)
                            or 300
                        )
                    except (TypeError, ValueError):
                        cache_seconds = 300
                    self._snowluma_provider_options = (
                        base_url,
                        access_token,
                        cache_seconds,
                    )
        except (AttributeError, TypeError, OSError):
            self._qzone_cookie_jar = None
            self._qzone_credential_provider = None
            self._snowluma_provider_options = None

    @staticmethod
    def _normalize_url(value: object, base_url: str) -> str | None:
        if not isinstance(value, str):
            return None
        value = unescape(value).strip()
        if not value:
            return None
        try:
            normalized = urljoin(base_url, value)
            parsed = urlsplit(normalized)
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return normalized

    @staticmethod
    def _deduplicate(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _looks_like_image_url(url: str) -> bool:
        text = url.lower()
        if text.startswith(("data:", "javascript:")):
            return False
        return bool(
            "qpic.cn" in text
            or "photo.store.qq.com" in text
            or "gtimg.cn" in text
            or search(r"\.(?:jpe?g|png|webp|gif)(?:[?#]|$)", text)
        )

    @classmethod
    def _to_qzone_original_url(cls, url: str) -> str:
        """把 QQ 图片 CDN 明确的预览尺寸档提升到原图档。"""
        if "/psc?/" not in url.lower():
            return url
        upgraded = sub(r"!/(?:m|c|r)(?=&|$)", "!/b", url, flags=2)
        upgraded = sub(
            r"(/single-photo/)(?:m|c|r)(?=&|$)",
            r"\1b",
            upgraded,
            flags=2,
        )
        return upgraded

    @staticmethod
    def _origin_score(url: str) -> int:
        text = url.lower()
        score = 0
        if search(r"(?:raw|origin|original|large|big|orignal)", text):
            score += 8
        if search(r"/0(?:[?#]|$)", text):
            score += 5
        if search(r"/(?:b|2000|1600)(?:[/?#]|$)", text):
            score += 4
        if search(r"(?:small|thumb|s_|/m(?:[/?#]|$)|/100(?:[/?#]|$)|/200(?:[/?#]|$))", text):
            score -= 5
        sizes = [
            int(value)
            for value in findall(r"/(\d{2,4})(?=/|\?|#|$)", text)
        ]
        size = sizes[-1] if sizes else 0
        if size >= 2000:
            score += 8
        elif size >= 1600:
            score += 7
        elif size >= 1280:
            score += 6
        elif size >= 1024:
            score += 5
        elif size >= 800:
            score += 4
        elif size >= 640:
            score += 2
        elif size >= 400:
            score -= 1
        elif size >= 280:
            score -= 2
        elif size >= 200:
            score -= 4
        elif size:
            score -= 6
        return score

    @classmethod
    def _pick_original_candidate(
        cls, values: list[object], base_url: str
    ) -> tuple[str | None, str | None]:
        normalized: list[str] = []
        for value in values:
            url = cls._normalize_url(value, base_url)
            if url is None or not cls._looks_like_image_url(url):
                continue
            normalized.append(url)
        normalized = cls._deduplicate(normalized)
        if not normalized:
            return None, None

        fallback = normalized[0]
        expanded = cls._deduplicate(
            [candidate for url in normalized for candidate in (cls._to_qzone_original_url(url), url)]
        )
        best = max(expanded, key=cls._origin_score)
        return best, fallback

    @staticmethod
    def _first_string(mapping: object, *keys: str) -> str | None:
        if not isinstance(mapping, dict):
            return None
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _mapping_image_candidates(cls, mapping: object) -> list[object]:
        if not isinstance(mapping, dict):
            return []
        origin_fields = (
            "picrawurl",
            "rawurl",
            "raw_url",
            "originurl",
            "origin_url",
            "origin",
            "picoriginurl",
            "picOriginUrl",
            "url4",
            "url3",
            "picbigurl",
            "bigurl",
            "big_url",
            "largeurl",
            "large_url",
            "hdurl",
            "hd_url",
            "raw",
        )
        thumb_fields = (
            "smallurl",
            "small_url",
            "thumb",
            "thumburl",
            "thumb_url",
            "picsmall",
            "url1",
            "url2",
            "url",
            "pre",
            "preview",
        )
        values: list[object] = [mapping.get(key) for key in (*origin_fields, *thumb_fields)]
        for value in mapping.values():
            if isinstance(value, str):
                values.append(value)
        return values

    @classmethod
    def _extract_script_images(
        cls, html: str, base_url: str
    ) -> dict[str, _QZoneImageRef]:
        payload = _extract_frontpage_data(html)
        if payload is None:
            return {}
        data = payload.get("data")
        cell_pic = data.get("cell_pic") if isinstance(data, dict) else None
        picdata = cell_pic.get("picdata") if isinstance(cell_pic, dict) else None
        result: dict[str, _QZoneImageRef] = {}
        for index, item in cls._mapping_values(picdata):
            if not isinstance(item, dict):
                continue
            flag = item.get("videoflag")
            if (type(flag) is int and flag == 1) or (
                isinstance(flag, str) and flag == "1"
            ):
                continue
            best, fallback = cls._pick_original_candidate(
                cls._mapping_image_candidates(item), base_url
            )
            if best is None:
                continue
            result[index] = _QZoneImageRef(
                index=index,
                url=best,
                fallback_url=fallback,
                topic_id=cls._first_string(
                    item, "topicId", "topicid", "albumId", "albumid", "album_id"
                ),
                pic_key=cls._first_string(
                    item, "picKey", "pic_key", "lloc", "pic_id", "id", "key"
                ),
            )
        return result

    @classmethod
    def _image_ref_from_node(
        cls,
        image_node: Tag,
        feed: Tag,
        base_url: str,
        default_index: str,
    ) -> _QZoneImageRef | None:
        params_raw = unescape(str(image_node.get("data-params") or image_node.get("data-param") or ""))
        params = parse_qs(params_raw, keep_blank_values=True)
        index = (params.get("index") or [default_index])[0]

        containers = [image_node]
        anchor = image_node.find_parent("a")
        if isinstance(anchor, Tag):
            containers.append(anchor)

        candidates: list[object] = []
        pic_key: str | None = None
        topic_id: str | None = None
        attrs = (
            "data-originurl",
            "data-origin",
            "data-original",
            "data-bigurl",
            "data-raw",
            "data-picurl",
            "data-pic",
            "data-url",
            "data-feedlazy",
            "data-src",
            "src",
            "href",
        )
        for container in containers:
            for attr in attrs:
                value = container.get(attr)
                if not isinstance(value, str) or not value.strip():
                    continue
                if attr == "data-originurl":
                    candidates.extend(part for part in value.split("|") if part)
                else:
                    candidates.append(value)

            pickey = container.get("data-pickey")
            if isinstance(pickey, str) and pickey.strip():
                parts = [part.strip() for part in pickey.split(",") if part.strip()]
                if parts:
                    first = parts[0]
                    if not first.lower().startswith(("http://", "https://", "//")):
                        pic_key = first
                        parts = parts[1:]
                    candidates.extend(parts)

            own_params = parse_qs(
                unescape(str(container.get("data-param") or container.get("data-params") or "")),
                keep_blank_values=True,
            )
            pic_key = pic_key or next(
                (
                    own_params[key][0]
                    for key in ("picKey", "pickey", "pic_key", "lloc")
                    if own_params.get(key)
                ),
                None,
            )
            topic_id = topic_id or next(
                (
                    own_params[key][0]
                    for key in ("topicId", "topicid", "albumId", "albumid")
                    if own_params.get(key)
                ),
                None,
            )

        topic_node = feed.select_one("[data-topicid]")
        if topic_id is None and isinstance(topic_node, Tag):
            raw_topic = topic_node.get("data-topicid")
            if isinstance(raw_topic, str) and raw_topic.strip():
                topic_id = raw_topic.strip()

        best, fallback = cls._pick_original_candidate(candidates, base_url)
        if best is None:
            return None
        return _QZoneImageRef(
            index=str(index),
            url=best,
            fallback_url=fallback,
            topic_id=topic_id,
            pic_key=pic_key,
        )

    def _get_qzone_api(self) -> QZoneApiClient | None:
        if (
            self._qzone_credential_provider is None
            and self._snowluma_provider_options is not None
        ):
            base_url, access_token, cache_seconds = self._snowluma_provider_options
            self._qzone_credential_provider = SnowLumaCredentialProvider(
                self.session,
                base_url=base_url,
                access_token=access_token,
                cache_seconds=cache_seconds,
            )
        if self._qzone_cookie_jar is None and self._qzone_credential_provider is None:
            return None
        if self._qzone_api is None:
            self._qzone_api = QZoneApiClient(
                self.session,
                self._qzone_cookie_jar,
                proxy=self.proxy,
                credential_provider=self._qzone_credential_provider,
            )
        return self._qzone_api

    def _share_headers(self, url: str) -> dict[str, str]:
        headers = self.headers.copy()
        if self._qzone_cookie_jar is not None:
            cookie = self._qzone_cookie_jar.get_cookie_header_for_url(url)
            if cookie:
                headers["Cookie"] = cookie
        return headers

    def _media_headers(self, page_url: str) -> dict[str, str]:
        api = self._get_qzone_api()
        if api is not None and api.available:
            headers = self.headers.copy()
            headers.update(api.media_headers(page_url))
            return headers
        return self.headers

    @classmethod
    def _feed_image_ref(
        cls,
        photo: object,
        *,
        index: int,
        topic_id: str | None,
        base_url: str,
    ) -> _QZoneImageRef | None:
        if not isinstance(photo, dict):
            return None
        best, fallback = cls._pick_original_candidate(
            [
                photo.get("raw"),
                photo.get("picrawurl"),
                photo.get("rawurl"),
                photo.get("originurl"),
                photo.get("picbigurl"),
                photo.get("bigurl"),
                photo.get("url"),
                photo.get("picsmallurl"),
                photo.get("smallurl"),
            ],
            base_url,
        )
        if best is None:
            return None
        return _QZoneImageRef(
            index=str(index),
            url=best,
            fallback_url=fallback,
            topic_id=topic_id,
            pic_key=cls._first_string(
                photo, "picKey", "pic_key", "lloc", "pic_id", "id", "key"
            ),
        )

    @staticmethod
    def _feed_is_video(photo: object) -> bool:
        if not isinstance(photo, dict):
            return False
        flag = photo.get("is_video")
        return bool(
            flag is True
            or flag == 1
            or flag == "1"
            or photo.get("videourl")
            or photo.get("video_url")
        )

    @classmethod
    def _apply_feed_media(
        cls,
        post: QZonePost,
        feed: object,
        page_url: str,
    ) -> None:
        if not isinstance(feed, dict):
            return
        photos = feed.get("photos")
        if not isinstance(photos, list):
            return
        topic_id = cls._first_string(
            feed, "albumid", "albumId", "album_id", "topicId", "topicid"
        )
        image_refs: list[_QZoneImageRef] = []
        for index, photo in enumerate(photos):
            if not isinstance(photo, dict):
                continue
            if cls._feed_is_video(photo):
                video_url = next(
                    (
                        normalized
                        for value in (
                            photo.get("video_download_url"),
                            photo.get("download_url"),
                            photo.get("videourl"),
                            photo.get("video_url"),
                            photo.get("url3"),
                        )
                        if (normalized := cls._normalize_url(value, page_url))
                    ),
                    None,
                )
                if video_url:
                    post.video_url = video_url
                    post.video_unavailable = False
                cover = next(
                    (
                        normalized
                        for value in (
                            photo.get("cover_url"),
                            photo.get("pic_url"),
                            photo.get("picsmallurl"),
                            photo.get("url1"),
                            photo.get("url"),
                        )
                        if (normalized := cls._normalize_url(value, page_url))
                    ),
                    None,
                )
                if cover:
                    post.video_cover_url = cover
                post.video_topic_id = topic_id or post.video_topic_id
                post.video_pic_key = (
                    cls._first_string(
                        photo,
                        "picKey",
                        "pic_key",
                        "lloc",
                        "videokey",
                        "video_id",
                        "id",
                    )
                    or post.video_pic_key
                )
                try:
                    duration = float(
                        photo.get("video_time")
                        or photo.get("videotime")
                        or photo.get("duration")
                        or 0
                    )
                except (TypeError, ValueError, OverflowError):
                    duration = 0.0
                if duration >= 1000:
                    duration /= 1000
                if duration > 0:
                    post.video_duration = duration
                continue

            ref = cls._feed_image_ref(
                photo,
                index=index,
                topic_id=topic_id,
                base_url=page_url,
            )
            if ref is not None:
                image_refs.append(ref)

        if image_refs:
            post.image_refs = image_refs
            post.image_urls = cls._deduplicate([ref.url for ref in image_refs])

    async def _upgrade_post_media(self, post: QZonePost, page_url: str) -> QZonePost:
        api = self._get_qzone_api()
        if api is None or not await api.ensure_auth():
            return post

        query = parse_qs(urlsplit(page_url).query)
        host_uin = (query.get("res_uin") or [""])[0]
        cell_id = (query.get("cellid") or [""])[0]
        if not host_uin:
            return post

        # 第一优先：用照片动态接口按分享页时间点回查同一条动态。
        # 这个响应直接给 raw/picrawurl/picbigurl/videourl，并带 albumid + picKey。
        try:
            feed_payload = await api.get_photo_feed(
                host_uin=host_uin,
                begintime=(post.timestamp + 1) if post.timestamp else 0,
            )
            feed = api.find_feed(
                feed_payload,
                cell_id=cell_id,
                timestamp=post.timestamp,
            )
            if feed is not None:
                self._apply_feed_media(post, feed, page_url)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 原媒体增强是 best-effort；任何接口结构变更都必须回退 H5。
            pass

        async def upgrade_image(ref: _QZoneImageRef) -> str:
            if not ref.topic_id or not ref.pic_key:
                return ref.url
            detail = await api.get_media_detail(
                host_uin=host_uin,
                topic_id=ref.topic_id,
                pic_key=ref.pic_key,
            )
            if detail is None or not detail.best_image_url:
                return ref.url
            return self._normalize_url(detail.best_image_url, page_url) or ref.url

        if post.image_refs:
            upgraded = await asyncio.gather(*(upgrade_image(ref) for ref in post.image_refs))
            post.image_urls = self._deduplicate(list(upgraded))

        if post.video_topic_id and post.video_pic_key:
            detail = await api.get_media_detail(
                host_uin=host_uin,
                topic_id=post.video_topic_id,
                pic_key=post.video_pic_key,
            )
            if detail is not None and detail.is_video:
                if detail.best_video_url:
                    post.video_url = (
                        self._normalize_url(detail.best_video_url, page_url)
                        or post.video_url
                    )
                    post.video_unavailable = False
                if detail.video_cover_url:
                    post.video_cover_url = (
                        self._normalize_url(detail.video_cover_url, page_url)
                        or post.video_cover_url
                    )
                if detail.video_duration > 0:
                    post.video_duration = detail.video_duration
        return post


    @staticmethod
    def _mapping_values(value: object) -> list[tuple[str, object]]:
        if isinstance(value, dict):
            return [(str(key), item) for key, item in value.items()]
        if isinstance(value, list):
            return [(str(index), item) for index, item in enumerate(value)]
        return []

    @classmethod
    def _first_nested_url(
        cls, value: object, base_url: str
    ) -> str | None:
        for _, item in cls._mapping_values(value):
            if not isinstance(item, dict):
                continue
            if normalized := cls._normalize_url(item.get("url"), base_url):
                return normalized
        return None

    @classmethod
    def _extract_script_video(cls, html: str, base_url: str) -> _QZoneVideo:
        payload = _extract_frontpage_data(html)
        if payload is None:
            return _QZoneVideo()

        data = payload.get("data")
        cell_pic = data.get("cell_pic") if isinstance(data, dict) else None
        picdata = cell_pic.get("picdata") if isinstance(cell_pic, dict) else None
        first_unavailable: _QZoneVideo | None = None
        for index, item in cls._mapping_values(picdata):
            if not isinstance(item, dict):
                continue
            flag = item.get("videoflag")
            if not (
                (type(flag) is int and flag == 1)
                or (isinstance(flag, str) and flag == "1")
            ):
                continue

            raw = item.get("videodata")
            if not isinstance(raw, dict):
                if first_unavailable is None:
                    first_unavailable = _QZoneVideo(
                        media_indices={index}, unavailable=True
                    )
                continue

            url = next(
                (
                    normalized
                    for candidate in (
                        raw.get("videourl"),
                        raw.get("actionurl"),
                    )
                    if (
                        normalized := cls._normalize_url(candidate, base_url)
                    )
                ),
                None,
            )
            if url is None:
                url = cls._first_nested_url(raw.get("videourls"), base_url)

            cover_url = cls._first_nested_url(raw.get("coverurl"), base_url)
            try:
                duration = float(raw.get("videotime", 0)) / 1000
            except (TypeError, ValueError, OverflowError):
                duration = 0.0
            if not isfinite(duration) or duration < 0:
                duration = 0.0

            video = _QZoneVideo(
                url=url,
                cover_url=cover_url,
                duration=duration,
                media_indices={index},
                unavailable=url is None,
                topic_id=cls._first_string(
                    item, "topicId", "topicid", "albumId", "albumid", "album_id"
                ),
                pic_key=cls._first_string(
                    item, "picKey", "pic_key", "lloc", "video_id", "vid", "id", "key"
                ),
            )
            if url is not None:
                return video
            if first_unavailable is None:
                first_unavailable = video
        return first_unavailable or _QZoneVideo()

    @staticmethod
    def _strip_unmatched_closing_delimiters(value: str) -> str:
        pairs = {")": "(", "]": "[", "}": "{"}
        while value and (opening := pairs.get(value[-1])):
            closing = value[-1]
            if value.count(closing) <= value.count(opening):
                break
            value = value[:-1]
        return value

    @classmethod
    def _style_url(cls, style: object, base_url: str) -> str | None:
        if not isinstance(style, str):
            return None
        matched = search(
            r"background-image\s*:\s*url\(\s*(['\"]?)(.*?)\1\s*\)",
            unescape(style),
            flags=0,
        )
        return cls._normalize_url(matched.group(2), base_url) if matched else None

    @property
    def _send_blue_links(self) -> bool:
        try:
            return bool(self.cfg.parser.qzone.send_blue_links)
        except AttributeError:
            return False

    @classmethod
    async def _inspect_blue_links(cls, urls: list[str]) -> list[LinkPreview]:
        semaphore = asyncio.Semaphore(cls.BLUE_LINK_CONCURRENCY_LIMIT)

        async def inspect_one(url: str) -> LinkPreview:
            async with semaphore:
                try:
                    return await inspect_link(url)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return LinkPreview("访问失败", url)

        return list(await asyncio.gather(*(inspect_one(url) for url in urls)))

    @staticmethod
    def _format_blue_links(previews: list[LinkPreview]) -> str:
        return "\n".join(
            value
            for preview in previews
            for value in (preview.title, preview.url)
            if value != ""
        )

    @classmethod
    def _resolve_text_link(cls, value: object, base_url: str) -> str | None:
        """解出 QQ 正文链接跳转器中的公开目标地址。"""
        resolved = cls._normalize_url(value, base_url)
        if resolved is None:
            return None

        parsed = urlsplit(resolved)
        if parsed.hostname not in {"urlshare.cn", "www.urlshare.cn"}:
            return resolved

        target_values = parse_qs(parsed.query).get("url")
        if not target_values:
            return resolved

        target = target_values[0]
        return cls._normalize_url(target, resolved) or resolved

    @classmethod
    def _extract_text(
        cls, text_node: Tag, base_url: str
    ) -> tuple[str, list[str]]:
        link_urls: list[str] = []
        for link_node in text_node.select("a[href]"):
            resolved = cls._resolve_text_link(link_node.get("href"), base_url)
            if resolved is None:
                continue
            link_urls.append(resolved)

            label = link_node.get_text(" ", strip=True)
            replacement = (
                f"{label}：{resolved}"
                if label and label != resolved
                else resolved
            )
            link_node.replace_with(replacement)

        return text_node.get_text("\n", strip=True), cls._deduplicate(link_urls)

    @classmethod
    def _extract_video(
        cls, root: Tag, base_url: str
    ) -> tuple[str | None, str | None, bool]:
        nodes = root.select(
            "video, .video, [data-video-url], [data-videourl], "
            "[data-play-url], [data-playurl], [data-v_vidioswfurl], "
            "[data-v-vidiourl], [data-param], [data-hook*='video']"
        )
        video_url: str | None = None
        cover_url: str | None = None
        has_video_marker = False
        video_attrs = (
            "data-video-url",
            "data-videourl",
            "data-play-url",
            "data-playurl",
            "data-v_vidioswfurl",
            "data-v-vidiourl",
        )
        cover_attrs = ("poster", "data-poster", "data-cover", "data-cover-url")

        for node in nodes:
            explicit_video_values = [node.get(attr) for attr in video_attrs]
            has_explicit_video_attr = any(
                node.has_attr(attr) for attr in video_attrs
            )
            legacy_params = parse_qs(
                unescape(str(node.get("data-param", ""))),
                keep_blank_values=True,
            )
            has_legacy_video_param = "videosrc" in legacy_params
            legacy_video_values = legacy_params.get("videosrc", [])
            cover_candidates = [node.get(attr) for attr in cover_attrs]
            is_video_element = node.name == "video"
            is_explicit_container = (
                node.name not in {"img", "source"}
                and (
                    "video" in node.get("class", [])
                    or "video" in str(node.get("data-hook", ""))
                )
            )
            has_video_selector = (
                is_video_element
                or "video" in node.get("class", [])
                or has_explicit_video_attr
                or "video" in str(node.get("data-hook", ""))
            )
            is_video_container = (
                any(explicit_video_values)
                or has_legacy_video_param
                or (any(cover_candidates) and has_video_selector)
                or is_explicit_container
            )
            if not is_video_element and not is_video_container:
                continue

            has_video_marker = True
            if cover_url is None:
                cover_url = next(
                    (
                        normalized
                        for value in cover_candidates
                        if (normalized := cls._normalize_url(value, base_url))
                    ),
                    None,
                )

            if is_video_element:
                video_candidates = [node.get("src")]
                video_candidates.extend(
                    source.get("src") for source in node.select("source[src]")
                )
            else:
                video_candidates = explicit_video_values + legacy_video_values

            if video_url is None:
                video_url = next(
                    (
                        normalized
                        for value in video_candidates
                        if (normalized := cls._normalize_url(value, base_url))
                    ),
                    None,
                )

        return video_url, cover_url, has_video_marker and video_url is None

    @classmethod
    def extract_post(cls, html: str, page_url: str) -> QZonePost:
        soup = BeautifulSoup(html, "html.parser")
        feed = soup.select_one('.feed[data-hook="info-detail"]')
        if not isinstance(feed, Tag):
            raise ParseException("未找到 QQ 空间公开动态")

        script_video = cls._extract_script_video(html, page_url)

        author_name = ""
        for selector in (
            ".feed-hd .username",
            '[data-hook="user-name"]',
            ".user-name",
            ".nickname",
            ".feed-hd .name",
        ):
            author_node = feed.select_one(selector)
            if author_node and (candidate := author_node.get_text(strip=True)):
                author_name = candidate
                break
        if not author_name:
            author_name = parse_qs(urlsplit(page_url).query).get(
                "res_uin", ["QQ空间用户"]
            )[0]

        avatar_url: str | None = None
        for selector in (
            ".feed-hd .pic",
            ".feed-hd .avatar",
            '.feed-hd [data-hook*="avatar"]',
        ):
            avatar_node = feed.select_one(selector)
            if avatar_node is not None and (
                avatar_url := cls._style_url(avatar_node.get("style"), page_url)
            ):
                break

        body = feed.select_one(".feed-bd")
        text = ""
        link_urls: list[str] = []
        image_urls: list[str] = []
        image_refs: list[_QZoneImageRef] = []
        if isinstance(body, Tag):
            text_node = feed.select_one(".feed-bd .txt")
            if isinstance(text_node, Tag):
                text, link_urls = cls._extract_text(text_node, page_url)

            script_images = cls._extract_script_images(html, page_url)
            for sequence, image_node in enumerate(
                body.select(
                    "[data-feedlazy], "
                    "img[data-hook*='viewPic'][src], "
                    "img.img[data-params][src]"
                )
            ):
                image_params = image_node.get("data-params")
                media_index: str | None = None
                if isinstance(image_params, str):
                    parsed_image_params = parse_qs(
                        unescape(image_params), keep_blank_values=True
                    )
                    media_values = parsed_image_params.get("index")
                    media_index = media_values[0] if media_values else None
                    if media_index and media_index in script_video.media_indices:
                        continue

                html_ref = cls._image_ref_from_node(
                    image_node,
                    feed,
                    page_url,
                    media_index or str(sequence),
                )
                script_ref = script_images.get(media_index or str(sequence))
                ref = script_ref or html_ref
                if ref is None:
                    continue
                if script_ref is not None and html_ref is not None:
                    ref.fallback_url = script_ref.fallback_url or html_ref.fallback_url
                    ref.topic_id = script_ref.topic_id or html_ref.topic_id
                    ref.pic_key = script_ref.pic_key or html_ref.pic_key
                image_refs.append(ref)
                image_urls.append(ref.url)

            # FrontPage 有时比 DOM 多给出媒体信息（懒加载节点未渲染出来）。
            known_indices = {ref.index for ref in image_refs}
            for index, ref in script_images.items():
                if index in known_indices or index in script_video.media_indices:
                    continue
                image_refs.append(ref)
                image_urls.append(ref.url)

        timestamp: int | None = None
        data_params = feed.get("data-params")
        if isinstance(data_params, str) and (
            timestamp_match := search(r"__(\d{10})(?:\D|$)", data_params)
        ):
            timestamp = int(timestamp_match.group(1))

        has_script_video = bool(
            script_video.url
            or script_video.unavailable
            or script_video.media_indices
        )
        if has_script_video:
            video_url = script_video.url
            video_cover_url = script_video.cover_url
            video_duration = script_video.duration
            video_unavailable = script_video.unavailable
        else:
            video_url, video_cover_url, video_unavailable = cls._extract_video(
                feed, page_url
            )
            video_duration = 0.0
        return QZonePost(
            author_name=author_name,
            avatar_url=avatar_url,
            text=text,
            link_urls=link_urls,
            timestamp=timestamp,
            image_urls=cls._deduplicate(image_urls),
            video_url=video_url,
            video_cover_url=video_cover_url,
            video_unavailable=video_unavailable,
            video_duration=video_duration,
            image_refs=image_refs,
            video_topic_id=script_video.topic_id,
            video_pic_key=script_video.pic_key,
        )

    @handle(
        "h5.qzone.qq.com/ugc/share",
        r"https?://h5\.qzone\.qq\.com/ugc/share/\?[^\s<>\"'，。；！？）】》」』]+",
    )
    @handle(
        "mobile.qzone.qq.com/l",
        r"https?://mobile\.qzone\.qq\.com/l\?[^\s<>\"'，。；！？）】》」』]+",
    )
    async def _parse_share(self, searched: Match[str]):
        url = self._strip_unmatched_closing_delimiters(
            unescape(searched.group(0))
        )
        html = await self._fetch_html(url)
        post = self.extract_post(html, url)
        post = await self._upgrade_post_media(post, url)
        media_headers = self._media_headers(url)

        contents: list[MediaContent] = []
        if post.video_url:
            contents.append(
                self.create_video_content(
                    post.video_url,
                    cover_url=post.video_cover_url,
                    duration=post.video_duration,
                    headers=media_headers,
                )
            )
        contents.extend(
            self.create_image_contents(post.image_urls, headers=media_headers)
        )

        if not post.text and not contents:
            raise ParseException("QQ空间动态没有可发送的内容")

        extra = {}
        if post.video_unavailable:
            notice = "页面包含视频，但未公开可下载的视频地址"
            extra["info"] = notice
            if not contents and notice not in post.text:
                post.text = f"{post.text}\n\n{notice}".strip()

        author = self.create_author(
            post.author_name,
            post.avatar_url,
            headers=self.headers,
        )
        result = self.result(
            author=author,
            text=post.text,
            timestamp=post.timestamp,
            url=url,
            contents=contents,
            send_groups=(
                [SendGroup(contents=contents, render_card=True)]
                if contents
                else []
            ),
            extra=extra,
        )
        if not self._send_blue_links or not post.link_urls:
            return result

        message = self._format_blue_links(
            await self._inspect_blue_links(post.link_urls)
        )
        if not message:
            return result

        if contents:
            result.send_groups.append(
                SendGroup(contents=[TextContent(message)])
            )
        else:
            fallback = "\n".join(
                part for part in (result.header, result.text) if part
            ).strip()
            result.send_groups = [
                SendGroup(contents=[TextContent(fallback)]),
                SendGroup(contents=[TextContent(message)]),
            ]
        return result

    async def _fetch_html(self, url: str) -> str:
        try:
            request_kwargs = {
                "headers": self._share_headers(url),
                "allow_redirects": True,
            }
            if self.proxy:
                request_kwargs["proxy"] = self.proxy
            async with self.session.get(url, **request_kwargs) as response:
                if response.status >= 400:
                    raise ClientError(f"HTTP {response.status} {response.reason}")
                if self._qzone_cookie_jar is not None:
                    try:
                        set_cookies = response.headers.getall("Set-Cookie", [])
                    except Exception:
                        set_cookies = []
                    if set_cookies:
                        self._qzone_cookie_jar.update_from_response(list(set_cookies))
                return await response.text()
        except (ClientError, asyncio.TimeoutError) as exc:
            raise ParseException(f"QQ空间分享页请求失败: {exc}") from exc


__all__ = ["QZoneParser", "QZonePost"]
