# -*- coding: utf-8 -*-
"""MaiBot adapter for Zhalslar/astrbot_plugin_parser core parsers."""
from __future__ import annotations

import asyncio
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from maibot_sdk import Command, Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import HookMode, HookOrder

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from .core.config import PluginConfig as CorePluginConfig
from .core.data import DynamicContent, FileContent, GraphicsContent, ImageContent, ParseResult, TextContent, VideoContent
from .core.download import Downloader
from .core.exception import ParseException
from .core.parsers import BaseParser, BilibiliParser
from .sender import ApiSettings, image_segment, send_file, send_group_forward, send_image, send_text, send_video, text_segment

URL_RE = re.compile(r"https?://[^\s\]\)）>\"']+")


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件设置"
    __ui_order__ = 0

    name: str = Field(default="multi_platform_parser", description="插件名称", json_schema_extra={"hidden": True})
    config_version: str = Field(default="1.2.0", description="配置文件版本", json_schema_extra={"hidden": True})
    version: str = Field(default="1.2.0", description="插件版本", json_schema_extra={"hidden": True})
    enabled: bool = Field(default=True, description="是否启用插件", json_schema_extra={"label": "启用插件", "hint": "关闭后插件完全停止工作", "order": 0})
    admin_qqs: list[str] = Field(default_factory=list, description="管理员QQ号列表", json_schema_extra={"label": "管理员QQ号", "hint": "只有管理员可以使用开启/关闭解析和登录B站命令，支持多个QQ号", "order": 1})


