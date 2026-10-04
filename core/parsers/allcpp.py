"""CPP 无差别同人站（allcpp.cn）展品解析器"""

import json
from html import unescape
from re import DOTALL, Match, findall, search, sub
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit

from aiohttp import ClientError

from ..config import PluginConfig
from ..cookie import CookieJar
from ..data import MediaContent, Platform, SendGroup, TextContent
from ..download import Downloader
from .base import BaseParser, ParseException, handle

# 图片 CDN，与页面 `getLookWebPicUrl()` 对应
PIC_CDN = "https://imagecdn3.allcpp.cn"
SITE_BASE = "https://www.allcpp.cn/"


class AllcppParser(BaseParser):
    """allcpp.cn（无差别同人站）解析器

    展品详情页（/d/<id>.do）会服务端渲染标题、封面、标签、作者等信息；
    图集（试阅）内容走 ``allcpp/doujinshi/contribute/getList.do`` 接口，
    该接口需要登录，未配置 Cookie 时退化为仅返回封面。

    图文（后花园文章）详情页（/w/<id>.do）内容由前端通过
    ``works.allcpp.cn/rest/works/<id>`` 接口异步加载，这里直接请求该接口。
    """

    platform: ClassVar[Platform] = Platform(
        name="allcpp", display_name="CPP无差别同人站"
    )

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.allcpp
        self.headers.update(
            {
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "referer": "https://www.allcpp.cn/",
            }
        )
        # 公开资源不携带 Cookie，避免把登录态暴露给不需要鉴权的请求。
        self.auth_headers = self.headers.copy()
        self.cookiejar = CookieJar(config, self.mycfg, domain="allcpp.cn")
        if self.cookiejar.cookies_str:
            self.auth_headers["cookie"] = self.cookiejar.cookies_str

    # https://icp.red/WmBvrs8XK （短链，重定向到 allcpp 展品页）
    @handle("icp.red", r"icp\.red/(?P<short_code>[A-Za-z0-9]+)")
    async def _parse_short_link(self, searched: Match[str]):
        url = f"https://icp.red/{searched.group('short_code')}"
        return await self.parse_with_redirect(url)

    @handle("allcpp.cn", r"allcpp\.cn/d/(?P<did>\d+)")
    async def _parse(self, searched: Match[str]):
        did = searched.group("did")
        page_url = f"https://www.allcpp.cn/d/{did}.do"

        html_text = await self._fetch_page(page_url)
        info = self._parse_page(html_text)

        title = info["title"] or f"展品 {did}"
        author = self.create_author(info["author_name"]) if info["author_name"] else None

        # 图集（试阅）需要登录，未登录时退化为仅封面；样图同样并入
        gallery, external_links = self._extract_gallery_content(
            await self._fetch_gallery(did)
        )
        info["external_links"].extend(external_links)
        public_image_urls = self._collect_images(info["cover"], [])
        protected_image_urls = self._collect_images(
            None, gallery + info["sample_images"]
        )
        public_keys = {url.split("?", 1)[0] for url in public_image_urls}
        protected_image_urls = [
            url
            for url in protected_image_urls
            if url.split("?", 1)[0] not in public_keys
        ]

        image_contents: list[MediaContent] = []
        if public_image_urls:
            image_contents.extend(
                self.create_image_contents(
                    public_image_urls,
                    headers=self._image_headers(page_url),
                )
            )
        if protected_image_urls:
            image_contents.extend(
                self.create_image_contents(
                    protected_image_urls,
                    headers=self._image_headers(page_url, use_auth=True),
                )
            )

        text = self._build_text(info, title)
        contents: list[MediaContent] = []
        if text:
            contents.append(TextContent(text))
        contents.extend(image_contents)

        send_groups: list[SendGroup] = []
        if len(contents) >= self.cfg.forward_threshold:
            # 达到阈值：整体一个 group，不设 force_merge，交由 sender 合并转发
            send_groups.append(SendGroup(contents=contents))
        else:
            if text:
                send_groups.append(
                    SendGroup(contents=[TextContent(text)], force_merge=False)
                )
            for img in image_contents:
                send_groups.append(SendGroup(contents=[img], force_merge=False))

        return self.result(
            title=title,
            text=text,
            author=author,
            contents=contents,
            send_groups=send_groups,
            url=page_url,
        )

    # https://www.allcpp.cn/w/<id>.do 图文（后花园文章）详情页
    @handle("allcpp.cn/w/", r"allcpp\.cn/w/(?P<wid>\d+)")
    async def _parse_work(self, searched: Match[str]):
        wid = searched.group("wid")
        page_url = f"https://www.allcpp.cn/w/{wid}.do"

        info = self._parse_work_data(await self._fetch_work(wid))

        title = info["title"] or f"图文 {wid}"
        image_headers = self._image_headers(page_url)
        author = (
            self.create_author(
                info["author_name"],
                avatar_url=info["author_avatar"],
                headers=image_headers,
            )
            if info["author_name"]
            else None
        )

        image_urls = self._collect_images(None, info["pics"])
        image_contents: list[MediaContent] = (
            self.create_image_contents(image_urls, headers=image_headers)
            if image_urls
            else []
        )

        show_work_content = bool(getattr(self.mycfg, "show_work_content", False))
        max_length = int(getattr(self.mycfg, "text_max_length", 100) or 100)

        text = self._build_work_text(
            info,
            title,
            show_work_content=show_work_content,
            max_length=max_length,
        )
        contents: list[MediaContent] = []
        if text:
            contents.append(TextContent(text))
        contents.extend(image_contents)

        send_groups: list[SendGroup] = []
        if len(contents) >= self.cfg.forward_threshold:
            send_groups.append(SendGroup(contents=contents))
        else:
            if text:
                send_groups.append(
                    SendGroup(contents=[TextContent(text)], force_merge=False)
                )
            for img in image_contents:
                send_groups.append(SendGroup(contents=[img], force_merge=False))

        return self.result(
            title=title,
            text=text,
            author=author,
            contents=contents,
            send_groups=send_groups,
            url=page_url,
        )

    async def _fetch_page(self, url: str) -> str:
        """拉取展品详情页 HTML"""
        async with self.session.get(url, headers=self.auth_headers) as resp:
            if resp.status >= 400:
                raise ClientError(f"HTTP {resp.status} {resp.reason}")
            return await resp.text()

    def _image_headers(
        self, page_url: str, *, use_auth: bool = False
    ) -> dict[str, str]:
        """生成图片请求头；仅登录后可见的详情/试阅图片携带 Cookie。"""
        headers = self.auth_headers if use_auth else self.headers
        return {**headers, "referer": page_url}

    async def _fetch_gallery(self, did: str) -> list[dict[str, Any]]:
        """拉取展品试阅（图集）内容，失败或未登录时返回空列表"""
        url = "https://www.allcpp.cn/allcpp/doujinshi/contribute/getList.do"
        params = {"pageindex": 1, "pagesize": 20, "id": did, "_plat": "web"}
        try:
            async with self.session.get(
                url, params=params, headers=self.auth_headers
            ) as resp:
                if resp.status >= 400:
                    return []
                data = await resp.json()
        except (ClientError, TimeoutError, ValueError):
            return []
        return data if isinstance(data, list) else []

    async def _fetch_work(self, wid: str) -> dict[str, Any]:
        """拉取图文（后花园文章）详情，接口在 works.allcpp.cn 子域"""
        url = f"https://works.allcpp.cn/rest/works/{wid}"
        try:
            async with self.session.get(url, headers=self.headers) as resp:
                if resp.status >= 400:
                    raise ClientError(f"HTTP {resp.status} {resp.reason}")
                text = await resp.text()
                data = json.loads(text) if text.strip() else None
        except (ClientError, TimeoutError, ValueError):
            raise ParseException(f"图文 {wid} 不存在或已删除")
        if not isinstance(data, dict) or not data.get("id"):
            raise ParseException(f"图文 {wid} 不存在或已删除")
        return data

    def _parse_page(self, html_text: str) -> dict[str, Any]:
        """从详情页 HTML 提取公开信息"""
        info: dict[str, Any] = {
            "title": None,
            "cover": None,
            "tags": [],
            "heat": None,
            "status": None,
            "author_name": None,
            "detail_text": None,
            "sample_images": [],
            "external_links": [],
            "is_logged_in": False,
        }

        # 标题
        if m := search(r'<h1 class="djs-info-title">(.*?)</h1>', html_text, DOTALL):
            info["title"] = self._clean_text(m.group(1))

        # 登录态（IS_USER_TRUENAME=true 表示已登录且实名）
        if m := search(r"var IS_USER_TRUENAME=(\w+);", html_text):
            info["is_logged_in"] = m.group(1).lower() == "true"

        # 展品级试阅外链（登录后页面脚本中的 shiyueUrl / otherUrl）。
        info["external_links"].extend(
            self._extract_trial_url_variables(html_text)
        )

        # 封面（取原图 href，不含 OSS 压缩样式）
        if m := search(r'<a class="djs-info-cover"[^>]*href="([^"]+)"', html_text):
            info["cover"] = self._normalize_page_url(m.group(1))

        # 标签
        if m := search(r'<ul class="djs-info-tag">(.*?)</ul>', html_text, DOTALL):
            tags = [
                self._clean_text(t)
                for t in findall(r"<li[^>]*>(.*?)</li>", m.group(1), DOTALL)
            ]
            info["tags"] = [t for t in tags if t]

        # 总热度
        if m := search(r'class="djs-info-hot-txt">(.*?)</label>', html_text, DOTALL):
            if span := search(r"<span>([^<]+)</span>", m.group(1)):
                info["heat"] = span.group(1).strip()

        # 状态（策划中 / 已发售 等）
        if m := search(r'class="sell-url[^"]*"[^>]*>(.*?)</a>', html_text, DOTALL):
            info["status"] = self._clean_text(m.group(1))

        # 上传人信息（作者）
        if m := search(r'<div id="djs-create-user">(.*?)</div>', html_text, DOTALL):
            uploader_block = m.group(1)
            if title_m := search(r'title="([^"]+)"', uploader_block):
                info["author_name"] = title_m.group(1).strip()
            elif label_m := search(r"<label[^>]*>(.*?)</label>", uploader_block, DOTALL):
                info["author_name"] = self._clean_text(label_m.group(1))

        # 展品详情（登录后才有）：文字描述 + 图集样图
        if m := search(
            r'<div class="djs-tab-box info[^"]*"[^>]*>(.*?)</div>',
            html_text,
            DOTALL,
        ):
            detail_block = m.group(1)
            if p := search(r"<p[^>]*>(.*?)</p>", detail_block, DOTALL):
                info["detail_text"] = self._clean_detail(p.group(1))
            info["sample_images"] = [
                url
                for u in findall(r'<img[^>]*src="([^"]+)"', detail_block)
                if (url := self._build_content_pic_url(u))
            ]
            info["external_links"].extend(
                self._extract_external_links(detail_block)
            )

        info["external_links"] = self._deduplicate_links(info["external_links"])
        return info

    @staticmethod
    def _parse_work_data(work: dict[str, Any]) -> dict[str, Any]:
        """从图文接口数据中提取展示信息"""
        user = AllcppParser._as_dict(work.get("user"))
        face = AllcppParser._as_dict(user.get("face"))
        author_name = user.get("nickname")
        author_avatar = face.get("picUrl")

        info: dict[str, Any] = {
            "title": work.get("name"),
            "author_name": author_name if isinstance(author_name, str) else None,
            "author_avatar": AllcppParser._build_face_url(
                author_avatar if isinstance(author_avatar, str) else ""
            ),
            "theme": work.get("theme"),
            "type_label": AllcppParser._work_type_label(work.get("type")),
            "hot": work.get("hotCount"),
            "tags": [],
            "foreword": None,
            "content": None,
            "pics": [],
        }

        tags = work.get("tags")
        if isinstance(tags, list):
            info["tags"] = [
                t.get("tag")
                for t in tags
                if isinstance(t, dict) and t.get("tag")
            ]

        foreword = work.get("foreword")
        if isinstance(foreword, str) and foreword.strip():
            info["foreword"] = AllcppParser._clean_detail(foreword)

        content = work.get("content")
        if isinstance(content, str) and content.strip():
            info["pics"].extend(AllcppParser._extract_content_images(content))
            info["content"] = AllcppParser._clean_detail(content)

        pics = work.get("pics")
        if isinstance(pics, list):
            for p in pics:
                if not isinstance(p, dict):
                    continue
                pic = p.get("pic")
                pic_url = pic.get("picUrl") if isinstance(pic, dict) else None
                url = AllcppParser._build_pic_url(str(pic_url) if pic_url else "")
                if url:
                    info["pics"].append(url)

        return info

    @staticmethod
    def _work_type_label(work_type: Any) -> str | None:
        """图文类型标签：0=图片，1=文字"""
        if work_type == 0:
            return "图片"
        if work_type == 1:
            return "文字"
        return None

    @staticmethod
    def _extract_content_images(content: str) -> list[str]:
        """提取图文正文内嵌的图片（/uupload/image/... 相对路径）"""
        images: list[str] = []
        for src in findall(r'<img[^>]*src="([^"]+)"', content):
            url = AllcppParser._build_content_pic_url(src)
            if url:
                images.append(url)
        return images

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        """接口字段异常时降级为空对象，避免单个字段导致整个解析失败。"""
        return value if isinstance(value, dict) else {}

    def _extract_gallery_content(
        self, data: list[dict[str, Any]]
    ) -> tuple[list[str], list[str]]:
        """从试阅接口数据中提取图片及图文试阅内的外部链接。"""
        images: list[str] = []
        external_links: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            works = item.get("works")
            if not isinstance(works, dict):
                continue

            content = works.get("content")
            if isinstance(content, str):
                external_links.extend(self._extract_external_links(content))

            pics = works.get("pics")
            if not isinstance(pics, list):
                continue
            for p in pics:
                if not isinstance(p, dict):
                    continue
                pic = p.get("pic")
                pic_url = pic.get("picUrl") if isinstance(pic, dict) else None
                if not pic_url:
                    pic_url = p.get("picUrl")
                url = self._build_pic_url(str(pic_url) if pic_url else "")
                if url:
                    images.append(url)
        return images, self._deduplicate_links(external_links)

    @staticmethod
    def _build_text(info: dict[str, Any], title: str) -> str | None:
        parts: list[str] = []
        if title:
            parts.append(title)
        if info.get("author_name"):
            parts.append(f"作者：{info['author_name']}")
        if info.get("tags"):
            parts.append("标签：" + " · ".join(info["tags"]))
        if info.get("heat"):
            parts.append(f"总热度：{info['heat']}")
        if info.get("status"):
            parts.append(f"状态：{info['status']}")
        if info.get("detail_text"):
            parts.append(info["detail_text"])
        if links := info.get("external_links"):
            parts.append("试阅外部链接：\n" + "\n".join(links))
        if not info.get("is_logged_in"):
            parts.append("（未登录，无法获取展品详情与图集，配置 Cookie 后可查看）")
        return "\n".join(parts) if parts else None

    @staticmethod
    def _build_work_text(
        info: dict[str, Any],
        title: str,
        *,
        show_work_content: bool = False,
        max_length: int = 100,
    ) -> str | None:
        parts: list[str] = []
        if title:
            parts.append(title)
        if info.get("author_name"):
            parts.append(f"作者：{info['author_name']}")
        if info.get("theme"):
            parts.append(f"主题：{info['theme']}")
        if info.get("type_label"):
            parts.append(f"类型：{info['type_label']}")
        if info.get("tags"):
            parts.append("标签：" + " · ".join(info["tags"]))
        if info.get("hot"):
            parts.append(f"热度：{info['hot']}")
        if info.get("foreword"):
            parts.append(info["foreword"])
        # 正文：图片类始终展示；文字类受「显示正文」配置控制
        if info.get("content") and (
            info.get("type_label") != "文字" or show_work_content
        ):
            parts.append(info["content"])
        text = "\n".join(parts) if parts else None
        # 仅文字类图文限制字数，图片类不截断
        if (
            text
            and info.get("type_label") == "文字"
            and max_length > 0
            and len(text) > max_length
        ):
            text = text[: max_length - 1] + "…"
        return text

    @staticmethod
    def _collect_images(cover: str | None, gallery: list[str]) -> list[str]:
        """合并封面与图集，去重"""
        images: list[str] = []
        seen: set[str] = set()
        for url in ([cover] if cover else []) + gallery:
            key = url.split("?", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            images.append(url)
        return images

    @staticmethod
    def _build_pic_url(raw: str) -> str | None:
        raw = unescape(raw or "").strip()
        if not raw:
            return None
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("//"):
            return f"https:{raw}"
        if raw.startswith("/upload/"):
            return f"{PIC_CDN}{raw}"
        if raw.startswith("upload/"):
            return f"{PIC_CDN}/{raw}"
        return f"{PIC_CDN}/upload/{raw.lstrip('/')}"

    @staticmethod
    def _build_face_url(raw: str) -> str | None:
        """用户头像 URL（/face/ 目录）"""
        raw = unescape(raw or "").strip()
        if not raw:
            return None
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("//"):
            return f"https:{raw}"
        if raw.startswith("/face/"):
            return f"{PIC_CDN}{raw}"
        if raw.startswith("face/"):
            return f"{PIC_CDN}/{raw}"
        return f"{PIC_CDN}/face/{raw.lstrip('/')}"

    @staticmethod
    def _build_content_pic_url(raw: str) -> str | None:
        """正文内嵌图片 URL（/uupload/image/... 已含目录前缀）"""
        raw = unescape(raw or "").strip()
        if not raw:
            return None
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("//"):
            return f"https:{raw}"
        return f"{PIC_CDN}/{raw.lstrip('/')}"

    @staticmethod
    def _normalize_page_url(raw: str) -> str | None:
        """将详情页里引用的封面地址统一为可下载的绝对 HTTP(S) URL。"""
        value = unescape(raw or "").strip()
        if not value:
            return None
        url = urljoin(SITE_BASE, value)
        return url if url.startswith(("http://", "https://")) else None

    @staticmethod
    def _extract_external_links(content: str) -> list[str]:
        """提取试阅 HTML 中的外部 HTTP(S) 链接，忽略 AllCPP 站内地址。"""
        raw_links = findall(
            r"(?:https?:)?//[^\s<>\"']+", unescape(content or "")
        )
        raw_links = [
            f"https:{url}" if url.startswith("//") else url for url in raw_links
        ]
        return AllcppParser._deduplicate_links(raw_links)

    @staticmethod
    def _extract_trial_url_variables(content: str) -> list[str]:
        """提取展品详情页脚本注入的试阅外链变量。"""
        values = findall(
            r"(?:shiyueUrl|otherUrl)\s*[:=]\s*[\"']([^\"']+)[\"']",
            unescape(content or ""),
        )
        values = [
            f"https:{url}" if url.startswith("//") else url for url in values
        ]
        return AllcppParser._deduplicate_links(values)

    @staticmethod
    def _deduplicate_links(links: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in links:
            url = raw.rstrip(".,;:!?)】）〉》")
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme not in ("http", "https")
                or not host
                or host == "allcpp.cn"
                or host.endswith(".allcpp.cn")
                or url in seen
            ):
                continue
            seen.add(url)
            result.append(url)
        return result

    @staticmethod
    def _clean_text(text: str) -> str:
        text = unescape(text or "")
        text = sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _clean_detail(text: str) -> str:
        """清理 HTML 文字：去标签、<br>/</p> 换行、去空白行"""
        text = unescape(text or "")
        text = sub(r"<br\s*/?>", "\n", text)
        text = sub(r"</p>", "\n", text)
        text = sub(r"<[^>]+>", "", text)
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(line for line in lines if line)
