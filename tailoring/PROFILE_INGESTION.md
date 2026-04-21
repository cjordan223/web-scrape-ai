# Profile Ingestion Guide

This is the safest way to add new experience to the tailoring profile without teaching the LLM to over-claim.

## Mental model

Each experience should be split into three layers:

1. `skills.json` = what the candidate is allowed to claim
2. `persona/vignettes/*.md` = proof story the model can selectively reuse
3. `persona/contributions.md` and `persona/evidence.md` = higher-level framing and reusable proof anchors

`tailoring/soul.md` is only a fallback mirror. The active pipeline prefers `tailoring/persona/`.

## Where a new experience goes

Use this routing rule:

- Add to [`skills.json`](/Users/conner/Documents/TexTailor/tailoring/skills.json) when the experience establishes a repeatable capability, tool, or domain claim.
- Add to [`persona/vignettes/`](/Users/conner/Documents/TexTailor/tailoring/persona/vignettes) when the experience is a specific story with constraints, judgment, or outcomes.
- Add to [`persona/contributions.md`](/Users/conner/Documents/TexTailor/tailoring/persona/contributions.md) when the experience changes the candidate's recurring contribution pattern.
- Add to [`persona/evidence.md`](/Users/conner/Documents/TexTailor/tailoring/persona/evidence.md) when the experience yields a compact proof point useful across many cover letters.
- Mirror only major changes into [`soul.md`](/Users/conner/Documents/TexTailor/tailoring/soul.md) so fresh clones still have a usable fallback.

## Example: zero-day threat hunting

This experience should be packaged as:

- Claim layer: "Zero-day response engineering", "Custom threat hunting scripts", "Safe enterprise script deployment", "Fast iteration under incident pressure"
- Story layer: a vignette explaining the tension between speed and safety when enterprise tools lag behind live threats
- Framing layer: contribution language about translating emerging threats into validated organization-wide response actions
- Evidence layer: one concise proof anchor about building custom hunts when vendor coverage was incomplete

That split lets the analyzer match relevant jobs while keeping the writer grounded in a real story instead of hallucinating details.

## Recommended intake shape

For a better UX, do not append raw user text directly into profile files. Introduce a structured intake step that turns freeform experience into a reviewed patch set.

Suggested flow:

1. User submits a short narrative.
2. Intake LLM extracts a normalized `experience packet`.
3. A rules layer decides which profile destinations should change.
4. The system shows a proposed diff for review before writing files.

Minimum packet fields:

```json
{
  "title": "Zero-day threat hunting and org-wide script deployment",
  "experience_type": "incident_response",
  "scope": "enterprise",
  "problem": "Vendor tooling lacked coverage for a zero-day",
  "actions": [
    "Developed custom threat-hunting scripts",
    "Validated scripts carefully before broad deployment",
    "Iterated quickly as threat intelligence changed"
  ],
  "constraints": [
    "High operational risk",
    "Need for fast response",
    "Need for safe deployment at scale"
  ],
  "tools": ["Python", "EDR/XDR", "enterprise security tooling"],
  "outcomes": [
    "Improved exposure visibility during active response"
  ],
  "confidence": "high",
  "safe_to_generalize": [
    "zero-day response engineering",
    "custom threat hunting scripts",
    "safe enterprise script deployment"
  ],
  "story_worthy": true
}
```

## Destination rules

Map the packet into files with simple rules:

- If `safe_to_generalize` is non-empty, propose `skills.json` additions.
- If `story_worthy` is true, propose a new vignette file with frontmatter tags.
- If the packet changes how the candidate should be described broadly, update `contributions.md`.
- If the packet yields a short reusable proof statement, update `evidence.md`.
- If details are employer-specific, keep them in vignette text and out of general skill lists.

## Guardrails

Use these checks before merging profile updates:

- Reject tools or claims that are not explicitly supported by the source experience.
- Prefer capability phrases over vendor-name inflation unless the tool is confirmed.
- Keep vignettes about judgment, constraints, and outcomes; keep skills lists terse.
- Require `skill_categories` in vignette frontmatter to match `skills.json` category names exactly.
- Treat `soul.md` as a mirror, not the primary edit target.

## Best next step for the product

The most intuitive product improvement would be a "Add experience" flow in the dashboard that:

- accepts a freeform story
- extracts a structured packet
- previews where each piece will go
- shows a proposed diff for `skills.json`, persona files, and `soul.md`
- asks for approval before saving

That gives the LLM context about intent and destination, while keeping profile quality high and avoiding blind ingestion.
