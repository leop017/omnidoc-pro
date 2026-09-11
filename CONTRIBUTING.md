# 贡献指南

感谢你对 OmniDoc Pro 的关注！本指南帮助你快速上手参与项目开发与改进。

## 项目简介

OmniDoc Pro 是一个本地文档预处理工作台，面向 RAG（检索增强生成）场景，提供深度 Word/Excel 解析、15+ 格式广度转换、Markdown 清洗/分块以及 LLM 增强能力。

## 开发环境搭建

### 前置要求

- Python >= 3.10
- pip / pipx / uv（任一）

### 安装开发依赖

```bash
# 克隆仓库
git clone <仓库地址>
cd omnidoc-pro

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 安装完整开发依赖
pip install -e ".[full,test]"
```

### 验证安装

```bash
# 运行测试
pytest -v

# 启动 WebUI 验证
omnidoc webui
```

## 代码规范

- **Python 版本**：3.10+，使用 type hints
- **格式化**：遵循 [ruff](https://docs.astral.sh/ruff/) 规范（`ruff check .` / `ruff format .`）
- **测试**：所有新功能需附带测试（`tests/` 目录，pytest + pytest-mock）
- **类型检查**：提交前运行 `mypy omnidoc/`

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
feat(chunker): 添加基于标题层级的 Markdown 分块
fix(cleaner): 修复 Windows CRLF 换行符导致空行未合并
docs: 更新 WebUI 使用文档
```

类型前缀：`feat` | `fix` | `docs` | `refactor` | `test` | `chore`

## 分支与 Pull Request 流程

1. 从 `main` 分支创建功能分支：`git checkout -b feat/你的功能`
2. 本地开发并运行测试：`pytest -v`
3. 推送分支：`git push origin feat/你的功能`
4. 在 GitHub 创建 Pull Request，填写变更说明
5. 等待 CI 通过 + 代码审查（至少 1 人）
6. 合并后删除远程分支

## 测试要求

- 新增功能必须有对应的单元测试
- 修改核心模块（`controller`、`engines`、`processors`）需确保已有测试不回归
- 运行全量测试：`pytest tests/ -v --cov=omnidoc`
- 目标覆盖率不低于 80%

## 发布说明

- 版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`
- 发布时在 `CHANGELOG.md`（如有）中记录变更
- 打 tag：`git tag -a v0.2.0 -m "Release v0.2.0"`

## 行为准则

- 尊重每一位贡献者
- 建设性讨论，对事不对人
- 报告安全问题请通过私有渠道（邮件或 GitHub Security Advisory），不要公开 issue

## 许可说明

本项目采用 GPL v3 + 商业双许可模式。你的贡献将默认在 GPL v3 下发布。如果你不希望贡献受 GPL 约束（例如包含专有代码），请在提交前与项目维护者沟通。

详见 [LICENSE](./LICENSE) 和 [LICENSE-COMMERCIAL](./LICENSE-COMMERCIAL.md)。

## 获取帮助

- 问题反馈：GitHub Issues
- 特性讨论：GitHub Discussions（如启用）
- 紧急安全漏洞：项目维护者邮箱
