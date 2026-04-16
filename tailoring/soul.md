# Candidate Persona Reference

<!--
╔══════════════════════════════════════════════════════════════════════════╗
║  MAINTENANCE GUIDE                                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

soul.md is the FALLBACK source. The pipeline reads from persona/ first.
This file is only used if persona/ doesn't exist (e.g., on a fresh clone).

WHAT LIVES WHERE
────────────────
  persona/identity.md       → name, profile, one-liner summary
  persona/contributions.md  → contribution patterns, what-I-bring
  persona/voice.md          → cover letter tone rules, anti-patterns, company-type adaptation
  persona/evidence.md       → bullet-point proof anchors
  persona/vignettes/*.md    → individual story vignettes with selection tags

TO ADD A NEW VIGNETTE
─────────────────────
  1. Create persona/vignettes/<slug>.md
  2. Add frontmatter with tags, company_types, skill_categories, keywords
     (copy any existing vignette as a template)
  3. Write the story body: problem → approach → outcome, ~150-300 chars
  4. That's it — persona.py auto-discovers files in persona/vignettes/

  Scoring: +3 per skill_categories match, +2 per company_types match,
           +1 per keywords match. Only score>0 vignettes are selected.
  Char budget per stage: ~1200-1500 chars for vignettes.

TO EDIT IDENTITY / VOICE / EVIDENCE
─────────────────────────────────────
  Edit the relevant persona/*.md file directly. No registration needed.
  Changes take effect on next pipeline run (no caching for persona content).

KEEP THIS FILE IN SYNC
───────────────────────
  If you update persona/, mirror major changes here so the fallback stays
  useful. Structure follows the same ## header sections below.
-->


## Identity

**Name:** Conner Jordan
**Primary Profile:** Full-Stack Software Engineer / Security Engineer / DevSecOps Engineer
**Core Orientation:** Builder-operator across full-stack development, security, infrastructure, and production systems
**Working Style:** Pragmatic, systems-minded, operationally reliable, documentation-first

---

## Who I Am (Concise)

I am a full-stack software engineer with deep security expertise who does my best work where the problems are messy, the constraints are real, and the solution needs to hold up in production. I turn ambiguity into a clear plan, then ship working software — whether that's a React dashboard, a Python backend, a security automation pipeline, or a containerized service on AWS.

I hold a CS degree in software engineering and have worked professionally as a web developer. I build across the entire stack daily, adapting to React, Vue, or whatever the current standard is. I am an AI-native developer — Claude Code, Cursor, Copilot, Codex, Gemini CLI, and other AI-integrated tools are part of my everyday production workflow, not experiments.

I am strongest at the intersection of:

- **Full-stack development (React, TypeScript, Python, Java, Node.js)**
- **Security engineering**
- **Application security (SAST/DAST/SCA, secure SDLC, pentesting)**
- **AI-native development and tooling**
- **Infrastructure and Linux systems**
- **Automation and DevOps**
- **System integration (SAML, REST APIs, multi-source data connectors)**
- **Threat hunting and incident response**
- **Cloud, hybrid, and containerized delivery**
- **Data integration and correlation**
- **Production reliability and operations**

---

## Narrative Vignettes

These are stories the LLM should draw from and reshape — not copy verbatim. Each has a problem, an approach, and a concrete outcome. Select and adapt the most relevant ones for each application.

### The Correlation Problem (UCOP — Coraline)
The University of California had five separate data sources for endpoint and vulnerability information — and none of them agreed. Asset counts drifted, ownership records conflicted, and remediation couldn't target what it couldn't see. I built Coraline — a full-stack React + Python application deployed as a containerized service on AWS ECS with PostgreSQL — that ingests all five feeds and reconciles them using hierarchical confidence matching. It resolved 500+ drifted asset records and gave the security team a single, trustworthy inventory across 7,000+ endpoints. Coraline is my flagship project: a production full-stack application that demonstrates React frontend development, Python backend engineering, AWS cloud deployment, database design, API integration, and data correlation — all in one system.

### Remediation at Scale (UCOP — Automation)
Patching 10,000+ macOS and Windows devices across the UC system meant dealing with inconsistent configurations, stale agents, and compliance deadlines that didn't wait. I built API-driven remediation automation — Python scripts that orchestrate CrowdStrike RTR and Defender actions, with runbooks so the ops team could execute without me. The approach was pragmatic: automate the 80% that's repetitive, document the 20% that needs judgment, and make the whole thing auditable.

### Zero-Day Hunting Under Pressure (UCOP — Threat Response)
When zero-day vulnerabilities hit before enterprise tooling had reliable coverage, I built custom threat-hunting scripts and deployed them across the organization to find exposure fast without creating new risk. That work required careful scoping, validation, and iteration: move quickly enough to respond to live threats, but cautiously enough that every script was safe to run at scale, explainable to operators, and adaptable as new indicators emerged.

### Governance Before It's Cool (UCOP — AI)
When the team started experimenting with LLM-based tooling, I built the governance framework before anyone asked for it. Established review standards, audit trails, and operational guardrails for AI-assisted security workflows. The point wasn't to slow adoption — it was to make adoption safe enough that leadership could say yes without risk.

### Fleet Reliability Under Pressure (GWR)
At Great Wolf Resorts, I managed endpoint operations across a hybrid Azure tenant — patching, BitLocker enforcement, configuration compliance, agent health monitoring. Built Python and PowerShell automation that handled the repetitive fleet work and freed the team to focus on incidents. Also built analytics tooling that turned noisy security logs into actionable reports leadership could actually use.

### Builder Instinct (Capstone — Phishing Detection)
Built a phishing detection system from scratch as a school capstone project — browser extension frontend, Python backend API, real-time URL analysis. It earned Most Innovative Project at the 2024 Capstone Festival. But the real point is: I see a security gap, I prototype a solution, and I ship it. Not a proposal deck — working code.

### RAG with Purpose (GWR — Security Chatbot)
Built an RAG-based security knowledge chatbot using LangChain and vector databases — not as a demo, but as internal tooling that reduced repeated questions to the security team. The implementation emphasized retrieval accuracy and source attribution, not flashy UX.

### AI-Native Development (Personal — JobForge)
Built JobForge, a full-stack job search and application automation platform: React + TypeScript SPA, FastAPI backend, SQLite persistence, LLM-powered analysis pipeline. The entire system was built using AI coding tools as daily production instruments — Claude Code, Cursor, Copilot, Codex, Gemini CLI, and others. This isn't dabbling; it's how I ship software every day. The same AI-native workflow extends across all my projects.

### Integration Engineering (UCOP — Multi-System Dashboard)
Integrated Rapid7, BigFix, Jamf, CrowdStrike, and Active Directory into a unified security dashboard through their respective APIs and SAML configurations. Designed data connectors, normalization layers, and reconciliation logic across systems that were never meant to talk to each other. This is deep integration work — not just REST calls, but understanding each system's data model and building the correlation layer between them.

---

## How I Contribute

### Core contribution pattern

I consistently contribute by:

- building automation that removes repetitive work
- improving visibility across fragmented systems
- reconciling inconsistent records into actionable data
- accelerating remediation workflows
- translating emerging threats into safe, organization-wide detection and response actions
- creating guardrails and documentation so delivery scales
- shipping tools that stay useful after launch

### What I bring to a team

#### Security Engineering
- I build and operate production security systems, not just prototypes.
- I focus on deployable controls and measurable risk reduction.
- I think in terms of remediation, reliability, and operational fit.

#### Threat Hunting and Incident Response
- I can turn rough threat intelligence into custom hunting logic when vendor coverage is incomplete.
- I balance fast response with high-confidence validation before deploying scripts broadly.
- I design detection and response tooling so operators can trust it under pressure.

#### Automation and DevSecOps
- I automate high-friction workflows with Python and PowerShell.
- I build CI/CD-oriented workflows and operational tooling.
- I care about repeatability, maintainability, and handoff quality.

#### Full-Stack Development
- I build production web applications across the entire stack — React/TypeScript frontends, Python/Java backends, SQL databases, cloud deployment.
- My personal portfolio, Coraline, and JobForge all demonstrate end-to-end full-stack delivery.
- I adapt to whatever framework the team uses — React, Vue, Next.js, Django, FastAPI, Spring Boot.

#### AI-Native Development
- I use AI coding tools (Claude Code, Cursor, Copilot, Codex, Gemini CLI) daily as production instruments, not experiments.
- I build with LLMs as first-class components — RAG pipelines, analysis engines, automated workflows.
- I understand both the development and governance sides of AI tooling.

#### Cloud / Platform
- I deliver containerized services and internal tools in cloud environments.
- I work at the intersection of infrastructure, security, and application engineering.
- I design with operational realities in mind (deployment, secrets, access, support).

#### System Integration
- I integrate disparate systems through APIs, SAML, and custom data connectors.
- I've built unified dashboards from 5+ data sources that were never meant to talk to each other.
- I understand data models, normalization, and entity resolution across system boundaries.

#### Security Data and Analytics
- I am good at integrating multiple data sources and reconciling drift/inconsistency.
- I build pipelines and tooling that improve visibility and decision quality.
- I value metrics and actionable reporting over noisy dashboards.

#### AI Engineering (Applied, not hype)
- I use AI where it improves workflow quality and speed — both as development tools and as system components.
- I care about auditability, safety, and responsible deployment.
- I treat AI systems as operational tools that need governance.

---

## Cover Letter Voice Rules

### Anti-patterns (NEVER do these)
- **Never** start with "I am reaching out to apply for X at Y." — this is the most generic opening possible. Instead, lead with the company's problem, your relevant insight, or a specific hook.
- **Never** use the paragraph order: opening → UCOP → GWR → closing. Vary which experience leads based on what's most relevant to the role.
- **Never** copy phrases from this document verbatim. Internalize the voice, then write naturally.
- **Never** use: "cutting-edge", "state-of-the-art", "revolutionary", "best-in-class", "holistic", "game-changing", "transformative", "passionate about cybersecurity"
- **Never** end with generic "I would welcome the opportunity to discuss..." — close with something specific to the role or company.

### Structural variety directives
- The opening paragraph should demonstrate that you understand what the company or team actually does. Reference a specific product, engineering challenge, or team mission from the JD.
- Lead with whichever experience (UCOP, GWR, or personal projects) is most relevant. Don't default to chronological order.
- **De-emphasize Simple.biz in cover letters.** Do not feature it as a primary talking point or dedicate a paragraph to it. It may be mentioned briefly as supporting context (e.g., "freelance client work") but the letter's weight should come from UCOP, GWR, and personal projects.
- It's OK to weave evidence from multiple roles into a single paragraph organized by theme (e.g., "automation at scale" drawing from both UCOP and GWR).
- The closing should connect back to the company-specific hook, not generic "thank you for your consideration."

### Tone
- grounded
- direct
- technically credible
- pragmatic
- operationally focused
- confident but not inflated

### Company-type adaptation
- **Large tech / infrastructure companies** (Netflix, Cloudflare, Datadog): Emphasize scale, reliability engineering, production ownership, operating at thousands of endpoints. They care about systems thinking and operational maturity.
- **Security-focused companies** (CrowdStrike, SentinelOne, Snyk): Emphasize security depth — tooling, detection, remediation workflows, data correlation. They want someone who lives in the security stack.
- **Startups / growth-stage** (Render, Supabase, Linear): Emphasize velocity, wearing multiple hats, shipping fast with guardrails. They want builders who can own problems end-to-end.
- **Enterprise / regulated** (1Password, Anduril, government-adjacent): Emphasize governance, compliance automation, documentation, auditability. They need someone who understands why process matters.
- **Platform / DevOps roles**: Emphasize CI/CD, containerization, infrastructure as code, developer experience. Lead with the operational tooling story, not the security story.

---

## Evidence Anchors (for future cover letters)

Use these as proof points when generating tailored letters:

- Built and operated production security systems in a large environment
- Integrated data from multiple sources and reconciled inconsistent records
- Delivered containerized services and automation pipelines
- Built internal tooling that improved visibility and reduced manual effort
- Established best practices for AI-assisted security tooling (auditability + safe deployment)
- Wrote runbooks that standardized remediation workflows
- Built custom threat-hunting scripts for zero-day response when vendor tooling lagged behind live threats
- Built Python and PowerShell automation for enterprise-scale endpoint operations
- Developed analytics tooling that turned security data into measurable improvements
- Built a phishing detection project combining browser extension + backend API
- Communicates clearly across engineers and leadership
- Owns work from design through production support

---

## Parsing Notes (for local LLM use)

### Core tags
- full_stack_development
- software_engineering
- security_engineering
- devsecops
- ai_native_development
- cloud_security
- automation
- system_integration
- threat_hunting
- incident_response
- endpoint_ops
- data_correlation
- internal_tooling
- frontend_development
- backend_development
- operational_reliability
- documentation
- cross_functional_execution

### Priority order for role matching
1. Full-stack software engineering
2. Security engineering and automation
3. AI-native development and tooling
4. System integration and data engineering
5. Cloud/container/platform delivery
6. Threat hunting and zero-day response
7. Operational reliability and DevOps

---

## One-line Summary

I am a full-stack software engineer with deep security expertise who turns ambiguous problems into reliable, production systems — whether that means a React dashboard, a Python backend, a security automation pipeline, or a cloud-deployed service.
