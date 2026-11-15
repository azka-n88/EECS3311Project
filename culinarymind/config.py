"""Loads local configuration from .env (never committed)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load_env(path=None):
    path = Path(path or ROOT / ".env")
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
DB_PATH = os.getenv("CULINARY_DB", str(ROOT / "culinarymind.db"))
RECIPES_PATH = ROOT / "data" / "recipes.json"
