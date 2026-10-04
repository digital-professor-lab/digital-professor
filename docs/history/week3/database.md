# PostgreSQL and pgvector deployment

The active knowledge-base database runs in Docker using the pinned `pgvector/pgvector:pg17` image. It is bound to `127.0.0.1:55432`, so only this computer can reach the published port. Persistent database files are in `docker_data/` under this Week 3 directory. Docker must be running.

## Connection

- Database: `course_knowledge`
- User: `coursekb`
- Host: `127.0.0.1`
- Port: `55432`
- Password: local `.env` file (`POSTGRES_PASSWORD`, mode `0600`)

Keep `.env` private; do not publish it or add it to a repository. Back up both `.env` and `docker_data/` together. The `data/`, `run/`, and `logs/` directories in this folder belong to the earlier, stopped native PostgreSQL instance and are not used by Docker.

## Start and stop

Run these commands from this `postgres/` directory:

```bash
docker compose --project-name entagile-kb up -d --wait
docker compose --project-name entagile-kb ps
docker compose --project-name entagile-kb stop
```

The container has an `unless-stopped` restart policy. `stop` preserves the database files. Do not delete `docker_data/` when stopping the container.

## Build or refresh the database

From this `postgres/` directory, create the schema after a fresh initialization:

```bash
docker exec -i entagile-course-kb psql -v ON_ERROR_STOP=1 -U coursekb -d course_knowledge < schema.sql
```

From the project root, reload the current catalog and both vector matrices:

```bash
week3/knowledge_base/.venv/bin/python week3/knowledge_base/postgres/import_data.py --host 127.0.0.1 --port 55432 --user coursekb --password-file week3/knowledge_base/postgres/.env
week3/knowledge_base/.venv/bin/python week3/knowledge_base/postgres/validate_deployment.py
```

The import checks input hashes and vector dimensions, then replaces all catalog and vector rows in one database transaction. It does not regenerate embeddings; regenerate them first if the source catalog changed. Validation checks table counts, record IDs and hashes, every stored vector against its NumPy source, the expected indexes, and a sample cosine query. Results are saved in `import_report.json` and `validation_report.json`.

Current validated contents: 2 courses, 6 documents, 130 sections, 221 passages, 216 concept cards, 476 embedding inputs, 476 BGE vectors (768 dimensions), and 476 Qwen vectors (1024 dimensions). pgvector version: 0.8.6.

The [retrieval pipeline](../retrieval/README.md) now queries these indexes and assembles cited source context. An answer model and HTTP application API are separate future work.
