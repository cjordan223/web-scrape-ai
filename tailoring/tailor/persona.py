"""Persona memory hierarchy — load, score, and inject persona content per pipeline stage.

Replaces monolithic soul.md injection with tagged vignette selection based on
analysis output (company_type, matched_category, matched_skills).
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfg

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Vignette:
    path: Path
    body: str
    tags: list[str] = field(default_factory=list)
    company_types: list[str] = field(default_factory=list)
    skill_categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-subset frontmatter delimited by ---. Returns (meta, body).

    HTML comments (<!-- ... -->) before the opening --- are stripped so
    vignette files can carry documentation comments without breaking parsing.
    """
    # Strip leading HTML comments before the frontmatter block
    text = re.sub(r"\A(\s*<!--.*?-->\s*)+", "", text, flags=re.DOTALL)
    m = re.match(r"\A---\s*\n(.*?\n)---\s*\n(.*)\Z", text, re.DOTALL)
    if not m:
        return {}, text.strip()

    raw = m.group(1)
    body = m.group(2).strip()
    meta: dict = {}

    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        # Parse bracket lists: [a, b, c]
        bracket = re.match(r"^\[(.*)\]$", v)
        if bracket:
            items = [x.strip().strip("'\"") for x in bracket.group(1).split(",") if x.strip()]
            meta[k] = items
        else:
            meta[k] = v

    return meta, body


_STAGE_BUDGETS: dict[tuple[str, str], tuple[int, bool]] = {
    ("strategy", "cover"): (1500, True),
    ("strategy", "resume"): (1500, False),
    ("draft", "cover"): (1500, True),
    ("draft", "resume"): (1500, False),
}


def _stage_budget(stage: str, doc_type: str) -> tuple[int, bool]:
    """Return (budget_chars, diverse) for a given pipeline stage + doc_type."""
    return _STAGE_BUDGETS.get((stage, doc_type), (1500, False))


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_RE.findall(value.lower()))


def _keyword_matches(keyword: str, matched_skills: set[str]) -> bool:
    """Match exact skills plus phrase/token variants.

    Analyzer output often contains normalized skill names ("AWS ECS deployments")
    while vignette keywords are shorter ("ECS"). A small token-overlap check keeps
    scoring robust without making every generic one-word keyword match everything.
    """
    kw = keyword.lower().strip()
    if not kw:
        return False
    kw_tokens = _tokens(kw)
    if not kw_tokens:
        return False
    for skill in matched_skills:
        skill_norm = skill.lower().strip()
        if kw == skill_norm or kw in skill_norm or skill_norm in kw:
            return True
        skill_tokens = _tokens(skill_norm)
        if not skill_tokens:
            continue
        if len(kw_tokens) == 1:
            if kw_tokens <= skill_tokens:
                return True
            continue
        overlap = len(kw_tokens & skill_tokens)
        if overlap / len(kw_tokens | skill_tokens) >= 0.5 or overlap == len(kw_tokens):
            return True
    return False


