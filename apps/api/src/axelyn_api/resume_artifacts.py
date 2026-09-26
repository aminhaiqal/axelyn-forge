"""Build portable JSON and JSON Schema artifacts for private resume sources."""

from __future__ import annotations

from .models import ResumeDraft, ResumePackageSource, ResumeSourcePackage
from .resume_import import encode_json, rendered_resume_sections, sdt_template_values


JSON_MEDIA_TYPE = "application/json"
JSON_SCHEMA_MEDIA_TYPE = "application/schema+json"
RESUME_SCHEMA_ID = "https://forge.axelyn.com/schemas/resume-source-v1.schema.json"


def build_resume_package(
    *,
    draft: dict[str, object],
    display_name: str,
    target_role: str | None,
    original_filename: str,
) -> bytes:
    package = ResumeSourcePackage(
        source=ResumePackageSource(
            display_name=display_name,
            target_role=target_role,
            original_filename=original_filename,
        ),
        resume=ResumeDraft.model_validate(draft),
        rendered_sections=rendered_resume_sections(draft),
        template_values=sdt_template_values(draft),
    )
    return encode_json(package.model_dump(mode="json", by_alias=True))


def build_resume_schema() -> bytes:
    schema = ResumeSourcePackage.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = RESUME_SCHEMA_ID
    schema["title"] = "Axelyn Forge Resume Source"
    schema["description"] = (
        "Portable structured resume content generated from a normalized Word source."
    )
    return encode_json(schema)
