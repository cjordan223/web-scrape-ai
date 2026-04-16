<!-- See coraline.md for full frontmatter field documentation -->
---
tags: [testing, appsec, automation, security_engineering]
company_types: [enterprise_regulated, large_tech, platform_devops]
skill_categories: [Testing and Quality Automation, Application Security, DevSecOps]
keywords: [Checkmarx, SAST, scanning, CI/CD, vulnerability, OpenSSL, security testing, build process, automation]
---
At the UC, I was asked to evaluate Checkmarx SAST for potential adoption. In a single working day, I tested the tool across a dozen different codebases and produced detailed write-ups plus an aggregate report covering behavior, issues encountered, and use cases — work that historically would have required an outside consultant. By the end of the week, I had already wired Checkmarx into my build process as a CI security gate. It immediately proved its value: the scans proactively caught several high-severity vulnerabilities, including a critical exploitable OpenSSL issue affecting our MySQL connections. The vulnerability was still active in the wild, but because the affected service ran in a containerized AWS environment behind MFA, we could make an informed risk acceptance decision with full visibility rather than discovering it reactively. That's the difference between having security testing in the pipeline and not — you get to choose your risk posture instead of having it chosen for you.
