---
tags: [data_correlation, cloud_security, internal_tooling]
company_types: [large_tech, security_focused]
skill_categories: [Security Data Engineering, Cloud Security]
keywords: [correlation, reconciliation, asset, inventory, Flask, Docker, ECS, endpoint, vulnerability]
---
<!--
VIGNETTE TEMPLATE — use this file as the canonical example when adding new vignettes.

FRONTMATTER FIELDS
──────────────────
tags:             Free-form labels (unused by scoring — for human navigation).
company_types:    Which company archetypes this story resonates with. Must match values
                  the analyzer emits: large_tech | security_focused | startup |
                  enterprise_regulated | platform_devops | other.
                  Scoring: +2 if the target company_type appears here.
skill_categories: Must match 'name' values in skills.json → core_skills[].name exactly.
                  Scoring: +3 per overlap with analysis matched_category.
keywords:         Individual skills/tools/concepts. Match against analysis matched_skills.
                  Scoring: +1 per keyword found in matched_skills.

BODY GUIDELINES
───────────────
  - Structure: problem → approach → concrete outcome
  - Length: 150-350 chars ideal; vignette budget per stage is ~1200-1500 chars total,
    so 4-5 vignettes can fit if each is concise
  - Tone: plain past-tense technical narrative. No buzzwords, no hedging.
  - Metrics: include real numbers if grounded (500 assets, 7000 endpoints, etc.)
  - The LLM should reshape this — write for comprehension, not for verbatim copying

TO ADD A NEW VIGNETTE
─────────────────────
  cp coraline.md <new_name>.md
  Edit frontmatter + body. File is auto-discovered on next pipeline run.
  No registration required.
-->
The University of California had five separate data sources for endpoint and vulnerability information — and none of them agreed. Asset counts drifted, ownership records conflicted, and remediation couldn't target what it couldn't see. I built Coraline, a containerized Flask/React service deployed on AWS ECS, that ingests all five feeds and reconciles them using hierarchical confidence matching. It resolved 500+ drifted asset records and gave the security team a single, trustworthy inventory across 7,000+ endpoints. The lesson: I solve problems by building the correlation layer nobody else wants to build.
