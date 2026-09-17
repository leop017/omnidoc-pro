# OmniDoc Pro

**一站式本地文档预处理工作台，为 RAG（检索增强生成）而设计。**

将 Word / Excel / PDF / PPT / 图片 / 音频 / HTML / CSV / 网页 等 20+ 格式统一转换为 RAG 友好的 Markdown 或分块（chunks），支持可选 LLM 图像描述增强，完全本地运行、无数据外泄。

<p>
  <a href="https://pypi.org/project/omnidoc-pro/"><img alt="PyPI 版本" src="https://img.shields.io/pypi/v/omnidoc-pro?label=PyPI&color=blueviolet"></a>
  <img alt="Python 版本" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blueviolet">
  <a href="./LICENSE"><img alt="许可" src="https://img.shields.io/badge/license-GPL%20v3%20%7C%20Commercial-rgb:4c1,1f6,1d4"></a>
  <img alt="状态" src="https://img.shields.io/badge/status-alpha-rgb:e79,fa4,3b7">
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

### 设计原则

1. **广度 + 深度路由**：Word/Excel 走深度引擎（结构化解析），其他格式走广度引擎（MarkItDown）
2. **UI 零侵入**：`core` / `engines` / `processors` 包绝不导入任何 UI 库
3. **优雅降级**：引擎失败 → 自动降级；LLM 不可用 → 跳过增强记 warning；单文件失败不中断批次
4. **并发限流**：LLM 图像描述用 `asyncio.Semaphore` 控制并发数

## 🚀 快速开始

### 安装

```bash
# 基础安装（核心 + 深度引擎依赖）
pip install omnidoc-pro

# 全功能安装（+ MarkItDown 广度引擎 + Gradio WebUI + LLM + CLI + 测试）
pip install "omnidoc-pro[full]"

# 按需安装
pip install "omnidoc-pro[markitdown]"   # 广度引擎
pip install "omnidoc-pro[gui]"          # Gradio WebUI
pip install "omnidoc-pro[llm]"         # LLM 图像描述
pip install "omnidoc-pro[cli]"         # Typer 命令行
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
omnidoc-pro/
├── omnidoc/
│   ├── __init__.py           # 包入口，导出公共 API
│   ├── core/
│   │   ├── config.py        # OmniDocConfig（Pydantic 统一配置）
│   │   ├── document.py      # Document / Chunk / Element / DocumentResult
│   │   └── interfaces.py    # EngineInterface / CleanerInterface / ...
│   ├── engines/
│   │   ├── deep_engine.py   # 深度引擎门面（Word/Excel/.doc）
│   │   ├── markitdown_engine.py  # 广度引擎门面 + SSRF 防护
│   │   └── deep/           # 深度解析内部模块
│   │       ├── _word.py     # WordBuilder
│   │       ├── _excel.py    # ExcelBuilder
│   │       ├── _doc.py      # DocBuilder（legacy .doc）
│   │       ├── _exporters.py  # md/html/json 导出器
│   │       ├── _models.py   # 解析数据模型
│   │       ├── _utils.py    # 工具函数
│   │       └── _logger.py   # 日志
│   ├── controller/
│   │   ├── router.py        # EngineRouter（路由 + 降级链）
│   │   └── conversion.py    # ConversionController（唯一入口）
│   ├── processors/
│   │   ├── pipeline.py      # ProcessingPipeline（clean→chunk→enhance）
│   │   ├── cleaners/
│   │   │   └── word_md.py   # WordMdCleaner（页码/空行/空格/重复）
│   │   ├── chunkers/
│   │   │   ├── fixed_size.py
│   │   │   ├── sentence.py
│   │   │   └── markdown.py
│   │   └── enhancers/
│   │       └── __init__.py  # LlmEnhancer 工厂
│   ├── ai/
│   │   └── llm_service.py   # LLM 服务（连接探测 / 图像描述 / 限流）
│   └── ui/
│       ├── webui.py         # Gradio WebUI（薄壳）
│       └── cli.py           # Typer CLI（薄壳）
├── tests/                    # 13 个测试文件
├── RELEASE_NOTES/            # 每版本 release notes（X.Y.Z.md）
│   ├── 0.1.0.md
│   └── README.md             # 命名规则 + 索引
├── .github/
│   └── workflows/
│       ├── release.yml       # tag push 自动 build + GitHub Release
│       └── publish-pypi.yml  # tag push 自动 twine 上传 PyPI
├── scripts/
│   └── release.py            # 手动一键发布脚本（build→tag→release→pypi）
├── omnidoc.spec              # PyInstaller 打包配置（CLI）
├── omnidoc-web.spec          # PyInstaller 打包配置（WebUI）
├── pyproject.toml
├── README.md
├── LICENSE                   # GPL v3
└── LICENSE-COMMERCIAL.md     # 商业许可说明
```