class ParserSectionConfig(PluginConfigBase):
    __ui_label__ = "解析设置"
    __ui_order__ = 1

    enable_bilibili: bool = Field(default=True, description="启用B站解析", json_schema_extra={"label": "B站", "hint": "开启B站链接解析", "order": 0})
    enable_douyin: bool = Field(default=True, description="启用抖音解析", json_schema_extra={"label": "抖音", "hint": "开启抖音链接解析", "order": 1})
    enable_xhs: bool = Field(default=True, description="启用小红书解析", json_schema_extra={"label": "小红书", "hint": "开启小红书链接解析", "order": 2})
    enable_xiaoheihe: bool = Field(default=True, description="启用小黑盒解析", json_schema_extra={"label": "小黑盒", "hint": "开启小黑盒链接解析", "order": 3})
    enable_acfun: bool = Field(default=False, description="启用A站解析（成人内容平台，请谨慎开启）", json_schema_extra={"label": "A站", "hint": "成人内容平台，默认关闭，请谨慎开启", "order": 4})
    enable_instagram: bool = Field(default=True, description="启用Instagram解析", json_schema_extra={"label": "Instagram", "hint": "开启Instagram链接解析", "order": 5})
    enable_iwara: bool = Field(default=False, description="启用iwara解析（成人内容平台，请谨慎开启）", json_schema_extra={"label": "iwara", "hint": "成人内容平台，默认关闭，请谨慎开启", "order": 6})
    enable_kuaishou: bool = Field(default=True, description="启用快手解析", json_schema_extra={"label": "快手", "hint": "开启快手链接解析", "order": 7})
    enable_ncm: bool = Field(default=True, description="启用网易云音乐解析", json_schema_extra={"label": "网易云音乐", "hint": "开启网易云音乐链接解析", "order": 8})
    enable_nga: bool = Field(default=True, description="启用NGA解析", json_schema_extra={"label": "NGA", "hint": "开启NGA链接解析", "order": 9})
    enable_shipinhao: bool = Field(default=True, description="启用微信视频号解析", json_schema_extra={"label": "微信视频号", "hint": "开启微信视频号链接解析", "order": 10})
    enable_tiktok: bool = Field(default=True, description="启用TikTok解析", json_schema_extra={"label": "TikTok", "hint": "开启TikTok链接解析", "order": 11})
    enable_twitter: bool = Field(default=True, description="启用Twitter/X解析", json_schema_extra={"label": "Twitter/X", "hint": "开启Twitter/X链接解析", "order": 12})
    enable_weibo: bool = Field(default=True, description="启用微博解析", json_schema_extra={"label": "微博", "hint": "开启微博链接解析", "order": 13})
    enable_youtube: bool = Field(default=True, description="启用YouTube解析", json_schema_extra={"label": "YouTube", "hint": "开启YouTube链接解析", "order": 14})
    enable_zhihu: bool = Field(default=True, description="启用知乎解析", json_schema_extra={"label": "知乎", "hint": "开启知乎链接解析", "order": 15})
    enable_pixiv: bool = Field(default=False, description="启用Pixiv解析（需配置Cookie，含R18内容）", json_schema_extra={"label": "Pixiv", "hint": "Pixiv解析需配置Cookie才能访问，含R18内容，默认关闭", "order": 16})

    group_whitelist: list[str] = Field(default_factory=list, description="只在这些QQ群自动解析", json_schema_extra={"label": "群白名单", "hint": "空列表表示所有群都允许解析", "order": 17})
    block_ai_reply: bool = Field(default=True, description="命中链接后阻止麦麦继续触发普通聊天", json_schema_extra={"label": "阻止AI回复", "hint": "开启后命中链接时麦麦不会继续聊天", "order": 18})
    debounce_seconds: int = Field(default=120, description="同一会话同一链接去重时间（秒）", ge=0, json_schema_extra={"label": "去重时间(秒)", "hint": "同一会话同一链接在此时间内不会重复解析", "order": 19})
    max_images: int = Field(default=9, description="单条链接最多发送图片数", ge=1, le=30, json_schema_extra={"label": "最大图片数", "hint": "单条链接最多发送多少张图片", "order": 20})
    max_text_chars: int = Field(default=700, description="摘要正文最大字符数", ge=80, le=3000, json_schema_extra={"label": "最大文字长度", "hint": "摘要正文的最大字符数", "order": 21})
    send_images: bool = Field(default=True, description="是否发送图片", json_schema_extra={"label": "发送图片", "hint": "是否发送解析到的图片", "order": 23})
    send_video: bool = Field(default=True, description="是否发送视频", json_schema_extra={"label": "发送视频", "hint": "是否发送解析到的视频", "order": 24})
    use_forward_for_multi: bool = Field(default=True, description="群聊多图/图文是否使用合并转发", json_schema_extra={"label": "合并转发", "hint": "群聊中多图或图文混排时使用合并转发", "order": 25})
    pixiv_use_forward: bool = Field(default=True, description="Pixiv图片使用合并转发逐张发送（关闭则合成为PDF）", json_schema_extra={"label": "Pixiv合并转发", "hint": "开启后Pixiv图片通过合并转发逐张发送，关闭则合成为PDF文件", "order": 26})
    source_max_size_mb: int = Field(default=80, description="单个媒体最大下载大小（MB），范围1-300", ge=1, le=300, json_schema_extra={"label": "最大文件大小(MB)", "hint": "单个媒体文件的最大下载大小，范围：1-300MB", "order": 27})
    source_max_minutes: int = Field(default=8, description="视频最大时长（分钟），范围1-60", ge=1, le=60, json_schema_extra={"label": "最大视频时长(分钟)", "hint": "视频的最大时长限制，范围：1-60分钟", "order": 28})


class EncryptSectionConfig(PluginConfigBase):
    __ui_label__ = "混淆设置"
    __ui_order__ = 2

    pixiv_encrypt_image_group: bool = Field(default=True, description="群聊Pixiv图片是否混淆后发送（仅R18/R18G作品）", json_schema_extra={"label": "群聊Pixiv图片混淆", "hint": "开启后，群聊中仅对R18/R18G作品的图片进行像素混淆加密处理，默认开启", "order": 0})
    pixiv_encrypt_image_private: bool = Field(default=False, description="私聊Pixiv图片是否混淆后发送（仅R18/R18G作品）", json_schema_extra={"label": "私聊Pixiv图片混淆", "hint": "开启后，私聊中仅对R18/R18G作品的图片进行像素混淆加密处理，默认关闭", "order": 1})