class PersonaStore:
    """Loads persona/ directory, scores vignettes, assembles per-stage persona text."""

    def __init__(self, persona_dir: Path):
        self._dir = persona_dir
        self._identity = ""
        self._contributions = ""
        self._voice = ""
        self._evidence = ""
        self._interests = ""
        self._motivation = ""
        self._vignettes: list[Vignette] = []
        self._selection_cache: dict[tuple[str, int, bool], tuple[list[Vignette], dict]] = {}
        self._load()

    def _load(self):
        for name in ("identity", "contributions", "voice", "evidence", "interests", "motivation"):
            p = self._dir / f"{name}.md"
            if p.exists():
                _, body = _parse_frontmatter(p.read_text())
                setattr(self, f"_{name}", body)

        vig_dir = self._dir / "vignettes"
        if vig_dir.is_dir():
            for f in sorted(vig_dir.glob("*.md")):
                meta, body = _parse_frontmatter(f.read_text())
                self._vignettes.append(Vignette(
                    path=f,
                    body=body,
                    tags=meta.get("tags", []),
                    company_types=meta.get("company_types", []),
                    skill_categories=meta.get("skill_categories", []),
                    keywords=meta.get("keywords", []),
                ))
        logger.info("Persona loaded: %d vignettes from %s", len(self._vignettes), self._dir)

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def contributions(self) -> str:
        return self._contributions

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def evidence(self) -> str:
        return self._evidence

    def select_vignettes(
        self,
        analysis: dict,
        budget_chars: int,
        *,
        diverse: bool = False,
    ) -> list[Vignette]:
        """Score and select vignettes that fit within budget_chars.

        When ``diverse`` is true, the selector caps each ``skill_category`` at one
        vignette so a single project area cannot anchor the entire output. This is
        used for cover letters, where breadth across distinct experiences matters
        more than piling on multiple stories from the same domain.
        """
        selected, _meta = self._select_with_meta(analysis, budget_chars, diverse=diverse)
        return selected

    def _select_with_meta(
        self,
        analysis: dict,
        budget_chars: int,
        *,
        diverse: bool = False,
    ) -> tuple[list[Vignette], dict]:
        """Same scoring as :meth:`select_vignettes` but also returns structured
        metadata describing which candidates were considered, which were picked,
        and why. Powers the ``vignette_selection`` trace event.
        """
        analysis_key = json.dumps(analysis, sort_keys=True, default=str)
        cache_key = (analysis_key, budget_chars, diverse)
        cached = self._selection_cache.get(cache_key)
        if cached:
            selected, meta = cached
            return list(selected), deepcopy(meta)

        company_type = analysis.get("company_context", {}).get("company_type", "")
        matched_categories: set[str] = set()
        matched_skills: set[str] = set()
        for req in analysis.get("requirements", []):
            cat = req.get("matched_category", "")
            if cat:
                matched_categories.add(cat.lower())
            for sk in req.get("matched_skills", []):
                matched_skills.add(sk.lower())

        scored: list[tuple[int, float, Vignette]] = []
        for v in self._vignettes:
            score = 0
            for sc in v.skill_categories:
                if sc.lower() in matched_categories:
                    score += 3
            if company_type and company_type in v.company_types:
                score += 2
            for kw in v.keywords:
                if _keyword_matches(kw, matched_skills):
                    score += 1
            if score > 0:
                scored.append((score, score / max(1, len(v.body)), v))

        scored.sort(key=lambda x: (-x[0], -x[1], len(x[2].body), x[2].path.stem))

        selected: list[Vignette] = []
        skipped: list[tuple[Vignette, int, float, str]] = []
        used = 0
        used_primary_categories: set[str] = set()
        for score, density, v in scored:
            if used + len(v.body) > budget_chars:
                skipped.append((v, score, density, "budget_exceeded"))
                continue
            if diverse:
                primary_category = v.skill_categories[0].lower() if v.skill_categories else ""
                if primary_category and primary_category in used_primary_categories:
                    skipped.append((v, score, density, "diverse_primary_category_collision"))
                    continue
                if primary_category:
                    used_primary_categories.add(primary_category)
            selected.append(v)
            used += len(v.body)

        selected_stems = {v.path.stem for v in selected}
        score_by_stem = {v.path.stem: score for score, _density, v in scored}
        density_by_stem = {v.path.stem: density for _score, density, v in scored}

        meta = {
            "budget_chars": budget_chars,
            "diverse": diverse,
            "budget_used": used,
            "budget_remaining": max(0, budget_chars - used),
            "matched_categories": sorted(matched_categories),
            "matched_skills_count": len(matched_skills),
            "company_type": company_type,
            "candidates_total": len(self._vignettes),
            "candidates_scored": len(scored),
            "selected": [
                {
                    "name": v.path.stem,
                    "score": score_by_stem.get(v.path.stem, 0),
                    "score_density": round(density_by_stem.get(v.path.stem, 0.0), 5),
                    "chars": len(v.body),
                    "skill_categories": list(v.skill_categories),
                    "primary_category": v.skill_categories[0] if v.skill_categories else None,
                }
                for v in selected
            ],
            "skipped": [
                {
                    "name": v.path.stem,
                    "score": score,
                    "score_density": round(density, 5),
                    "chars": len(v.body),
                    "reason": reason,
                }
                for v, score, density, reason in skipped
            ],
            "unscored": [
                v.path.stem for v in self._vignettes
                if v.path.stem not in score_by_stem and v.path.stem not in selected_stems
            ],
        }
        self._selection_cache[cache_key] = (list(selected), deepcopy(meta))
        return selected, meta

    def explain_selection(
        self,
        analysis: dict,
        doc_type: str,
        stage: str,
    ) -> dict:
        """Public hook: compute selection metadata for a given stage/doc.

        Returns the same shape logged by the ``vignette_selection`` trace event
        so callers can emit it without re-implementing stage budget logic.
        """
        budget, diverse = _stage_budget(stage, doc_type)
        _selected, meta = self._select_with_meta(analysis, budget, diverse=diverse)
        meta["doc_type"] = doc_type
        meta["stage"] = stage
        return meta

    @property
    def interests(self) -> str:
        return self._interests

    def for_analysis(self) -> str:
        """Identity + contributions + interests for the analysis stage."""
        parts = [self._identity, self._contributions, self._interests]
        return "\n\n".join(p for p in parts if p)

    def _render_vignettes(self, vigs: list[Vignette]) -> str:
        """Render selected vignettes with explicit per-vignette source headers.

        The header uses the filename stem (e.g. `coraline`, `rag_chatbot`) so the
        LLM can see which project each narrative describes and does not braid
        details from adjacent vignettes into a single story.
        """
        if not vigs:
            return ""
        rendered = []
        for v in vigs:
            rendered.append(f"### Source project: {v.path.stem}\n{v.body}")
        return "## Narrative Vignettes (each ### block is a discrete project — do not merge details across blocks)\n" + "\n\n".join(rendered)

    def for_strategy(self, analysis: dict, doc_type: str) -> str:
        """Persona text for strategy stage."""
        budget, diverse = _stage_budget("strategy", doc_type)
        vigs = self.select_vignettes(analysis, budget, diverse=diverse)
        rendered = self._render_vignettes(vigs)
        if doc_type == "cover":
            parts = [self._identity]
            if rendered:
                parts.append(rendered)
            parts.append(self._voice)
            parts.append(self._evidence)
            if self._motivation:
                parts.append(self._motivation)
            return "\n\n".join(p for p in parts if p)
        parts = [self._identity]
        if rendered:
            parts.append(rendered)
        parts.append(self._contributions)
        return "\n\n".join(p for p in parts if p)

    def for_draft(self, analysis: dict, doc_type: str) -> str:
        """Persona text for draft stage."""
        budget, diverse = _stage_budget("draft", doc_type)
        vigs = self.select_vignettes(analysis, budget, diverse=diverse)
        rendered = self._render_vignettes(vigs)
        if doc_type == "cover":
            parts = [self._identity]
            if rendered:
                parts.append(rendered)
            parts.append(self._voice)
            if self._motivation:
                parts.append(self._motivation)
            if self._interests:
                parts.append(self._interests)
            return "\n\n".join(p for p in parts if p)
        parts = [self._identity]
        if rendered:
            parts.append(rendered)
        return "\n\n".join(p for p in parts if p)

    def for_qa(self, doc_type: str) -> str:
        """Minimal persona for QA stage — voice anti-patterns for cover, empty for resume."""
        if doc_type == "cover":
            # Extract just the anti-patterns section from voice
            lines = self._voice.splitlines()
            anti = []
            in_anti = False
            for line in lines:
                if "Anti-patterns" in line:
                    in_anti = True
                    anti.append(line)
                elif in_anti:
                    if line.startswith("## "):
                        break
                    anti.append(line)
            return "\n".join(anti) if anti else ""
        return ""


