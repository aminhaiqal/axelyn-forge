# Axelyn Forge

Axelyn Forge validates canonical resume and cover-letter JSON, resolves semantic bindings, and replaces text inside Word Structured Document Tags (SDTs). DOCX templates remain the source of truth for presentation: Forge edits `w:t` payloads without rebuilding paragraphs, runs, tables, numbering, or document layout. Tailoring also creates PDF derivatives through headless LibreOffice for convenient delivery.

Current version: `0.2.0`. Releases follow semantic versioning and are recorded in `CHANGELOG.md` and Git tags.

## Setup

Python 3.9 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Inspect and render

List every tagged content control discovered across the Word XML parts:

```bash
.venv/bin/forge inspect \
  --template templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx
```

Render the included canonical resume and fixed-slot binding fixture:

```bash
.venv/bin/forge render \
  --template templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx \
  --data data/profile.json \
  --bindings bindings/software-engineer.json \
  --output output/amin.docx
```

`schemas/profile.schema.json` is the default schema. Supply `--schema` to use a different one. Rendering validates the data and resolves all bindings before it writes an output file. The source template can never be used as the output path.

Convert any existing Forge DOCX to PDF without modifying the source document:

```bash
.venv/bin/forge docx-to-pdf \
  --input output/amin.docx \
  --output output/amin.pdf

# Equivalent convenience script when `forge` is on PATH:
scripts/docx-to-pdf.sh output/amin.docx output/amin.pdf
```

The standalone command requires LibreOffice Writer. The Docker image already includes it. PDF conversion uses an isolated temporary LibreOffice profile, validates the resulting PDF, and atomically replaces the requested output only after success.

## AI tailoring boundary

An AI agent can express job-specific content changes as semantic operations against stable IDs, then Forge applies and validates them before rendering. For example:

```json
{
  "operations": [
    {
      "operation": "rewrite",
      "target": "summary-1",
      "value": "A truthful job-targeted summary..."
    },
    {
      "operation": "rewrite",
      "target": "skills-programming",
      "field": "items",
      "value": ["TypeScript", "Python", "SQL"]
    }
  ]
}
```

Apply the operations to a copy of the canonical JSON:

```bash
.venv/bin/forge apply \
  --data data/profile.json \
  --operations tailoring/example.operations.json \
  --output-data output/tailored.resume.json
```

The AI layer never edits DOCX XML. Unsupported operations, unknown IDs, invalid fields, and any result that fails the resume schema are rejected without writing output.

### OpenAI provider

Forge uses the OpenAI Responses API with strict Structured Outputs. Set the API key in your shell; there is intentionally no CLI key argument and Forge never writes or prints it:

```bash
export OPENAI_API_KEY="your-project-api-key"
```

Save or attach a JD as a UTF-8 text file, then run the complete workflow:

```bash
.venv/bin/forge tailor \
  --jd /path/to/job-description.txt \
  --context context/ \
  --template templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx \
  --data data/profile.json \
  --bindings bindings/software-engineer.json \
  --output-dir output
```

Cover-letter generation is enabled by default. It uses
`templates/Amin_Haiqal_Cover_Letter_SDT_Template.docx`, validates the generated
semantic document with `schemas/cover-letter.schema.json`, and resolves
`bindings/cover-letter.json`. Derived cover letters receive company- and role-specific
document metadata so stale application details cannot leak from the source template.
Add `--no-cover-letter` to emit only the resume.

Alternatively, supply a public job-posting URL. Forge uses OpenAI web search to read the exact posting before context selection and tailoring:

```bash
.venv/bin/forge tailor \
  --jd-url "https://careers.example.com/jobs/123" \
  --context-db data/context.sqlite3 \
  --template templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx \
  --data data/profile.json \
  --bindings bindings/software-engineer.json \
  --output-dir output
```

