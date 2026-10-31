# Security policy

H3 Studio is a local, single-user tool; please read [`docs/SECURITY-MODEL.md`](docs/SECURITY-MODEL.md) for what it does and does not defend against.

## Reporting a vulnerability
Please **do not open a public issue** for a security problem. Use GitHub's *Report a vulnerability* (Security tab → Advisories → Report a vulnerability) on this repository.
Include: version or commit, what you did, what happened, and the impact. Never include real passwords, API tokens, prompts or videos.

You can expect an acknowledgement within a few days. This is a volunteer project without an SLA; fixes are released as patch versions and noted in `CHANGELOG.md`.

## Supported versions
Only the latest release receives fixes.

## Scope
In scope: authentication, CSRF, upload handling, path handling, information disclosure, command execution, secrets handling in this repository.
Out of scope: vulnerabilities in H3cApp, the models, ffmpeg, macmon, Tailscale or Python packages (report those upstream), and attacks that require control of the user's Mac account.
