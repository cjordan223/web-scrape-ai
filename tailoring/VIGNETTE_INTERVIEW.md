# Vignette Gap Interview

5 of 19 skill categories in `skills.json` have **zero vignette coverage**. Answer whichever you have a good story for — skip any that don't have a concrete experience behind them.

---

## 1. AI-Native Development

*Covers: Claude Code, Cursor, Copilot, LLM-integrated app design, RAG pipelines*

What's a specific project where you used AI dev tools (Claude Code, Cursor, Copilot, etc.) to build something that would've been impractical without them? What was the outcome — shipping speed, scope you wouldn't have attempted, etc.?


**Answer:**

AI dev tools are ubiquitus at every level of my development cycle. They allow me to have a local datbase admin, local AWS expert, local senior architect...you get the picture.
 I believe Coraline is a SaaS level tool that would have required six figures of annual billing to host in an enterprise just 3 years ago. However, we are now living in the "fast fashion" era of saas, where devs are empowered to build and architect extremly complex workflows with detailed auditing and controls. To distill it into an answer, Coraline would have probably been like a simple Python CLI automation that we ran every day. But DevTools allowed us to build out a full stack application with a persistent database for auditing and a frontend for better UX/UI. All right.

---

## 2. Infrastructure and Reliability

*Covers: Linux admin, production ops, containers, monitoring, hybrid/cloud infra*

Tell me about a time you owned production infrastructure — stood up a system, kept it running, or rescued it when it broke. Linux, containers, monitoring, whatever. What was the environment and what did you actually do?


**Answer:**
When the service desk team transitioned to ManageEngine, the new system required an AWS server deployment within our environment. Because their team lacked experience with the platform, I stepped in to lead the deployment, leveraging my previous automation experience from Great Wolf Lodge. I provisioned the server and handled the end-to-end setup independently.

Throughout the rollout, I served as the primary Tier 3 escalation point and subject matter expert. I troubleshot complex emerging issues, successfully identifying and resolving a misconfigured AWS certificate and a restrictive Web Application Firewall (WAF) rule. Ultimately, I kept our infrastructure deliverables flawless while providing actionable, high-level insights to help the service desk and other departments troubleshoot their own components. Despite starting the project from scratch, I quickly adapted, owned the technical execution, and drove the deployment to a successful completion.---


more info: /Users/connerjordan/Documents/Jobs/Ucop-stuff/zoho.txt

## 3. Penetration Testing and Offensive Tools

*Covers: Burp Suite, Metasploit, Nmap, web app pentesting, network recon*

Do you have a pentest or red-team engagement story? Could be professional, academic, or CTF. What did you find, what tools did you use, and what was the impact?



**Answer:**

1) I participate in Capture the Flag exercises routinely. I think they're a great way to get a better understanding of the system, not just the vulnerabilities, but how the system works. In fact, I was doing a pen test related to SMB protocol. And just a few weeks later, our desktop engineering team at the UC was pushing back because our Active Directory managed environment was going to be migrated to the cloud. And they/we were used to being able to just connect to a VPN connected user's laptop via the file explorer. And they didn't really know how to articulate what that feature was. They just knew they're like, we want to be able to remote into the file explorer. And me having the optics from the other side of things, just recently using SMB to exploit a vulnerability for capture the flag test. I was able to articulate what you're talking about is the SMB protocol. The SMB protocol is archaic and old. And so we had to figure out other remote options for them, but basically had that fundamental knowledge of why the old system was going away when no one else was able to be able to really articulate that to them. I was able to really articulate that to them. I was able to because I had this kind of pen tester perspective of SMB actually being a huge smoking gun or whatever the word is SMB is a four letter word basically in security, but to them it's just like this non-issue, like this user feature that they thought was like shouldn't stay on.


2) Yeah, just personally, I have a permanent instance of OWASP top 10 running in my environment. I have a pretty decent grasp on all of the low-hanging fruit, and I keep those types of issues in mind when I'm developing. But also, I can quickly assess existing code bases, especially with security tools like SEMGREP or v6audit. (u can add more here?), against common vulnerabilities that I see in the OWASP Top 10. Burp Suite is a tool that we use to check our locally hosted apps for certain vulnerabilities, but it's not fully implemented or integrated into our workflows. Personally, I have a lot of experience with it too, with security research.


---

## 4. Identity and Access

*Covers: MFA, IAM, identity portal architecture, auth provider integration*

Have you built or overhauled an IAM/MFA/auth system? What was broken or missing, what did you implement, and what changed for users or the org?
I already answered this.
more info: /Users/connerjordan/Documents/Jobs/Ucop-stuff/SAML_INT.txt

**Answer:**

---

## 5. Testing and Quality Automation

*Covers: Selenium, WCAG/ADA accessibility, cross-browser/device testing, CI test gates*

Tell me about a time you built or significantly improved a testing pipeline — Selenium suites, accessibility audits, CI test gates, etc. What triggered it and what did it catch?


**Answer:**

At the UC, I was asked to test out checkmarks, static application security testing. I was able to test the tool on a dozen different code bases over the course of a single working day, providing detailed write-ups, as well as an aggregate report. The general behavior, issues encountered, and possible use cases. This whole workflow would typically historically involve hiring an outside consultant or contractor for this project, but given the fast iterations we can perform with AI tools, we can abstract away a lot of that noise and meaningful tailored personal results specific to our ecosystem. Once the initial report was done, by the end of the day, or by the end of the week, rather, I had already wired up checkmarks as part of my build process, which proactively got ahead of several high vulnerabilities, including one critical exploitable vulnerability. With OpenSSL, because it was a MySQL vulnerability via OpenSSL vulnerability, which was still out in the wild, but we could still basically call that an accepted risk given that it was in a containerized environment in our AWS system requiring multi-factor authentication login. But we still had that full visibility, which was great.
