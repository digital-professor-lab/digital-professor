# Digital Professor — 结构化课程检索系统

[English](README.md) · [文件说明](docs/FILE_GUIDE.zh-CN.md)

这个项目把微积分 I、数论 I 的六份课程文件，转成可追溯的知识库、两套 embedding 和混合检索系统。它输出原文证据和结构化检索报告，供下游 LLM、evaluation、validation 使用。目前不生成最终答案，也没有在线 HTTP 服务。

这是 Week 3–4 工作的团队共享版：代码按功能组织，早期周报、Week 2 模型实验保留为历史资料。目录采用工程项目的组织方式，但系统仍处于研究原型阶段。

## 五分钟了解项目

1. 在浏览器打开 [Week 4 报告](docs/reports/week4/digital-professor-week4-report.html)。
2. 看下方流程及 [文件用途说明](docs/FILE_GUIDE.zh-CN.md)。
3. 查看 [50 题完整输出](artifacts/evaluations/refinement_runs/facets_6.jsonl) 与 [检索 JSON Schema](contracts/retrieval_report.schema.json)。
4. 要运行系统，再按快速开始操作。只阅读报告和已有结果不需要数据库或下载模型。

## 每一步在做什么

| 步骤 | 输入 → 处理 → 输出 | 代码位置 |
| --- | --- | --- |
| 1. 知识库 | 六份 LaTeX → 提取课程、文档、章节、片段、概念关联 → SQL/JSONL 结构化知识 | `src/digital_professor/knowledge/` |
| 2. Embedding | 关联原文的文本 → 统一分段输入 → BGE、Qwen3 归一化向量 | `src/digital_professor/embeddings/` |
| 3. 数据库 | 知识记录与向量导出 → 导入 PostgreSQL/pgvector → 数据表与检索索引 | `infra/postgres/`、`src/digital_professor/database/` |
| 4. 检索 | 问题与过滤条件 → 范围/来源判断、语义与关键词检索、融合及选择 → 带引用原文与报告 | `src/digital_professor/retrieval/` |
| 5. 评估 | 问题与预期证据 → 核对证据覆盖和输出状态 → 每题指标、汇总报告 | `src/digital_professor/evaluation/` |

三层 schema 各有用途：**knowledge input** 保证知识库结构稳定；**retrieved evidence** 让系统准确识别每个片段，作为 LLM 输入；**retrieval report** 记录请求、结果和过程，供下游验证质量、决定是否重新检索。`found` 表示返回了证据，不代表最终答案已经验证。检索分数是排名值，不是确定性百分比。

## 文件结构

```text
github-ready/
├── README.md / README.zh-CN.md    # Start here / 从这里开始
├── src/digital_professor/
│   ├── knowledge/               # Parse and validate course knowledge
│   ├── embeddings/              # Prepare, encode, validate vectors
│   ├── database/                # Import and validate PostgreSQL
│   ├── retrieval/               # Search, scope policy, output checks
│   ├── evaluation/              # Benchmarks and experiments
│   └── paths.py                 # Shared portable paths
├── infra/postgres/              # SQL, Docker Compose, .env.example
├── contracts/                   # JSON interchange schema
├── data/
│   ├── sources/                 # Six source files
│   ├── catalog/                 # Linked knowledge records + SQLite
│   ├── embeddings/              # Shared inputs + two vector exports
│   └── benchmark/               # 50 questions + source hashes
├── tests/                       # Retrieval and request behavior tests
├── artifacts/
│   ├── evaluations/             # Saved runs; new evaluations write here
│   ├── history/                 # Frozen original catalog / DB reports
│   └── validation/              # Packaging verification results
├── docs/
│   ├── FILE_GUIDE*.md           # File-by-file guide in both languages
│   ├── reports/                 # Week 1–4 presentation reports
│   ├── architecture/            # Workflow diagrams and system reports
│   ├── research/                # Integration discussion PDFs
│   └── history/                 # Original notes and design decisions
├── archive/                     # Week 1 drafts / Week 2 model prototype
├── tools/                       # Offline package verification
├── requirements.lock.txt        # Captured runtime dependencies
├── requirements-test.txt        # Small test-only dependency set
├── pyproject.toml               # Importable src package
├── .github/workflows/ci.yml      # Offline-data checks in CI
└── .gitignore                   # Exclude local secrets / runtime state
```

## 快速开始：使用随项目附带的数据

