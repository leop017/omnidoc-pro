# 设计方案：RAG Benchmark + 高级 Chunk 策略

- 状态：已评审（必要性 §6 / 可行性 §7，2026-10-12）· 暂缓实施，日后再做
- 基线：omnidoc-pro 0.3.9（421 tests passed，chunk 偏移量 round-trip 不变量已验证）
- 关联模块：`omnidoc/processors/chunkers/`、`omnidoc/core/config.py`、`omnidoc/controller/conversion.py`、`omnidoc/processors/pipeline.py`

---

## 0. 目标与非目标

**目标**

1. 建立**可离线、确定性、零新增硬依赖**的 RAG Benchmark，量化"分块质量 → 检索质量"的因果链，使 chunk 策略的改动可度量、可回归、可在 CI 中设门槛。
2. 设计 4 个高级 chunk 策略（layout / recursive / semantic / parent-child）+ 1 项零成本元数据增强（breadcrumb），全部走现有 `ChunkerInterface` 契约，opt-in 引入，**不改变任何默认行为**（与 0.3.x 零风险修复原则一致）。
3. 形成"benchmark 定门槛 → 策略实现 → benchmark 验收"的闭环。

**非目标**

- 不做端到端 LLM 生成质量评测（faithfulness/answer relevance 留作可选扩展）；
- 不引入向量库、不改变 `DocumentResult` 对外契约；
- 不在本方案内实现代码，仅定义接口、算法与验收标准。

---

## 1. RAG Benchmark 设计

### 1.1 总体架构

```
omnidoc/benchmark/
├── __init__.py
├── dataset.py      # 基准语料 + QA 用例加载/校验（jsonl 契约）
├── tokenizers.py   # 零依赖分词：en→词干小写词；zh→字符 bigram；混排自动分流
├── retrievers.py   # Bm25Retriever（纯 Python）；KeywordRetriever（消融基线）
├── metrics.py      # 检索指标 + 结构指标（纯函数，可单测）
├── runner.py       # BenchmarkRunner：config × corpus → chunk → index → 评测
├── report.py       # Markdown/JSONL 对比报告（多策略对比表）
└── cli.py          # `omnidoc benchmark run/compare`（挂到现有 typer app）
```

原则：**复用现有管线**。Runner 内部调用 `get_controller().convert_batch()`，对 `DocumentResult.chunks` 建索引——benchmark 评测的就是线上真实产物，而不是平行实现。`rag_failed=True` 的结果直接计为该用例失败。

评测环境冻结：Runner 强制 `enhanced_md=False`、`llm.enabled=False`（断言校验）——gold span 基于未增强的确定性 markdown，否则定位漂移。

### 1.2 数据契约

**语料**：`bench_corpus/` 目录 + `questions.jsonl`。自带 3 套固定 fixture（tests/fixtures/）+ 用户自选真实语料模式：

```jsonl
{"id": "qa-001",
 "source": "corpus/report.docx",
 "question": "2024年Q3华东区销售额是多少？",
 "gold_answer": "华东区Q3销售额为1,240万元",
 "gold_keywords": ["华东", "1240"],
 "tags": ["zh", "docx", "table"]}
```

- `gold_answer` 必须能在**转换后的 markdown**（`result.document.text`）中定位（精确匹配 → 空白归一化匹配 → 关键词窗口兜底），定位结果记为 gold span `(start, end)`。转换是确定性的，偏移稳定（审计已验证 chunk 偏移不变量）。
- `relevant_chunks` = 与 gold span 重叠率 ≥ 50% 的 chunk 集合；若无任何重叠 → 用例标记 `unanswerable`，从检索指标中剔除但计入结构指标（暴露"答案被切碎"问题）。

**用例规模建议**：fixture ≥ 30 题/语料（表格密集 10、长文 10、中文段落 10）；真实语料模式由用户按此模板自备。

### 1.3 指标体系

