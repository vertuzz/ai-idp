# Contributing

AI-IDP is a public, Apache-2.0-licensed general-purpose IDP experiment. Contributions are welcome when they keep the system explainable, replaceable, testable and independent of a specific business domain.

## Guidelines

- Use English for code, tests, comments, documentation, issue descriptions, pull requests, commit messages and user-visible API strings.
- Do not submit real confidential documents, personal data, credentials, private endpoints, copied proprietary datasets or confidential model outputs.
- Use synthetic, public-domain or explicitly redistribution-licensed test fixtures with attribution where necessary.
- Preserve hexagonal boundaries: domain/application code must not depend on provider SDKs, HTTP framework objects or storage implementation details.
- Include unit tests for behavior changes. For model-facing changes, include documented opt-in integration/evaluation instructions and expected cost.
- Preserve field-level evidence and avoid any UI/API claim that uncalibrated decision scores are correctness probabilities.
- Before proposing a new mandatory infrastructure dependency, explain why the PostgreSQL/local-only MVP is insufficient.
- Check dependency license compatibility with Apache 2.0 and record third-party notices if required.
- Follow the implementation milestones and document architecture changes in docs/11-decisions-and-open-questions.md.

## Local development

Implementation scaffolding is planned but not yet committed. Once available, the project will use Python, uv, Docker Compose, and a local PostgreSQL instance. Never commit a populated .env file; use the example environment file instead.

## Security vulnerabilities

Follow [SECURITY.md](SECURITY.md); please do not publish exploitable vulnerability details in a public issue before a fix is available.
