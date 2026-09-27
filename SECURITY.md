# Security Policy

## Supported versions

Only the latest minor release receives security fixes while the project is pre-1.0.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" in the Security tab).

Include affected version, configuration, reproduction steps and impact. We aim to acknowledge within 3 business
days and to ship a fix or mitigation within 30 days for high-severity issues. We will credit you in the release notes
unless you prefer otherwise.

## Scope notes

Read [docs/security.md](docs/security.md) first. It documents known limitations, for example that the Docker socket
proxy is not a sandbox against a compromised hangar process, and that job containers have outbound internet access.
Reports that bypass the documented controls (API key scopes, per-agent internal tokens, job tokens, encryption at rest,
container hardening) are especially welcome.