需要 Python 3.11+（本次本地验证使用 3.12）、Docker 和 Compose。下列命令都在本项目根目录运行。依赖包括 PyTorch 和 embedding 库，安装及模型下载可能比较大；锁定文件记录了已使用的环境，不保证任意系统/CPU 都有对应安装包。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
```
已附带 catalog 和小型向量导出，以下检查不需要数据库、答案模型或 API key：

```bash
python -m digital_professor.knowledge.validate_kb
python -m digital_professor.embeddings.validate_embeddings
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/verify_saved_results.py
```
要运行实时检索，创建自己的本地数据库：

```bash
cp infra/postgres/.env.example infra/postgres/.env
# Edit infra/postgres/.env and choose your own POSTGRES_PASSWORD.
docker compose --project-directory infra/postgres -f infra/postgres/compose.yaml up -d --wait
docker compose --project-directory infra/postgres -f infra/postgres/compose.yaml exec -T database psql -v ON_ERROR_STOP=1 -U coursekb -d course_knowledge < infra/postgres/schema.sql
python -m digital_professor.database.import_data
python -m digital_professor.database.validate_deployment
python -m digital_professor.retrieval.search "What does the Fundamental Theorem of Calculus say about accumulation?" --format json
```

复制 `.env.example` 后，先编辑 `.env`，设置你自己的 `POSTGRES_PASSWORD`。查询模型首次使用会下载到被忽略的 `.cache/`，向量文件不能代替查询模型。

默认数据库 `course_knowledge`，用户 `coursekb`，本地端口 `55432`。如果端口已被占用，在本地 `infra/postgres/.env` 增加 `DP_DB_PORT=55433`；Docker、导入、校验、检索都会使用这个端口。不要上传真实 `.env`。

导入会替换这个项目数据库中的知识库和向量记录。停止数据库但保留数据：

```bash
docker compose --project-directory infra/postgres -f infra/postgres/compose.yaml stop
```

## 更新课程内容后的重建

```bash
python -m digital_professor.knowledge.build_kb
python -m digital_professor.knowledge.validate_kb
python -m digital_professor.embeddings.prepare_embedding_inputs
python -m digital_professor.embeddings.generate_embeddings bge_base_en_v1_5
python -m digital_professor.embeddings.generate_embeddings qwen3_embedding_0_6b
python -m digital_professor.embeddings.validate_embeddings
python -m digital_professor.evaluation.build_benchmark
python -m digital_professor.database.import_data
python -m digital_professor.database.validate_deployment
```

重建会覆盖当前派生文件；修改课程内容前先保存实验版本。内容改变后需重新审查 benchmark 的证据锚点。准备 embedding 输入时会重新解析模型 revision；要复现已锁定的向量，请保留现有 manifest。当前 catalog 使用仓库相对路径，`paths.py` 负责解析，不依赖你从哪个目录启动。

## 跑评估

```bash
python -m digital_professor.evaluation.evaluate_refinement
python -m digital_professor.evaluation.evaluate_paraphrases
```

需要实时数据库和模型，结果写入 `artifacts/evaluations/`。如果要保留以前的运行结果，先另存归档。其他对照实验见文件说明。

## 当前进展与验证范围

已保存的 benchmark 中，**46/46 可回答题**覆盖全部预期证据，**4/4 范围外或缺少来源的题**返回 `not_found` 和空证据；合计 50 题符合预期检索结果。额外六种问法达到 5/6。标签是基于当前来源的暂定标签，课程文件仍未经过教师验证；这些结果不代表教材内容或 LLM 最终回答全部正确。

本次目录整理已重建并验证 catalog、校验两套向量、检查模块导入、通过 13 项行为测试，并用新目录来源核对已有 50 题记录。整理时 Docker 没有运行，因此未重新执行实时数据库初始化和模型检索。详见 [整理验证记录](artifacts/validation/packaging-checks.json)。

## 如何理解历史文件

`artifacts/evaluations/` 保留以前运行的原始 hash 和路径；对应的旧 catalog 在 `artifacts/history/original-catalog/`。现在可运行的数据在 `data/`。不要把旧结果改称为整理后重新跑出的结果。`docs/history/` 与 Week 2 归档可能提到旧路径，当前运行方式以本 README 为准。

来源是课程设计/教材提纲文件，不是完整原教材；定位使用 LaTeX 源文件行号，不是教材页码。共享版不包含真实凭据、模型权重、本机环境或数据库运行文件。建议先建小组私有仓库；公开课程材料前确认分享权限。