`--jd` and `--jd-url` are mutually exclusive. URL ingestion accepts only public HTTP(S) URLs, constrains search to the supplied hostname, and fails rather than substituting a different posting when the exact page is unavailable. The normalized job text and retrieved source URLs are saved in `Amin_Haiqal_Resume_[Job_Title].job-source.json`.

The main tailoring and cover-letter models default to `gpt-5.6-terra`. The context selector and URL retriever default to `gpt-5.6-luna`. Override them independently with `OPENAI_MODEL` / `--model`, `OPENAI_COVER_LETTER_MODEL` / `--cover-letter-model`, `OPENAI_CONTEXT_MODEL` / `--context-model`, and `OPENAI_WEB_MODEL` / `--web-model`; use pinned model snapshots when repeatable AI behavior matters. The validated renderer remains deterministic regardless of model choice.

After resolving the JD input, `--context` adds a context-selection call before the main tailoring call. URL input adds one earlier web-search call:

1. Forge locally splits Markdown documents and JSON evidence records into source-aware, stable context chunks.
2. The complete chunk snapshot is transactionally synchronized to SQLite (`data/context.sqlite3` by default).
3. The selector reads stored chunks, receives the JD and chunk catalog, then returns ranked chunk IDs, role signals, and material gaps.
4. Forge rejects unknown, duplicate, empty, or excessive selections and resolves accepted IDs from SQLite.
5. The main tailoring call receives the canonical resume and only the selected context chunks verbatim.
6. Protected-field checks produce the validated tailored resume locally.
7. When enabled, a separate structured call writes nine complete, evidence-referenced cover-letter paragraphs using the tailored resume and the same selected context.
8. Forge assembles protected identity and application fields, validates both canonical documents, and renders both DOCX templates.
9. Headless LibreOffice converts the finished DOCX files into validated PDFs; the DOCX files remain untouched.

Index or refresh the database independently:

```bash
.venv/bin/forge context-index \
  --context context/ \
  --database data/context.sqlite3
```

Inspect the persisted chunks:

```bash
.venv/bin/forge context-list --database data/context.sqlite3
```

To tailor from an existing database without reparsing Markdown, omit `--context` and supply `--context-db data/context.sqlite3`. When `--context context/` is supplied without `--context-db`, the CLI automatically uses `data/context.sqlite3`.

SQLite stores the schema version, source-document hashes and lengths, and each chunk's stable ID, source path, ordinal, heading hierarchy, content, and content hash. Synchronization replaces the previous snapshot inside one transaction; Markdown documents and JSON evidence files remain the editable sources of truth.

### OpenAI request costs in SQLite

Every OpenAI call made by the `tailor` workflow creates an `llm_requests` ledger row before the request starts. URL retrieval, context selection, main tailoring, and optional cover-letter generation share one workflow ID but remain separate rows. Keyword extraction is part of the existing context-selection response, so alignment does not add another OpenAI request. Disabling the cover letter skips its request entirely. Successful rows capture:

- requested and actual model, service tier, response ID, response status, and duration;
- input, ordinary input, cached input, cache-write, output, reasoning, and total tokens;
- the versioned public-pricing row and rate snapshot used for the estimate;
- ordinary-input, cached-input, cache-write, output, web-search tool, and total estimated USD costs.

The same workflow ID and usage-database path are written into the generated operations, job-source, context-selection, and keyword-alignment audit JSON, so an output resume can be traced back to all of its cost rows.

A provider failure remains in the ledger with `status=failed`, the exception details, and a null cost because OpenAI returned no usage data. A process interrupted during a call leaves `status=started`, making incomplete accounting visible. Prompt text, resume data, job-description text, and API keys are never stored in the usage tables.

By default, usage is stored in the same `data/context.sqlite3` file as context chunks. A custom `--context-db` becomes the usage database too unless `--usage-db` is supplied explicitly:

