# Third Party Notices

## Zhalslar/astrbot_plugin_parser

- Source: https://github.com/Zhalslar/astrbot_plugin_parser
- License: MIT License
- Usage in this MaiBot port:
  - Reused parser core under `core/`
  - Replaced AstrBot message event and send APIs with MaiBot SDK hooks and OneBot HTTP sending

## Color2333/maibot-multi-platform-parser

- Source: https://github.com/Color2333/maibot-multi-platform-parser
- License: MIT License
- Usage in this improved version:
  - Reused MaiBot SDK integration framework
  - Extended platform parser support to 20 platforms
  - Added admin commands (开启解析、关闭解析、登录B站)
  - Added Bilibili QR code login functionality
  - Added group @-only response and quoted-message parsing

## SnowLuma (QQ Space credential service)

- The QQ Space parser (`core/parsers/qzone.py`, `core/qzone_api.py`) can obtain `qzone.qq.com`
  credentials at runtime through SnowLuma's OneBot HTTP `get_credentials` action.
- SnowLuma is an independently deployed service; this plugin only calls its public OneBot HTTP
  action and does not read SnowLuma private files or process memory. Manual QQ Space cookies are
  always retained as a fallback.
- This integration is disabled by default and requires both `enable_qzone = true` and
  `qzone_confirm_thirdparty = true` before it is activated.

## Metube (self-hosted download service)

- The Metube parser (`core/parsers/metube.py`) submits links to a user-self-hosted Metube instance
  (configured via `metube_url`). Metube is not a third-party cloud service.
- This integration is disabled by default and requires both `enable_metube = true` and
  `metube_confirm = true` before it is activated.

The original MIT license text is included in `LICENSE`.
