import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .api import apply_resume_operations_file, inspect_template, render_resume, validate_resume_file
from .errors import ForgeError
from .context_selection import DEFAULT_CONTEXT_SELECTION_MODEL
from .context_store import SQLiteContextStore, sync_context_database
from .job_source import DEFAULT_WEB_SEARCH_MODEL
from .openai_provider import DEFAULT_OPENAI_MODEL
from .tailoring import tailor_resume_with_openai
from .usage_store import OpenAIUsageStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Render canonical resume JSON into SDT-enabled DOCX templates.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect = subcommands.add_parser("inspect", help="list tagged content controls in a DOCX")
    inspect.add_argument("--template", required=True, type=Path)

    validate = subcommands.add_parser("validate", help="validate canonical resume JSON")
    validate.add_argument("--data", required=True, type=Path)
    validate.add_argument("--schema", type=Path, default=Path("schemas/profile.schema.json"))

    apply = subcommands.add_parser(
        "apply",
        help="apply AI-authored semantic operations to canonical resume JSON",
    )
    apply.add_argument("--data", required=True, type=Path)
    apply.add_argument("--operations", required=True, type=Path)
    apply.add_argument("--output-data", required=True, type=Path)
    apply.add_argument("--schema", type=Path, default=Path("schemas/profile.schema.json"))

    context_index = subcommands.add_parser(
        "context-index",
        help="parse verified Markdown context into a SQLite chunk database",
    )
    context_index.add_argument("--context", required=True, type=Path)
    context_index.add_argument("--database", required=True, type=Path)

    context_list = subcommands.add_parser(
        "context-list",
        help="list persisted context chunks from SQLite",
    )
    context_list.add_argument("--database", required=True, type=Path)

    usage_list = subcommands.add_parser(
        "usage-list",
        help="list OpenAI request, token, and estimated-cost ledger rows",
    )
    usage_list.add_argument("--database", required=True, type=Path)
    usage_list.add_argument("--workflow-id")
    usage_list.add_argument("--limit", type=int, default=100)

    usage_summary = subcommands.add_parser(
        "usage-summary",
        help="summarize OpenAI token usage and estimated cost from SQLite",
    )
    usage_summary.add_argument("--database", required=True, type=Path)
    usage_summary.add_argument("--workflow-id")

    render = subcommands.add_parser("render", help="validate, bind, and render a new DOCX")
    render.add_argument("--template", required=True, type=Path)
    render.add_argument("--data", required=True, type=Path)
    render.add_argument("--bindings", required=True, type=Path)
    render.add_argument("--output", required=True, type=Path)
    render.add_argument("--schema", type=Path, default=Path("schemas/profile.schema.json"))
    render.add_argument(
        "--allow-unbound",
        action="store_true",
        help="leave template controls with no binding unchanged",
    )

    tailor = subcommands.add_parser(
        "tailor",
        help="use OpenAI to turn a JD into validated resume JSON and DOCX",
    )
    job_source = tailor.add_mutually_exclusive_group(required=True)
    job_source.add_argument("--jd", type=Path, help="UTF-8 job-description file")
    job_source.add_argument(
        "--jd-url",
        help="public job-posting URL retrieved with OpenAI web search",
    )
    tailor.add_argument(
        "--context",
        type=Path,
        help="optional verified candidate-context Markdown file or directory",
    )
    tailor.add_argument(
        "--context-db",
        type=Path,
        help="SQLite chunk database (defaults to data/context.sqlite3 when --context is used)",
    )
    tailor.add_argument(
        "--usage-db",
        type=Path,
        help=(
            "SQLite OpenAI usage ledger (defaults to --context-db, otherwise "
            "data/context.sqlite3)"
        ),
    )
    tailor.add_argument("--template", required=True, type=Path)
    tailor.add_argument("--data", required=True, type=Path)
    tailor.add_argument("--bindings", required=True, type=Path)
    tailor.add_argument("--output-dir", required=True, type=Path)
    tailor.add_argument("--schema", type=Path, default=Path("schemas/profile.schema.json"))
    tailor.add_argument(
        "--model",
        help="OpenAI model (defaults to OPENAI_MODEL or gpt-5.6-terra)",
    )
    tailor.add_argument(
        "--context-model",
        help="context selector model (defaults to OPENAI_CONTEXT_MODEL or gpt-5.6-luna)",
    )
    tailor.add_argument(
        "--web-model",
        help="URL retrieval model (defaults to OPENAI_WEB_MODEL or gpt-5.6-luna)",
    )
    tailor.add_argument(
        "--filename-prefix",
        default="Amin_Haiqal_Resume",
        help="safe prefix used before the model-extracted job title",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            controls = inspect_template(args.template)
            print(json.dumps([control.as_dict() for control in controls], indent=2, ensure_ascii=False))
            return 0

        if args.command == "validate":
            validate_resume_file(args.data, args.schema)
            print(f"Valid resume: {args.data}")
            return 0

        if args.command == "apply":
            report = apply_resume_operations_file(
                data=args.data,
                schema=args.schema,
                operations=args.operations,
                output=args.output_data,
            )
            print(f"Tailored resume JSON: {report.output}")
            print(f"Applied operations: {report.applied_operations}")
            return 0

        if args.command == "context-index":
            report = sync_context_database(args.context, args.database)
            print(f"Context database: {report.database}")
            print(f"Documents: {report.documents}; chunks: {report.chunks}")
            return 0

        if args.command == "context-list":
            chunks = SQLiteContextStore(args.database).load_chunks()
            print(
                json.dumps(
                    [chunk.as_prompt_dict() for chunk in chunks],
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "usage-list":
            requests = OpenAIUsageStore(args.database).list_requests(
                limit=args.limit,
                workflow_id=args.workflow_id,
            )
            print(json.dumps(requests, indent=2, ensure_ascii=False))
            return 0

        if args.command == "usage-summary":
            summary = OpenAIUsageStore(args.database).summary(
                workflow_id=args.workflow_id,
            )
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 0

        if args.command == "tailor":
            model = args.model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
            context_model = args.context_model or os.environ.get(
                "OPENAI_CONTEXT_MODEL", DEFAULT_CONTEXT_SELECTION_MODEL
            )
            web_model = args.web_model or os.environ.get(
                "OPENAI_WEB_MODEL", DEFAULT_WEB_SEARCH_MODEL
            )
            context_database = args.context_db
            if args.context is not None and context_database is None:
                context_database = Path("data/context.sqlite3")
            usage_database = args.usage_db or context_database or Path("data/context.sqlite3")
            result = tailor_resume_with_openai(
                template=args.template,
                data=args.data,
                schema=args.schema,
                bindings=args.bindings,
                job_description=args.jd,
                job_description_url=args.jd_url,
                candidate_context=args.context,
                context_database=context_database,
                usage_database=usage_database,
                output_dir=args.output_dir,
                candidate_prefix=args.filename_prefix,
                model=model,
                context_selection_model=context_model,
                web_search_model=web_model,
            )
            print(f"OpenAI model: {result.model}")
            print(f"OpenAI workflow ID: {result.workflow_id}")
            print(f"OpenAI usage database: {result.usage_database}")
            if result.job_source_output is not None:
                print(f"Web search model: {result.web_search_model}")
                print(f"Job source: {result.job_source_output}")
            if result.context_selection_output is not None:
                print(f"Context selection model: {result.context_selection_model}")
                if result.context_database is not None:
                    print(f"Context database: {result.context_database}")
                print(f"Context selection: {result.context_selection_output}")
            if result.keyword_alignment_output is not None:
                print(f"Keyword alignment: {result.keyword_alignment_output}")
            if result.keyword_coverage is not None:
                coverage = result.keyword_coverage
                print(
                    "Evidence-backed keyword coverage: "
                    f"{coverage['surfacedAfter']}/{coverage['targetedKeywords']} "
                    f"({coverage['percentage']:.1f}%)"
                )
                if coverage["changedSections"]:
                    print("Sections tailored: " + ", ".join(coverage["changedSections"]))
            if result.no_op_operations_removed:
                print(
                    "No-op operations removed: "
                    + ", ".join(result.no_op_operations_removed)
                )
            print(f"Tailoring operations: {result.operations_output}")
            print(f"Tailored resume JSON: {result.data_output}")
            print(f"Tailored DOCX: {result.docx_output}")
            print(
                "OpenAI requests: "
                f"{result.usage_summary['requests']}; estimated cost: USD "
                f"{result.usage_summary['estimated_cost_usd']:.8f}"
            )
            if result.usage_summary["web_search_calls"]:
                print(
                    "Web search actions: "
                    f"{result.usage_summary['web_search_calls']}; estimated tool cost: USD "
                    f"{result.usage_summary['web_search_cost_usd']:.8f}"
                )
            if result.usage_summary["unpriced_requests"]:
                print(
                    "Warning: some requests have no public-price estimate; "
                    "inspect the usage ledger for cost_status.",
                    file=sys.stderr,
                )
            if result.gaps:
                print("Material gaps:")
                for gap in result.gaps:
                    print(f"- {gap}")
            return 0

        result = render_resume(
            template=args.template,
            data=args.data,
            schema=args.schema,
            bindings=args.bindings,
            output=args.output,
            strict=not args.allow_unbound,
        )
        report = result.report
        print(f"Rendered DOCX: {report.output}")
        print(
            f"Controls: {report.controls}; changed: {report.changed_controls}; "
            f"unchanged: {report.unchanged_controls}"
        )
        if report.unused_values:
            print("Unused bindings: " + ", ".join(report.unused_values), file=sys.stderr)
        return 0
    except ForgeError as exc:
        print(f"Forge error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
