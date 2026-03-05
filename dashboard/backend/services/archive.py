"""Tailoring archive service — snapshot packages + config into SQLite archive DB."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Config — same paths as app.py
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent  # services/
_REPO_ROOT = _HERE.parent.parent.parent  # dashboard/backend/services -> dashboard/backend -> dashboard -> repo root
_TAILORING_ROOT = _REPO_ROOT / "tailoring"
_TAILORING_OUTPUT_DIR = _TAILORING_ROOT / "output"
_ARCHIVE_DB = Path.home() / ".local" / "share" / "job_scraper" / "tailoring_archive.db"

_PROMPT_NAMES = [
    "_STYLE_GUARDRAILS",
    "_RESUME_STRATEGY_SYSTEM",
    "_RESUME_DRAFT_SYSTEM",
    "_RESUME_QA_SYSTEM",
    "_COVER_STRATEGY_SYSTEM",
    "_COVER_DRAFT_SYSTEM",
    "_COVER_QA_SYSTEM",
]

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    package_count INTEGER NOT NULL,
    config_snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS archived_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archive_id INTEGER NOT NULL REFERENCES archives(id),
    slug TEXT NOT NULL,
    meta TEXT,
    analysis TEXT,
    resume_strategy TEXT,
    cover_strategy TEXT,
    resume_tex TEXT,
    cover_tex TEXT,
    resume_pdf BLOB,
    cover_pdf BLOB,
    llm_trace TEXT,
    UNIQUE(archive_id, slug)
);
"""


def _get_archive_db() -> sqlite3.Connection:
    _ARCHIVE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_ARCHIVE_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _read_text(p: Path) -> str | None:
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(p: Path) -> bytes | None:
    if not p.exists():
        return None
    try:
        return p.read_bytes()
    except Exception:
        return None


def _snapshot_configs() -> dict:
    snapshot: dict = {}

    # skills.json
    skills_path = _TAILORING_ROOT / "skills.json"
    raw = _read_text(skills_path)
    snapshot["skills_json"] = json.loads(raw) if raw else None

    # soul.md
    snapshot["soul_md"] = _read_text(_TAILORING_ROOT / "soul.md")

    # baselines
    snapshot["baseline_resume_tex"] = _read_text(
        _TAILORING_ROOT / "Baseline-Dox" / "Conner_Jordan_Software_Engineer" / "Conner_Jordan_Resume.tex"
    )
    snapshot["baseline_cover_tex"] = _read_text(
        _TAILORING_ROOT / "Baseline-Dox" / "Conner_Jordan_Cover_letter" / "Conner_Jordan_Cover_Letter.tex"
    )

    # writer.py prompt constants
    try:
        from tailor import writer  # type: ignore
        prompts = {}
        for name in _PROMPT_NAMES:
            prompts[name] = getattr(writer, name, None)
        snapshot["prompts"] = prompts
    except Exception:
        snapshot["prompts"] = None

    return snapshot


def _is_complete_package(d: Path) -> bool:
    """A package is complete if it has meta.json and at least one PDF."""
    if not (d / "meta.json").exists():
        return False
    return (d / "Conner_Jordan_Resume.pdf").exists() or (d / "Conner_Jordan_Cover_Letter.pdf").exists()


