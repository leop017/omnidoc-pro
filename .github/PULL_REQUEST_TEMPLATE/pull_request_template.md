## 变更说明

<!-- 简述本 PR 做了什么，为什么做 -->

## 测试

- [ ] 已运行 `pytest tests/ -v --cov=omnidoc` 并通过
- [ ] 已运行 `ruff check .` 并通过
- [ ] 已运行 `ruff format .` 并确认无 diff
- [ ] 新增功能附带了对应测试

## 影响范围

- [ ] 仅文档 / CI 配置变更
- [ ] 修改了 `omnidoc/core`（数据模型、接口、配置）
- [ ] 修改了 `omnidoc/engines`（Deep / MarkItDown 引擎）
- [ ] 修改了 `omnidoc/processors`（清洗、分块、增强管道）
- [ ] 修改了 `omnidoc/ui`（CLI / WebUI）

## 发布相关（如适用）

- [ ] 已更新 `RELEASE_NOTES/<version>.md`
- [ ] 已同步 `omnidoc/__init__.py` 与 `pyproject.toml` 中的版本号
