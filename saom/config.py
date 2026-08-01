import os
from pathlib import Path

DEFAULT_MEMORY = Path.home() / ".saom" / "memory"


def get_memory_dir():
    return Path(os.environ.get("SAOM_MEMORY_DIR", str(DEFAULT_MEMORY)))


def ensure_memory():
    d = get_memory_dir()
    for sub in ["bridge", "dashboard", "graph", "knowledge", "lessons", "rules", "sessions", "skills", "vault", "working"]:
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def llm_config():
    return {
        "api_key": os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        "base_url": os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        "model": os.environ.get("LLM_MODEL", "gpt-4o"),
    }
