# 万能链接解析器（MaiBot 移植版）

自动解析 QQ 群里的多平台链接，并把图文或视频发送回群聊。

## 迁移来源

本插件是基于原 MaiBot 移植版的改进版本，解析核心迁移自 AstrBot 插件：

- **解析核心来源**：`Zhalslar/astrbot_plugin_parser`
  - 原仓库：https://github.com/Zhalslar/astrbot_plugin_parser
  - 原许可：MIT License
- **原移植版来源**：`Color2333/maibot-multi-platform-parser`
  - 原仓库：https://github.com/Color2333/maibot-multi-platform-parser

本版本在原移植版基础上扩展了全部17个平台的解析支持，并添加了管理员命令、B站扫码登录等功能。

## 功能

支持解析以下平台的链接：

- 哔哩哔哩（视频、动态、专栏、直播）
- 抖音（短链、视频、图文）
- 小红书（短链、图文、视频）
- 小黑盒（帖子、游戏分享）
- A站（视频）
- Instagram（帖子）
- iwara（视频）
- 快手（视频）
- 网易云音乐（歌曲、歌单）
- NGA（帖子）
- 微信视频号
- TikTok（视频）
- Twitter/X（推文）
- 微博（微博、视频）
- YouTube（视频）
- 知乎（回答、文章）
- Pixiv（插画、漫画、小说、动图，含R18/R18G内容，支持图片混淆加密）

### Pixiv 图片混淆功能

- 开启后，仅对 R18/R18G 作品的图片进行像素混淆加密处理，全年龄作品不受影响。用于降低发送时被系统风控拦截或封禁的风险（如果被举报可能会导致封号）。
- 群聊默认开启，私聊默认关闭，可分别通过 `pixiv_encrypt_image_group` 和 `pixiv_encrypt_image_private` 配置。

> ⚠️ **风险警告**：QQ 群聊环境下，发送 R18/R18G 图片极易触发系统风控（包括 AI 自动举报机制），**即使未被人工举报也可能导致群聊被封禁、机器人账号被处罚**。群聊场景下**必须保持混淆开启**，切勿抱有"不开也没事"的侥幸心理。私聊环境风险相对较低，但同样存在被举报后封禁的可能，请自行评估。

> 以上为基于实际使用经验的提示：作者曾因忘记开启群聊混淆，导致群聊被封禁 7 天、个人账号被封禁 1 天。

**注意**：混淆后的图片无法直接查看原始内容，需要使用解密工具还原：