# ── Module-level singleton ────────────────────────────────────────────

_store: PersonaStore | None = None


def _fallback_from_soul() -> PersonaStore | None:
    """If persona/ doesn't exist, create a minimal store from soul.md."""
    if not cfg.SOUL_MD.exists():
        return None

    # Create a temporary in-memory store that just returns soul.md content
    class _SoulFallback(PersonaStore):
        def __init__(self, soul_text: str):
            self._dir = cfg.SOUL_MD.parent
            self._identity = soul_text[:4000]
            self._contributions = ""
            self._voice = ""
            self._evidence = ""
            self._interests = ""
            self._motivation = ""
            self._vignettes = []
            self._selection_cache = {}

        def for_analysis(self) -> str:
            return self._identity

        def for_strategy(self, analysis: dict, doc_type: str) -> str:
            return self._identity

        def for_draft(self, analysis: dict, doc_type: str) -> str:
            return self._identity

        def for_qa(self, doc_type: str) -> str:
            return ""

    logger.info("persona/ directory not found, falling back to soul.md")
    return _SoulFallback(cfg.SOUL_MD.read_text())


def get_store() -> PersonaStore:
    """Return the module-level PersonaStore singleton."""
    global _store
    if _store is None:
        persona_dir = cfg.PERSONA_DIR
        if persona_dir.is_dir():
            _store = PersonaStore(persona_dir)
        else:
            fallback = _fallback_from_soul()
            if fallback:
                _store = fallback
            else:
                raise FileNotFoundError(
                    f"Neither {persona_dir} nor {cfg.SOUL_MD} found"
                )
    return _store
