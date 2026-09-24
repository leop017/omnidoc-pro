# OmniDoc Pro

**一站式本地文档预处理工作台，为 RAG（检索增强生成）而设计。**

将 Word / Excel / PDF / PPT / 图片 / 音频 / HTML / CSV / 网页 等 20+ 格式统一转换为 RAG 友好的 Markdown 或分块（chunks），支持可选 LLM 图像描述增强，完全本地运行、无数据外泄。

> **MarkItDown 是格式转换器，OmniDoc Pro 是 RAG 管道。** 它复用了 MarkItDown 的格式覆盖，在此基础上增加三级优雅降级（深度 → 广度 → LLM）、结构化分块（带元数据与偏移量）、内置 LLM 图像增强、SSRF 防护。如果你只需要"PDF 转 Markdown"，直接用 MarkItDown；如果你需要生产级 RAG 预处理管道，用 OmniDoc Pro。

<p>
  <a href="https://pypi.org/project/omnidoc-pro/"><img alt="PyPI 版本" src="https://img.shields.io/pypi/v/omnidoc-pro?label=PyPI&color=blueviolet"></a>
  <img alt="Python 版本" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blueviolet">
  <img alt="测试" src="https://img.shields.io/badge/tests-292%20passed-rgb:4c1,1f6,1d4">
  <a href="./LICENSE"><img alt="许可" src="https://img.shields.io/badge/license-GPL%20v3%20%7C%20Commercial-rgb:4c1,1f6,1d4"></a>
</p>
<p>
  <a href="https://github.com/leop017/omnidoc-pro/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/leop017/omnidoc-pro?style=flat-square"></a>
  <a href="https://github.com/leop017/omnidoc-pro/issues"><img alt="GitHub Issues" src="https://img.shields.io/github/issues/leop017/omnidoc-pro?style=flat-square"></a>
  <a href="https://github.com/leop017/omnidoc-pro/commits/main"><img alt="GitHub Last Commit" src="https://img.shields.io/github/last-commit/leop017/omnidoc-pro?style=flat-square"></a>
</p>

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| **深度解析** | Word（`.docx`）/ Excel（`.xlsx`）结构化深度解析，保留表格、列表、代码块 |
| **广度覆盖** | PDF / PPT / 图片 / 音频 / HTML / CSV / EPUB / 网页 URL 等 15+ 格式（MarkItDown 引擎） |
| **优雅降级** | 深度引擎失败自动降级到广度引擎，单个文件出错不中断整批处理 |
| **RAG 分块** | 内置 3 种分块策略（固定大小 / 句子 / Markdown 结构），输出带元数据 |
| **LLM 增强** | 可选 OpenAI / Ollama 图像描述，`asyncio.Semaphore` 限流，离线时自动跳过 |
| **SSRF 防护** | URL 抓取自动拒绝内网 / 回环 / 保留 IP，防止服务器端请求伪造 |
| **UI 解耦** | 核心层零 UI 依赖；Gradio WebUI 和 Typer CLI 只是薄壳 |

## 📦 架构

```
┌─────────────────────────────────────────────────────┐
│  UI 层（薄壳，零核心逻辑）                           │
│  Gradio WebUI (omnidoc.ui.webui)                   │
│  Typer CLI    (omnidoc.ui.cli)                     │
├─────────────────────────────────────────────────────┤
│  控制器层（纯核心，唯一入口）                        │
│  ConversionController                               │
│    ├── EngineRouter（广度+深度路由 / 降级链）        │
│    └── ProcessingPipeline（清洗→分块→LLM 增强）     │
├─────────────────────────────────────────────────────┤
│  引擎层                                             │
│  DeepEngine (.doc/.docx/.xls/.xlsx 深度解析)        │
│  MarkItDownEngine (PDF/PPT/图片/URL 等广度解析)      │
├─────────────────────────────────────────────────────┤
│  处理器层                                            │
│  WordMdCleaner (页码/空行/重复行/空格 清洗)          │
│  FixedSize / Sentence / Markdown Chunker            │
│  LlmEnhancer (图像描述, asyncio.Semaphore 限流)     │
├─────────────────────────────────────────────────────┤
│  核心模型                                           │
│  OmniDocConfig (Pydantic)                           │
│  Document / Chunk / Element / DocumentResult         │
│  EngineInterface / CleanerInterface / ...           │
└─────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 无 Python 环境？直接下 exe（Windows）

Windows 用户可下载独立可执行文件（已内置 Python + 全部依赖，解压即用）：

- [`omnidoc.exe`](https://github.com/leop017/omnidoc-pro/releases) — CLI 版（双击或拖文件转换）
- [`omnidoc-web.exe`](https://github.com/leop017/omnidoc-pro/releases) — WebUI 版（自动开浏览器）

Linux / macOS 用户请通过 `pip install` 安装。

### 安装

```bash
# 推荐：全功能（深度 + 广度 + LLM + CLI + WebUI + 测试）
pip install "omnidoc-pro[full]"