async def archive_create(body: dict = Body(...)) -> JSONResponse:
    tag = (body.get("tag") or "").strip()
    if not tag:
        return JSONResponse({"ok": False, "error": "Tag is required"}, status_code=400)

    conn = _get_archive_db()
    try:
        # Check for duplicate tag
        if conn.execute("SELECT 1 FROM archives WHERE tag = ?", (tag,)).fetchone():
            return JSONResponse({"ok": False, "error": f"Archive tag '{tag}' already exists"}, status_code=409)

        config_snapshot = _snapshot_configs()

        # Find complete packages
        packages = []
        if _TAILORING_OUTPUT_DIR.exists():
            for d in sorted(_TAILORING_OUTPUT_DIR.iterdir()):
                if not d.is_dir() or d.name.startswith("_"):
                    continue
                if _is_complete_package(d):
                    packages.append(d)

        if not packages:
            return JSONResponse({"ok": False, "error": "No complete packages to archive"}, status_code=400)

        # Insert archive row
        cur = conn.execute(
            "INSERT INTO archives (tag, created_at, package_count, config_snapshot) VALUES (?, ?, ?, ?)",
            (tag, datetime.now(timezone.utc).isoformat(), len(packages), json.dumps(config_snapshot)),
        )
        archive_id = cur.lastrowid

        # Insert each package
        for d in packages:
            conn.execute(
                """INSERT INTO archived_packages
                   (archive_id, slug, meta, analysis, resume_strategy, cover_strategy,
                    resume_tex, cover_tex, resume_pdf, cover_pdf, llm_trace)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    archive_id,
                    d.name,
                    _read_text(d / "meta.json"),
                    _read_text(d / "analysis.json"),
                    _read_text(d / "resume_strategy.json"),
                    _read_text(d / "cover_strategy.json"),
                    _read_text(d / "Conner_Jordan_Resume.tex"),
                    _read_text(d / "Conner_Jordan_Cover_Letter.tex"),
                    _read_bytes(d / "Conner_Jordan_Resume.pdf"),
                    _read_bytes(d / "Conner_Jordan_Cover_Letter.pdf"),
                    _read_text(d / "llm_trace.jsonl"),
                ),
            )

        conn.commit()
        return JSONResponse({
            "ok": True,
            "id": archive_id,
            "tag": tag,
            "package_count": len(packages),
            "config_snapshot_keys": list(config_snapshot.keys()),
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        conn.close()


async def archive_list() -> JSONResponse:
    conn = _get_archive_db()
    try:
        rows = conn.execute(
            "SELECT id, tag, created_at, package_count FROM archives ORDER BY id DESC"
        ).fetchall()
        return JSONResponse({"archives": [dict(r) for r in rows]})
    finally:
        conn.close()


async def pipeline_packages() -> JSONResponse:
    """Return all archived packages across all archives for the pipeline inspector."""
    conn = _get_archive_db()
    try:
        rows = conn.execute(
            """SELECT ap.archive_id, ap.slug, ap.meta, a.tag, a.created_at as archive_created_at
               FROM archived_packages ap
               JOIN archives a ON a.id = ap.archive_id
               ORDER BY ap.archive_id DESC, ap.slug""",
        ).fetchall()
        items = []
        for r in rows:
            meta = None
            try:
                meta = json.loads(r["meta"]) if r["meta"] else None
            except Exception:
                pass
            items.append({
                "archive_id": r["archive_id"],
                "archive_tag": r["tag"],
                "archive_created_at": r["archive_created_at"],
                "slug": r["slug"],
                "meta": meta,
            })
        return JSONResponse({"packages": items})
    finally:
        conn.close()


async def pipeline_trace(archive_id: int, slug: str) -> JSONResponse:
    """Return parsed LLM trace for a single archived package."""
    conn = _get_archive_db()
    try:
        row = conn.execute(
            "SELECT llm_trace, meta, analysis, resume_strategy, cover_strategy FROM archived_packages WHERE archive_id = ? AND slug = ?",
            (archive_id, slug),
        ).fetchone()
        if not row:
            return JSONResponse({"ok": False, "error": "Package not found"}, status_code=404)

        events: list[dict] = []
        if row["llm_trace"]:
            for line in row["llm_trace"].strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

        def _parse_safe(text: str | None) -> dict | None:
            if not text:
                return None
            try:
                return json.loads(text)
            except Exception:
                return None

        return JSONResponse({
            "archive_id": archive_id,
            "slug": slug,
            "meta": _parse_safe(row["meta"]),
            "analysis": _parse_safe(row["analysis"]),
            "resume_strategy": _parse_safe(row["resume_strategy"]),
            "cover_strategy": _parse_safe(row["cover_strategy"]),
            "events": events,
        })
    finally:
        conn.close()


async def archive_detail(archive_id: int) -> JSONResponse:
    conn = _get_archive_db()
    try:
        row = conn.execute(
            "SELECT id, tag, created_at, package_count, config_snapshot FROM archives WHERE id = ?",
            (archive_id,),
        ).fetchone()
        if not row:
            return JSONResponse({"ok": False, "error": "Archive not found"}, status_code=404)

        archive = dict(row)
        try:
            archive["config_snapshot"] = json.loads(archive["config_snapshot"])
        except Exception:
            pass

        pkgs = conn.execute(
            "SELECT slug, meta FROM archived_packages WHERE archive_id = ? ORDER BY slug",
            (archive_id,),
        ).fetchall()
        package_list = []
        for p in pkgs:
            entry = {"slug": p["slug"]}
            try:
                entry["meta"] = json.loads(p["meta"]) if p["meta"] else None
            except Exception:
                entry["meta"] = None
            package_list.append(entry)

        archive["packages"] = package_list
        return JSONResponse(archive)
    finally:
        conn.close()
