# AI 图片元数据解析

一个面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的图片元数据解析插件。

它读取 AI 生图文件中已经存在的参数，不调用视觉模型，也不会把图片上传到第三方服务。插件适合在 QQ/OneBot 群聊中查看 A1111、ComfyUI 或 NovelAI 生成图片的提示词、模型、采样器、Seed 等信息。

## 功能

- `/kkt` 指令解析当前消息或引用消息中的一张或多张图片，也支持作为文件发送的 PNG 原图。
- 可选的自动解析模式：收到图片后，仅在成功识别到元数据时回复。
- 解析 PNG 的 `tEXt`、`zTXt` 和 `iTXt` 文本块。
- 支持 Stable Diffusion WebUI/A1111 的 `parameters`。
- 支持 ComfyUI 的 API `prompt` 和编辑器 `workflow`。
- 支持 NovelAI/NAI 常见 JSON 参数。
- 支持本地路径、HTTP(S) URL、`base64://` 和 Data URI 图片引用。
- OneBot QQ 使用合并转发消息展示多张图片的结果。
- 可限制图片大小、下载超时、并发数量和原始元数据长度。

## 安装

### 从 AstrBot 插件市场或 ZIP 安装

将仓库目录放到 AstrBot 的插件目录，或在 AstrBot 管理面板中选择插件 ZIP 安装。AstrBot 启动时会自动读取 `_conf_schema.json` 并创建配置项。

### 手动安装

```bash
cd data/plugins
git clone https://github.com/the-snowpear/astrbot_plugin_ai_image_metadata.git
cd astrbot_plugin_ai_image_metadata
python -m pip install -r requirements.txt
```

然后重启 AstrBot，在插件配置页面调整选项。

## 使用

在包含图片的消息中发送：

```text
/kkt
```

也可以先发送图片或 PNG 原图文件，再使用 QQ 的「回复／引用」功能选中该消息，发送 `/kkt`。无需把图片重新附在指令消息中，群聊和私聊均可使用。

| 发送方式 | 处理内容 |
| --- | --- |
| 图片 + `/kkt` | 当前消息中的图片 |
| 引用图片消息 + `/kkt` | 被引用消息中的图片 |
| 引用 PNG 文件消息 + `/kkt` | 被引用消息中的原图文件 |
| 当前消息带图片，同时引用另一条图片消息 | 按消息顺序解析，去除重复来源 |

插件会为每张图片生成一个合并转发节点，内容包括图片尺寸、来源格式、正向/反向提示词、模型、VAE、采样器、步数、CFG、Seed、LoRA 和其他字段。

没有可识别元数据时，命令模式会明确提示；自动模式保持静默，避免群聊产生噪音。

自动解析默认关闭。在插件配置中启用 `auto_parse` 并保存后，直接发送图片即可触发，无需 `/kkt` 或 @ 机器人。自动模式只处理当前消息中的图片，不追溯引用消息；`/kkt` 不会再触发一次自动回复。若未收到结果，可以引用图片发送 `/kkt` 查看具体原因，下载或文件获取失败也会在 AstrBot 日志中留下记录。

## 配置

| 配置项 | 默认值 | 说明 |
| --- | ---: | --- |
| `auto_parse` | `false` | 是否监听普通图片消息并自动解析 |
| `max_file_size_mb` | `20` | 单张图片最大大小 |
| `download_timeout_seconds` | `15` | 下载远程图片的超时时间 |
| `max_concurrent_images` | `3` | 一条消息最多并行解析数量 |
| `show_raw_metadata` | `true` | 是否展示原始元数据 |
| `raw_metadata_max_chars` | `8000` | 原始元数据最大展示长度 |

## 支持范围与限制

当前首版只解析 PNG 内嵌文本元数据。JPEG、WebP 等格式会返回不支持结果，后续可以在 `metadata_parser` 接口上扩展 EXIF/XMP。

元数据可能在平台压缩、转码或重新上传过程中丢失；插件只能解析机器人实际收到的文件。ComfyUI 的节点结构差异较大，无法映射到标准字段的内容会保留在原始 JSON 中。

引用内容不可用时，插件会通过 OneBot `get_msg` 获取原消息。文件下载依赖协议端提供有效链接；过期或无法访问的文件会返回提示。想保留 PNG 元数据时，可将原图作为文件发送后引用解析。

## 开发

项目不依赖 AstrBot 才能运行解析器测试；`main.py` 在缺少 AstrBot 运行时的环境中会使用测试占位类型。

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q .
```

核心目录：

```text
metadata_parser/
├── png.py       # PNG 文本块读取
├── a1111.py     # A1111 parameters
├── comfyui.py   # ComfyUI prompt/workflow
├── novelai.py   # NovelAI/NAI JSON
└── parser.py    # 统一入口
```

## 贡献

欢迎提交新的图片样例、格式兼容修复和测试。提交 PR 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并确保测试通过。

## 许可证

本项目使用 [MIT License](LICENSE)。
