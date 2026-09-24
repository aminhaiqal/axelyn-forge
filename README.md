# Axelyn Forge

Axelyn Forge is an API-first service for producing focused resumes, cover letters, and reusable career-document systems from verified experience. The public web app is built with Astro and Tailwind CSS. A FastAPI service exposes the catalog and accepts customer briefs, while the existing Python document engine continues to provide validated JSON, DOCX rendering, PDF conversion, evidence selection, and OpenAI-assisted tailoring.

The active product no longer depends on Discord.

## Repository layout

```text
apps/
  api/                     FastAPI HTTP service and API tests
  web/                     Astro and Tailwind public website
packages/
  forge-core/              Document engine, CLI, and core tests
infra/
  docker/                  API and web container images
  nginx/                   Static hosting and API reverse proxy
  compose.yaml             Local and single-host production stack
.github/workflows/
  ci.yml                   Tests, image validation, and verified GHCR publishing
bindings/                  Semantic JSON-to-DOCX bindings
context/                   Verified source material
data/                      Canonical structured documents
schemas/                   JSON Schemas
templates/                 Private or deploy-time DOCX templates
```

## Run locally

Python 3.9 or newer and Node.js 24 are required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e "./packages/forge-core[dev]" -e "./apps/api[dev]"
npm install
cp .env.example .env
```

Start the API:

```bash
.venv/bin/forge-api
```

In a second terminal, start Astro:

```bash
npm run dev:web
```

Open `http://localhost:4321`. The Astro development server proxies `/api` to the API on port 8000. Interactive API documentation is available at `http://localhost:8000/api/docs`.

## HTTP API

The first public contract is versioned under `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Check API and SQLite availability. |
| `GET` | `/api/v1/services` | Return the public service catalog. |
| `POST` | `/api/v1/service-requests` | Validate and store a customer service brief. |

Example request:

```bash
curl http://localhost:8000/api/v1/service-requests \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "service_id": "application-kit",
    "full_name": "Taylor Example",
    "email": "taylor@example.com",
    "project_summary": "I need a focused resume and cover letter for a backend engineering role.",
    "job_posting_url": "https://example.com/jobs/123",
    "timeline": "Within two weeks",
    "consent": true
  }'
```

Submissions receive an opaque `req_…` reference and are stored in the SQLite database configured by `FORGE_DATABASE`. No public endpoint exposes submitted customer details.

## Containers

The Compose stack builds the API and static web app, places the API behind Nginx, rate-limits the public intake endpoint, and persists SQLite state in a named volume. A separate core image in `infra/docker/core.Dockerfile` provides the `forge` CLI and LibreOffice without baking private candidate files into any image.

```bash
cp .env.example .env
docker compose -f infra/compose.yaml up --build
```

Open `http://localhost:8080`. Only the web container publishes a host port; Nginx proxies `/api` to the private API service.

For a single-host production deployment behind a dedicated Cloudflare Tunnel, use the published images and mount the tunnel token from a root-readable file:

```bash
FORGE_API_IMAGE=ghcr.io/aminhaiqal/axelyn-forge-api:sha-<commit> \
FORGE_WEB_IMAGE=ghcr.io/aminhaiqal/axelyn-forge-web:sha-<commit> \
CLOUDFLARE_TUNNEL_TOKEN_FILE=/run/secrets/axelyn-forge-tunnel \
docker compose -f infra/compose.production.yaml up -d
```

The production stack does not publish a host port. Cloudflare Tunnel connects directly to the internal `web:8080` service, while the API and its SQLite volume stay private.

## Document engine

The core package retains the deterministic document pipeline. DOCX templates control presentation, canonical JSON controls facts and document structure, and AI output is limited to validated semantic rewrite operations.

Validate a canonical profile:

```bash
.venv/bin/forge validate \
  --data data/profile.json \
  --schema schemas/profile.schema.json
```

Render with a private Word template:

```bash
.venv/bin/forge render \
  --template /path/to/private-resume-template.docx \
  --data data/profile.json \
  --bindings bindings/software-engineer.json \
  --output output/resume.docx
```

Run the full OpenAI-assisted workflow:

```bash
.venv/bin/forge tailor \
  --jd /path/to/job-description.txt \
  --context context/ \
  --template /path/to/private-resume-template.docx \
  --data data/profile.json \
  --bindings bindings/software-engineer.json \
  --output-dir output
```

Set `OPENAI_API_KEY` before running AI-assisted commands. Provider output cannot modify protected identity, contact, employer, role, date, education, type, or stable-ID fields. OpenAI requests use `store=False`, and usage metadata is written to SQLite without prompt content or API keys.

## Verification

```bash
.venv/bin/python -m pytest
npm run build:web
docker compose -f infra/compose.yaml config
```

CI runs the Python tests, checks and builds the Astro app, and builds the API, web, and core container images. Pushes to `main` and version tags publish all three images to GitHub Container Registry.

## Private data

Keep `.env`, candidate DOCX files, SQLite databases, generated output, and `.forge-private/` out of Git. Service requests contain personal information; back up and restrict access to the `forge-state` volume according to your retention policy.
