# Week 3 / Week 4 GitHub 同步清单

检查日期：2026-10-03。当前 entagile 目录不是 Git 仓库；本清单用于整理上传内容，尚未创建仓库或推送。

推荐：保留现有 `resource/`、`week3/`、`week4/` 结构，把代码、构建输入、当前数据快照、最新评估依据和展示报告一起同步。不要直接把整个本地文件夹上传。

## 已完成的工作

- 将两门课程的六份 LaTeX 材料解析成课程、文档、章节、片段、概念卡和证据关联；保留 scope、原文和源文件行号。
- 为同一组 476 条输入生成 BGE、Qwen3 两套 embedding，导入 PostgreSQL / pgvector。
- 实现向量与关键词混合检索、结果融合、范围和来源检查、软文件限制、分问题检索、带引用的原文上下文。
- 定义单条命中记录和完整检索报告，增加 JSON Schema、运行时一致性校验及测试。
- 在当前 50 题 benchmark 上，46 道可回答题覆盖全部预期证据；4 道范围外/缺少来源题返回 not_found 和空证据。六种额外问法覆盖 5/6。这里评估的是检索，尚未评估 LLM 回答。
- Week 4 用交互报告介绍 knowledge input、retrieved evidence、retrieval report 三层 schema。

## 必传代码：21 个 Python 文件

以下路径均以 `week3/knowledge_base/` 为基准。Week 4 目前没有单独的 Python 检索实现；最新检索改动仍在这些文件里。

| 用途 | 文件 |
| --- | --- |
| 知识库解析、SQL 数据结构、入库 | `build_kb.py` |
| 知识库验证 | `validate_kb.py` |
| embedding 输入准备、分段 | `prepare_embedding_inputs.py` |
| 两种 embedding 生成 | `generate_embeddings.py` |
| embedding 验证 | `validate_embeddings.py` |
| PostgreSQL 数据与向量导入 | `postgres/import_data.py` |
| PostgreSQL 部署验证 | `postgres/validate_deployment.py` |
| 混合检索、证据选择与上下文 | `retrieval/search.py` |
| 范围/来源决策、问题拆分 | `retrieval/request_policy.py` |
| 输出一致性校验 | `retrieval/report_contract.py` |
| 模块说明/初始化 | `retrieval/__init__.py` |
| scope 与来源规则测试 | `retrieval/test_request_policy.py` |
| 检索选择和输出行为测试 | `retrieval/test_search_policy.py` |
| benchmark 题目与证据构建 | `retrieval/build_benchmark.py` |
| 模型对比、证据评估 | `retrieval/run_benchmark.py` |
| 初始检索冒烟评估 | `retrieval/evaluate_retrieval.py` |
| 每文件上限对照实验 | `retrieval/ablate_file_cap.py` |
| 失败题诊断 | `retrieval/diagnose_failures.py` |
| hard/soft 策略对照 | `retrieval/evaluate_policy_update.py` |
| 最新范围规则与分问题检索评估 | `retrieval/evaluate_refinement.py` |
| 额外问法评估 | `retrieval/evaluate_paraphrases.py` |

历史实验脚本也建议保留：它们解释尝试过什么，且评估脚本之间有导入依赖，不宜只挑几个核心文件。

## 必传配置和说明

- `week3/knowledge_base/postgres/schema.sql`：实际 PostgreSQL 表结构、关系与检索索引。
- `week3/knowledge_base/postgres/compose.yaml`：Docker 数据库配置；使用环境变量读取密码，不包含实际密码。
- `week3/knowledge_base/retrieval/retrieval_report.schema.json`：检索报告及命中记录的正式输出结构。
- `week3/knowledge_base/requirements-embeddings.lock.txt`：依赖版本，包含模型、数据库连接、向量与重排依赖。
- `week3/knowledge_base/.gitignore`：现有本地环境/数据库排除规则。
- 三份 README：`knowledge_base/README.md`、`knowledge_base/postgres/README.md`、`knowledge_base/retrieval/README.md`。
- `week3/course_knowledge_retrieval_plan.md`、`retrieval/evaluation_framework.md`：设计和评估方式。

## 建议随代码上传：输入、数据与最新证据

### 原始构建输入

`build_kb.py` 从项目根目录的 `resource/` 读取这六个文件，因此只上传 Week 3 / Week 4 无法从头构建：

- `resource/Calc1_Syllabus_Claude.tex`
- `resource/Calc1_Content_Claude.tex`
- `resource/Calc1_Book_Claude.tex`
- `resource/Number_Syllabus_Claude.tex`
- `resource/Number_Content_Claude.tex`
- `resource/Number_Claude_Interactive.tex`

课程材料建议先在小组私有仓库同步；若要公开，确认材料可公开分享。它们是当前提供的课程整理文件，不是完整原教材。

