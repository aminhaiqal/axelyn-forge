# Changelog

Axelyn Forge follows semantic versioning. Git tags use the corresponding `vMAJOR.MINOR.PATCH` format.

## Unreleased

### Added

- Added a shared guided resume builder for new and imported sources, with standard fields, editable custom sections, and a source inbox for imported lines that do not map cleanly.
- Added Classic, Modern, and Compact single-column ATS-friendly templates that render every populated section into Word and PDF.
- Added authenticated structured resume creation and a public resume-template catalog to the versioned API.
- Added private source-level Word draft generation so imported PDF or DOCX content can be downloaded as an editable `.docx` before approval.
- Added section-based browser editing for experience, projects, education, skills, languages, and additional resume content.
- Added a private, resource-bounded LibreOffice conversion service and standard resume generation as matched DOCX/PDF bundles.
- Added owner-scoped generated-document listing so authenticated users can return to their latest downloads.
- Added a private job-match workspace for pasted descriptions and PDF, DOCX, TXT, PNG, or JPEG uploads, with three clear match states and evidence-gap guidance.
- Added evidence-grounded tailored resume generation in Word and PDF for Match and Some match results.
- Added bounded Tesseract OCR to the private converter for job-post screenshots.

### Changed

- Removed the dark standard-template promotion panel from the resume library and made the source workspace full width.
- Replaced authenticated workspace headers with a responsive white sidebar that expands on desktop, collapses to a tablet rail, and becomes a compact mobile navigation bar.
- Updated the responsive resume workspace to expose persistent DOCX and PDF download controls for each approved role version.

## 0.3.0 — 2026-09-25

### Added

- Added an Astro and Tailwind public service website with a responsive service catalog, process explanation, and accessible request form.
- Added a versioned FastAPI service with health, service-catalog, and service-request endpoints.
- Added validated SQLite persistence for customer service briefs with opaque public references.
- Added separate API, web, and document-core container images, an Nginx reverse proxy, intake rate limiting, and container health checks.
- Added CI for backend tests, frontend checks, and container builds, plus GHCR publishing for `main` and version tags.
- Added Clerk sign-in, sign-up, signed-in user controls, and route protection for the Astro workspace.
- Added Clerk session verification to the FastAPI Forge endpoint and associated stored briefs with the authenticated user ID.
- Added a dedicated Astro SSR container behind the Nginx gateway.
- Added a private resume library with batch PDF/DOCX import, extraction review, named role versions, and owner-scoped access.
- Added standard-template DOCX rendering and authenticated document downloads.
- Added a server-only Cloudflare Worker gateway for the private `axelyn-forge-private` R2 bucket.

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
