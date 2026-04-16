#!/usr/bin/env python3
"""Benchmark Gemma 4 31B vs Qwen 3 30B on tailoring pipeline tasks.

Tests three pipeline-critical capabilities:
  1. JSON structured output (analysis phase) — can the model return valid JSON?
  2. LaTeX generation (draft phase) — can it produce compilable LaTeX?
  3. Strategy planning (strategy phase) — can it follow complex structured instructions?

Each test runs on both models, measures time, and checks output quality.
"""

import json
import re
import sys
import time

import requests

OLLAMA_URL = "http://localhost:11434"
MODELS = ["qwen3:30b", "gemma4:31b-it-q8_0"]

# Synthetic JD for testing — realistic enough to exercise the prompts
SAMPLE_JD = """\
Title: Senior Software Engineer, Platform Security
Company: Acme Cloud Inc.

We're looking for a Senior Software Engineer to join our Platform Security team.
You'll build and maintain security tooling that protects our cloud infrastructure.

Requirements:
- 3+ years of experience with Python and Go
- Experience with container security (Docker, Kubernetes)
- Familiarity with CI/CD pipelines (GitHub Actions, Jenkins)
- Knowledge of cloud platforms (AWS, GCP)
- Experience building internal security tools or dashboards
- Understanding of vulnerability management and remediation workflows
- Strong communication skills and ability to work cross-functionally
- Bachelor's degree in Computer Science or equivalent experience
"""


def chat(model: str, system: str, user: str, json_mode: bool = False) -> tuple[str, float]:
    """Send a chat to Ollama native API. Returns (content, duration_seconds)."""
    base = OLLAMA_URL
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 16384},
    }
    if json_mode:
        payload["format"] = "json"

    start = time.monotonic()
    resp = requests.post(f"{base}/api/chat", json=payload, timeout=(30, 600))
    elapsed = time.monotonic() - start
    resp.raise_for_status()

    content = resp.json()["message"].get("content", "")
    # Strip think tags (Qwen 3)
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    if "</think>" in content:
        content = content.split("</think>", 1)[1]
    return content.strip(), elapsed


def extract_json_from(text: str) -> dict | None:
    """Try to parse first JSON object from text."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    decoder = json.JSONDecoder()
    for s in starts:
        try:
            obj, _ = decoder.raw_decode(text[s:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def test_json_analysis(model: str) -> dict:
    """Test 1: JSON structured output (analysis phase)."""
    system = """\
You are a job application strategist. Analyze the job description and produce a structured mapping.

Respond with ONLY a JSON object:
{
  "company_name": "string",
  "role_title": "string",
  "company_context": {
    "what_they_build": "1-2 sentences",
    "engineering_challenges": "what this team cares about",
    "company_type": "large_tech|security_focused|startup|enterprise_regulated|platform_devops|other"
  },
  "requirements": [
    {
      "jd_requirement": "what the JD asks for",
      "matched_skills": ["skill1", "skill2"],
      "priority": "high|medium|low"
    }
  ],
  "summary_angle": "1-sentence guidance on how to angle the professional summary"
}"""

    content, elapsed = chat(model, system, f"## Job Description\n{SAMPLE_JD}", json_mode=True)
    parsed = extract_json_from(content)

    result = {
        "test": "json_analysis",
        "model": model,
        "elapsed_s": round(elapsed, 1),
        "output_chars": len(content),
        "json_valid": parsed is not None,
        "has_requirements": False,
        "requirement_count": 0,
        "has_company_context": False,
        "priorities_valid": False,
    }

    if parsed:
        reqs = parsed.get("requirements", [])
        result["has_requirements"] = len(reqs) > 0
        result["requirement_count"] = len(reqs)
        result["has_company_context"] = isinstance(parsed.get("company_context"), dict)
        valid_priorities = {"high", "medium", "low"}
        result["priorities_valid"] = all(
            r.get("priority") in valid_priorities for r in reqs if isinstance(r, dict)
        )

    return result


def test_latex_generation(model: str) -> dict:
    """Test 2: LaTeX generation (draft phase)."""
    system = r"""\
You are a LaTeX resume expert. Generate a minimal but complete LaTeX resume document.

Output requirements:
- Return ONLY the complete .tex file content. No explanations, no markdown fences.
- Must include \documentclass, \begin{document}, \end{document}
- Include a Professional Summary section and a Work Experience section
- Use \section{} for section headers
- Must compile with pdflatex"""

    user = f"""\
