# Security Policy

## Supported Versions

Security fixes target the latest released version of ss2json.

## Reporting a Vulnerability

Please do not open a public issue for vulnerabilities. Email the maintainer or use the repository's private security advisory flow when available.

Include:

- A description of the issue and impact.
- Steps to reproduce.
- Whether screenshots, image bytes, API keys, or extracted data are exposed.

## Security Expectations

ss2json sends images to the configured AI provider. Users should avoid sending sensitive screenshots to providers they do not trust. The CLI must not print API keys, persist temporary screenshots after capture, or emit non-JSON errors that break automation.
