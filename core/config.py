from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class ParserItem:
    name: str
    enable: bool = True
    use_proxy: bool = False
    cookies: str = ""
    show_body_text: bool = True
    video_send_mode: str = "first"
    video_codecs: str = "AVC"
    video_quality: str = "_720P"
    nsfw: str = ""
    max_page: int = 0
    encrypt_image: bool = False
    forward_image: bool = True


class ParserConfig:
    def __init__(self, items: Iterable[ParserItem]):
        self._nodes: dict[str, ParserItem] = {}
        for item in items:
            self._nodes[item.name] = item
            setattr(self, item.name, item)

    def platforms(self) -> list[str]:
        return list(self._nodes.keys())

    def enabled_platforms(self) -> list[str]:
        return [name for name, item in self._nodes.items() if item.enable]


class PluginConfig:
    def __init__(
        self,
        *,
        data_dir: Path,
        enabled_platforms: list[str],
        proxy: str | None = None,
        source_max_size: int = 80,
        source_max_minute: int = 8,
        debounce_interval: int = 120,
        download_timeout: int = 120,
        download_retry_times: int = 1,
        common_timeout: int = 30,
        bilibili_cookies: str = "",
        bilibili_video_codecs: str = "AVC",
        bilibili_video_quality: str = "_720P",
        douyin_cookies: str = "",
        xhs_cookies: str = "",
        xiaoheihe_cookies: str = "",
        xiaoheihe_show_body_text: bool = True,
        acfun_cookies: str = "",
        instagram_cookies: str = "",
        iwara_cookies: str = "",
        iwara_nsfw: str = "blur",
        kuaishou_cookies: str = "",
        ncm_cookies: str = "",
        nga_cookies: str = "",
        shipinhao_cookies: str = "",
        tiktok_cookies: str = "",
        twitter_cookies: str = "",
        weibo_cookies: str = "",
        youtube_cookies: str = "",
        zhihu_cookies: str = "",
        pixiv_cookies: str = "",
        pixiv_nsfw: str = "blur",
        pixiv_max_page: int = 0,
        pixiv_encrypt_image_group: bool = True,
        pixiv_encrypt_image_private: bool = False,
        pixiv_forward_image: bool = True,
        use_proxy_platforms: list[str] | None = None,
    ):
        self.whitelist: list[str] = []
        self.blacklist: list[str] = []
        self.arbiter = False
        self.debounce_interval = debounce_interval
        self.source_max_size = source_max_size
        self.source_max_minute = source_max_minute
        self.audio_to_file = True
        self.single_heavy_render_card = False
        self.forward_threshold = 4
        self.show_download_fail_tip = True
        self.download_timeout = download_timeout
        self.download_retry_times = download_retry_times
        self.common_timeout = common_timeout
        self.proxy = proxy or None
        self.clean_cron = ""

        self.max_duration = source_max_minute * 60
        self.max_size = source_max_size * 1024 * 1024

        self.data_dir = data_dir
        self.cache_dir = data_dir / "cache"
        self.cookie_dir = data_dir / "cookies"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_dir.mkdir(parents=True, exist_ok=True)

        proxy_platforms = set(use_proxy_platforms or [])
        enabled = set(enabled_platforms)
        self.parser = ParserConfig(
            [
                ParserItem(
                    "bilibili",
                    enable="bilibili" in enabled,
                    use_proxy="bilibili" in proxy_platforms,
                    cookies=bilibili_cookies,
                    video_codecs=bilibili_video_codecs,
                    video_quality=bilibili_video_quality,
                ),
                ParserItem(
                    "douyin",
                    enable="douyin" in enabled,
                    use_proxy="douyin" in proxy_platforms,
                    cookies=douyin_cookies,
                ),
                ParserItem(
                    "xhs",
                    enable="xhs" in enabled,
                    use_proxy="xhs" in proxy_platforms,
                    cookies=xhs_cookies,
                ),
                ParserItem(
                    "xiaoheihe",
                    enable="xiaoheihe" in enabled,
                    use_proxy="xiaoheihe" in proxy_platforms,
                    cookies=xiaoheihe_cookies,
                    show_body_text=xiaoheihe_show_body_text,
                ),
                ParserItem(
                    "acfun",
                    enable="acfun" in enabled,
                    use_proxy="acfun" in proxy_platforms,
                    cookies=acfun_cookies,
                ),
                ParserItem(
                    "instagram",
                    enable="instagram" in enabled,
                    use_proxy="instagram" in proxy_platforms,
                    cookies=instagram_cookies,
                ),
                ParserItem(
                    "iwara",
                    enable="iwara" in enabled,
                    use_proxy="iwara" in proxy_platforms,
                    cookies=iwara_cookies,
                    nsfw=iwara_nsfw,
                ),
                ParserItem(
                    "kuaishou",
                    enable="kuaishou" in enabled,
                    use_proxy="kuaishou" in proxy_platforms,
                    cookies=kuaishou_cookies,
                ),
                ParserItem(
                    "ncm",
                    enable="ncm" in enabled,
                    use_proxy="ncm" in proxy_platforms,
                    cookies=ncm_cookies,
                ),
                ParserItem(
                    "nga",
                    enable="nga" in enabled,
                    use_proxy="nga" in proxy_platforms,
                    cookies=nga_cookies,
                ),
                ParserItem(
                    "shipinhao",
                    enable="shipinhao" in enabled,
                    use_proxy="shipinhao" in proxy_platforms,
                    cookies=shipinhao_cookies,
                ),
                ParserItem(
                    "tiktok",
                    enable="tiktok" in enabled,
                    use_proxy="tiktok" in proxy_platforms,
                    cookies=tiktok_cookies,
                ),
                ParserItem(
                    "twitter",
                    enable="twitter" in enabled,
                    use_proxy="twitter" in proxy_platforms,
                    cookies=twitter_cookies,
                ),
                ParserItem(
                    "weibo",
                    enable="weibo" in enabled,
                    use_proxy="weibo" in proxy_platforms,
                    cookies=weibo_cookies,
                ),
                ParserItem(
                    "youtube",
                    enable="youtube" in enabled,
                    use_proxy="youtube" in proxy_platforms,
                    cookies=youtube_cookies,
                ),
                ParserItem(
                    "zhihu",
                    enable="zhihu" in enabled,
                    use_proxy="zhihu" in proxy_platforms,
                    cookies=zhihu_cookies,
                ),
                ParserItem(
                    "pixiv",
                    enable="pixiv" in enabled,
                    use_proxy="pixiv" in proxy_platforms,
                    cookies=pixiv_cookies,
                    nsfw=pixiv_nsfw,
                    max_page=pixiv_max_page,
                    encrypt_image=False,  # 由 plugin.py 根据群聊/私聊动态设置
                    forward_image=pixiv_forward_image,
                ),
            ]
        )

    def add_blacklist(self, umo: str) -> None:
        if umo not in self.blacklist:
            self.blacklist.append(umo)

    def remove_blacklist(self, umo: str) -> None:
        if umo in self.blacklist:
            self.blacklist.remove(umo)