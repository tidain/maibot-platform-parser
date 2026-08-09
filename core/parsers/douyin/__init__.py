import re
from typing import TYPE_CHECKING, ClassVar

import msgspec

import logging
logger = logging.getLogger(__name__)

from ...config import PluginConfig
from ...cookie import CookieJar
from ..base import (
    BaseParser,
    Downloader,
    ParseException,
    Platform,
    handle,
)

if TYPE_CHECKING:
    from ...data import ParseResult


class DouyinParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name="douyin", display_name="抖音")

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.douyin
        self.cookiejar = CookieJar(config, self.mycfg, domain="douyin.com")
        self._set_cookies()

    def _set_cookies(self, cookies_str: str = ""):
        """设置cookie到请求头"""
        cookies_str = cookies_str or self.cookiejar.cookies_str
        if cookies_str:
            self.ios_headers["Cookie"] = cookies_str
            self.android_headers["Cookie"] = cookies_str

    # https://v.douyin.com/_2ljF4AmKL8
    @handle("v.douyin", r"v\.douyin\.com/[a-zA-Z0-9_\-]+")
    @handle("jx.douyin", r"jx\.douyin\.com/[a-zA-Z0-9_\-]+")
    async def _parse_short_link(self, searched: re.Match[str]):
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    # https://www.douyin.com/video/7521023890996514083
    # https://www.douyin.com/note/7469411074119322899
    @handle("douyin", r"douyin\.com/(?P<ty>video|note)/(?P<vid>\d+)")
    @handle("iesdouyin", r"iesdouyin\.com/share/(?P<ty>slides|video|note)/(?P<vid>\d+)")
    @handle("m.douyin", r"m\.douyin\.com/share/(?P<ty>slides|video|note)/(?P<vid>\d+)")
    # https://jingxuan.douyin.com/m/video/7574300896016862490?app=yumme&utm_source=copy_link
    @handle(
        "jingxuan.douyin",
        r"jingxuan\.douyin.com/m/(?P<ty>slides|video|note)/(?P<vid>\d+)",
    )
    async def _parse_douyin(self, searched: re.Match[str]):
        ty, vid = searched.group("ty"), searched.group("vid")
        logger.debug(f"[抖音] 解析类型: {ty}, ID: {vid}")
        if ty == "slides":
            return await self.parse_slides(vid)

        urls = (
            self._build_m_douyin_url(ty, vid),
            self._build_iesdouyin_url(ty, vid),
        )
        logger.debug(f"[抖音] 尝试解析URL列表: {urls}")

        for url in urls:
            try:
                logger.debug(f"[抖音] 尝试解析: {url}")
                return await self.parse_video(url)
            except ParseException as e:
                logger.warning(f"[抖音] 解析失败 {url}, 错误: {e}")
                continue
        raise ParseException("分享已删除或资源直链提取失败, 请稍后再试")

    @staticmethod
    def _build_iesdouyin_url(ty: str, vid: str) -> str:
        return f"https://www.iesdouyin.com/share/{ty}/{vid}"

    @staticmethod
    def _build_m_douyin_url(ty: str, vid: str) -> str:
        return f"https://m.douyin.com/share/{ty}/{vid}"

    async def parse_with_redirect(self, url: str) -> "ParseResult":
        """先重定向再解析，并更新 cookies"""
        logger.debug(f"[抖音] 短链重定向请求: {url}")
        try:
            async with self.session.get(
                url, headers=self.ios_headers, allow_redirects=False
            ) as resp:
                logger.debug(f"[抖音] 短链重定向响应状态码: {resp.status}")
                # 从响应中提取 Set-Cookie 并更新
                set_cookie_headers = resp.headers.getall("Set-Cookie", [])
                self.cookiejar.update_from_response(set_cookie_headers)
                self._set_cookies()

                # 只有在状态码是重定向状态码时才获取 Location
                redirect_url = url
                if resp.status in (301, 302, 303, 307, 308):
                    redirect_url = resp.headers.get("Location", url)
                    logger.debug(f"[抖音] 重定向到: {redirect_url}")
        except Exception as e:
            if "getaddrinfo failed" in str(e):
                raise ParseException("抖音链接解析失败：无法访问抖音服务器，请检查网络或配置代理") from e
            raise

        if redirect_url == url:
            raise ParseException(f"无法重定向 URL: {url}")

        keyword, searched = self.search_url(redirect_url)
        return await self.parse(keyword, searched)

    async def parse_video(self, url: str):
        async with self.session.get(
            url, headers=self.ios_headers, allow_redirects=False
        ) as resp:
            if resp.status != 200:
                raise ParseException(f"status: {resp.status}")
            text = await resp.text()
            set_cookie_headers = resp.headers.getall("Set-Cookie", [])
            self.cookiejar.update_from_response(set_cookie_headers)
            self._set_cookies()

        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        matched = pattern.search(text)

        if not matched or not matched.group(1):
            logger.debug("[抖音] 未在HTML中找到 window._ROUTER_DATA")
            raise ParseException("can't find _ROUTER_DATA in html")

        logger.debug("[抖音] 成功提取 window._ROUTER_DATA")

        from .video import RouterData

        video_data = msgspec.json.decode(
            matched.group(1).strip(), type=RouterData
        ).video_data
        logger.debug(
            f"[抖音] 解析成功 - 作者: {video_data.author.nickname}, 描述: {video_data.desc[:50]}..."
        )
        # 使用新的简洁构建方式
        contents = []

        # 添加图片内容
        if image_urls := video_data.image_urls:
            logger.debug(f"[抖音] 检测到图文内容，图片数量: {len(image_urls)}")
            contents.extend(
                self.create_image_contents(image_urls, headers=self.ios_headers)
            )

        # 添加视频内容
        elif video_url := video_data.video_url:
            cover_url = video_data.cover_url
            duration = video_data.video.duration if video_data.video else 0
            logger.debug(f"[抖音] 检测到视频内容，时长: {duration}秒")
            contents.append(
                self.create_video_content(
                    video_url, cover_url, duration, headers=self.ios_headers
                )
            )

        # 构建作者
        author = self.create_author(
            video_data.author.nickname, video_data.avatar_url, headers=self.ios_headers
        )

        return self.result(
            title=video_data.desc,
            author=author,
            contents=contents,
            timestamp=video_data.create_time,
        )

    async def parse_slides(self, video_id: str):
        url = "https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/"
        params = {
            "aweme_ids": f"[{video_id}]",
            "request_source": "200",
        }
        logger.debug(f"[抖音] 请求参数: {params}")
        async with self.session.get(
            url, params=params, headers=self.android_headers
        ) as resp:
            logger.debug(f"[抖音] 幻灯片API响应状态码: {resp.status}")
            resp.raise_for_status()
            # 从响应中提取 Set-Cookie 并更新
            set_cookie_headers = resp.headers.getall("Set-Cookie", [])
            self.cookiejar.update_from_response(set_cookie_headers)
            self._set_cookies()

            from .slides import SlidesInfo

            response_text = await resp.read()
            logger.debug(f"[抖音] 幻灯片API响应体大小: {len(response_text)} 字节")
            slides_data = msgspec.json.decode(
                response_text, type=SlidesInfo
            ).aweme_details[0]
        logger.debug(
            f"[抖音] 幻灯片解析成功 - 作者: {slides_data.name}, 描述: {slides_data.desc[:50]}..."
        )
        contents = []

        # 添加图片内容
        if image_urls := slides_data.image_urls:
            logger.debug(f"[抖音] 检测到幻灯片图片，数量: {len(image_urls)}")
            contents.extend(
                self.create_image_contents(image_urls, headers=self.android_headers)
            )

        # 添加动态内容
        if dynamic_urls := slides_data.dynamic_urls:
            logger.debug(f"[抖音] 检测到幻灯片动态效果，数量: {len(dynamic_urls)}")
            contents.extend(
                self.create_dynamic_contents(dynamic_urls, headers=self.android_headers)
            )

        # 构建作者
        author = self.create_author(
            slides_data.name, slides_data.avatar_url, headers=self.android_headers
        )

        return self.result(
            title=slides_data.desc,
            author=author,
            contents=contents,
            timestamp=slides_data.create_time,
        )
