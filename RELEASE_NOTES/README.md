# 发布说明索引

每个版本一个文件，命名 `X.Y.Z.md`。push `vX.Y.Z` tag 时由 `.github/workflows/release.yml` 自动查找对应文件作为 release notes（也可用 `scripts/release.py release vX.Y.Z` 手动附带）。

## 版本

- [0.1.5](./0.1.5.md) — 安全加固 + 鲁棒性修复（SSRF / .xls / Markdown 分块 / CI ref）
- [0.1.4](./0.1.4.md) — 真实 Bug 修复 + Excel 合并单元格与分块策略改进
- [0.1.3](./0.1.3.md) — 发布测试门禁 + 代码清理
- [0.1.2](./0.1.2.md) — 发布流程完善 + 文档维护
- [0.1.1](./0.1.1.md) — 修复 + CI 自动化
- [0.1.0](./0.1.0.md) — 首次公开发布
