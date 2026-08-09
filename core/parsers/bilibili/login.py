import asyncio
import json
from collections.abc import AsyncGenerator

from bilibili_api import Credential
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

import logging

logger = logging.getLogger("plugin.multi_platform_parser.core")

from ...config import PluginConfig


class BilibiliLogin:
    """哔哩哔哩登录类"""

    def __init__(self, config: PluginConfig):
        self.credential_file = config.data_dir / "cookies" / "bilibili_credential.json"
        self.raw_cookies = config.parser.bilibili.cookies
        self._credential: Credential | None = None

    def _save_credential(self):
        """存储哔哩哔哩登录凭证"""
        if self._credential is None:
            return

        self.credential_file.write_text(
            json.dumps(self._credential.get_cookies(), ensure_ascii=False)
        )

    def _load_credential(self):
        """从文件加载哔哩哔哩登录凭证"""
        if not self.credential_file.exists():
            return

        self._credential = Credential.from_cookies(
            json.loads(self.credential_file.read_text())
        )

    async def login_with_qrcode(self) -> bytes:
        """通过二维码登录获取哔哩哔哩登录凭证"""
        self._qr_login = QrCodeLogin()
        await self._qr_login.generate_qrcode()

        qr_pic = self._qr_login.get_qrcode_picture()
        return qr_pic.content

    async def check_qr_state(self) -> AsyncGenerator[str, None]:
        """检查二维码登录状态"""
        scan_tip_pending = True

        for _ in range(30):
            state = await self._qr_login.check_state()
            match state:
                case QrCodeLoginEvents.DONE:
                    yield "登录成功"
                    self._credential = self._qr_login.get_credential()
                    self._save_credential()
                    break
                case QrCodeLoginEvents.CONF:
                    if scan_tip_pending:
                        yield "二维码已扫描, 请确认登录"
                        scan_tip_pending = False
                case QrCodeLoginEvents.TIMEOUT:
                    yield "二维码过期, 请重新生成"
                    break
            await asyncio.sleep(2)
        else:
            yield "二维码登录超时, 请重新生成"

    def _cookies_to_dict(self, cookies_str: str) -> dict[str, str]:
        """将 cookies 字符串转换为字典"""
        res = {}
        for cookie in cookies_str.split(";"):
            name, value = cookie.strip().split("=", 1)
            res[name] = value
        return res

    async def _init_credential(self):
        """初始化哔哩哔哩登录凭证"""
        if not self.raw_cookies:
            self._load_credential()
            return

        credential = Credential.from_cookies(self._cookies_to_dict(self.raw_cookies))
        if await credential.check_valid():
            logger.info(f"`parser_bili_ck` 有效, 保存到 {self.credential_file}")
            self._credential = credential
            self._save_credential()
        else:
            logger.info(f"`parser_bili_ck` 已过期, 尝试从 {self.credential_file} 加载")
            self._load_credential()

    @property
    async def credential(self) -> Credential | None:
        """哔哩哔哩登录凭证"""

        if self._credential is None:
            await self._init_credential()
            return self._credential

        if not await self._credential.check_valid():
            logger.warning("哔哩哔哩凭证已过期, 请重新配置")
            return None

        if await self._credential.check_refresh():
            logger.info("哔哩哔哩凭证需要刷新")
            if self._credential.has_ac_time_value() and self._credential.has_bili_jct():
                await self._credential.refresh()
                logger.info(f"哔哩哔哩凭证刷新成功, 保存到 {self.credential_file}")
                self._save_credential()
            else:
                logger.warning(
                    "哔哩哔哩凭证刷新需要包含 `SESSDATA`, `ac_time_value` 项"
                )

        return self._credential