```bash
.venv/bin/forge tailor \
  --jd /path/to/job-description.txt \
  --context context/ \
  --context-db data/context.sqlite3 \
  --usage-db data/context.sqlite3 \
  --template templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx \
  --data data/profile.json \
  --bindings bindings/software-engineer.json \
  --output-dir output
```

List individual requests or summarize all recorded spend:

```bash
.venv/bin/forge usage-list --database data/context.sqlite3
.venv/bin/forge usage-summary --database data/context.sqlite3
```

Both commands accept `--workflow-id`; `usage-list` also accepts `--limit`.

Cost is explicitly recorded as an estimate based on the public standard-service price snapshot, not as an invoice amount. The seeded GPT-5.6 rates account for the separate cached-read and cache-write categories and apply the published long-context multipliers above 272K input tokens. Web retrieval also records the current $10 per 1,000 search-action price plus model-rate search-content tokens. Contract discounts, regional-processing uplifts, and future pricing changes can make billed cost differ. Current rates are sourced from the [OpenAI model pricing comparison](https://developers.openai.com/api/docs/models/compare), [built-in tool pricing](https://developers.openai.com/api/docs/pricing#built-in-tools), and [prompt-caching documentation](https://developers.openai.com/api/docs/guides/prompt-caching#measure-cache-reads-and-writes).

The command produces auditable files named from the model-extracted job title. URL input adds the job-source audit; configured context selection adds both the selection and keyword-alignment audits:

- `Amin_Haiqal_Resume_[Job_Title].job-source.json`
- `Amin_Haiqal_Resume_[Job_Title].context-selection.json`
- `Amin_Haiqal_Resume_[Job_Title].keyword-alignment.json`
- `Amin_Haiqal_Resume_[Job_Title].operations.json`
- `Amin_Haiqal_Resume_[Job_Title].json`
- `Amin_Haiqal_Resume_[Job_Title].docx`
- `Amin_Haiqal_Resume_[Job_Title].pdf`
- `Amin_Haiqal_Cover_Letter_[Company]_[Job_Title].json`
- `Amin_Haiqal_Cover_Letter_[Company]_[Job_Title].docx`
- `Amin_Haiqal_Cover_Letter_[Company]_[Job_Title].pdf`

The context-selection call sends the JD and full indexed context catalog to OpenAI. It also extracts concise employer terminology and classifies each term as required, preferred, or responsibility-level. Forge then deterministically checks those terms against canonical stable-ID entities and the selected verified context. Up to 12 supported terms become `mustSurface` guidance for the main call; unsupported terms remain explicit gaps and cannot become candidate claims. No-op rewrites are removed before operations are applied.

The main call sends the JD, canonical resume, explicit editable-target catalog, selection signals, evidence-backed keyword guidance, and selected context excerpts. The cover-letter call receives the tailored resume and the same verified evidence, but returns complete prose instead of resume operations. Every paragraph must cite allowed resume or context IDs, with `job-description` used for employer-specific statements. URL ingestion sends only the requested URL and retrieval instructions. All calls use `store=False`. Provider output cannot modify protected identity, contact, employer, role, date, education, type, or stable-ID fields. After rendering values are resolved, the keyword-alignment audit reports exact before/after coverage, missing targeted terms, changed Word binding tags, and changed resume sections.

## Discord bot

Forge can run as a private Discord Gateway bot on a small VPS. It makes an outbound connection to Discord, so the VPS does not need a domain, TLS certificate, reverse proxy, or public application port.

The bot registers one grouped slash command with three mutually exclusive JD inputs and an optional cover-letter switch:

```text
/forge tailor jd:<job-description-text>
/forge tailor file:<job-description.txt>
/forge tailor url:<https://company.example/jobs/123>
/forge tailor jd:<job-description-text> cover_letter:False
```

Discord slash-command values are named options, so pasted text uses `jd:` rather than an unnamed positional argument. Forge requires exactly one of `jd`, `file`, or `url`. The optional `cover_letter` boolean defaults to `True`; setting it to `False` skips generation and its OpenAI cost. Forge accepts up to 6,000 normalized characters in direct `jd` input and removes common invisible clipboard artifacts before counting them. If the normalized input is still too long, the error reports the exact count; use a non-empty UTF-8 `.txt` file for longer descriptions. URL input passes through the same public-URL validation and OpenAI web-search ingestion as the CLI.

The command acknowledges the interaction privately, runs the blocking Forge workflow outside Discord's event loop, and edits the private response with four attachments by default: resume DOCX/PDF and cover-letter DOCX/PDF. With `cover_letter:False`, it returns only the two resume files. The response identifies the selected candidate profile and includes request count, estimated OpenAI cost, evidence-backed keyword coverage, changed sections, and material-gap count. Only one request runs at a time across all profiles. A concurrent request receives a private busy response instead of waiting behind an expiring Discord interaction.

Access is default-deny. In the original single-profile mode, `DISCORD_ALLOWED_USER_IDS` must contain at least one numeric user ID and every allowed user runs the same candidate profile. In multi-profile mode, the profile manifest's `discordUsers` mapping is the allowlist and each ID is routed to its configured candidate. No message-content or other privileged Gateway intent is used, and all command responses are ephemeral.

### Multiple candidate profiles

Set `FORGE_PROFILES_FILE` to a private JSON manifest to enable multi-profile mode. Relative asset paths are resolved from the manifest's directory. Every candidate has isolated resume data, cover-letter data, context, SQLite context/usage database, and output directory; Forge refuses to start if distinct profiles share any of those paths. Templates, schemas, and bindings may be shared when their structures are compatible.

```json
{
  "schemaVersion": "1",
  "profiles": {
    "amin": {
      "displayName": "Muhammad Amin Haiqal",
      "template": "/app/templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx",
      "data": "/app/data/profile.json",
      "schema": "/app/schemas/profile.schema.json",
      "bindings": "/app/bindings/software-engineer.json",
      "coverLetterTemplate": "/app/templates/Amin_Haiqal_Cover_Letter_SDT_Template.docx",
      "coverLetterData": "/app/data/cover_letter.json",
      "coverLetterSchema": "/app/schemas/cover-letter.schema.json",
      "coverLetterBindings": "/app/bindings/cover-letter.json",
      "context": "/app/context",
      "database": "/state/profiles/amin/context.sqlite3",
      "outputDir": "/state/profiles/amin/output",
      "filenamePrefix": "Amin_Haiqal_Resume",
      "coverLetterPrefix": "Amin_Haiqal_Cover_Letter"
    },
    "second-candidate": {
      "displayName": "Second Candidate",
      "template": "/state/profiles/second-candidate/resume.docx",
      "data": "/state/profiles/second-candidate/resume.json",
      "schema": "/app/schemas/profile.schema.json",
      "bindings": "/state/profiles/second-candidate/resume-bindings.json",
      "coverLetterTemplate": "/state/profiles/second-candidate/cover-letter.docx",
      "coverLetterData": "/state/profiles/second-candidate/cover-letter.json",
      "coverLetterSchema": "/app/schemas/cover-letter.schema.json",
      "coverLetterBindings": "/state/profiles/second-candidate/cover-letter-bindings.json",
      "context": "/state/profiles/second-candidate/context",
      "database": "/state/profiles/second-candidate/context.sqlite3",
      "outputDir": "/state/profiles/second-candidate/output",
      "filenamePrefix": "Second_Candidate_Resume",
      "coverLetterPrefix": "Second_Candidate_Cover_Letter"
    }
  },
  "discordUsers": {
    "111111111111111111": "amin",
    "222222222222222222": "second-candidate"
  }
}
```

Replace the example Discord IDs with the real numeric IDs. Keep the manifest and the second candidate's personal files out of Git. In the Docker deployment, store them under the persistent `/state` volume, set `FORGE_PROFILES_FILE=/state/profiles.json`, and restart the bot. Adding `FORGE_PROFILES_FILE` switches authorization to the manifest; the legacy `DISCORD_ALLOWED_USER_IDS` value is ignored.

### Discord application setup

1. Create an application in the Discord Developer Portal and add a bot.
2. Keep all privileged Gateway intents disabled.
3. Install the app in a private test server with the `bot` and `applications.commands` scopes. Grant only the permissions needed to use commands, send messages, and attach files.
4. Enable Developer Mode in Discord, then copy your user ID and test-server ID.
5. Copy `.env.example` to `.env` and replace the placeholder values. Never commit `.env` or paste either token into chat.

Setting `DISCORD_GUILD_ID` keeps the command scoped to one server and makes command updates appear immediately during development. If it is omitted, Forge registers the command globally while still enforcing the user allowlist.

### VPS deployment

Docker Compose runs the bot as an unprivileged user with a read-only container filesystem. The named `forge-state` volume is the only persistent writable location and contains the SQLite context/cost database plus generated artifacts. The image includes LibreOffice Writer and maps the template's unembedded Aptos, Calibri, Cambria, and Courier fonts to available substitutes, including metric-compatible replacements where available. Because Microsoft Word and LibreOffice use different layout engines, inspect the PDF fixture after template or font changes; the DOCX remains the authoritative document.

```bash
cp .env.example .env
chmod 600 .env
# Edit .env locally on the VPS, then:
docker compose up -d --build
docker compose logs -f forge-discord
```

There are no published container ports. The VPS firewall can remain closed except for the SSH access you already use for administration.

Inspect the accumulated OpenAI estimate without entering the container shell:

```bash
docker compose exec forge-discord \
  forge usage-summary --database /state/context.sqlite3
```

Update or restart the service with:

```bash
git pull --ff-only
docker compose up -d --build
```

### Automatic VPS deployment

Pushes to `agent/resume-tailoring-pipeline` run the full test suite and then deploy the exact pushed commit through `.github/workflows/deploy-discord.yml`. GitHub authenticates with a dedicated SSH key that is restricted on the VPS to `scripts/vps-deploy.sh`; it is not a general-purpose shell credential.

The VPS keeps immutable releases under `/home/debian/apps/axelyn-forge-deploy/releases`. A deployment rebuilds and recreates the bot, waits for a successful Discord Gateway connection, and updates the `current` release link only after verification. A failed replacement rolls back to the prior release. The environment file remains at `/home/debian/apps/axelyn-forge/.env`, while SQLite and generated artifacts remain in the existing `forge-state` Docker volume.

The GitHub `production` environment uses these repository secrets:

- `VPS_HOST`
- `VPS_USER`
- `VPS_SSH_PRIVATE_KEY`
- `VPS_KNOWN_HOSTS`

If the production branch changes, update both the workflow trigger and `DEPLOY_BRANCH` in `scripts/vps-deploy.sh` together.

Back up the `forge-state` volume regularly. SQLite, generated resume and cover-letter JSON, DOCX, and PDF files can contain personal information and should not be placed in a public directory.

## Binding paths

A source beginning with `document` is an absolute semantic path, such as `document.profile.fullName`. Any other source begins with a stable canonical ID, such as `experience-axelyn.role` or `aria-highlight-1.text`. Bindings can join arrays, compose several values with a separator, select a link by semantic fields, split one semantic value across fixed continuation slots, and intentionally emit a literal value.

## Tests

```bash
.venv/bin/python -m unittest discover -v
```

The suite covers resume and cover-letter schema failures, duplicate stable IDs, SDT discovery, complete binding coverage, evidence-reference validation, protected identity assembly, multiple and Unicode replacements, preservation of paragraph/run properties, missing bindings, source-template protection, DOCX archive validity, atomic PDF conversion, and Discord two-file/four-file delivery.
