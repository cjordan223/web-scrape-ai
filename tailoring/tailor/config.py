"""Paths, model config, and constants for the tailoring engine.

This is the main tuning surface. All validation thresholds and LLM settings
are here. See QUALITY_BAR.md for what each gate does and how to tune.
"""

from __future__ import annotations

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

DB_PATH = Path.home() / ".local" / "share" / "job_scraper" / "jobs.db"
LOCK_PATH = Path.home() / ".local" / "share" / "job_scraper" / "ollama.lock"

# ── LM Studio (OpenAI-compatible) ─────────────────────────────────────
# Backward compatible env overrides:
# - TAILOR_LMSTUDIO_URL / TAILOR_LMSTUDIO_MODELS_URL (preferred)
# - TAILOR_OLLAMA_URL / TAILOR_OLLAMA_MODELS_URL (legacy)
OLLAMA_URL = os.environ.get(
    "TAILOR_LMSTUDIO_URL",
    os.environ.get("TAILOR_OLLAMA_URL", "http://localhost:1234/v1/chat/completions"),
)
OLLAMA_MODELS_URL = os.environ.get(
    "TAILOR_LMSTUDIO_MODELS_URL",
    os.environ.get("TAILOR_OLLAMA_MODELS_URL", "http://localhost:1234/v1/models"),
)
# Optional explicit model override:
# - TAILOR_LMSTUDIO_MODEL (preferred)
# - TAILOR_OLLAMA_MODEL (legacy)
# Use "default" to auto-pick the first model returned by /v1/models.
OLLAMA_MODEL = os.environ.get(
    "TAILOR_LMSTUDIO_MODEL",
    os.environ.get("TAILOR_OLLAMA_MODEL", "default"),
)
OLLAMA_TIMEOUT = 300  # seconds per LLM call
LOCK_TIMEOUT = 300  # seconds to wait for file lock (prevents concurrent LLM access)

# ── Validation thresholds ──────────────────────────────────────────────
# These control the hard gates in validator.py. Adjust based on your model's output.
# Run `python -m tailor validate <output_dir>` to test thresholds on existing output.

RESUME_BULLET_COUNT = 14  # 6 (UCOP) + 5 (GWR) + 3 (Simple.biz) — default target
RESUME_CHAR_TOLERANCE = 0.20  # ±20% body text vs baseline
COVER_CHAR_TOLERANCE = 0.15  # ±15% body text vs baseline
MAX_RETRIES = 3  # full pipeline retries (strategy + draft + QA) per document

RESUME_TARGET_PAGES = 1
RESUME_MIN_FILL_RATIO = 0.85  # page 1 must be ≥85% filled vertically
RESUME_COMPACT_MODE_ENABLED = True
RESUME_FIT_MAX_STAGES = 3
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
