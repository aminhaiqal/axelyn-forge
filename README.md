# Axelyn Forge

Axelyn Forge validates canonical resume JSON, resolves semantic bindings, and replaces text inside Word Structured Document Tags (SDTs). The DOCX template remains the source of truth for presentation: Forge edits `w:t` payloads without rebuilding paragraphs, runs, tables, numbering, or document layout.

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

The main tailoring model defaults to `gpt-5.6-terra`. The context selector and URL retriever default to `gpt-5.6-luna`. Override them independently with `OPENAI_MODEL` / `--model`, `OPENAI_CONTEXT_MODEL` / `--context-model`, and `OPENAI_WEB_MODEL` / `--web-model`; use pinned model snapshots when repeatable AI behavior matters. The validated renderer remains deterministic regardless of model choice.

After resolving the JD input, `--context` adds a context-selection call before the main tailoring call. URL input adds one earlier web-search call:

1. Forge locally splits the Markdown file or directory into source-aware, stable context chunks.
2. The complete chunk snapshot is transactionally synchronized to SQLite (`data/context.sqlite3` by default).
3. The selector reads stored chunks, receives the JD and chunk catalog, then returns ranked chunk IDs, role signals, and material gaps.
4. Forge rejects unknown, duplicate, empty, or excessive selections and resolves accepted IDs from SQLite.
5. The main tailoring call receives the canonical resume and only the selected context chunks verbatim.
6. Protected-field checks, schema validation, binding, and deterministic DOCX rendering run locally.

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

SQLite stores the schema version, source-document hashes and lengths, and each chunk's stable ID, source path, ordinal, heading hierarchy, verbatim content, and content hash. Synchronization replaces the previous snapshot inside one transaction; Markdown remains the editable source of truth.

### OpenAI request costs in SQLite

Every OpenAI call made by the `tailor` workflow creates an `llm_requests` ledger row before the request starts. URL retrieval, context selection, and main tailoring share one workflow ID but remain separate rows. Successful rows capture:

- requested and actual model, service tier, response ID, response status, and duration;
- input, ordinary input, cached input, cache-write, output, reasoning, and total tokens;
- the versioned public-pricing row and rate snapshot used for the estimate;
- ordinary-input, cached-input, cache-write, output, web-search tool, and total estimated USD costs.

The same workflow ID and usage-database path are written into the generated operations, job-source, and context-selection audit JSON, so an output resume can be traced back to all of its cost rows.

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

The command produces auditable files named from the model-extracted job title. URL input adds the first file below, and context selection adds the second:

- `Amin_Haiqal_Resume_[Job_Title].job-source.json`
- `Amin_Haiqal_Resume_[Job_Title].context-selection.json`
- `Amin_Haiqal_Resume_[Job_Title].operations.json`
- `Amin_Haiqal_Resume_[Job_Title].json`
- `Amin_Haiqal_Resume_[Job_Title].docx`

The context-selection call sends the JD and full indexed context catalog to OpenAI. The main call sends the JD, canonical resume, explicit editable-target catalog, selection signals, and selected context excerpts. URL ingestion sends only the requested URL and retrieval instructions. All calls use `store=False`. Provider output cannot modify protected identity, contact, employer, role, date, education, type, or stable-ID fields.

## Discord bot

Forge can run as a private Discord Gateway bot on a small VPS. It makes an outbound connection to Discord, so the VPS does not need a domain, TLS certificate, reverse proxy, or public application port.

The bot registers one grouped slash command with three mutually exclusive input options:

```text
/forge tailor jd:<job-description-text>
/forge tailor file:<job-description.txt>
/forge tailor url:<https://company.example/jobs/123>
```

Discord slash-command values are named options, so pasted text uses `jd:` rather than an unnamed positional argument. Forge requires exactly one of `jd`, `file`, or `url`. Direct `jd` input is limited by Discord to 6,000 characters. File input is limited to a non-empty UTF-8 `.txt` file; URL input passes through the same public-URL validation and OpenAI web-search ingestion as the CLI.

The command acknowledges the interaction privately, runs the blocking Forge workflow outside Discord's event loop, and edits the private response with the generated DOCX, request count, estimated OpenAI cost, and material-gap count. Only one request runs at a time. A concurrent request receives a private busy response instead of waiting behind an expiring Discord interaction.

Access is default-deny. `DISCORD_ALLOWED_USER_IDS` must contain at least one numeric user ID. No message-content or other privileged Gateway intent is used, and all command responses are ephemeral.

### Discord application setup

1. Create an application in the Discord Developer Portal and add a bot.
2. Keep all privileged Gateway intents disabled.
3. Install the app in a private test server with the `bot` and `applications.commands` scopes. Grant only the permissions needed to use commands, send messages, and attach files.
4. Enable Developer Mode in Discord, then copy your user ID and test-server ID.
5. Copy `.env.example` to `.env` and replace the placeholder values. Never commit `.env` or paste either token into chat.

Setting `DISCORD_GUILD_ID` keeps the command scoped to one server and makes command updates appear immediately during development. If it is omitted, Forge registers the command globally while still enforcing the user allowlist.

### VPS deployment

Docker Compose runs the bot as an unprivileged user with a read-only container filesystem. The named `forge-state` volume is the only persistent writable location and contains the SQLite context/cost database plus generated artifacts.

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

Back up the `forge-state` volume regularly. SQLite, generated resume JSON, and DOCX files can contain personal information and should not be placed in a public directory.

## Binding paths

A source beginning with `document` is an absolute semantic path, such as `document.profile.fullName`. Any other source begins with a stable canonical ID, such as `experience-axelyn.role` or `aria-highlight-1.text`. Bindings can join arrays, compose several values with a separator, select a link by semantic fields, split one semantic value across fixed continuation slots, and intentionally emit a literal value.

## Tests

```bash
.venv/bin/python -m unittest discover -v
```

The suite covers schema failures, duplicate stable IDs, SDT discovery, complete binding coverage, identity rendering, multiple and Unicode replacements, preservation of paragraph/run properties, missing bindings, source-template protection, and output archive validity.