# 仅核心 + 深度引擎（Word/Excel）
pip install omnidoc-pro

# 按需安装
pip install "omnidoc-pro[markitdown]"   # 广度引擎（PDF/PPT/图片/HTML/CSV…）
pip install "omnidoc-pro[llm]"          # LLM 图像描述
pip install "omnidoc-pro[cli]"         # Typer 命令行
pip install "omnidoc-pro[gui]"         # Gradio WebUI
```

> `[full]` 安装已自动包含 MarkItDown 依赖。仅安装基础包时，广度引擎不可用（深度引擎正常），安装 `[markitdown]` 可启用。

### 30 秒上手

```bash
pip install "omnidoc-pro[full]"
omnidoc convert report.docx -f md          # 转换 Word → Markdown
omnidoc convert data.xlsx -f md --chunk    # 转换 Excel → 分块
```

### 命令行使用

```bash
# 转换单个文件
omnidoc convert report.docx -f md

# 批量转换 + RAG 分块
omnidoc convert docs/*.pdf docs/*.docx --chunk --chunk-strategy sentence --chunk-size 512

# 启用 LLM 图像描述
omnidoc convert slides.pptx --llm --llm-base-url http://localhost:11434/v1 \
    --llm-api-key sk-xxx --llm-model llama3 --json

# JSON 输出（适合 RAG 管线集成）
omnidoc convert data.xlsx --json
```

### WebUI 使用

```bash
omnidoc webui --port 7860
# 浏览器自动打开 http://127.0.0.1:7860
```

### Python API

```python
from omnidoc import get_controller, OmniDocConfig

cfg = OmniDocConfig()
cfg.chunking.enabled = True
cfg.chunking.strategy = "markdown"
cfg.chunking.chunk_size = 256
cfg.chunking.chunk_overlap = 32

controller = get_controller()
result = controller.convert("report.docx", cfg)

print(result.markdown)        # RAG 友好的 Markdown
print(len(result.chunks))     # 分块数量
for chunk in result.chunks:
    print(chunk.text[:100])
```

### 输出示例

转换一个 Excel 文件（`sales_2025.xlsx`，含两个 Sheet）并分块后的 Markdown 输出：

````markdown
<!-- source: sales_2025.xlsx | 2 sheets | 14 rows total -->
## Sheet: 销售汇总

| 部门 | 金额 | 状态 |
|------|------|------|
| 华东 | ¥1,234.00 | 已审核 |
| 华南 | ¥5,678.00 | 待审批 |
| 华北 | ¥3,210.00 | 已审核 |

## Sheet: 明细

| 客户 | 订单号 | 金额 | 备注 |
|------|--------|------|------|
| 张三 | ORD-2025-001 | ¥200.00 | （合并单元格已展开） |
| 李四 | ORD-2025-002 | ¥450.00 | VIP |
````

`--chunk --chunk-strategy markdown --json` 的分块输出：

```json
[
  {"text": "## Sheet: 销售汇总\n\n| 部门 | 金额 | 状态 |\n...",
   "start_index": 0, "end_index": 156,
   "chunk_index": 0, "chunk_count": 3, "sheet_name": "销售汇总"},
  {"text": "## Sheet: 明细\n\n| 客户 | 订单号 | 金额 | 备注 |\n...",
   "start_index": 157, "end_index": 298,
   "chunk_index": 1, "chunk_count": 3, "sheet_name": "明细"}
]
```

每个 chunk 均携带 `chunk_index` / `chunk_count`（进度提示）及源文件元数据，可直接写入向量数据库的 metadata 字段。

## 📋 支持格式

| 类别 | 格式 | 引擎 |
|------|------|------|
| 深度 | `.docx` `.doc` `.xls` `.xlsx` | DeepEngine（python-docx / openpyxl / pandas） |
| 广度 | PDF `.pdf` | MarkItDownEngine |
| 广度 | PPT `.ppt` `.pptx` | MarkItDownEngine |
| 广度 | 图片 `.png` `.jpg` `.jpeg` `.webp` `.gif` | MarkItDownEngine |
| 广度 | 音频 `.mp3` `.wav` `.m4a` | MarkItDownEngine（需 whisper） |
| 广度 | 网页 `http(s)://...` | MarkItDownEngine（+ SSRF 防护） |
| 广度 | HTML `.html` `.htm` | MarkItDownEngine |
| 广度 | CSV `.csv` | MarkItDownEngine |
| 广度 | EPUB `.epub` | MarkItDownEngine |
| 广度 | 文本 `.txt` `.md` | MarkItDownEngine |

## 🗂 项目结构

```
omnidoc/
├── core/         # OmniDocConfig / Document / Chunk / 接口
├── engines/      # DeepEngine（深度）+ MarkItDownEngine（广度 + SSRF 防护）
├── controller/   # EngineRouter（路由/降级链）+ ConversionController（唯一入口）
├── processors/   # 清洗 + 3 种分块器 + LlmEnhancer
├── ai/           # LLM 服务（连接探测 / 图像描述 / 限流）
└── ui/           # CLI（Typer）+ WebUI（Gradio）薄壳
```

## 🔒 许可证

双许可模式：

| 使用场景 | 许可证 | 说明 |
|---------|--------|------|
| 个人 / 开源 / 学术 | **GPL v3**（免费） | 衍生作品必须以 GPL v3 发布 |
| 企业 / 商业闭源 | **商业授权**（付费） | 免除 GPL v3 开源义务 |

- [GPL v3 全文](./LICENSE) | [商业许可条款](./LICENSE-COMMERCIAL.md) | 商业授权咨询：leop@astermail.org

## 🤝 贡献

欢迎参与！请参阅 [CONTRIBUTING.md](./CONTRIBUTING.md)。

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/leop017/omnidoc-pro.git
cd omnidoc-pro

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# 安装开发依赖
pip install -e ".[full,test]"

# 运行测试
pytest tests/ -v

# 代码检查
ruff check .
```

## 📦 发布（Releases）

### 自动发布（推荐）

推送 `vX.Y.Z` tag 即自动触发两套 GitHub Actions，无需手动运行任何脚本：

- [`.github/workflows/release.yml`](./.github/workflows/release.yml)
  触发：`push` 到 `v*.*.*` tag（也可在 Actions 页面手动 **Run workflow**，指定 tag）
  流程：
  - Linux（`build`）：构建 sdist + wheel
  - Windows（`build-exe`）：用 PyInstaller 打包 `omnidoc.exe`（CLI）与 `omnidoc-web.exe`（WebUI）
  - `release`：创建 GitHub Release，把以上 4 个文件一并附上（自动带 `RELEASE_NOTES/X.Y.Z.md` 作为 release notes）
  所需 secret：`GITHUB_TOKEN`（内置，无需配置）

- [`.github/workflows/publish-pypi.yml`](./.github/workflows/publish-pypi.yml)
  触发：`push` 到 `v*.*.*` tag（也可在 Actions 页面手动 **Run workflow**，指定 tag）
  流程：build → `twine upload` 到正式 PyPI
  所需 secret：`PYPI_API_TOKEN`（以 `pypi-` 开头的 API token，单一 token，用户名固定为 `__token__`）

> **手动 Run workflow 说明**：两个 workflow 都支持在 GitHub Actions 页面点 **Run workflow**，输入参数 `ref` 要填一个**已存在的 tag**（如 `v0.1.1`），workflow 会 checkout 该 tag 并构建上传。

典型发布流程：

```bash
# 1. bump pyproject.toml 与 omnidoc/__init__.py 的 version 字段（两者保持一致）
# 2. 写 RELEASE_NOTES/x.y.z.md
# 3. 打 tag 并推送（同时触发两个 workflow）
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
# 到 GitHub Actions 页面查看两个 workflow 的运行状态
```

> 仅维护者：本地可借助 `scripts/release.py` 一键完成 build / tag / 手动 PyPI 上传，详见该脚本头部说明。

## 📊 版本

当前版本 **0.1.9** — 完整变更日志见 [RELEASE_NOTES/](./RELEASE_NOTES/README.md)

## 👤 致谢

- [MarkItDown](https://github.com/microsoft/markitdown) — 广度解析引擎
- [Mammoth](https://github.com/mwilliamson/python-mammoth) — Word 转 HTML
- [python-docx](https://python-docx.readthedocs.io/) — Word 结构化解析
- [Gradio](https://www.gradio.app/) — WebUI 框架

## 📮 联系

- 项目主页：https://github.com/leop017/omnidoc-pro
- 商业授权咨询：leop@astermail.org
- 提交 Issue 请遵循 [贡献指南](./CONTRIBUTING.md) 中的格式规范
