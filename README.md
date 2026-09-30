# Axelyn Forge

Axelyn Forge is an API-first resume workspace. Signed-in users upload PDF/DOCX resumes, which are processed once into finished DOCX/PDF pairs and remain immutable until deleted. `/app/match` records evidence-grounded job comparisons and tailored versions. `/app/forge` keeps persistent, compressed coaching context and can read public links without treating them as proof of the candidate's work. `/app/tracker` records applications and produces evidence-cited interview briefs. FastAPI verifies the Clerk session for every private operation.

The active product no longer depends on Discord.

## Repository layout

```text
apps/
  api/                     FastAPI HTTP service and API tests
  converter/               Private LibreOffice conversion service
  web/                     Astro SSR app, Tailwind UI, and Clerk controls
packages/
  forge-core/              Shared document and provider primitives
infra/
  docker/                  API, converter, frontend, and gateway images
  nginx/                   Public gateway and API rate limiting
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

Python 3.10 or newer and Node.js 24 are required. The project is linked to the Clerk application `app_3JnxByEpwwusQHm8vejwoGXx8DV`.

```bash
python3 -m venv .venv
.venv/bin/pip install -e "./packages/forge-core[dev]" -e "./apps/api[dev]" -e "./apps/converter[dev]"
npm install
npm install --global clerk
clerk auth login
(cd apps/web && clerk env pull --app app_3JnxByEpwwusQHm8vejwoGXx8DV --instance dev)
```

Load the Clerk development values without committing them, then start the API:

```bash
set -a
source apps/web/.env
set +a
.venv/bin/forge-converter &
.venv/bin/forge-api
```

In a second terminal, start Astro:

```bash
npm run dev:web
```

Open `http://localhost:4321`. The Astro development server proxies `/api` to the API on port 8000. Sign up through the navigation, then open `/app`. Interactive API documentation is available at `http://localhost:8000/api/docs`.

`CLERK_SECRET_KEY` is server-only. Never expose it through an Astro `PUBLIC_` variable, client JavaScript, container build argument, or committed environment file.

## HTTP API

The first public contract is versioned under `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Check API and SQLite availability. |
| `GET` | `/api/v1/services` | Return the public service catalog. |
| `GET` | `/api/v1/me` | Return the authenticated Clerk user ID. |
| `POST` | `/api/v1/service-requests` | Validate and store a customer service brief. |
| `GET` | `/api/v1/resumes` | List resume sources owned by the signed-in user. |
| `POST` | `/api/v1/resumes/imports` | Import up to five PDF/DOCX sources and create a layout-preserving SDT/JSON/Schema bundle. |
| `GET` | `/api/v1/resume-source-artifacts` | List the personalized DOCX, PDF, JSON, and schema files for imported resumes. |
| `GET` | `/api/v1/resume-source-artifacts/{id}/download` | Download an owned resume artifact. |
| `POST` | `/api/v1/resumes/{id}/render` | Validate that resume's JSON and render it through its private SDT template as DOCX or PDF. |
| `DELETE` | `/api/v1/resumes/{id}` | Delete an owned resume source and its files. |
| `GET`, `POST` | `/api/v1/job-applications` | List or create private job-application records with a resume attachment snapshot. |
| `PUT`, `DELETE` | `/api/v1/job-applications/{id}` | Update or remove an owned job-application record. |
| `POST` | `/api/v1/job-matches` | Analyze pasted or uploaded job-description content against an owned resume. |
| `GET` | `/api/v1/job-matches` | List the signed-in user's saved job-match history. |
| `GET` | `/api/v1/job-matches/{id}` | Reopen one owned analysis with its generated document links. |
| `POST` | `/api/v1/job-matches/{id}/tailor` | Generate an evidence-grounded DOCX/PDF bundle for a Match or Some match result. |
| `GET` | `/api/v1/job-match-documents/{id}/download` | Download an owned tailored resume document. |
| `GET`, `POST` | `/api/v1/forge-ai/threads` | List evidence discussions or open one for an owned saved match. |
| `GET` | `/api/v1/forge-ai/threads/{id}` | Reopen the full transcript, compressed memory, and current evidence score. |
| `POST` | `/api/v1/forge-ai/threads/{id}/messages` | Add evidence or a question and receive a source-aware coaching response. |
| `POST` | `/api/v1/forge-ai/threads/{id}/enhance` | Apply a strict evidence-cited rewrite plan and create a derived DOCX/PDF pair. |
| `GET` | `/api/v1/job-applications/{id}/interview-brief` | Load the private interview brief saved for a tracked application. |
| `POST` | `/api/v1/job-applications/{id}/interview-brief` | Generate or replace an evidence-grounded interview brief from the submitted resume snapshot. |

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

Service submissions receive an opaque `req_…` reference and are stored in the SQLite database configured by `FORGE_DATABASE`. Private resume, job tracker, and job-match operations require a valid Clerk session and remain scoped to the authenticated user.

## Containers

The Compose stack builds the FastAPI service, private LibreOffice/Tesseract converter, Astro SSR frontend, and Nginx gateway. Nginx rate-limits write endpoints, while SQLite state remains in a named volume. Local resume objects use the private state volume. Production uses the authenticated `axelyn-forge-storage` Worker and a private R2 bucket; its bearer token stays server-only. The converter has no published port, uses a read-only filesystem and bounded concurrency, validates each PDF before the API stores it, and extracts text from PNG/JPEG job-post screenshots.

```bash
docker compose --env-file apps/web/.env -f infra/compose.yaml up --build
```

Open `http://localhost:8080`. Only the Nginx gateway publishes a host port; the Astro and API services stay on the private Compose network.