**A. 检索质量（核心）** — 查询 = `question`，文档 = chunk text：

| 指标 | 定义 | 说明 |
|---|---|---|
| Recall@k | mean(\|relevant ∩ top-k\| / \|relevant\|) | k 默认 5，另报 1/3/10 |
| MRR | mean(1 / 首个 relevant 的排名) | 对"答案在第几块"敏感 |
| nDCG@k | 二元相关增益的折损归一 | 排序质量 |

**B. 分块结构质量（不依赖检索器，可独立设门槛）**：

| 指标 | 定义 | 门槛意义 |
|---|---|---|
| coverage | Σ chunk span 并集 / 文档长度 | 必须 = 100%，防"分块丢内容"回归 |
| span_integrity | 完整落在单一 chunk 内的 gold span 占比 | 直接度量"答案被切断" |
| boundary_quality | 切点落在句末/标题起始的比例 | 切分点文明度 |
| oversize_ratio | 超过 embedding 窗口（默认 8192 tok 估算 1 token≈1.5 char zh）的 chunk 占比 | 上游索引兼容性 |
| size_p50/p95 | chunk 字符长度分位数 | 分布健康度 |
| redundancy | 1 − 去重字符数 / 总字符数 | overlap 策略的存储代价 |

**C. 端到端模拟（可选档）**：`small-to-big` 评测模式——用 child/parent 元数据（见 2.4）检索 child、以 parent 参与重排，验证 parent-child 策略收益。LLM judge 仅在 `llm.enabled` 时启用，离线自动跳过（复用 System Rule #3 降级模式）。

### 1.4 运行与报告

```
omnidoc benchmark run --corpus corpus/ --questions questions.jsonl \
    --strategies fixed,sentence,markdown,layout,recursive \
    --chunk-size 512 --chunk-overlap 64 --k 5 \
    --report bench_report.md --json bench_results.jsonl

omnidoc benchmark compare bench_a.json bench_b.json   # 两份结果的差分表
```

- 报告：策略 × 指标对比表 + 按 `tags`（格式/语言）分组明细 + 每题失败明细（top-k 命中情况、被切断的 gold span 所在 chunk 索引）。
- 确定性：BM25 纯 Python 实现、无随机性；同输入两次运行结果逐字节一致（CI 断言）。
- CI 门槛（`pr-checks.yml` 新增 job）：fixture 语料上，新增策略的 Recall@5 与 span_integrity 不得低于 baseline（markdown/fixed）− 1pp；coverage 必须 100%。

---

## 2. 高级 Chunk 策略设计

所有策略遵循既有契约：实现 `ChunkerInterface`、无状态、参数从 config dict 读取、经 `base.make_chunk` 产出（保证 `chunk_index/chunk_count` 与偏移量 round-trip 不变量 `text[s:e] == chunk.text`）、非法参数抛 `ValueError`（由 pipeline 捕获 → `rag_failed`）。

### 2.1 LayoutChunker（`layout`）— 结构感知，P1 首选

**动机**：Excel/Word 深度引擎的产出以表格为核心（审计确认 `_md_content`/`_build_html_table` 路径），当前 markdown 策略会把长表格硬切，行上下文丢失；且不感知围栏代码。

**算法**（纯 markdown 结构解析，零依赖）：

