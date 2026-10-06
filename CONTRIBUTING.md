# 贡献指南

感谢你关注这个项目。欢迎提交兼容性修复、解析样例、文档改进和新格式支持。

## 提交问题

请尽量提供：

- AstrBot 和插件版本；
- 图片来源（A1111、ComfyUI、NovelAI 或其他工具）；
- 图片格式和传输方式；
- 期望字段与实际输出；
- 脱敏后的元数据文本或最小复现样例。

不要上传包含个人信息、私密提示词或密钥的原图。

## 开发流程

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q .
```

新增解析格式时，请把格式处理放在 `metadata_parser/`，保持 `parse_image()` 的统一返回结构，并补充至少一个脱敏测试样例。

## Pull Request

- 一个 PR 尽量只解决一个问题。
- 更新用户可见行为时同步修改 README 或 CHANGELOG。
- 不要提交图片缓存、日志、密钥、AstrBot 运行数据或本地配置。
- 提交前确认测试通过，说明已验证的场景和已知限制。