class NetworkSectionConfig(PluginConfigBase):
    __ui_label__ = "网络设置"
    __ui_order__ = 3

    proxy: str = Field(default="", description="解析/下载代理", json_schema_extra={"label": "代理地址", "hint": "例如 http://127.0.0.1:7890，留空则不使用代理", "order": 0})
    proxy_bilibili: bool = Field(default=False, description="B站使用代理", json_schema_extra={"label": "B站代理", "hint": "B站请求是否走代理", "order": 1})
    proxy_douyin: bool = Field(default=False, description="抖音使用代理", json_schema_extra={"label": "抖音代理", "hint": "抖音请求是否走代理", "order": 2})
    proxy_xhs: bool = Field(default=False, description="小红书使用代理", json_schema_extra={"label": "小红书代理", "hint": "小红书请求是否走代理", "order": 3})
    proxy_xiaoheihe: bool = Field(default=False, description="小黑盒使用代理", json_schema_extra={"label": "小黑盒代理", "hint": "小黑盒请求是否走代理", "order": 4})
    proxy_acfun: bool = Field(default=False, description="A站使用代理", json_schema_extra={"label": "A站代理", "hint": "A站请求是否走代理", "order": 5})
    proxy_instagram: bool = Field(default=True, description="Instagram使用代理", json_schema_extra={"label": "Instagram代理", "hint": "Instagram请求是否走代理，默认开启", "order": 6})
    proxy_iwara: bool = Field(default=True, description="iwara使用代理", json_schema_extra={"label": "iwara代理", "hint": "iwara请求是否走代理，默认开启", "order": 7})
    proxy_kuaishou: bool = Field(default=False, description="快手使用代理", json_schema_extra={"label": "快手代理", "hint": "快手请求是否走代理", "order": 8})
    proxy_ncm: bool = Field(default=False, description="网易云音乐使用代理", json_schema_extra={"label": "网易云音乐代理", "hint": "网易云音乐请求是否走代理", "order": 9})
    proxy_nga: bool = Field(default=False, description="NGA使用代理", json_schema_extra={"label": "NGA代理", "hint": "NGA请求是否走代理", "order": 10})
    proxy_shipinhao: bool = Field(default=False, description="微信视频号使用代理", json_schema_extra={"label": "微信视频号代理", "hint": "微信视频号请求是否走代理", "order": 11})
    proxy_tiktok: bool = Field(default=True, description="TikTok使用代理", json_schema_extra={"label": "TikTok代理", "hint": "TikTok请求是否走代理，默认开启", "order": 12})
    proxy_twitter: bool = Field(default=True, description="Twitter/X使用代理", json_schema_extra={"label": "Twitter/X代理", "hint": "Twitter/X请求是否走代理，默认开启", "order": 13})
    proxy_weibo: bool = Field(default=False, description="微博使用代理", json_schema_extra={"label": "微博代理", "hint": "微博请求是否走代理", "order": 14})
    proxy_youtube: bool = Field(default=True, description="YouTube使用代理", json_schema_extra={"label": "YouTube代理", "hint": "YouTube请求是否走代理，默认开启", "order": 15})
    proxy_zhihu: bool = Field(default=False, description="知乎使用代理", json_schema_extra={"label": "知乎代理", "hint": "知乎请求是否走代理", "order": 16})
    proxy_pixiv: bool = Field(default=True, description="Pixiv使用代理", json_schema_extra={"label": "Pixiv代理", "hint": "Pixiv请求是否走代理，默认开启", "order": 17})
    common_timeout: int = Field(default=30, description="普通请求超时秒数", ge=5, le=120, json_schema_extra={"label": "请求超时(秒)", "hint": "普通请求的超时时间", "order": 18})
    download_timeout: int = Field(default=120, description="下载超时秒数", ge=10, le=600, json_schema_extra={"label": "下载超时(秒)", "hint": "文件下载的超时时间", "order": 19})
    download_retry_times: int = Field(default=1, description="下载重试次数", ge=0, le=5, json_schema_extra={"label": "下载重试次数", "hint": "下载失败时的重试次数", "order": 20})


