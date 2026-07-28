# Security Policy

## Supported Version

Security fixes are applied to the latest version on the default branch.

## Reporting a Vulnerability

Do not publish credentials, cookies, private transcripts, or exploit details in
a public issue. Use GitHub's private vulnerability reporting feature when it is
available for this repository.

Include the affected module, reproduction steps, expected impact, and a minimal
proof of concept that does not contain third-party private data.

## Local Data Boundary

The application stores authentication state, downloaded media, transcripts,
analysis results, logs, models, and knowledge-base indexes locally. These paths
are excluded from version control by the root `.gitignore`:

- `.env`
- `cache/`
- `output/`
- `logs/`

Users remain responsible for platform terms, content rights, credential
protection, and deletion of local research data.
