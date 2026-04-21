"""Paths, model config, and constants for the tailoring engine.

This is the main tuning surface. All validation thresholds and LLM settings
are here. See QUALITY_BAR.md for what each gate does and how to tune.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
TAILORING_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = TAILORING_ROOT / "Baseline-Dox"
RESUME_TEX = BASELINE_DIR / "Conner_Jordan_Software_Engineer" / "Conner_Jordan_Resume.tex"
COVER_TEX = BASELINE_DIR / "Conner_Jordan_Cover_letter" / "Conner_Jordan_Cover_Letter.tex"
SKILLS_JSON = TAILORING_ROOT / "skills.json"
SOUL_MD = TAILORING_ROOT / "soul.md"
PERSONA_DIR = TAILORING_ROOT / "persona"
QUALITY_BAR_MD = TAILORING_ROOT / "QUALITY_BAR.md"
OUTPUT_DIR = TAILORING_ROOT / "output"
GROUNDING_CONFIG = TAILORING_ROOT / "grounding" / "v1.json"

DB_PATH = Path.home() / ".local" / "share" / "job_scraper" / "jobs.db"
LOCK_PATH = Path.home() / ".local" / "share" / "textailor" / "llm.lock"

# ── LLM Endpoint (Ollama default) ─────────────────────────────────────
OLLAMA_URL = os.environ.get(
    "TAILOR_LLM_URL",
    os.environ.get("TAILOR_OLLAMA_URL", "http://localhost:11434/v1/chat/completions"),
)
OLLAMA_MODELS_URL = os.environ.get(
    "TAILOR_LLM_MODELS_URL",
    os.environ.get("TAILOR_OLLAMA_MODELS_URL", "http://localhost:11434/v1/models"),
)
# Use "default" to auto-pick the first model returned by /v1/models.
OLLAMA_MODEL = os.environ.get(
    "TAILOR_LLM_MODEL",
    os.environ.get("TAILOR_OLLAMA_MODEL", "default"),
)
OLLAMA_TIMEOUT = 600  # seconds per LLM call (thinking models need extra time)
LOCK_TIMEOUT = 300  # seconds to wait for file lock (prevents concurrent LLM access)

# ── Multi-provider support ────────────────────────────────────────────
LLM_API_KEY = os.environ.get("TAILOR_LLM_API_KEY", "")
LLM_PROVIDER = os.environ.get("TAILOR_LLM_PROVIDER", "ollama")

# ── Validation thresholds ──────────────────────────────────────────────
# These control the hard gates in validator.py. Adjust based on your model's output.
# Run `python -m tailor validate <output_dir>` to test thresholds on existing output.

RESUME_BULLET_COUNT = 14  # 6 (UCOP) + 5 (GWR) + 3 (Simple.biz) — default target
RESUME_CHAR_TOLERANCE = 0.20  # ±20% body text vs baseline
COVER_CHAR_TOLERANCE = 0.15  # ±15% body text vs baseline
MAX_RETRIES = 3  # full pipeline retries (strategy + draft + QA) per document

RESUME_TARGET_PAGES = 1
RESUME_MIN_FILL_RATIO = 0.85  # page 1 must be ≥85% filled vertically
RESUME_COMPACT_MODE_ENABLED = False  # manual-only; auto-fit should prefer content reduction
RESUME_FIT_MAX_STAGES = 2
RESUME_COMPANIES = [
    "University of California, Office of the President",
    "Great Wolf Resorts",
    "Simple.biz",
]
RESUME_COMPANY_BULLET_TARGETS = {
    "University of California, Office of the President": 6,
    "Great Wolf Resorts": 5,
    "Simple.biz": 3,
}
RESUME_COMPANY_BULLET_FLOORS = {
    "University of California, Office of the President": 4,
    "Great Wolf Resorts": 4,
    "Simple.biz": 3,
}

# ── Section order (canonical) ──────────────────────────────────────────
# validator._check_section_order() ensures these appear in this order in the .tex output.
RESUME_SECTIONS = [
    "PROFESSIONAL SUMMARY",
    "TECHNICAL SKILLS",
    "WORK EXPERIENCE",
    "EDUCATION",
    "CERTIFICATIONS",
]

# ── Run-scoped file read cache ────────────────────────────────────────
# Avoids re-reading baseline files that don't change mid-run.
_FILE_CACHE: dict[str, str] = {}
_JSON_CACHE: dict[str, dict] = {}


def clear_file_cache() -> None:
    """Clear the run-scoped file read cache (call at run start)."""
    _FILE_CACHE.clear()
    _JSON_CACHE.clear()


def read_cached(path: Path) -> str:
    """Read a file with run-scoped caching."""
    key = str(path)
    if key not in _FILE_CACHE:
        _FILE_CACHE[key] = path.read_text(encoding="utf-8")
    return _FILE_CACHE[key]


def read_json_cached(path: Path) -> dict:
    """Read and parse a JSON file with run-scoped caching."""
    key = str(path)
    if key not in _JSON_CACHE:
        _JSON_CACHE[key] = json.loads(read_cached(path))
    return _JSON_CACHE[key]
