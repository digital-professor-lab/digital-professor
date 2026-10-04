# 文件用途说明

[English](FILE_GUIDE.md) · [项目入口](../README.zh-CN.md)

当前代码按功能分组。所有可运行命令采用 `python -m digital_professor.<模块>`。历史源码映射见 [file-mapping.json](file-mapping.json)。

| 文件（相对 src/digital_professor） | 用途 |
| --- | --- |
| `knowledge/build_kb.py` | 解析课程来源，构建关联的 SQL/JSONL 记录。 |
| `knowledge/validate_kb.py` | 检查 ID、关联、原文行号及 hash。 |
| `embeddings/prepare_embedding_inputs.py` | 为两个模型准备统一的分段文本。 |
| `embeddings/generate_embeddings.py` | 编码并保存归一化向量及行映射。 |
| `embeddings/validate_embeddings.py` | 检查维度、归一化、行 ID 和 hash。 |
| `database/import_data.py` | 以事务导入/替换知识库和向量记录。 |
| `database/validate_deployment.py` | 核对数据库记录、索引和向量导出。 |
| `retrieval/search.py` | 混合检索、证据选择和带引用上下文。 |
| `retrieval/request_policy.py` | 判断范围/来源请求，生成聚焦子问题。 |
| `retrieval/report_contract.py` | 运行时校验状态与证据的一致性。 |
| `evaluation/build_benchmark.py` | 生成 50 题、证据锚点与 manifest。 |
| `evaluation/run_benchmark.py` | 运行模型对照，计算证据覆盖指标。 |
| `evaluation/evaluate_retrieval.py` | 跨课程的小型检索冒烟评估。 |
| `evaluation/ablate_file_cap.py` | 比较每文件片段上限。 |
| `evaluation/diagnose_failures.py` | 分析遗漏的预期证据。 |
| `evaluation/evaluate_policy_update.py` | 比较 hard/soft 每文件限制。 |
| `evaluation/evaluate_refinement.py` | 对照整题、聚焦子问题与上下文大小。 |
| `evaluation/evaluate_paraphrases.py` | 检查两道已知题的六种额外问法。 |
| `paths.py` | 统一解析数据路径与数据库端口。 |

每个 `__init__.py` 定义对应 Python 包，没有单独运行流程。

| 其他文件/目录 | 用途 |
| --- | --- |
| `infra/postgres/schema.sql` | 知识、向量表及检索索引。 |
| `infra/postgres/compose.yaml` | 固定数据库镜像、本地持久化配置。 |
| `infra/postgres/.env.example` | 不含实际密码的本地配置模板。 |
| `contracts/retrieval_report.schema.json` | 完整命中记录/报告的交换结构。 |
| `tests/test_request_policy.py` | 范围、来源和输出决策测试。 |
| `tests/test_search_policy.py` | 选择预算、Not found 行为测试。 |
| `data/sources/*.tex` | 六份当前入库来源。 |
| `data/catalog/` | 课程、文档、章节、片段、概念、证据关联、问题记录、manifest 与 SQLite。 |
| `data/embeddings/` | 统一输入、精确模型版本、行映射、小型向量矩阵。 |
| `data/benchmark/` | 当前固定题集和便携 catalog 对应的 hash。 |
| `artifacts/evaluations/` | 历史运行记录；也是新评估的默认输出位置。 |
| `artifacts/history/` | 原始 catalog 和数据库验证快照，保持原样。 |
| `artifacts/validation/` | 整理后副本的验证结果。 |
| `docs/reports/` | 按周整理的展示报告。 |
| `docs/architecture/` | 流程 HTML 图示与 PDF 报告。 |
| `docs/research/` | 集成讨论 PDF，文件名保留原版本。 |
| `docs/history/` | 原始计划、旧 README 与进展记录。 |
| `archive/week2/` | 早期 Gemini/DeepSeek/Kimi 课程实验和结果。 |
| `archive/week1-drafts/` | 早期展示草稿。 |
| `tools/verify_saved_results.py` | 离线核对历史命中与新目录来源。 |
| `requirements.lock.txt` | 记录完整依赖环境。 |
| `requirements-test.txt` | 离线检查及 CI 的精简依赖。 |
| `pyproject.toml` | 支持可编辑安装的包配置。 |
| `.github/workflows/ci.yml` | 自动运行单元测试、数据/向量及历史输出检查。 |
| `.gitignore` | 阻止本地密码和运行文件进入 Git。 |

历史 Week 2 的运行说明保留原样，不是当前检索入口；调用外部模型需要组员自己的 API key，并会产生相应调用费用。新整理版没有运行这些 API 调用。