### 知识库快照

建议上传 `week3/knowledge_base/data/`：JSONL、manifest、六份 source snapshots、质量说明和 SQLite，合计约 1.45 MiB。SQLite 可选；JSONL 和 snapshots 更便于审查，保存原快照也方便核对历史评估。

### 向量导出

建议上传 `week3/knowledge_base/embeddings/` 的九个文件，合计约 4.01 MiB：共享输入、输入 manifest、embedding report，以及两个模型各自的 `manifest.json`、`rows.jsonl`、`vectors.npy`。

这些小型向量导出不是模型权重。保留它们可减少组员重新生成文档向量的工作；查询时仍需要下载/加载 embedding 模型。

### 最新评估

以 `week3/knowledge_base/retrieval/` 为基准，优先上传：

- `benchmark_50.jsonl`、`benchmark_manifest.json`：测试问题、证据标签和版本。
- `refinement_report.md`、`refinement_results.json`：最新汇总及逐题评分。
- `refinement_runs/facets_6.jsonl`：当前策略的 50 题完整输出，约 1.10 MiB。
- `paraphrase_validation.json`：额外问法结果，避免只展示成功样本。
- `examples/sample_search.json`、`examples/sample_llm_prompt.txt`：接口示例；这是较早示例，最新完整 schema 以 facets_6 和正式 JSON Schema 为准。
- `postgres/import_report.json`、`postgres/validation_report.json`：数据库导入和验证结果（位于 knowledge_base 下）。

### 展示文件

- `week3/digital-professor-week3-report.html`
- `week4/digital-professor-week4-report.html`
- `week4/output/digital-professor-system-workflow-en.html`（补充架构展示，可选）

Week 4 报告的页脚链接指向 Week 3 的 schema 和评估说明，保留目录关系才能正常打开。

## 可选上传：实验历史与补充文档

小型 Markdown 报告和 JSON 汇总建议保留。完整历史运行输出可稍后上传或作为单独的实验归档：

- `benchmark_report.md`、`benchmark_results.json`、`benchmark_runs/`：初始五种检索配置，运行输出约 5.64 MiB。
- `policy_update_report.md`、`policy_update_results.json`、`policy_update_runs/`：hard/soft 设置，运行输出约 6.28 MiB。
- `refinement_runs/full_6.jsonl`、`refinement_runs/full_8.jsonl`：最新对照组。
- `benchmark_archive/v1/`：旧题集及其输出，约 6.09 MiB；不能与新版指标混在一起。
- `evaluation_report.md`、`evaluation_results.json`、`failure_diagnostics.md`、`file_cap_ablation.md`、`file_cap_ablation.json`。
- Week 4 的三份 integration PDF：是讨论资料，不是运行依赖；先选定要分享的版本，不必全上传。
- Week 3 两张 report preview PNG：展示截图，可不传。

## 不上传

- `week3/knowledge_base/postgres/.env`：实际数据库密码。
- `week3/knowledge_base/.venv/`：本机 Python 环境。
- `week3/knowledge_base/.cache/`：模型权重和下载缓存。
- `week3/knowledge_base/postgres/docker_data/`：Docker PostgreSQL 实际运行目录。
- `week3/knowledge_base/postgres/data/`、`run/`、`logs/`：旧数据库状态、运行文件和日志。
- 所有 `__pycache__/`、`*.pyc`、`.DS_Store`。

现有 `.gitignore` 已排除大部分上述目录，但未排除 `.DS_Store`。建仓库时建议在根目录增加相应规则，并提供不含真实密码的 `.env.example`，让组员自己设置 `POSTGRES_PASSWORD`。

## 上传前需要说明的复现限制

1. 代码主要按文件位置寻找资源，但生成的 catalog、manifest、历史检索记录和 HTML 示例中包含本机绝对路径。`validate_kb.py` 和数据库导入会访问这些路径；组员不能直接拿这些快照开箱运行。
2. 换机器应重建本机 catalog，并按 benchmark 构建流程更新对应 manifest，再生成/导入数据；不要随意改历史文件中的路径，否则会破坏已经记录的 hash 对应关系。保留原始快照作为历史结果依据。
3. README 中的 `.venv/bin/python` 是本机运行路径。组员需要先创建环境并安装锁定依赖、启动 Docker、设置自己的数据库密码；环境与缓存不从 GitHub 复制。
4. 查询代码仍读取本地 `postgres/.env`，并默认连接 `127.0.0.1:55432`。这次分享的是本地研究原型，不是已经部署的团队在线服务。

推荐组员阅读顺序：Week 4 report → retrieval README → retrieval_report.schema.json → search.py / request_policy.py → schema.sql / build_kb.py → refinement_report.md / facets_6.jsonl。
