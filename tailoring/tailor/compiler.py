"""Compile LaTeX files to PDF using pdflatex."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_pdflatex() -> str | None:
    """Resolve pdflatex path across common macOS/homebrew installs."""
    env_bin = os.environ.get("PDFLATEX_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.exists():
            return str(p)
        return env_bin
    return (
        shutil.which("pdflatex")
        or ("/Library/TeX/texbin/pdflatex" if Path("/Library/TeX/texbin/pdflatex").exists() else None)
        or ("/usr/texbin/pdflatex" if Path("/usr/texbin/pdflatex").exists() else None)
        or ("/opt/homebrew/bin/pdflatex" if Path("/opt/homebrew/bin/pdflatex").exists() else None)
    )


def compile_tex(tex_path: Path) -> Path | None:
    """Compile a .tex file to PDF. Returns PDF path on success, None on failure.

    Runs pdflatex twice (for references) in a temp directory, then copies
    the PDF back next to the .tex file.
    """
    if not tex_path.exists():
        logger.error("TeX file not found: %s", tex_path)
        return None

    pdflatex = _resolve_pdflatex()
    if not pdflatex:
        logger.error("pdflatex not found; set PDFLATEX_BIN or install TeX")
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Copy tex file to temp dir
        tmp_tex = tmp / tex_path.name
        shutil.copy2(tex_path, tmp_tex)

        # Run pdflatex twice
        for pass_num in (1, 2):
            result = subprocess.run(
                [pdflatex, "-interaction=nonstopmode", "-halt-on-error", tmp_tex.name],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.error(
                    "pdflatex pass %d failed for %s:\n%s",
                    pass_num, tex_path.name, result.stdout[-2000:]
                )
                return None

        # Copy PDF back
        pdf_name = tex_path.stem + ".pdf"
        tmp_pdf = tmp / pdf_name
        if not tmp_pdf.exists():
            logger.error("PDF not produced: %s", tmp_pdf)
            return None

        out_pdf = tex_path.parent / pdf_name
        shutil.copy2(tmp_pdf, out_pdf)
        logger.info("Compiled %s -> %s", tex_path.name, out_pdf)
        return out_pdf