1. 块解析：heading / table（连续 `|` 行含分隔行）/ fenced code（``` 或 ~~~ 配对）/ list block（连续列表行）/ paragraph；
2. 表格**原子性**：`keep_tables_atomic=True`（默认）时表格永不跨块；超限表格整体独立成块并置 `metadata["oversize"]=True`（宁可超限不可破坏行——列对齐即表格语义）；`allow_oversize_table=False` 时降级为按行组切分并加 warning；
3. 孤儿表格回挂：表格前最近的 heading lineage 作为其 header/breadcrumb；
4. 超长 paragraph/list 块 → 委托递归切分（2.2 的分隔符层级）；
5. 偏移量沿用 `_group_span` 的源文切片方案，天然满足 round-trip。

### 2.2 RecursiveCharacterChunker（`recursive`）

- 分隔符层级默认 `["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]`，config `separators` 可覆盖；
- 贪心装包 ≤ `chunk_size`；单元仍超限 → 用下一级分隔符递归；最终硬切兜底；
- overlap：复用上一块**按最粗可用分隔符**对齐的尾部单元（优于 fixed 的裸字符窗口，切点更文明）；
- 递归全程携带 `(start, end)` 源文偏移，拼接保证单调连续。

### 2.3 SemanticChunker（`semantic`）— 可选依赖 + 强制降级

1. 句子切分复用 `sentence.py::_split_with_offsets`（偏移已验证）；
2. 批量 embed 句向量，计算相邻句余弦距离 `d_i`；`threshold = percentile(d_i, similarity_percentile)`（默认 90）；
3. 在超阈值断点处合并句子成块，尊重 `chunk_size` 上限；
4. embed 端点复用 `LlmSettings`（新增 `embedding_model` 字段）；**不可用时降级为 sentence 策略 + warning**。注意：chunker 自身无 warning 通道（异常会被 pipeline 捕获为 `rag_failed`），故降级判定放在 **pipeline `_chunk` 层**——预检 embedder 可用性后改选 sentence 并 `add_warning`（或 SemanticChunker 置 `metadata["semantic_fallback"]=True`，由 pipeline 扫描转为 warning），绝不 raise 中断批次。

### 2.4 Parent-Child（`parent_child` 元数据契约，非独立策略）

作为 `layout`/`markdown` 的后处理元数据层（config 开关；**实现在 pipeline 后处理层**，不进各 chunker 内部，避免双实现漂移）：

- child = 原子块切片（表格/段落/代码块）；parent = 其所属 header 子树 span；
- 每个 chunk 增加 `metadata["parent_id"]`（parent span 的稳定 hash）与 `parent_start/parent_end`；
- **不改写 `chunk.text`**（保住 round-trip 不变量）；索引侧按 child 检索、按 parent span 展开上下文，benchmark 的 small-to-big 模式负责验证收益。

### 2.5 Breadcrumb 元数据增强（零成本，全策略可用）

`metadata["headings"] = ["H1", "H2", …]`（祖先标题链）+ 可选 `metadata["breadcrumb"] = "H1 > H2"`（与 parent_child 同由 pipeline 后处理层统一注入）。检索方可将其拼入 embedding 输入——**确定性的 contextual retrieval lite**，无 LLM 成本；LLM 上下文摘要留作 `llm.enabled` 时的可选增强（失败降级为 breadcrumb-only）。

### 2.6 Config 变更（`ChunkingSettings`）

```python
strategy: Literal["fixed", "sentence", "markdown",
                  "recursive", "semantic", "layout"] = "fixed"
separators: list[str] = []            # recursive；空=内置默认层级
similarity_percentile: int = 90       # semantic，[50, 99]
keep_tables_atomic: bool = True       # layout
allow_oversize_table: bool = True     # layout
breadcrumb: bool = False              # 全策略
parent_child: bool = False            # layout/markdown
# LlmSettings 增：embedding_model: str = ""
```

`validate_issues()` 同步镜像各 chunker 的 ValueError 规则（沿用现有模式）；**所有新字段默认关闭/空，`fixed/sentence/markdown` 三个旧策略行为逐字节不变**——这是本方案的风险底线。

---

## 3. 实施阶段与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| P0 | benchmark 骨架：dataset/tokenizers/BM25/metrics/runner/report/CLI + 3 套 fixture | 421 旧测试全绿；benchmark 同输入双跑逐字节一致；输出 coverage=100% |
| P1 | `layout` + `breadcrumb` + `recursive`；benchmark 设门槛 | 表格密集 fixture：layout 的 span_integrity 与 Recall@5 ≥ markdown 基线；boundary_quality 提升；无 coverage 回归 |
| P2 | `semantic`（含降级链）+ `parent_child` + small-to-big 评测 + LLM 可选摘要（**条件必要**：P0/P1 数据确认仍有缺口后启动） | 无 embedder 时降级为 sentence 且有 warning；有 embedder 时改述类问题 Recall@5 ≥ sentence 基线 |

## 4. 风险与对策

| 风险 | 对策 |
|---|---|
| BM25 对中文区分度不足（零依赖分词） | zh 用字符 bigram + gold_keywords 双通道；文档明示局限；可选 `jieba` extra 增强，不进核心依赖 |
| 语义策略非确定性（模型版本漂移） | fixture 固定模型名；该部分测试 `skipif` 未安装；阈值指标容忍 ±1pp |
| 超限原子表格与 embedding 窗口冲突 | `oversize_ratio` 进报告；`allow_oversize_table=False` 提供按行组降级路径 |
| 新增字段误伤旧配置 | pydantic 默认值全向"旧行为"对齐；`to_engine_kwargs()` 增量字段仅在新策略分支被读取 |
| benchmark 语料偏置 | 结构指标（coverage/span_integrity/boundary）与检索指标分离设门槛；支持用户自带语料模式 |

---

## 5. 与现有审计结论的衔接

- 本方案全部为**opt-in 新路径**，默认行为零变更，规避了源码审计中"修复即风险"的两处遗留（markdown chunker 围栏感知、Excel `\n` 启发式）：layout 策略在**新路径内**实现围栏感知与表格原子性，不动旧策略一行代码，旧策略的改进由 benchmark 数据决定是否单独立项。
- 复用审计中已验证的不变量（chunk 偏移 round-trip、`rag_failed` 语义、降级 warning 契约）作为 benchmark 的结构指标与失败判定的基石。

---

## 6. 必要性分析（2026-10-12 评审）

**结论：P0/P1 是问题驱动、当前缺位的必要项；P2 是收益驱动的条件项。**

### 6.1 问题真实存在且有实证

1. **分块是一等功能，质量却不可度量**。CLI/WebUI 暴露 `--chunk-strategy`、`export_chunks`，pipeline 有 `rag_failed` 语义——"RAG-ready"是核心卖点，但 421 个测试全部验证**结构正确性**（偏移 round-trip、元数据），无一回答"这样切对 RAG 好不好"。质量盲区 = 卖点无证据。
2. **审计已实证真实缺陷且无法量化影响**：markdown 策略不感知代码围栏（运行时探针复现：代码注释被误判为标题并错误分块）；fixed/sentence 会把深度引擎的核心产出——表格——拦腰切断。影响多大、用户该选哪个策略，目前无数据可答。
3. **"修复即风险"的死锁只有新路径能解**。审计结论：对旧 chunker 的原地修复均为行为变更、非零风险。benchmark + opt-in 新策略是唯一同时满足"改进"与"零回归风险"的演进方式；没有 benchmark，新策略连验收标准都无法定义。

### 6.2 替代方案否决记录

| 替代方案 | 否决理由 |
|---|---|
| 不做，维持现状 | 质量盲区持续；引擎侧任何重构都可能造成检索质量**静默回归**且现有测试无法拦截；0.3.9 已达加固平台期（审计确认无剩余零风险修复项），项目失去可度量的演进轴 |
| 引入 LangChain/LlamaIndex splitter | 违背零硬依赖核心原则；外部 splitter **不保留源文偏移**——接入等于放弃审计已验证的 round-trip 核心资产 |
| 引入 Ragas/TruLens 评测 | LLM-judge 中心、依赖网络、非确定性，与项目"离线可跑、双跑逐字节一致才进 CI"哲学冲突；BM25+结构指标是最小必要内核 |
| 只修旧策略不加 benchmark | 审计已证明该类修复必然是行为变更，改完无法证明"变好了"还是"只是变了" |

### 6.3 不做的代价

策略参数暴露给用户却无法指导选择；围栏缺陷与表格切碎问题永久失焦；引擎演进与分块质量脱钩，静默回归不可见；项目停留在"正确但无法证明有用"的状态。

---

## 7. 可行性分析（2026-10-12 评审）

**结论：整体可行，无阻断项。** 关键假设已逐一对源码核实：

| 方案假设 | 代码事实（已核实） | 判定 |
|---|---|---|
| 新策略零接口改动 | `pipeline.py` 以 `chunker_factory=get_chunker` 注入，`chunker.chunk(document, dict(chunking))` 传纯 dict，新增 key 天然透传 | ✅ |
| Config 扩展安全 | `config.py` `strategy: Literal[...]` 单行扩展 + `validate_issues()` 镜像；pydantic 默认值兜底旧行为 | ✅ |
| BM25 零新硬依赖 | 核心依赖无 numpy/http client；BM25、余弦、分位数（`statistics.quantiles`）纯 Python 可实现 | ✅ |
| semantic 复用 LLM 通道 | `llm_service.py` 惰性 `import openai`，Ollama 走 OpenAI 兼容 `/v1/embeddings`；`[llm]` extra 已存在 | ✅ |
| CI 门槛可挂载 | `pr-checks.yml` 已存在；fixture 用 python-docx/openpyxl（核心依赖）生成 | ✅ |
| gold span 定位可靠 | 转换路径确定性；chunk 偏移 round-trip 已验证 | ✅ |

### 7.1 已回灌进正文的两处实现调整

1. **semantic 降级通道**：chunker 无 warning 通道 → 降级判定上移至 pipeline `_chunk` 层（见 §2.3 修订）。
2. **breadcrumb / parent_child 位置**：统一在 pipeline 后处理层注入，不进各 chunker（见 §2.4/§2.5 修订）。

### 7.2 边界条件

- fixture 固定 .docx/.xlsx/.md（不引 PDF 依赖）；
- Runner 冻结 `enhanced_md=False`、`llm.enabled=False`（见 §1.1 修订）；
- 报告输出显式 `sorted()` 键序保证双跑一致；
- 中文 bigram BM25 区分度有限——门槛取**策略间相对值**，绝对召回不外推，报告明示。

### 7.3 工作量量级（按交付物，非时间）

| 阶段 | 新增代码 | 新增测试 |
|---|---|---|
| P0 benchmark | ~700–900 LOC（含 BM25 ~150） | ~15 个（指标纯函数为主） |
| P1 layout/recursive/breadcrumb | ~400–500 LOC | ~12 个（偏移 round-trip 属性测试为主） |
| P2 semantic/parent-child | ~250–350 LOC | ~8 个（降级链 + skipif 网络测试） |

---

## 8. 实施切入备忘（日后再实施时从这里开始）

1. **入口顺序**：`omnidoc/benchmark/metrics.py` 纯函数 + `tokenizers.py` 先行（零风险、易测）→ fixture 生成（conftest 内用 python-docx/openpyxl）→ Bm25Retriever → runner/report/CLI。
2. **策略注册点**：`omnidoc/processors/chunkers/__init__.py::get_chunker` 工厂表 + `config.py::ChunkingSettings` Literal。
3. **降级与元数据注入统一走 pipeline**：`_chunk` 层做 semantic 预检降级；chunks 产出后做 breadcrumb/parent_child 后处理（勿散落进 chunker）。
4. **验收门槛挂载**：`.github/workflows/pr-checks.yml` 新增 benchmark job（coverage=100% 硬门槛 + Recall@5/span_integrity 相对基线 −1pp 容差）。
5. **开工前置**：重读本文件 §1.2 数据契约与 §2 各算法小节；基线测试需保持全绿（评审时点 404 passed；当前基线 421 passed）。
