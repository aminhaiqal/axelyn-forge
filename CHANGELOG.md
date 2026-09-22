# Changelog

Axelyn Forge follows semantic versioning. Git tags use the corresponding `vMAJOR.MINOR.PATCH` format.

## Unreleased

### Added

- Added an ephemeral `/forge whoami` command so prospective users can retrieve their own Discord ID without enabling Developer Mode or having prior Forge authorization.

### Fixed

- Constrained OpenAI context selection to valid candidate chunk IDs and bounded keyword lengths so harmless model formatting drift no longer aborts tailoring.

## 0.2.0 — 2026-09-08

### Added

- Multi-profile Discord routing based on an explicit Discord-user-to-candidate manifest.
- Per-profile resume, cover-letter, context, SQLite ledger, output, and filename configuration.
- Startup validation that prevents distinct candidate profiles from sharing private data or storage paths.
- Candidate-profile identification in successful Discord responses.

### Compatibility

- Existing single-profile deployments remain supported through `DISCORD_ALLOWED_USER_IDS` and the legacy `FORGE_*` environment variables.

## 0.1.0 — 2026-09-02

### Added

- Single-profile Discord resume and cover-letter tailoring.
- DOCX and PDF generation with semantic bindings and protected fields.
- Evidence-backed context selection, keyword alignment, and OpenAI usage accounting.
- Markdown and structured JSON evidence indexing.
