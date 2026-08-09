# Third Party Notices

## Zhalslar/astrbot_plugin_parser

- Source: https://github.com/Zhalslar/astrbot_plugin_parser
- License: MIT License
- Usage in this MaiBot port:
  - Reused parser core under `core/`
  - Replaced AstrBot message event and send APIs with MaiBot SDK hooks and OneBot HTTP sending
  - Added a small `astrbot.api.logger` compatibility shim for migrated core modules

## Color2333/maibot-multi-platform-parser

- Source: https://github.com/Color2333/maibot-multi-platform-parser
- License: MIT License
- Usage in this improved version:
  - Reused MaiBot SDK integration framework
  - Extended platform parser support from 4 to 16 platforms
  - Added admin commands (开启解析、关闭解析、登录B站)
  - Added Bilibili QR code login functionality

The original MIT license text is included in `LICENSE`.
