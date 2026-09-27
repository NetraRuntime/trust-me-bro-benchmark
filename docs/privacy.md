# Privacy and credentials

Keys come only from environment variables at request time. Config accepts environment-variable names, not literal keys. URLs with credentials, query parameters or fragments are rejected. Authorization headers are sent only to configured endpoints; redirects are not followed. Error bodies and arbitrary headers are not saved.

Configured key values, Bearer strings and common `sk-`/`sk_` patterns are redacted recursively from persisted values. This is defense in depth, not general PII detection. Keep secrets out of names, model IDs, probe IDs, paths and metadata. Do not enable HTTP wire logging with real credentials. Rotate credentials pasted into chats through the provider's dashboard.

Response text and reasoning traces are not stored by default. Public bundled prompts are saved. Private probes contribute only IDs, roles, levels and hashes. SHA-256 hashes are **not encryption or anonymization**: low-entropy text can be guessed, and equality patterns can be sensitive.

`--store-text` saves credential-redacted visible responses, including truncated ones when present. This enables semantic disagreement inspection but may include personal data or echoed private prompts. There is no automatic PII detector or custom PII-redaction pipeline. Review before sharing; sanitization can change the scientific estimand and must be documented.

Hashes and counts suffice to reproduce this JSD/exact-match analysis without raw text or keys. They do not permit semantic reanalysis or prove requests were sent. Retain private probe files separately and securely to repeat experiments, checking the suite hash.

Prompts are sent to configured providers; their retention policies apply. `tmb` uses no separate telemetry service. Results, `.env` files and `*.local.yaml` are ignored by Git. Never force-add paid API results or private probes. Local retention is your responsibility; local deletion does not delete a provider's copy.
