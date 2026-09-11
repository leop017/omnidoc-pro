## 🚀 首次公开发布

**OmniDoc Pro** —— 面向 RAG 场景的本地文档预处理工作台。

### 本次发布

- 深度 Word/Excel 解析（mammoth / python-docx / openpyxl）
- 广度支持 15+ 格式（MarkItDown 引擎）
- 内置清洗 / 分块 / LLM 增强流水线
- Gradio WebUI + Typer CLI 双入口
- GPL v3 + 商业双许可

### 二进制

- `omnidoc.exe` —— CLI 单文件可执行程序（~248 MB）
- `omnidoc-web.exe` —— WebUI 单文件可执行程序（~311 MB）

两个 exe 均包含完整的 Python 运行时与依赖，无需预装 Python。

### PyPI 包

- `omnidoc_pro-0.1.0-py3-none-any.whl` —— Wheel 包
- `omnidoc_pro-0.1.0.tar.gz` —— Source 分发

安装：

```bash
pip install omnidoc-pro
# 或指定扩展
pip install "omnidoc-pro[gui,legacy-doc,llm]"
```

### 已知限制

- 当前为 Windows 构建，Linux/macOS 二进制暂不提供（可通过 pip 安装 Python 版本）
- LLM 增强功能需自行配置 API key（OpenAI / Ollama / 兼容 API）

### 反馈

- 问题：GitHub Issues
- 商业授权：leop@astermail.org
