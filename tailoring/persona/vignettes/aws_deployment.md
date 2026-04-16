<!-- See coraline.md for full frontmatter field documentation -->
---
tags: [cloud_deployment, learning, internal_tooling]
company_types: [startup, large_tech, platform_devops]
skill_categories: [Cloud Security, DevSecOps]
keywords: [AWS, ECS, CodePipeline, CodeBuild, Docker, containerized, deployment, CI/CD]
---
When UCOP approved AWS access for Coraline's internal deployment, they asked me to research the deployment architecture and then walk their AWS engineer through it so he could apply the patterns elsewhere — deploying a locally-developed app to internal users was new territory for the org. I had zero AWS deployment background. The ECS containerized deployment through CodePipeline and CodeBuild was a nightmare of opaque errors that didn't match any documentation I could find. It was a solo effort, done in late hours, researching docs and iterating on build configs. Three years ago that might have stopped me. But I went from no AWS knowledge to leading the deployment effort in about two and a half weeks, and I'm still the one pioneering new deployment patterns and navigating the cross-department politics that come with them.
