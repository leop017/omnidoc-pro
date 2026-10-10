# 发布说明索引

每个版本一个文件，命名 `X.Y.Z.md`。push `vX.Y.Z` tag 时由 `.github/workflows/release.yml` 自动查找对应文件作为 release notes（也可用 `scripts/release.py release vX.Y.Z` 手动附带）。

## 版本

- [0.3.4](./0.3.4.md) — 三项零风险修复：Excel 增强 Markdown ≥2×2 合并列对齐 / 全部工作表缺失零诊断 ERROR / URL 重定向 scheme 防护
- [0.3.3](./0.3.3.md) — Excel 增强 Markdown 合并单元格腿范围 off-by-one 修复（_excel.py）
- [0.3.2](./0.3.2.md) — Excel 深度引擎 3 项零风险修复（HTML 错位 / Markdown 双转义 / 空表零诊断）
- [0.3.1](./0.3.1.md) — LLM 增强返回新对象时的 re-chunk 一致性修复
- [0.3.0](./0.3.0.md) — WebUI 并发批量转换防护（URL 输入框 scheme 校验 + rag_failed 状态提示）
- [0.2.9](./0.2.9.md) — 降级链 DEGRADED 语义 + 广度依赖完整化 + Ollama 入口 + CSV 排重 + 分块异常标记
- [0.2.8](./0.2.8.md) — Ollama provider 感知门控 + 全角句界正则 + 图片 MIME 魔数嗅探
- [0.2.7](./0.2.7.md) — LLM 图像描述本地非图片文件守卫（零风险）
- [0.2.6](./0.2.6.md) — 发布脚本 / 配置 / 健壮性零风险加固（11 项）
- [0.2.5](./0.2.5.md) — 0.2.x 审计回归修复（URL 抓取 charset + 0-chunk 退出码）
- [0.2.4](./0.2.4.md) — 可跳过 sheet 不误报 DEGRADED + 分块元数据嵌套 list 隔离 + 写盘韧性 + CLI 输出净化
- [0.2.3](./0.2.3.md) — 多 sheet 文件保护 + 分块偏移 round-trip + 图片 URL 净化
- [0.2.2](./0.2.2.md) — 部分成功语义修复（DEGRADED）+ LLM 增强后重分块 + 结构保留
- [0.2.1](./0.2.1.md) — 深度代码评估修复：安全加固（SSRF/LLM图像）+ 数据一致性（文件名去重/降级链）+ 工程质量
- [0.2.0](./0.2.0.md) — RAG 分块结果可下载（JSONL）+ 分块参数前置校验
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
