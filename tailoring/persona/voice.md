---
tags: []
---
<!--
PURPOSE: Injected into cover strategy and cover draft stages only. Not used for resumes.
         The QA stage gets only the Anti-patterns section (parsed by for_qa()).
EDIT:
  - Anti-patterns: add any phrases or structural patterns the LLM keeps defaulting to.
    The for_qa() method extracts everything between "## Anti-patterns" and the next "## "
    header — keep that section self-contained.
  - Company-type adaptation: add a new bullet when you identify a new company archetype.
    The key (e.g., "large_tech") must match what the analyzer emits as company_type in
    analysis.json → company_context.company_type.
  - Tone: these adjectives shape the cover letter register. Edit freely.
KEEP UNDER ~2600 chars total so it fits in the cover draft budget (~3000 chars total for all persona).
-->
## Anti-patterns (NEVER do these)
- **Never** start with "I am reaching out to apply for X at Y." — this is the most generic opening possible. Instead, lead with the company's problem, your relevant insight, or a specific hook.
- **Never** use the paragraph order: opening → UCOP → GWR → closing. Vary which experience leads based on what's most relevant to the role.
- **Never** copy phrases from this document verbatim. Internalize the voice, then write naturally.
- **Never** use: "cutting-edge", "state-of-the-art", "revolutionary", "best-in-class", "holistic", "game-changing", "transformative", "passionate about cybersecurity"
- **Never** end with generic "I would welcome the opportunity to discuss..." — close with something specific to the role or company.

## Structural variety directives
- The opening paragraph should demonstrate that you understand what the company or team actually does. Reference a specific product, engineering challenge, or team mission from the JD.
- Lead with whichever experience (UCOP, GWR, Simple.biz, or personal projects) is most relevant. Don't default to chronological order.
- It's OK to weave evidence from multiple roles into a single paragraph organized by theme (e.g., "automation at scale" drawing from both UCOP and GWR).
- The closing should connect back to the company-specific hook, not generic "thank you for your consideration."

## Tone
- grounded
- direct
- technically credible
- pragmatic
- operationally focused
- confident but not inflated

## Company-type adaptation
- **Large tech / infrastructure companies** (Netflix, Cloudflare, Datadog): Emphasize scale, reliability engineering, production ownership, operating at thousands of endpoints. They care about systems thinking and operational maturity.
- **Security-focused companies** (CrowdStrike, SentinelOne, Snyk): Emphasize security depth — tooling, detection, remediation workflows, data correlation. They want someone who lives in the security stack.
- **Startups / growth-stage** (Render, Supabase, Linear): Emphasize velocity, wearing multiple hats, shipping fast with guardrails. They want builders who can own problems end-to-end.
- **Enterprise / regulated** (1Password, Anduril, government-adjacent): Emphasize governance, compliance automation, documentation, auditability. They need someone who understands why process matters.
- **Platform / DevOps roles**: Emphasize CI/CD, containerization, infrastructure as code, developer experience. Lead with the operational tooling story, not the security story.
