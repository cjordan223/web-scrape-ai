<!-- See coraline.md for full frontmatter field documentation -->
---
tags: [data_correlation, cloud_security, internal_tooling]
company_types: [large_tech, security_focused]
skill_categories: [Security Data Engineering, Cloud Security]
keywords: [correlation, reconciliation, asset, inventory, Flask, Docker, ECS, endpoint, vulnerability]
---
Coraline started as a command-line script to answer one question: which managed assets were missing vulnerability agents? I pulled inventories from Rapid7, BigFix, and Jamf via their APIs and tried to match records. IP addresses were the obvious join key — and immediately unreliable. VPNs, network configs, and multi-homed devices meant the same machine had different IPs across platforms. I tried MAC addresses next — better, but still inconsistent across a spread-out network. Through my own research I landed on hardware UUID: a machine-level identifier that's 99.9% stable and wasn't something anyone was tracking. That became the correlation key. Once matching was reliable, the scope grew — other teams needed the same reconciled view. The CLI became a full-stack Flask/React app on AWS ECS so anyone could access it. And once asset tracking was trivial, we uncovered deeper problems — like Rapid7's scan engine not covering our full inventory, which we wouldn't have caught otherwise. The data is still messy; that's why the tool exists.
