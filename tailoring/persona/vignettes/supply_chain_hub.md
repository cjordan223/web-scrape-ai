<!-- See coraline.md for full frontmatter field documentation -->
---
tags: [supply_chain_security, data_engineering, internal_tooling, endpoint_ops]
company_types: [enterprise_regulated, large_tech, security_focused, platform_devops]
skill_categories: [Security Data Engineering, Application Security, Security Automation, Endpoint Operations and Remediation, Technical Communication and Delivery]
keywords: [supply chain, dependency analysis, SCA and dependency analysis, Jamf, BigFix, package inventory, VS Code extensions, npm, telemetry, normalization, JSONL, SHA256, endpoint, operational visibility, technical architecture communication]
---
The supply-chain work in Coraline is how I build now: not a one-off script, but a telemetry product. Developer machines had a blind spot around user-installed packages, CLI tools, browser extensions, editor extensions, and config-driven tooling - the kind of surface normal software inventory misses. I designed Coraline to ingest Jamf extension-attribute data and BigFix task-plus-analysis payloads, preserve raw evidence, and normalize both into one queryable model. The BigFix path uses chunking, gzip/base64, record counts, SHA-256 checks, JSONL parsing, and explicit rollout/transport/data-quality states. The pattern is bigger than Coraline: find the invisible attack surface, define the trust boundary, normalize the data, and ship the UI/API that makes it usable.
