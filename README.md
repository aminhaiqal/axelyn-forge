# Axelyn Forge

Axelyn Forge is an API-first service for producing focused resumes, cover letters, and reusable career-document systems from verified experience. The Astro and Tailwind web app has a Clerk-protected `/app` resume library for importing private PDF/DOCX sources, reviewing extracted content, organizing role versions, and rendering the Axelyn standard as DOCX and PDF. `/app/match` compares a selected resume with pasted or uploaded job descriptions, explains the gaps, and creates evidence-grounded tailored files when the fit supports it. FastAPI verifies the same Clerk session for every private operation.

The active product no longer depends on Discord.

## Repository layout

```text
apps/
  api/                     FastAPI HTTP service and API tests
  converter/               Private LibreOffice conversion service
  web/                     Astro SSR app, Tailwind UI, and Clerk controls
packages/
  forge-core/              Document engine, CLI, and core tests
infra/
  docker/                  API, frontend, gateway, and core images
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
| `POST` | `/api/v1/forge-briefs` | Analyze evidence for the signed-in user's `/app` workspace. |
| `GET` | `/api/v1/resumes` | List resume sources owned by the signed-in user. |
| `POST` | `/api/v1/resumes/imports` | Import up to five PDF/DOCX resume sources for review. |
| `GET`, `DELETE` | `/api/v1/resumes/{id}` | Read or delete one owned resume source. |
| `GET` | `/api/v1/resumes/{id}/editable.docx` | Render the current private draft as an editable Word document. |
| `PUT` | `/api/v1/resumes/{id}/draft` | Save profile, experience, project, education, skill, language, and additional content fields. |
| `POST` | `/api/v1/resumes/{id}/accept` | Approve a reviewed source as a named role version. |
| `GET` | `/api/v1/resume-variants` | List the signed-in user's approved versions. |
| `GET` | `/api/v1/generated-documents` | List private generated files owned by the signed-in user. |
| `POST` | `/api/v1/resume-variants/{id}/render` | Render an owned version as a private DOCX/PDF bundle. |
| `GET` | `/api/v1/documents/{id}/download` | Download an owned generated document. |
| `POST` | `/api/v1/job-matches` | Analyze pasted or uploaded job-description content against an owned resume. |
| `POST` | `/api/v1/job-matches/{id}/tailor` | Generate an evidence-grounded DOCX/PDF bundle for a Match or Some match result. |
| `GET` | `/api/v1/job-match-documents/{id}/download` | Download an owned tailored resume document. |

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

Service submissions receive an opaque `req_…` reference. Forge workspace briefs require a valid Clerk session and are stored with the authenticated Clerk user ID. They receive an opaque `frg_…` reference and a deterministic analysis of supported language, evidence gaps, and the strongest source passages. Both are stored in the SQLite database configured by `FORGE_DATABASE`; no public endpoint exposes submitted customer details or career evidence.

## Containers

The Compose stack builds the FastAPI service, private LibreOffice/Tesseract converter, Astro SSR frontend, and Nginx gateway. Nginx rate-limits write endpoints, while SQLite state remains in a named volume. Local resume objects use the private state volume. Production uses the authenticated `axelyn-forge-storage` Worker and a private R2 bucket; its bearer token stays server-only. The converter has no published port, uses a read-only filesystem and bounded concurrency, validates each PDF before the API stores it, and extracts text from PNG/JPEG job-post screenshots. A separate core image in `infra/docker/core.Dockerfile` provides the `forge` CLI without baking private candidate files into any image.

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
clerk doctor
```

CI runs the Python tests, checks and builds the Astro app, and builds the API, converter, frontend, gateway, and core container images. Pushes to `main` and version tags publish all five images to GitHub Container Registry.

## Private data

Keep `.env`, candidate DOCX files, SQLite databases, generated output, and `.forge-private/` out of Git. Service requests contain personal information; back up and restrict access to the `forge-state` volume according to your retention policy.
