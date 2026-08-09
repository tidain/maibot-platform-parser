# 万能链接解析器 - 插件市场提交说明

## 推荐分类

- Utility Tools
- External Integration

## 推荐标签

- link-parser
- bilibili
- douyin
- xhs
- xiaoheihe
- acfun
- instagram
- tiktok
- twitter
- youtube
- zhihu
- astrbot-port

## 迁移来源

本插件是基于原 MaiBot 移植版的改进版本，解析核心迁移自 AstrBot 插件。

### 解析核心来源
- 原项目：`Zhalslar/astrbot_plugin_parser`
- 原仓库：https://github.com/Zhalslar/astrbot_plugin_parser
- 原许可：MIT License

### 移植框架来源
- 原项目：`Color2333/maibot-multi-platform-parser`
- 原仓库：https://github.com/Color2333/maibot-multi-platform-parser
- 原许可：MIT License

### 改进说明
- 扩展平台解析支持从 4 个到 16 个
- 添加管理员命令（开启解析、关闭解析、登录B站）
- 添加 B站扫码登录功能
- 保留原解析核心，将 AstrBot 消息事件、发送接口和配置读取改为 MaiBot SDK Hook 与 OneBot HTTP 发送

## 上架备注

当前 `_manifest.json` 的 `urls.repository` 指向本改进版仓库；上游来源保留在 README 与 `THIRD_PARTY_NOTICES.md`。
