# Security Policy

## Reporting Security Issues

Please do not open a public issue for vulnerabilities, leaked credentials, or infrastructure details. Contact the maintainer privately using the contact method listed on the project profile or repository owner profile.

Include:

- A short description of the issue.
- Affected file, endpoint, or workflow.
- Reproduction steps when safe to share.
- Whether any secret, token, host, or credential may have been exposed.

## Secret Handling

Never commit:

- `.env` files
- API keys
- SSH passwords
- TURN username or credential values
- private keys or certificates
- local workspaces, logs, screenshots, or diagnostics with private infrastructure details

Use environment variables or private local files copied from `*.env.example`.

If a secret was ever written to a local `.env`, log, terminal transcript, screenshot, or diagnostic report, rotate it before publishing or sharing the repository.

## Supported Scope

This is a portfolio demo repository. Security fixes for the demo backend, WebSocket protocol, frontend pages, deployment templates, and documentation are in scope. Production hardening, multi-tenant isolation, and hosted service operations are outside the default support scope unless explicitly documented.

