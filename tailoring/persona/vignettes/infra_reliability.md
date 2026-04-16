<!-- See coraline.md for full frontmatter field documentation -->
---
tags: [infrastructure, cloud_ops, production_ops]
company_types: [enterprise_regulated, large_tech]
skill_categories: [Infrastructure and Reliability, Cloud Security]
keywords: [AWS, deployment, Linux, containers, monitoring, WAF, certificate, production, troubleshooting, DNS, Route 53, load balancer, Windows Server, MFA, Duo]
---
When UCOP transitioned its self-service password portal from Adaxes to ManageEngine ADSelfService Plus, the deployment required standing up an AWS-hosted Windows Server behind an application load balancer — serving 2,900 users. I led the deployment end-to-end, coordinating across several teams who each owned a piece of the stack. Getting the application internet-facing meant systematically working through Windows Firewall rules, AWS Security Groups, ALB target groups, and Route 53 DNS. A key technical challenge was a protocol mismatch: the service ran on HTTP, but Duo MFA integration required HTTPS. I traced it through the Tomcat server.xml config, migrated the service to HTTPS on port 9251, then standardized on 443 for a clean production URL. I also resolved an AWS certificate issue and a WAF rule that was silently dropping legitimate traffic. The project was a good example of how infrastructure work is really coordination work — each layer was straightforward on its own, but getting them aligned across teams required clear communication and methodical troubleshooting. The result was a zero-downtime migration with full MFA enforcement.
