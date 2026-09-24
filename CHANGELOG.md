# Changelog

Axelyn Forge follows semantic versioning. Git tags use the corresponding `vMAJOR.MINOR.PATCH` format.

## Unreleased

## 0.3.0 — 2026-09-25

### Added

- Added an Astro and Tailwind public service website with a responsive service catalog, process explanation, and accessible request form.
- Added a versioned FastAPI service with health, service-catalog, and service-request endpoints.
- Added validated SQLite persistence for customer service briefs with opaque public references.
- Added separate API, web, and document-core container images, an Nginx reverse proxy, intake rate limiting, and container health checks.
- Added CI for backend tests, frontend checks, and container builds, plus GHCR publishing for `main` and version tags.

### Changed

- Reorganized the repository into `apps`, `packages`, and `infra` boundaries while retaining the existing Forge CLI and document engine.
- Moved document-engine tests away from the private candidate resume template by generating a deterministic test-only DOCX fixture.

### Fixed

- Constrained OpenAI context selection to valid candidate chunk IDs and bounded keyword lengths so harmless model formatting drift no longer aborts tailoring.

### Removed

- Removed the Discord bot adapter, Discord dependency, and Discord-specific VPS deployment workflow.

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
