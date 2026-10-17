# Security Policy

**Status:** This repository contains a self-hosted API and worker, document readers, model
adapters and evaluation tools. Deployment assumes one trusted access boundary; no public
authentication or multi-tenant isolation is implemented. Reviewed benchmark acceptance
is still pending. See [deployment and release gates](docs/13-operations-and-release.md).

## Secrets and sensitive data

- Never commit API keys, passwords, tokens, cookies, database URLs with credentials, private documents or real client data.
- Use environment variables and local untracked configuration. Keep .env out of git.
- Treat all uploaded files as untrusted. Enforce upload limits, decompression budgets, file-type validation, memory/runtime caps, sanitized paths and disabled macro/remote resource execution.
- Treat document text as untrusted input to LLMs; document content must not override application instructions, authorize tool execution or request secret disclosure.
- By default do not write source text, images, full prompts or API credentials to local trace/log exports.
- OpenRouter processing involves third-party model providers. Deployers must ensure their document-processing policies allow such transfers.
- Until explicit authentication and authorization are implemented, the service is intended for deployment only within a trusted network. Never expose the development API to the public internet without an access-control layer.
- Implement retention and deletion policies before using real sensitive documents.

## Reporting vulnerabilities

Use GitHub's private vulnerability reporting feature if enabled for this repository. If private reporting is unavailable, contact the maintainers through a private channel rather than opening a public issue containing exploit details.

No supported release or security SLA is promised at this planning stage.