## 🔒 许可证

本项目采用 **双许可（Dual License）** 模式：

| 使用场景 | 许可证 | 说明 |
|---------|--------|------|
| 个人 / 开源 / 学术 | **GPL v3**（免费） | 完全免费，但衍生作品必须以 GPL v3 发布 |
| 企业 / 商业闭源 | **商业许可证**（付费） | 免除 GPL v3 开源义务，需向作者购买授权 |

- 开源许可证全文见 [LICENSE](./LICENSE)（GPL v3）
- 商业许可条款见 [LICENSE-COMMERCIAL.md](./LICENSE-COMMERCIAL.md)
- 商业授权请联系：leop@astermail.org

> 详见下方「[许可证详情](#许可证详情)」章节。

## 📖 许可证详情

### 个人 / 开源使用（GPL v3，免费）

- 个人学习、研究、开源项目集成均可**免费使用**
- 如果你修改了本项目并以任何形式分发（包括 SaaS 形式提供），修改后的代码必须以 **GPL v3** 许可证开源
- 商用闭源分发**不被** GPL v3 允许

### 企业 / 商业使用（商业许可证，付费）

- 如果你的公司需要**闭源商业化**使用本项目（不公开修改后的代码），需要购买商业许可证
- 商业许可证免除 GPL v3 的开源义务
- 具体条款请联系作者获取报价

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

### 无 Python 环境？直接下 exe

不想装 Python？从 [GitHub Releases](https://github.com/leop017/omnidoc-pro/releases) 下载独立可执行文件：

- `omnidoc.exe` — 命令行版（双击或拖文件转换）
- `omnidoc-web.exe` — WebUI 版（自动开浏览器，等价于 `omnidoc webui`）

这两个 exe 由 PyInstaller 打包，已内置 Python 运行时与全部依赖，解压即用、无需 Python 环境。

> 仅维护者：本地可借助 `scripts/release.py` 一键完成 build / tag / 手动 PyPI 上传，详见该脚本头部说明。

## 📊 版本

当前版本：**0.1.2**（Alpha）

- 变更日志见 [RELEASE_NOTES/](./RELEASE_NOTES/README.md)
  - [v0.1.2](./RELEASE_NOTES/0.1.2.md) — 发布流程完善 + 文档维护
  - [v0.1.1](./RELEASE_NOTES/0.1.1.md) — 修复 + CI 自动化
  - [v0.1.0](./RELEASE_NOTES/0.1.0.md) — 首次公开发布

## 👤 致谢

- [MarkItDown](https://github.com/microsoft/markitdown) — 广度解析引擎
- [Mammoth](https://github.com/mwilliamson/python-mammoth) — Word 转 HTML
- [python-docx](https://python-docx.readthedocs.io/) — Word 结构化解析
- [Gradio](https://www.gradio.app/) — WebUI 框架

## 📮 联系

- 项目主页：https://github.com/leop017/omnidoc-pro
- 商业授权咨询：leop@astermail.org
- 提交 Issue 请遵循 [贡献指南](./CONTRIBUTING.md) 中的格式规范
