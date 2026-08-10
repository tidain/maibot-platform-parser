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
- Pixiv（插画、漫画、小说、动图，含R18模糊处理，支持图片混淆加密）

### Pixiv 图片混淆功能

开启后，仅对 R18/R18G 作品的图片进行像素混淆加密处理，全年龄作品不受影响。用于防止图片被检测风控。群聊默认开启，私聊默认关闭，可分别通过 `pixiv_encrypt_image_group` 和 `pixiv_encrypt_image_private` 配置。

**注意**：混淆后的图片无法直接查看原始内容，需要使用解密工具还原：

- 🔗 **解密工具**：[点击跳转解密页面](https://nj-1307802825.cos-website.ap-nanjing.myqcloud.com/hunxiao//)

> 将加密图片上传到解密工具即可还原为原始图片。

其他特性：
- 图片优先使用群聊合并转发
- 视频使用 OneBot HTTP 直接发送
- 群白名单、去重冷却、媒体大小限制
- 支持代理配置
- 支持 Cookie 配置以解锁更多内容

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
enable_twitter = true       # 启用Twitter/X解析
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
source_max_size_mb = 80     # 单个媒体最大下载大小（MB），范围：1-300
source_max_minutes = 8      # 视频最大时长（分钟），范围：1-60
```

### 混淆配置

```toml
[encrypt]
pixiv_encrypt_image_group = true    # 群聊Pixiv图片混淆（仅R18/R18G作品，默认开启）
pixiv_encrypt_image_private = false # 私聊Pixiv图片混淆（仅R18/R18G作品，默认关闭）
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

> **gallery-dl 说明**：Instagram 解析器通过 `subprocess` 调用 `gallery-dl`（`python -m gallery_dl`）获取图片链接。gallery-dl 已在依赖中声明会自动安装，无需手动配置。如需使用 Instagram 解析功能，请确保 gallery-dl 已正确安装。

## ⚠️ 免责声明
- 本插件支持的 iwara、A站、Pixiv 等平台可能包含成人/R18内容。发送此类内容可能违反 QQ/Tencent 服务条款，**存在导致机器人账号被封禁的风险**。使用者需自行承担一切风险和后果，插件开发者不对因使用本插件而造成的任何损失负责。请谨慎使用，并在合规范围内使用本插件。

## 许可与署名

本移植版遵循 MIT License。第三方来源与许可见 `THIRD_PARTY_NOTICES.md`。

## 致谢

- 感谢 `Zhalslar` 提供的解析核心（`astrbot_plugin_parser`）
- 感谢 `Color2333` 提供的 MaiBot 移植版基础框架
- 感谢所有为项目做出贡献的开发者！