Generate a tailored resume for this job. Keep it minimal but structurally complete.

{SAMPLE_JD}

Candidate: Software engineer with 5 years experience in Python, security tooling, and cloud infrastructure.
Previous roles at University of California (security engineer) and Great Wolf Resorts (full-stack dev)."""

    content, elapsed = chat(model, system, user)

    has_documentclass = r"\documentclass" in content
    has_begin = r"\begin{document}" in content
    has_end = r"\end{document}" in content
    has_section = r"\section" in content
    # Check for common LaTeX errors
    has_raw_ampersand = bool(re.search(r"(?<!\\)&", content)) if has_begin else False
    has_raw_underscore = bool(re.search(r"(?<!\\)_(?!{)", content)) if has_begin else False

    m = re.search(r"(\\documentclass.*?\\end\{document\})", content, re.DOTALL)
    extractable = m is not None

    return {
        "test": "latex_generation",
        "model": model,
        "elapsed_s": round(elapsed, 1),
        "output_chars": len(content),
        "has_documentclass": has_documentclass,
        "has_begin_end": has_begin and has_end,
        "has_sections": has_section,
        "extractable": extractable,
        "no_raw_ampersand": not has_raw_ampersand,
        "no_raw_underscore": not has_raw_underscore,
    }


def test_strategy_json(model: str) -> dict:
    """Test 3: Complex structured strategy (strategy phase)."""
    system = """\
You are a resume tailoring strategist. Build a precise writing plan.

Return ONLY JSON:
{
  "summary_strategy": "one sentence describing summary angle",
  "skills_tailoring": {
    "Languages": "reordering guidance",
    "Security Tooling": "additions/reordering guidance",
    "Frameworks and Infrastructure": "guidance",
    "DevOps and CI/CD": "guidance",
    "Databases": "guidance"
  },
  "experience_rewrites": [
    {
      "company": "University of California",
      "bullet_rewrites": [
        {
          "baseline_topic": "which bullet to rewrite",
          "rewrite_angle": "how to reframe for JD",
          "jd_requirement_addressed": "which JD req"
        }
      ]
    },
    {
      "company": "Great Wolf Resorts",
      "bullet_rewrites": [...]
    }
  ],
  "risk_controls": ["anti-hallucination reminders"]
}"""

    content, elapsed = chat(model, system, f"## Job Description\n{SAMPLE_JD}", json_mode=True)
    parsed = extract_json_from(content)

    result = {
        "test": "strategy_json",
        "model": model,
        "elapsed_s": round(elapsed, 1),
        "output_chars": len(content),
        "json_valid": parsed is not None,
        "has_skills_tailoring": False,
        "has_experience_rewrites": False,
        "experience_count": 0,
        "has_risk_controls": False,
    }

    if parsed:
        st = parsed.get("skills_tailoring")
        result["has_skills_tailoring"] = isinstance(st, dict) and len(st) > 0
        er = parsed.get("experience_rewrites", [])
        result["has_experience_rewrites"] = isinstance(er, list) and len(er) > 0
        result["experience_count"] = len(er) if isinstance(er, list) else 0
        result["has_risk_controls"] = isinstance(parsed.get("risk_controls"), list)

    return result


def print_result(r: dict):
    """Pretty-print a single test result."""
    test = r.pop("test")
    model = r.pop("model")
    elapsed = r.pop("elapsed_s")
    chars = r.pop("output_chars")

    checks = {k: v for k, v in r.items() if isinstance(v, bool)}
    metrics = {k: v for k, v in r.items() if not isinstance(v, bool)}

    passed = sum(checks.values())
    total = len(checks)
    check_str = f"{passed}/{total} checks passed"

    print(f"  {test}: {elapsed}s, {chars} chars, {check_str}")
    for k, v in checks.items():
        mark = "+" if v else "X"
        print(f"    [{mark}] {k}")
    for k, v in metrics.items():
        print(f"    {k}: {v}")


def main():
    models = sys.argv[1:] if len(sys.argv) > 1 else MODELS
    tests = [test_json_analysis, test_latex_generation, test_strategy_json]

    for model in models:
        print(f"\n{'='*60}")
        print(f"MODEL: {model}")
        print(f"{'='*60}")
        for test_fn in tests:
            try:
                result = test_fn(model)
                print_result(result)
            except Exception as e:
                print(f"  {test_fn.__name__}: FAILED — {e}")
        print()


if __name__ == "__main__":
    main()
