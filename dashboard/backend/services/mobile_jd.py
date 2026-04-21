"""OCR mobile JD screenshots via macOS Vision framework and insert into DB."""

from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import Vision
from Cocoa import NSURL
from CoreFoundation import CFRunLoopGetCurrent, CFRunLoopRunInMode, kCFRunLoopDefaultMode
from services.audit import log_state_change

MOBILE_JD_DIR = Path(__file__).resolve().parents[3] / "tailoring" / "mobile-jd"


def ocr_image(path: Path) -> str:
    """Run macOS Vision OCR on a single image file. Returns recognised text."""
    url = NSURL.fileURLWithPath_(str(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    success, error = handler.performRequests_error_([request], None)
    if not success:
        raise RuntimeError(f"Vision OCR failed on {path}: {error}")
    lines: list[str] = []
    for obs in request.results():
        candidate = obs.topCandidates_(1)
        if candidate:
            lines.append(candidate[0].string())
    return "\n".join(lines)


def _natural_sort_key(p: Path):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", p.name)]


def parse_folder_name(name: str) -> tuple[str, str]:
    """Split 'Company - Title' into (company, title). Falls back gracefully."""
    if " - " in name:
        parts = name.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", name.strip()


def scan_and_process(db_path: str | None = None) -> dict:
    """Scan MOBILE_JD_DIR for pending folders, OCR, insert into DB."""
    if not MOBILE_JD_DIR.exists():
        return {"processed": 0, "results": [], "error": "mobile-jd directory not found"}

    if db_path is None:
        import app as _app
        db_path = _app.DB_PATH

    llm_runtime = None
    model_id = None
    try:
        from services.tailoring import _ensure_results_approved_jd_column, _polish_job_description, _resolve_active_llm_runtime
        try:
            llm_runtime, model_id = _resolve_active_llm_runtime()
        except Exception:
            llm_runtime = None
            model_id = None
    except Exception:
        _ensure_results_approved_jd_column = None
        _polish_job_description = None

    results = []
    for entry in sorted(MOBILE_JD_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_done ", ".")):
            continue

        images = sorted(
            [f for f in entry.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")],
            key=_natural_sort_key,
        )
        if not images:
            continue

        company, title = parse_folder_name(entry.name)

        # OCR all images and concatenate
        texts: list[str] = []
        for img in images:
            try:
                txt = ocr_image(img)
                if txt.strip():
                    texts.append(txt)
            except Exception as e:
                texts.append(f"[OCR error: {e}]")

        jd_text = "\n\n".join(texts).strip()
        if not jd_text:
            continue

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"mobile://ingest/{int(time.time())}-{os.urandom(4).hex()}"
        req_summary = None
        approved_jd_text = jd_text
        polished_with_llm = False
        if _polish_job_description is not None:
            req_summary, approved_jd_text, polished_with_llm = _polish_job_description(
                jd_text,
                title,
                url,
                llm_runtime,
                model_id,
            )
        snippet = (req_summary or jd_text[:200]).strip() or None
        approved_jd_text = (approved_jd_text or jd_text).strip() or None

        # Insert into DB
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            if _ensure_results_approved_jd_column is not None:
                _ensure_results_approved_jd_column(conn)
            cur = conn.execute(
                """INSERT INTO jobs
                   (url, title, company, board, seniority, experience_years, salary_k, score, status,
                    snippet, query, source, jd_text, approved_jd_text, filter_verdicts, run_id, created_at, updated_at)
                   VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, 'qa_approved', ?, 'mobile-ingest', 'mobile', ?, ?, NULL, 'mobile-ingest', ?, ?)
                   ON CONFLICT(url) DO NOTHING""",
                (url, title, company, snippet, jd_text, approved_jd_text, now, now),
            )
            job_id = cur.lastrowid if cur.rowcount > 0 else None
            if job_id is not None:
                log_state_change(
                    conn,
                    job_id=job_id,
                    job_url=url,
                    old_state=None,
                    new_state="qa_approved",
                    action="ingest_mobile",
                    detail={
                        "query": "mobile-ingest",
                        "folder": entry.name,
                        "auto_approved": True,
                        "polished_with_llm": polished_with_llm,
                    },
                )
            conn.commit()
        except Exception as e:
            results.append({"folder": entry.name, "ok": False, "error": str(e)})
            continue
        finally:
            if conn is not None:
                conn.close()

        # Rename folder to mark as done
        done_name = entry.parent / f"_done {entry.name}"
        try:
            entry.rename(done_name)
        except OSError:
            pass

        results.append({
            "folder": entry.name,
            "ok": True,
            "job_id": job_id,
            "title": title,
            "company": company,
            "images": len(images),
            "jd_chars": len(jd_text),
            "auto_approved": True,
            "polished_with_llm": polished_with_llm,
        })

    return {"processed": len(results), "results": results}