- 🔗 **解密工具**：[点击跳转解密页面](https://nj-1307802825.cos-website.ap-nanjing.myqcloud.com/hunxiao//)

> 将加密图片上传到解密工具即可还原为原始图片。

其他特性：
- 文本/图片/合并转发优先通过 MaiBot SDK（`ctx.send.*`）发送，享受 SDK 的权限校验与频率控制
- SDK 调用失败时自动回退到 OneBot HTTP API，确保消息发送可靠性
- 视频和文件因 SDK 暂不支持，通过 OneBot HTTP API 直接发送（需配置 `[api]` 中的 host/port/token）
- 群白名单、去重冷却、媒体大小限制
- 支持代理配置
- 支持 Cookie 配置以解锁更多内容

### 消息发送机制与回退策略

插件采用「SDK 优先，HTTP 兜底」的双重保险策略：

| 消息类型 | 主通道（SDK） | 回退通道（OneBot HTTP） | 说明 |
|---------|-------------|----------------------|------|
| 文本消息 | `ctx.send.text()` | `send_group_msg`/`send_private_msg` | SDK 异常或返回 False 时自动回退 |
| 图片消息 | `ctx.send.image()` | `send_group_msg`/`send_private_msg` | SDK 异常或返回 False 时自动回退 |
| 合并转发 | `ctx.send.forward()` | `send_group_forward_msg`/`send_private_forward_msg` | SDK 异常或返回 False 时自动回退 |
| 视频消息 | —（SDK 不支持） | `send_group_msg`/`send_private_msg` | 仅 OneBot HTTP |
| 文件上传 | —（SDK 不支持） | `upload_group_file`/`upload_private_file` | 仅 OneBot HTTP |

> **注意**：SDK 发送失败时会在日志中输出 `SDK send.* 异常/返回 False，回退到 OneBot HTTP` 警告，便于排查问题。命令处理器（开启/关闭解析、B站登录）仅使用 SDK，失败时记录日志但不回退（命令场景无 message context 可用于 HTTP 回退）。

> **关于 manifest 能力声明**：插件在 `_manifest.json` 中声明了 `send.text`、`send.image`、`send.forward` 三个 SDK 能力，覆盖文本、图片、合并转发三种消息类型。视频消息和文件上传因 SDK 暂不支持对应接口，直接通过 OneBot HTTP API 发送，**不受 manifest 能力声明约束**。这意味着插件实际具备的视频/文件发送能力超出了 manifest 声明范围，这是当前 SDK 能力限制下的折中方案。

## 命令

| 命令 | 说明 | 权限 |
|------|------|------|
| `开启解析` | 开启当前会话的链接解析 | 管理员 |
| `关闭解析` | 关闭当前会话的链接解析 | 管理员 |
| `登录B站` / `blogin` / `登录b站` | 扫码登录B站获取Cookie | 管理员 |

## 配置

主要配置位于 `config.toml`（参考 `config.toml.example`）：

### 插件配置

```toml
[plugin]
enabled = true              # 是否启用插件
admin_qqs = []              # 管理员QQ号列表，只有管理员可以使用命令
```

### 解析器配置

```toml
[parser]
enable_bilibili = true      # 启用B站解析
enable_douyin = true        # 启用抖音解析
enable_xhs = true           # 启用小红书解析
enable_xiaoheihe = true     # 启用小黑盒解析
enable_acfun = false        # 启用A站解析（成人内容平台，默认关闭）
enable_instagram = true     # 启用Instagram解析
enable_iwara = false        # 启用iwara解析（成人内容平台，默认关闭）
enable_kuaishou = true      # 启用快手解析
enable_ncm = true           # 启用网易云音乐解析
enable_nga = true           # 启用NGA解析
enable_shipinhao = true     # 启用微信视频号解析
enable_tiktok = true        # 启用TikTok解析
enable_twitter = true       # 启用Twitter/X解析（需在[more]中开启 twitter_confirm_thirdparty 才会实际生效）
enable_weibo = true         # 启用微博解析
enable_youtube = true       # 启用YouTube解析
enable_zhihu = true         # 启用知乎解析
enable_pixiv = false        # 启用Pixiv解析（需配置Cookie，含R18内容，默认关闭）
group_whitelist = []        # 允许自动解析的群号，空列表表示所有群
block_ai_reply = true       # 命中链接后是否阻止麦麦继续普通聊天
debounce_seconds = 120      # 同一会话同一链接去重时间（秒）
max_images = 9              # 单条链接最多发送图片数
max_text_chars = 700        # 摘要正文最大字符数
send_images = true          # 是否发送图片
send_video = true           # 是否发送视频
use_forward_for_multi = true  # 群聊多图/图文是否使用合并转发
pixiv_use_forward = true      # Pixiv图片合并转发发送（关闭则合成为PDF）
source_max_size_mb = 80     # 单个媒体最大下载大小（MB），范围：1-300
source_max_minutes = 8      # 视频最大时长（分钟），范围：1-60
```

### 更多设置

```toml
[more]
pixiv_encrypt_image_group = true      # 群聊Pixiv图片混淆（仅R18/R18G作品，默认开启）
pixiv_encrypt_image_private = false   # 私聊Pixiv图片混淆（仅R18/R18G作品，默认关闭）
twitter_confirm_thirdparty = false    # Twitter第三方服务确认（推文链接会转发到xdown.app，开启表示知悉并同意）
```

### 网络配置

```toml
[network]
proxy = ""                  # 解析/下载代理，例如 http://127.0.0.1:7890，留空则不使用
proxy_bilibili = false      # B站使用代理
proxy_douyin = false        # 抖音使用代理
proxy_xhs = false           # 小红书使用代理
proxy_xiaoheihe = false     # 小黑盒使用代理
proxy_acfun = false         # A站使用代理
proxy_instagram = true      # Instagram使用代理（默认开启）
proxy_iwara = true          # iwara使用代理（默认开启）
proxy_kuaishou = false      # 快手使用代理
proxy_ncm = false           # 网易云音乐使用代理
proxy_nga = false           # NGA使用代理
proxy_shipinhao = false     # 微信视频号使用代理
proxy_tiktok = true         # TikTok使用代理（默认开启）
proxy_twitter = true        # Twitter/X使用代理（默认开启）
proxy_weibo = false         # 微博使用代理
proxy_youtube = true        # YouTube使用代理（默认开启）
proxy_zhihu = false         # 知乎使用代理
proxy_pixiv = true          # Pixiv使用代理（默认开启）
common_timeout = 30         # 普通请求超时秒数
download_timeout = 120      # 下载超时秒数
download_retry_times = 1    # 下载重试次数
```

### Cookie 配置

```toml
[cookies]
bilibili = ""               # B站 Cookie（可选）
douyin = ""                 # 抖音 Cookie（可选）
xhs = ""                    # 小红书 Cookie（可选）
# ... 其他平台 Cookie
pixiv = ""                  # Pixiv Cookie（必填，否则无法解析）
```

### API 配置

```toml
[api]
host = "127.0.0.1"          # OneBot HTTP API 主机
port = 3000                 # OneBot HTTP API 端口
token = ""                  # OneBot HTTP API Token
bot_uin = ""                # 发送合并转发节点时使用的 bot QQ
```

## 依赖

依赖已在 `_manifest.json` 中声明，MaiBot 会自动安装。主要依赖包括：

| 依赖 | 用途 |
|------|------|
| `aiofiles` | 异步文件读写 |
| `msgspec` | 高性能 JSON 解析 |
| `yt-dlp` | YouTube/TikTok 等视频下载 |
| `bilibili-api-python` | B站 API 调用 |
| `curl_cffi` | 小黑盒/iwara/知乎请求（绕过反爬） |
| `tqdm` | 下载进度条 |
| `beautifulsoup4` | 微博/NGA/Twitter/知乎 HTML 解析 |
| `apscheduler` | 缓存清理定时任务 |
| `apilmoji` | 卡片渲染中的 emoji 处理 |
| `pillow` | 图片处理/卡片渲染 |
| `httpx` | Pixiv API 请求 |
| `gallery-dl` | Instagram 图文解析 |

## 外部工具与第三方服务

本插件在解析过程中会调用以下外部工具或第三方服务，请知悉：

### gallery-dl（Instagram 解析）

- Instagram 解析器通过 `subprocess` 调用 `gallery-dl`（`python -m gallery_dl`）获取图片链接。
- **风险边界**：URL 来自用户消息，经正则匹配后作为子进程参数传入。由于使用 `create_subprocess_exec`（非 shell 执行），且 URL 已经过正则白名单过滤，命令注入风险较低。但仍建议仅在可信会话中启用 Instagram 解析。
- gallery-dl 已在依赖中声明会自动安装，无需手动配置。

### ffmpeg（视频处理）

- B站、抖音等平台下载的视频需要通过 `ffmpeg` 合并/转码音视频流（`core/utils.py`）。
- ffmpeg 调用使用固定命令模板，参数均为本地文件路径，不接受用户输入，风险较低。
- **请确保系统已安装 ffmpeg 并可在 PATH 中找到**，否则视频解析功能将不可用。

### xdown.app（Twitter/X 解析）

- **重要提示**：Twitter/X 解析器（`core/parsers/twitter.py`）会将用户发送的推文链接转发到第三方服务 `xdown.app` 的 API（`https://xdown.app/api/ajaxSearch`）进行解析。
- 这意味着推文链接会被发送到第三方服务器，请评估是否可接受此外部数据流转。
- **二次确认机制**：即使 `enable_twitter = true`，还必须额外开启 `twitter_confirm_thirdparty = true` 才会实际解析 Twitter 链接。这是强制性的知情同意机制，确保用户明确知悉推文链接会被转发到第三方服务。关闭时会在日志中输出警告。

## 数据存储与凭据安全

- **Cookie 明文存储**：各平台 Cookie 和 B站登录凭据（含 `SESSDATA` 等敏感字段）会以明文 JSON 形式写入插件数据目录 `data/cookies/`（如 `data/cookies/bilibili_credential.json`）。
- **权限隔离建议**：请确保运行 MaiBot 的服务器/容器对该数据目录设置了合理的文件系统权限，避免其他用户或进程读取。生产环境建议以独立低权限用户运行，并对 `data/cookies/` 目录设置 `600`/`700` 权限。
- 这些凭据是解析器类插件功能所需（用于访问需要登录的平台内容），无法避免落盘，请妥善管理。

## ⚠️ 免责声明
- 本插件仅供技术学习与交流，不鼓励用于任何违规用途。
- 本插件支持的 iwara、A站、Pixiv 等平台可能包含成人/R18内容。发送此类内容可能违反 QQ/Tencent 服务条款，**存在导致机器人账号被封禁的风险**。使用者需自行承担一切风险和后果，插件开发者不对因使用本插件而造成的任何损失负责。请谨慎使用，并在合规范围内使用本插件。

## 许可与署名

本移植版遵循 MIT License。第三方来源与许可见 `THIRD_PARTY_NOTICES.md`。

## 致谢

- 感谢 `Zhalslar` 提供的解析核心（`astrbot_plugin_parser`）
- 感谢 `Color2333` 提供的 MaiBot 移植版基础框架
- 感谢所有为项目做出贡献的开发者！