class CookieSectionConfig(PluginConfigBase):
    __ui_label__ = "Cookie设置"
    __ui_order__ = 4

    bilibili: str = Field(default="", description="B站 Cookie", json_schema_extra={"label": "B站", "hint": "B站账号的Cookie，可选", "order": 0})
    douyin: str = Field(default="", description="抖音 Cookie", json_schema_extra={"label": "抖音", "hint": "抖音账号的Cookie，可选", "order": 1})
    xhs: str = Field(default="", description="小红书 Cookie", json_schema_extra={"label": "小红书", "hint": "小红书账号的Cookie，可选", "order": 2})
    xiaoheihe: str = Field(default="", description="小黑盒 Cookie", json_schema_extra={"label": "小黑盒", "hint": "小黑盒账号的Cookie，可选", "order": 3})
    acfun: str = Field(default="", description="A站 Cookie", json_schema_extra={"label": "A站", "hint": "A站账号的Cookie，可选", "order": 4})
    instagram: str = Field(default="", description="Instagram Cookie", json_schema_extra={"label": "Instagram", "hint": "Instagram账号的Cookie，可选", "order": 5})
    iwara: str = Field(default="", description="iwara Cookie", json_schema_extra={"label": "iwara", "hint": "iwara账号的Cookie，可选", "order": 6})
    kuaishou: str = Field(default="", description="快手 Cookie", json_schema_extra={"label": "快手", "hint": "快手账号的Cookie，可选", "order": 7})
    ncm: str = Field(default="", description="网易云音乐 Cookie", json_schema_extra={"label": "网易云音乐", "hint": "网易云音乐账号的Cookie，可选", "order": 8})
    nga: str = Field(default="", description="NGA Cookie", json_schema_extra={"label": "NGA", "hint": "NGA账号的Cookie，可选", "order": 9})
    shipinhao: str = Field(default="", description="微信视频号 Cookie", json_schema_extra={"label": "微信视频号", "hint": "微信视频号的Cookie，可选", "order": 10})
    tiktok: str = Field(default="", description="TikTok Cookie", json_schema_extra={"label": "TikTok", "hint": "TikTok账号的Cookie，可选", "order": 11})
    twitter: str = Field(default="", description="Twitter/X Cookie", json_schema_extra={"label": "Twitter/X", "hint": "Twitter/X账号的Cookie，可选", "order": 12})
    weibo: str = Field(default="", description="微博 Cookie", json_schema_extra={"label": "微博", "hint": "微博账号的Cookie，可选", "order": 13})
    youtube: str = Field(default="", description="YouTube Cookie", json_schema_extra={"label": "YouTube", "hint": "YouTube账号的Cookie，可选", "order": 14})
    zhihu: str = Field(default="", description="知乎 Cookie", json_schema_extra={"label": "知乎", "hint": "知乎账号的Cookie，可选", "order": 15})
    pixiv: str = Field(default="", description="Pixiv Cookie", json_schema_extra={"label": "Pixiv", "hint": "Pixiv账号的Cookie，必填，否则无法解析", "order": 16})


class ApiConfig(PluginConfigBase):
    __ui_label__ = "API设置"
    __ui_order__ = 5

    host: str = Field(default="127.0.0.1", description="OneBot HTTP API 主机", json_schema_extra={"label": "主机地址", "hint": "OneBot HTTP API 的主机地址", "order": 0})
    port: int = Field(default=3000, description="OneBot HTTP API 端口", ge=1, le=65535, json_schema_extra={"label": "端口", "hint": "OneBot HTTP API 的端口号", "order": 1})
    token: str = Field(default="", description="OneBot HTTP API Token", json_schema_extra={"label": "Token", "hint": "OneBot HTTP API 的认证Token，可选", "order": 2})
    bot_uin: str = Field(default="", description="发送合并转发节点时使用的 bot QQ", json_schema_extra={"label": "Bot QQ", "hint": "发送合并转发时使用的机器人QQ号，可选", "order": 3})


