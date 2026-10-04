"""Project paths shared by every stage; independent of the working directory."""
import os
from pathlib import Path
PROJECT_ROOT = Path(os.environ.get("DP_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
SOURCES = PROJECT_ROOT / "data/sources"
CATALOG = PROJECT_ROOT / "data/catalog"
EMBEDDINGS = PROJECT_ROOT / "data/embeddings"
BENCHMARK = PROJECT_ROOT / "data/benchmark"
EVALUATIONS = PROJECT_ROOT / "artifacts/evaluations"
DATABASE_CONFIG = PROJECT_ROOT / "infra/postgres"
DATABASE_REPORTS = PROJECT_ROOT / "artifacts/database"
CACHE = PROJECT_ROOT / ".cache/huggingface"

def resolve_source(value):
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path

def database_port():
    """Use the same optional port override as Docker Compose."""
    value = os.environ.get("DP_DB_PORT")
    env_file = DATABASE_CONFIG / ".env"
    if value is None and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DP_DB_PORT="):
                value = line.partition("=")[2]
    return int(value or 55432)
