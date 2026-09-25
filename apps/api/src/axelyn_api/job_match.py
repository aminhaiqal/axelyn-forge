"""Evidence-grounded job matching and deterministic resume prioritization."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Iterable

from .models import JobMatchAnalysis, RoleAlignmentInput
from .role_alignment import analyze_role_alignment
from .resume_import import ResumeImportError, extract_resume


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
TEXT_SUFFIXES = {".txt"}
DOCUMENT_SUFFIXES = {".docx", ".pdf"}
JOB_FILE_SUFFIXES = IMAGE_SUFFIXES | TEXT_SUFFIXES | DOCUMENT_SUFFIXES
MAX_JOB_DESCRIPTION_CHARACTERS = 20_000
BULLET_PREFIXES = ("•", "-", "–")
DATE_PATTERN = re.compile(
    r"(?:19|20)\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")


def extract_job_document(filename: str, payload: bytes) -> str:
    """Extract a text, DOCX, or PDF job-description attachment."""
    suffix = Path(filename).suffix.casefold()
    if suffix == ".txt":
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ResumeImportError("TXT job descriptions must use UTF-8 encoding.") from error
        return text.strip()
    if suffix in DOCUMENT_SUFFIXES:
        return extract_resume(filename, payload).text.strip()
    if suffix in IMAGE_SUFFIXES:
        raise ResumeImportError("Image job descriptions require OCR processing.")
    raise ResumeImportError("Use PDF, DOCX, TXT, PNG, JPG, or JPEG job-description files.")


def combine_job_description(parts: Iterable[str]) -> str:
    text = "\n\n".join(part.strip() for part in parts if part.strip()).strip()
    if len(text) < 100:
        raise ValueError("Add at least 100 characters of readable job-description text.")
    if len(text) > MAX_JOB_DESCRIPTION_CHARACTERS:
        raise ValueError(
            f"Job-description text is limited to {MAX_JOB_DESCRIPTION_CHARACTERS:,} characters."
        )
    return text


def draft_to_evidence_text(draft: dict[str, object]) -> str:
    """Build analysis text from the latest structured draft, not a stale upload."""
    values = [
        str(draft.get("full_name") or ""),
        str(draft.get("headline") or ""),
        str(draft.get("summary") or ""),
    ]
    sections = draft.get("sections")
    if isinstance(sections, dict):
        for section in (
            "experience",
            "projects",
            "education",
            "skills",
            "languages",
            "additional",
        ):
            lines = sections.get(section)
            if isinstance(lines, list):
                values.extend(str(line) for line in lines)
    custom_sections = draft.get("custom_sections")
    if isinstance(custom_sections, list):
        for custom in custom_sections:
            if not isinstance(custom, dict):
                continue
            values.append(str(custom.get("title") or ""))
            lines = custom.get("lines")
            if isinstance(lines, list):
                values.extend(str(line) for line in lines)
    text = "\n".join(value.strip() for value in values if value.strip())
    return text or str(draft.get("extracted_text") or "")


def analyze_job_match(
    *,
    target_role: str,
    company: str | None,
    job_description: str,
    resume_text: str,
) -> JobMatchAnalysis:
    alignment = analyze_role_alignment(
        RoleAlignmentInput(
            target_role=target_role,
            company=company,
            job_description=job_description,
            career_evidence=resume_text,
        )
    )
    score = alignment.coverage_score
    if score >= 70:
        match_state = "match"
        label = "Match"
        lead = (
            "This resume supports most of the role's priority language with direct, "
            "verifiable evidence."
        )
    elif score >= 40:
        match_state = "some_match"
        label = "Some match"
        lead = (
            "This resume has useful overlap, but several priority requirements do not "
            "appear in the current evidence."
        )
    else:
        match_state = "no_match"
        label = "No match"
        lead = (
            "This resume does not contain enough direct evidence for the role's priority "
            "requirements."
        )

    reasons = [lead]
    if alignment.matched_keywords:
        reasons.append(
            "Supported by current evidence: "
            + ", ".join(alignment.matched_keywords[:6])
            + "."
        )
    if alignment.gap_keywords:
        reasons.append(
            "Missing from the selected resume: "
            + ", ".join(alignment.gap_keywords[:6])
            + "."
        )

    recommendations: list[str] = []
    for keyword in alignment.gap_keywords[:5]:
        recommendations.append(
            f"Add {keyword} only if you can support it with a concrete project, responsibility, or result."
        )
    if match_state == "no_match":
        recommendations.append(
            "Build or document relevant experience before tailoring this resume to the role."
        )
    else:
        recommendations.append(
            "Lead with the strongest matching evidence and keep unsupported requirements out."
        )

    return JobMatchAnalysis(
        match_percentage=score,
        match_state=match_state,
        match_label=label,
        matched_keywords=alignment.matched_keywords,
        missing_keywords=alignment.gap_keywords,
        evidence_highlights=alignment.evidence_highlights,
        reasons=reasons,
        recommendations=recommendations,
        can_generate=match_state != "no_match",
    )


def _tokens(value: str) -> set[str]:
    return {token.casefold().strip(".-") for token in TOKEN_PATTERN.findall(value)}


def _relevance(value: str, keywords: set[str]) -> int:
    return len(_tokens(value) & keywords)


def _entry_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for index, line in enumerate(lines):
        is_bullet = line.startswith(BULLET_PREFIXES)
        nearby = lines[max(0, index - 1) : index + 2]
        starts_entry = (
            current
            and not is_bullet
            and any(DATE_PATTERN.search(value) for value in nearby)
            and any(item.startswith(BULLET_PREFIXES) for item in current)
        )
        if starts_entry:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _prioritize_entries(lines: list[str], keywords: set[str]) -> list[str]:
    blocks = _entry_blocks(lines)
    prioritized: list[tuple[int, int, list[str]]] = []
    for index, block in enumerate(blocks):
        plain = [line for line in block if not line.startswith(BULLET_PREFIXES)]
        bullets = [line for line in block if line.startswith(BULLET_PREFIXES)]
        ordered_bullets = [
            line
            for _, _, line in sorted(
                (
                    (-_relevance(line, keywords), bullet_index, line)
                    for bullet_index, line in enumerate(bullets)
                )
            )
        ]
        ordered = [*plain, *ordered_bullets]
        prioritized.append((-_relevance(" ".join(block), keywords), index, ordered))
    return [line for _, _, block in sorted(prioritized) for line in block]


def tailor_resume_draft(
    draft: dict[str, object],
    *,
    target_role: str,
    matched_keywords: list[str],
) -> dict[str, object]:
    """Prioritize relevant source material without rewriting or inventing claims."""
    tailored = copy.deepcopy(draft)
    tailored["target_role"] = target_role
    if not str(tailored.get("headline") or "").strip():
        tailored["headline"] = target_role
    keywords = {keyword.casefold() for keyword in matched_keywords}
    sections = tailored.get("sections")
    if not isinstance(sections, dict):
        return tailored
    for name in ("experience", "projects"):
        lines = sections.get(name)
        if isinstance(lines, list):
            sections[name] = _prioritize_entries([str(line) for line in lines], keywords)
    skills = sections.get("skills")
    if isinstance(skills, list):
        sections["skills"] = [
            line
            for _, _, line in sorted(
                (
                    (-_relevance(str(line), keywords), index, str(line))
                    for index, line in enumerate(skills)
                )
            )
        ]
    return tailored
