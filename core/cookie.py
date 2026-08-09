from __future__ import annotations

import time
from dataclasses import dataclass
from http import cookiejar
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from astrbot.api import logger

from .config import ParserItem, PluginConfig


@dataclass(slots=True)
class Cookie:
    domain: str
    path: str
    name: str
    value: str
    secure: bool
    expires: int

    def __post_init__(self) -> None:
        self.domain = self.domain.lower()

    def is_expired(self) -> bool:
        return self.expires != 0 and self.expires < int(time.time())

    def match(self, domain: str, path: str, secure: bool) -> bool:
        if self.is_expired():
            return False

        if self.secure and not secure:
            return False

        if not self._domain_matches(domain):
            return False

        return self._path_matches(path)

    def _domain_matches(self, request_domain: str) -> bool:
        cookie_domain = self.domain

        if cookie_domain.startswith("."):
            suffix = cookie_domain[1:]
            return request_domain == suffix or request_domain.endswith(f".{suffix}")

        return request_domain == cookie_domain

    def _path_matches(self, request_path: str) -> bool:
        if request_path == self.path:
            return True
        if not request_path.startswith(self.path):
            return False
        if self.path.endswith("/"):
            return True
        return (
            len(request_path) > len(self.path) and request_path[len(self.path)] == "/"
        )


