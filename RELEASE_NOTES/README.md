# 发布说明索引

每个版本一个文件，命名 `X.Y.Z.md`。push `vX.Y.Z` tag 时由 `.github/workflows/release.yml` 自动查找对应文件作为 release notes（也可用 `scripts/release.py release vX.Y.Z` 手动附带）。

## 版本

- [0.1.9](./0.1.9.md) — WebUI 下载功能（转换结果文件化 / gr.File 输出）
- [0.1.8](./0.1.8.md) — Gradio 6 兼容性修复（theme 迁移 / show_copy_button / launch 收敛）
- [0.1.7](./0.1.7.md) — 分块元数据准确性修复（chunk_count / 偏移量 / 类型卫生）
- [0.1.6](./0.1.6.md) — 打通 `max_chunk_size` 契约（config / CLI / WebUI 端到端）
- [0.1.5](./0.1.5.md) — 安全加固 + 鲁棒性修复（SSRF / .xls / Markdown 分块 / CI ref）
- [0.1.4](./0.1.4.md) — 真实 Bug 修复 + Excel 合并单元格与分块策略改进
- [0.1.3](./0.1.3.md) — 发布测试门禁 + 代码清理
- [0.1.2](./0.1.2.md) — 发布流程完善 + 文档维护
- [0.1.1](./0.1.1.md) — 修复 + CI 自动化
- [0.1.0](./0.1.0.md) — 首次公开发布