class PluginConfig(PluginConfigBase):
    __ui_label__ = "全部配置"

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    parser: ParserSectionConfig = Field(default_factory=ParserSectionConfig)
    encrypt: EncryptSectionConfig = Field(default_factory=EncryptSectionConfig)
    network: NetworkSectionConfig = Field(default_factory=NetworkSectionConfig)
    cookies: CookieSectionConfig = Field(default_factory=CookieSectionConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


class MultiPlatformParserPlugin(MaiBotPlugin):
    """自动解析抖音、小红书、小黑盒等社媒链接。"""

    config_model = PluginConfig
    config_reload_subscriptions: tuple[str, ...] = ()

    _downloader: Downloader | None = None
    _parsers: list[BaseParser] = []
    _recent: dict[tuple[str, str], float] = {}
    _blacklist: set[str] = set()

    async def on_load(self) -> None:
        if not self.config.plugin.enabled:
            self.ctx.logger.info("Multi platform parser disabled")
            return
        core_cfg = self._build_core_config()
        self._downloader = Downloader(core_cfg)

        enabled = set(core_cfg.parser.enabled_platforms())
        self._parsers = [
            parser_cls(core_cfg, self._downloader)
            for parser_cls in BaseParser.get_all_subclass()
            if parser_cls.platform.name in enabled
        ]
        names = ", ".join(parser.platform.display_name for parser in self._parsers) or "none"
        self.ctx.logger.info("Multi platform parser loaded: %s", names)

    async def on_unload(self) -> None:
        for parser in self._parsers:
            await parser.close_session()
        self._parsers = []
        if self._downloader is not None:
            await self._downloader.close()
            self._downloader = None
        self.ctx.logger.info("Multi platform parser unloaded")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data
        self.ctx.logger.info("Multi platform parser config updated to %s", version)

    @HookHandler(
        hook="chat.receive.after_process",
        name="multi_platform_parser_hook",
        description="自动解析抖音/小红书/小黑盒等平台链接",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
    )
    async def handle_link(self, **kwargs) -> dict[str, Any] | None:
        if not self.config.plugin.enabled or not self._parsers:
            return None

        message: dict[str, Any] = kwargs.get("message", {}) or {}
        if not self._is_allowed_group(message):
            return None

        session_id = str(message.get("session_id", "") or self._group_or_user_id(message) or "unknown")
        if session_id in self._blacklist:
            return None

        source = self._message_source(message)
        candidates = self._extract_urls(source)
        matched: tuple[BaseParser, str, Any, str] | None = None
        for url in candidates:
            for parser in self._parsers:
                try:
                    keyword, searched = parser.search_url(url)
                    matched = (parser, keyword, searched, url)
                    break
                except ParseException:
                    continue
            if matched:
                break

        if not matched:
            return None

        parser, keyword, searched, url = matched
        session_id = str(message.get("session_id", "") or self._group_or_user_id(message) or "unknown")
        if self._is_recent(session_id, url):
            return {"action": "abort"} if self.config.parser.block_ai_reply else None

        self.ctx.logger.info("Multi platform link detected: %s %s", parser.platform.display_name, url)
        asyncio.create_task(self._process_task(parser, keyword, searched, url, message))

        if self.config.parser.block_ai_reply:
            return {"action": "abort"}
        return None

    async def _process_task(self, parser: BaseParser, keyword: str, searched: Any, url: str, message: dict[str, Any]) -> None:
        try:
            # 根据群聊/私聊设置Pixiv图片混淆开关
            if parser.platform.name == "pixiv":
                is_group = self._get_group_id(message) is not None
                parser.mycfg.encrypt_image = (
                    self.config.encrypt.pixiv_encrypt_image_group if is_group
                    else self.config.encrypt.pixiv_encrypt_image_private
                )
            result = await parser.parse(keyword, searched)
            if not result.url:
                result.url = url
            await self._send_result(message, result)
        except Exception as exc:
            self.ctx.logger.warning("Multi platform parser failed for %s: %s", url, exc)
            await send_text(message, f"这个链接解析失败了：{exc}", self.config.api)

    async def _send_result(self, message: dict[str, Any], result: ParseResult) -> None:
        header = self._format_header(result)
        text_nodes: list[list[dict[str, Any]]] = []
        media_items = self._flatten_contents(result)

        if header:
            text_nodes.append([text_segment(header)])

        image_nodes: list[list[dict[str, Any]]] = []
        videos: list[VideoContent | DynamicContent] = []

        image_count = 0
        files: list[FileContent] = []
        for content in media_items:
            if isinstance(content, TextContent):
                if content.text:
                    text_nodes.append([text_segment(self._truncate(content.text, self.config.parser.max_text_chars))])
            elif isinstance(content, GraphicsContent):
                if content.text:
                    image_nodes.append([text_segment(self._truncate(content.text, self.config.parser.max_text_chars))])
                if self.config.parser.send_images and image_count < self.config.parser.max_images:
                    path = await content.get_path()
                    image_nodes.append([image_segment(path)])
                    image_count += 1
            elif isinstance(content, ImageContent):
                if self.config.parser.send_images and image_count < self.config.parser.max_images:
                    path = await content.get_path()
                    image_nodes.append([image_segment(path)])
                    image_count += 1
            elif isinstance(content, FileContent):
                files.append(content)
            elif isinstance(content, (VideoContent, DynamicContent)):
                videos.append(content)

        nodes = text_nodes + image_nodes
        sent_forward = False
        if self.config.parser.use_forward_for_multi and len(nodes) > 1 and self._get_group_id(message):
            sent_forward = await send_group_forward(message, nodes, self.config.api)

        if not sent_forward:
            if header:
                await send_text(message, header, self.config.api)
            for node in image_nodes:
                segment = node[0]
                if segment.get("type") == "text":
                    await send_text(message, segment["data"]["text"], self.config.api)
                elif segment.get("type") == "image":
                    await send_image(message, self._path_from_file_segment(segment), self.config.api)

        if self.config.parser.send_video:
            for video in videos[:1]:
                path = await video.get_path()
                await send_video(message, path, self.config.api)

        for file_content in files:
            path = await file_content.get_path()
            await send_file(message, path, file_content.name, self.config.api)

        # 如果是 Pixiv 解析且图片已混淆，发送解密提示
        if result.platform.name == "pixiv" and result.extra.get("encrypted"):
            decrypt_url = "https://nj-1307802825.cos-website.ap-nanjing.myqcloud.com/hunxiao//"
            decrypt_msg = f"图片已混淆加密，访问 {decrypt_url} 上传图片即可解除混淆查看原图"
            await send_text(message, decrypt_msg, self.config.api)

    def _build_core_config(self) -> CorePluginConfig:
        data_dir = Path(__file__).resolve().parents[2] / "data" / "multi_platform_parser"
        enabled_platforms = []
        if self.config.parser.enable_bilibili:
            enabled_platforms.append("bilibili")
        if self.config.parser.enable_douyin:
            enabled_platforms.append("douyin")
        if self.config.parser.enable_xhs:
            enabled_platforms.append("xhs")
        if self.config.parser.enable_xiaoheihe:
            enabled_platforms.append("xiaoheihe")
        if self.config.parser.enable_acfun:
            enabled_platforms.append("acfun")
        if self.config.parser.enable_instagram:
            enabled_platforms.append("instagram")
        if self.config.parser.enable_iwara:
            enabled_platforms.append("iwara")
        if self.config.parser.enable_kuaishou:
            enabled_platforms.append("kuaishou")
        if self.config.parser.enable_ncm:
            enabled_platforms.append("ncm")
        if self.config.parser.enable_nga:
            enabled_platforms.append("nga")
        if self.config.parser.enable_shipinhao:
            enabled_platforms.append("shipinhao")
        if self.config.parser.enable_tiktok:
            enabled_platforms.append("tiktok")
        if self.config.parser.enable_twitter:
            enabled_platforms.append("twitter")
        if self.config.parser.enable_weibo:
            enabled_platforms.append("weibo")
        if self.config.parser.enable_youtube:
            enabled_platforms.append("youtube")
        if self.config.parser.enable_zhihu:
            enabled_platforms.append("zhihu")
        if self.config.parser.enable_pixiv:
            enabled_platforms.append("pixiv")
        use_proxy_platforms = []
        if self.config.network.proxy_bilibili:
            use_proxy_platforms.append("bilibili")
        if self.config.network.proxy_douyin:
            use_proxy_platforms.append("douyin")
        if self.config.network.proxy_xhs:
            use_proxy_platforms.append("xhs")
        if self.config.network.proxy_xiaoheihe:
            use_proxy_platforms.append("xiaoheihe")
        if self.config.network.proxy_acfun:
            use_proxy_platforms.append("acfun")
        if self.config.network.proxy_instagram:
            use_proxy_platforms.append("instagram")
        if self.config.network.proxy_iwara:
            use_proxy_platforms.append("iwara")
        if self.config.network.proxy_kuaishou:
            use_proxy_platforms.append("kuaishou")
        if self.config.network.proxy_ncm:
            use_proxy_platforms.append("ncm")
        if self.config.network.proxy_nga:
            use_proxy_platforms.append("nga")
        if self.config.network.proxy_shipinhao:
            use_proxy_platforms.append("shipinhao")
        if self.config.network.proxy_tiktok:
            use_proxy_platforms.append("tiktok")
        if self.config.network.proxy_twitter:
            use_proxy_platforms.append("twitter")
        if self.config.network.proxy_weibo:
            use_proxy_platforms.append("weibo")
        if self.config.network.proxy_youtube:
            use_proxy_platforms.append("youtube")
        if self.config.network.proxy_zhihu:
            use_proxy_platforms.append("zhihu")
        if self.config.network.proxy_pixiv:
            use_proxy_platforms.append("pixiv")
        return CorePluginConfig(
            data_dir=data_dir,
            enabled_platforms=enabled_platforms,
            proxy=(self.config.network.proxy or "").strip() or None,
            source_max_size=self.config.parser.source_max_size_mb,
            source_max_minute=self.config.parser.source_max_minutes,
            debounce_interval=self.config.parser.debounce_seconds,
            download_timeout=self.config.network.download_timeout,
            download_retry_times=self.config.network.download_retry_times,
            common_timeout=self.config.network.common_timeout,
            bilibili_cookies=self.config.cookies.bilibili,
            douyin_cookies=self.config.cookies.douyin,
            xhs_cookies=self.config.cookies.xhs,
            xiaoheihe_cookies=self.config.cookies.xiaoheihe,
            acfun_cookies=self.config.cookies.acfun,
            instagram_cookies=self.config.cookies.instagram,
            iwara_cookies=self.config.cookies.iwara,
            kuaishou_cookies=self.config.cookies.kuaishou,
            ncm_cookies=self.config.cookies.ncm,
            nga_cookies=self.config.cookies.nga,
            shipinhao_cookies=self.config.cookies.shipinhao,
            tiktok_cookies=self.config.cookies.tiktok,
            twitter_cookies=self.config.cookies.twitter,
            weibo_cookies=self.config.cookies.weibo,
            youtube_cookies=self.config.cookies.youtube,
            zhihu_cookies=self.config.cookies.zhihu,
            pixiv_cookies=self.config.cookies.pixiv,
            pixiv_encrypt_image_group=self.config.encrypt.pixiv_encrypt_image_group,
            pixiv_encrypt_image_private=self.config.encrypt.pixiv_encrypt_image_private,
            pixiv_use_forward=self.config.parser.pixiv_use_forward,
            use_proxy_platforms=use_proxy_platforms,
        )

    def _format_header(self, result: ParseResult) -> str:
        parts = [f"{result.platform.display_name}解析"]
        if result.author and result.author.name:
            parts.append(f"作者：{result.author.name}")
        if result.title:
            parts.append(f"标题：{self._truncate(result.title, 120)}")
        if result.text:
            parts.append(self._truncate(result.text, self.config.parser.max_text_chars))
        if result.extra_info:
            parts.append(str(result.extra_info))
        if result.url:
            parts.append(f"链接：{result.url}")
        return "\n".join(part for part in parts if part)

    def _flatten_contents(self, result: ParseResult) -> list[Any]:
        contents: list[Any] = []
        if result.send_groups:
            for group in result.send_groups:
                contents.extend(group.contents)
        else:
            contents.extend(result.contents)
        if result.repost:
            contents.extend(self._flatten_contents(result.repost))
        return contents

    def _message_source(self, message: dict[str, Any]) -> str:
        parts = [str(message.get("processed_plain_text", "") or "")]
        for seg in message.get("raw_message", []) or []:
            if not isinstance(seg, dict):
                continue
            data = seg.get("data", {})
            if isinstance(data, dict):
                for key in ("url", "source_url", "jumpUrl", "content"):
                    value = data.get(key)
                    if value:
                        parts.append(str(value))
        return "\n".join(parts)

    def _extract_urls(self, text: str) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for match in URL_RE.finditer(text):
            url = match.group(0).rstrip(".,，。!！?？")
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    def _is_allowed_group(self, message: dict[str, Any]) -> bool:
        group_id = self._get_group_id(message)
        if not group_id:
            return True
        whitelist = [str(item) for item in self.config.parser.group_whitelist if str(item).strip()]
        return not whitelist or group_id in whitelist

    def _is_recent(self, session_id: str, url: str) -> bool:
        interval = int(self.config.parser.debounce_seconds)
        if interval <= 0:
            return False
        now = time.time()
        key = (session_id, url)
        expires_at = self._recent.get(key, 0)
        self._recent[key] = now + interval
        for old_key, old_expires in list(self._recent.items()):
            if old_expires < now:
                self._recent.pop(old_key, None)
        return expires_at > now

    def _group_or_user_id(self, message: dict[str, Any]) -> str | None:
        return self._get_group_id(message) or self._get_user_id(message)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        text = str(text or "").strip()
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 1)].rstrip() + "…"

    @staticmethod
    def _path_from_file_segment(segment: dict[str, Any]) -> Path:
        file_value = str(segment.get("data", {}).get("file", ""))
        if file_value.startswith("file://"):
            parsed = urllib.parse.urlparse(file_value)
            return Path(urllib.request.url2pathname(parsed.path))
        return Path(file_value)

    @staticmethod
    def _get_group_id(message: dict[str, Any]) -> str | None:
        message_info = message.get("message_info", {})
        group_info = message_info.get("group_info") if isinstance(message_info, dict) else None
        group_id = group_info.get("group_id") if isinstance(group_info, dict) else None
        return str(group_id) if group_id else None

    def _get_user_id(self, kwargs: dict[str, Any]) -> str | None:
        user_id = str(kwargs.get("user_id", "") or "")
        if user_id:
            return user_id
        message = kwargs.get("message", {}) or {}
        message_info = message.get("message_info", {}) if isinstance(message, dict) else {}
        user_info = message_info.get("user_info", {}) if isinstance(message_info, dict) else {}
        user_id = user_info.get("user_id") if isinstance(user_info, dict) else None
        return str(user_id) if user_id else None

    def _get_bilibili_parser(self) -> BilibiliParser | None:
        for parser in self._parsers:
            if isinstance(parser, BilibiliParser):
                return parser
        return None

    def _is_admin(self, user_id: str) -> bool:
        admin_qqs = [str(qq).strip() for qq in self.config.plugin.admin_qqs if str(qq).strip()]
        return user_id in admin_qqs

    @Command("open_parser", pattern=r"^开启解析$")
    async def open_parser(self, **kwargs):
        """开启当前会话的解析（仅管理员）"""
        stream_id = str(kwargs.get("stream_id", "") or "")
        user_id = self._get_user_id(kwargs) or ""
        if not self._is_admin(user_id):
            await self.ctx.send.text("权限不足，只有管理员可以执行此命令", stream_id)
            return True, "权限不足", 2
        if stream_id and stream_id in self._blacklist:
            self._blacklist.remove(stream_id)
            await self.ctx.send.text("当前会话的解析已开启", stream_id)
        else:
            await self.ctx.send.text("当前会话的解析本来就是开启的", stream_id)
        return True, "已处理", 2

    @Command("close_parser", pattern=r"^关闭解析$")
    async def close_parser(self, **kwargs):
        """关闭当前会话的解析（仅管理员）"""
        stream_id = str(kwargs.get("stream_id", "") or "")
        user_id = self._get_user_id(kwargs) or ""
        if not self._is_admin(user_id):
            await self.ctx.send.text("权限不足，只有管理员可以执行此命令", stream_id)
            return True, "权限不足", 2
        if stream_id and stream_id not in self._blacklist:
            self._blacklist.add(stream_id)
            await self.ctx.send.text("当前会话的解析已关闭", stream_id)
        else:
            await self.ctx.send.text("当前会话的解析本来就是关闭的", stream_id)
        return True, "已处理", 2

    @Command("login_bilibili", pattern=r"^(登录B站|blogin|登录b站)$")
    async def login_bilibili(self, **kwargs):
        """扫码登录B站（仅管理员）"""
        stream_id = str(kwargs.get("stream_id", "") or "")
        user_id = self._get_user_id(kwargs) or ""
        if not self._is_admin(user_id):
            await self.ctx.send.text("权限不足，只有管理员可以执行此命令", stream_id)
            return True, "权限不足", 2
        parser = self._get_bilibili_parser()
        if not parser:
            await self.ctx.send.text("B站解析器未启用，请在配置中启用 bilibili 平台", stream_id)
            return True, "B站解析器未启用", 2
        try:
            qrcode = await parser.login.login_with_qrcode()
            import base64
            qrcode_b64 = base64.b64encode(qrcode).decode()
            await self.ctx.send.image(qrcode_b64, stream_id)
            async for msg in parser.login.check_qr_state():
                await self.ctx.send.text(msg, stream_id)
            return True, "登录流程已完成", 2
        except Exception as exc:
            self.ctx.logger.warning("B站登录失败: %s", exc)
            await self.ctx.send.text(f"登录失败: {exc}", stream_id)
            return True, f"登录失败: {exc}", 2


def create_plugin() -> MultiPlatformParserPlugin:
    return MultiPlatformParserPlugin()