For a single-host production deployment behind a dedicated Cloudflare Tunnel, use the published images and mount the tunnel token from a root-readable file:

```bash
FORGE_API_IMAGE=ghcr.io/aminhaiqal/axelyn-forge-api:sha-<commit> \
FORGE_CONVERTER_IMAGE=ghcr.io/aminhaiqal/axelyn-forge-converter:sha-<commit> \
FORGE_FRONTEND_IMAGE=ghcr.io/aminhaiqal/axelyn-forge-frontend:sha-<commit> \
FORGE_WEB_IMAGE=ghcr.io/aminhaiqal/axelyn-forge-web:sha-<commit> \
CLOUDFLARE_TUNNEL_TOKEN_FILE=/run/secrets/axelyn-forge-tunnel \
docker compose --env-file /path/to/forge-production.env \
  -f infra/compose.production.yaml up -d
```

The production environment file must contain the Clerk **production-instance** publishable and secret keys. The production stack does not publish a host port. Cloudflare Tunnel connects directly to the internal `web:8080` gateway, while the frontend, API, converter, and SQLite volume stay private.

It must also contain `FORGE_STORAGE_ENDPOINT` and `FORGE_STORAGE_TOKEN`. Deploy the private R2 gateway with `infra/cloudflare/storage.wrangler.jsonc`; store `FORGE_STORAGE_TOKEN` with `wrangler secret put`, never in the Wrangler config.

`infra/cloudflare/` contains the edge proxy for `forge.axelyn.com`. Its Worker custom domain creates the public hostname and forwards requests through a Workers VPC binding to the dedicated Forge tunnel:

```bash
npx wrangler deploy --config infra/cloudflare/wrangler.jsonc
```

OpenRouter requests use `store=False`, zero-data-retention routing, and denied provider data collection. `OPENROUTER_FORGE_AI_MODEL` controls evidence coaching; `OPENROUTER_WEB_CONTEXT_MODEL` controls domain-restricted public-link reading. Website context remains separate from user-confirmed responsibilities.

## Verification

```bash
.venv/bin/python -m pytest
npm run build:web
docker compose -f infra/compose.yaml config
clerk doctor
```

CI runs the Python tests, checks and builds the Astro app, and builds the API, converter, frontend, and gateway container images. Pushes to `main` publish all four images to GitHub Container Registry, invoke the production host's restricted `deploy <commit-sha>` command, and verify the public health endpoint. Version tags publish immutable images without changing production.

The restricted host command is versioned at `infra/deploy/production-deploy.sh`. It accepts only the exact head of `main`, deploys commit-addressed images, waits for Compose health checks, and restores the prior release if the replacement stack fails.

## Private data

Keep `.env`, candidate DOCX files, SQLite databases, generated output, and `.forge-private/` out of Git. Service requests contain personal information; back up and restrict access to the `forge-state` volume according to your retention policy.