class CookieJar:
    def __init__(
        self, config: PluginConfig, parser_cfg: ParserItem, domain: str
    ) -> None:
        self.domain = domain.lower()

        self.cookie_file = config.cookie_dir / f"{parser_cfg.name}_cookies.txt"
        self.cookies: list[Cookie] = []

        self.raw_cookies = parser_cfg.cookies
        self.cookies_str = ""

        if self.raw_cookies:
            self.cookies_str = self.clean_cookies_str(self.raw_cookies)
            self._load_from_cookies_str(self.cookies_str)
            self.save_to_file()

        if self.cookie_file.exists():
            self.load_from_file()

    # ---------------- public ----------------

    def file_exists(self) -> bool:
        return self.cookie_file.exists()

    def get(
        self, path: str = "/", secure: bool = True, domain: str | None = None
    ) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for cookie in self._ordered_matching_cookies(
            path=path, secure=secure, domain=domain
        ):
            cookies.setdefault(cookie.name, cookie.value)
        return cookies

    def get_cookie_header(
        self, path: str = "/", secure: bool = True, domain: str | None = None
    ) -> str:
        cookies = self._ordered_matching_cookies(
            path=path, secure=secure, domain=domain
        )
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookies)

    def get_cookie_header_for_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.hostname:
            return ""
        return self.get_cookie_header(
            domain=parsed.hostname,
            path=parsed.path or "/",
            secure=parsed.scheme == "https",
        )

    def purge_expired(self) -> None:
        self.cookies = [c for c in self.cookies if not c.is_expired()]
        self._sync_cookies_str()
        if self.cookie_file.exists() or self.cookies:
            self.save_to_file()

    def _matching_cookies(
        self, path: str = "/", secure: bool = True, domain: str | None = None
    ) -> list[Cookie]:
        request_domain = (domain or self.domain).lower()
        return [c for c in self.cookies if c.match(request_domain, path, secure)]

    def _ordered_matching_cookies(
        self, path: str = "/", secure: bool = True, domain: str | None = None
    ) -> list[Cookie]:
        return sorted(
            self._matching_cookies(path=path, secure=secure, domain=domain),
            key=lambda cookie: len(cookie.path),
            reverse=True,
        )

    def to_dict(self) -> dict[str, str]:
        """将 cookies 字符串转换为字典"""
        return self.get()

    # ---------------- persistence ----------------

    @staticmethod
    def _normalize_cookie_newlines(cookies_str: str) -> str:
        return cookies_str.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def clean_cookies_str(cookies_str: str) -> str:
        return CookieJar._normalize_cookie_newlines(cookies_str).strip(" \n")

    @staticmethod
    def _normalize_header_cookies_str(cookies_str: str) -> str:
        return CookieJar.clean_cookies_str(cookies_str).replace("\n", "")

    @staticmethod
    def _is_netscape_cookie_file(cookies_str: str) -> bool:
        valid_row_count = 0
        for line in cookies_str.splitlines():
            if line.strip().lower() == "# netscape http cookie file":
                return True
            if CookieJar._parse_netscape_cookie_line(line) is not None:
                valid_row_count += 1
                if valid_row_count >= 2:
                    return True
        return False

    @staticmethod
    def _parse_netscape_cookie_line(
        line: str,
    ) -> tuple[str, str, str, str, int, str, str] | None:
        if not line.strip():
            return None

        line = line.lstrip()
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            return None

        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")

        parts = line.split("\t")
        if len(parts) != 7:
            return None

        domain, include_subdomains, path, secure, expires, name, value = parts
        if not domain or not path or not name:
            return None
        if path[0] != "/":
            return None
        if any(sep in domain for sep in ("=", ";")):
            return None
        if any(char.isspace() for char in domain):
            return None
        if any(sep in name for sep in ("=", ";")):
            return None
        if any(char.isspace() for char in name):
            return None
        if include_subdomains.upper() not in {"TRUE", "FALSE"}:
            return None
        if secure.upper() not in {"TRUE", "FALSE"}:
            return None

        try:
            expires_at = int(expires)
        except ValueError:
            return None

        return domain, include_subdomains, path, secure, expires_at, name, value

    def _sync_cookies_str(self) -> None:
        self.cookies_str = "; ".join(f"{c.name}={c.value}" for c in self.cookies)

    def _load_from_cookies_str(self, cookies_str: str) -> None:
        cookies_str = self.clean_cookies_str(cookies_str)
        if not cookies_str:
            return

        if self._is_netscape_cookie_file(cookies_str):
            self._load_from_netscape_cookies_str(cookies_str)
            return

        self._load_from_header_cookies_str(cookies_str)

    def _load_from_header_cookies_str(self, cookies_str: str) -> None:
        normalized = self._normalize_header_cookies_str(cookies_str)

        for item in normalized.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue

            parts = item.split("=", 1)
            if len(parts) != 2:
                continue

            name, value = parts
            if not name.strip():
                continue
            self.cookies.append(
                Cookie(
                    domain=f".{self.domain}",
                    path="/",
                    name=name.strip(),
                    value=value.strip(),
                    secure=True,
                    expires=0,
                )
            )

        self._sync_cookies_str()

    def _load_from_netscape_cookies_str(self, cookies_str: str) -> None:
        for line in cookies_str.splitlines():
            parsed = self._parse_netscape_cookie_line(line)
            if parsed is None:
                continue

            domain, include_subdomains, path, secure, expires_at, name, value = parsed

            if include_subdomains.upper() == "TRUE":
                if not domain.startswith("."):
                    domain = f".{domain}"
            else:
                domain = domain.lstrip(".")

            self.cookies.append(
                Cookie(
                    domain=domain,
                    path=path,
                    name=name,
                    value=value,
                    secure=secure.upper() == "TRUE",
                    expires=expires_at,
                )
            )

        self._sync_cookies_str()

    def save_to_file(self) -> None:
        cj = cookiejar.MozillaCookieJar(self.cookie_file)

        for c in self.cookies:
            cj.set_cookie(
                cookiejar.Cookie(
                    version=0,
                    name=c.name,
                    value=c.value,
                    port=None,
                    port_specified=False,
                    domain=c.domain,
                    domain_specified=True,
                    domain_initial_dot=c.domain.startswith("."),
                    path=c.path,
                    path_specified=True,
                    secure=c.secure,
                    expires=c.expires,
                    discard=c.expires == 0,
                    comment=None,
                    comment_url=None,
                    rest={"HttpOnly": ""},
                    rfc2109=False,
                )
            )

        cj.save(ignore_discard=True, ignore_expires=True)
        logger.debug(f"已保存 {len(cj)} 个 Cookie 到 {self.cookie_file}")

    def load_from_file(self) -> None:
        cj = cookiejar.MozillaCookieJar(self.cookie_file)
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
        except Exception:
            logger.warning(f"加载 cookie 文件失败：{self.cookie_file}")
            return

        self.cookies = []
        for c in cj:
            self.cookies.append(
                Cookie(
                    domain=c.domain,
                    path=c.path,
                    name=c.name,
                    value=c.value or "",
                    secure=c.secure,
                    expires=c.expires or 0,
                )
            )

        self._sync_cookies_str()
        logger.debug(f"从文件加载 {len(self.cookies)} 个 Cookie")

    # ---------------- update from response ----------------

    def update_from_response(self, set_cookie_headers: list[str]) -> None:
        if not set_cookie_headers:
            return

        logger.debug(
            f"开始更新 cookies，收到 {len(set_cookie_headers)} 个 Set-Cookie 头"
        )

        updated = False
        updated_items = []
        added_items = []
        ignored_items = []

        for header in set_cookie_headers:
            logger.debug(f"解析 Set-Cookie: {header}")

            sc = SimpleCookie()
            sc.load(header)

            if not sc:
                logger.debug("解析结果为空，跳过该 header")
                continue

            for name, morsel in sc.items():
                value = morsel.value
                path = morsel["path"] or "/"
                domain = morsel["domain"] or f".{self.domain}"
                secure = bool(morsel["secure"])

                expires = 0
                if morsel["expires"]:
                    try:
                        expires = int(
                            time.mktime(
                                time.strptime(
                                    morsel["expires"], "%a, %d-%b-%Y %H:%M:%S %Z"
                                )
                            )
                        )
                    except Exception as e:
                        logger.debug(
                            f"解析 expires 失败: {morsel['expires']}，错误: {e}"
                        )
                        expires = 0

                existing = next(
                    (
                        c
                        for c in self.cookies
                        if c.name == name and c.domain == domain and c.path == path
                    ),
                    None,
                )

                if existing:
                    # 如果值完全一样，仍然记录但标记为“未变更”
                    if (
                        existing.value == value
                        and existing.secure == secure
                        and existing.expires == expires
                    ):
                        ignored_items.append((name, domain, path))
                        logger.debug(
                            f"Cookie 未变更，忽略: {name} (domain={domain}, path={path})"
                        )
                        continue

                    old_value = existing.value
                    existing.value = value
                    existing.secure = secure
                    existing.expires = expires

                    updated_items.append(
                        (name, domain, path, old_value, value, secure, expires)
                    )
                    logger.debug(
                        f"Cookie 更新: {name} (domain={domain}, path={path}) "
                        f"old_value={old_value} new_value={value} secure={secure} expires={expires}"
                    )
                else:
                    self.cookies.append(
                        Cookie(
                            domain=domain,
                            path=path,
                            name=name,
                            value=value,
                            secure=secure,
                            expires=expires,
                        )
                    )
                    added_items.append((name, domain, path, value, secure, expires))
                    logger.debug(
                        f"Cookie 新增: {name} (domain={domain}, path={path}) "
                        f"value={value} secure={secure} expires={expires}"
                    )

                updated = True

        if updated:
            self.purge_expired()
            self.save_to_file()
            logger.debug(
                "Cookies 已更新并保存 "
                f"(新增 {len(added_items)}，更新 {len(updated_items)}，忽略 {len(ignored_items)})"
            )
            logger.debug(f"当前 Cookie 总数: {len(self.cookies)}")
            logger.debug(f"当前 cookies_str: {self.cookies_str}")
