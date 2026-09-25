"""Defensive DOCX/PDF text extraction and standard-template normalization."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree
from pypdf import PdfReader


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_DOCX_MEMBERS = 2_000
MAX_PDF_PAGES = 80
WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_PARAGRAPH = f"{{{WORD_NAMESPACE}}}p"
W_TEXT = f"{{{WORD_NAMESPACE}}}t"
W_TAB = f"{{{WORD_NAMESPACE}}}tab"
W_BREAK = f"{{{WORD_NAMESPACE}}}br"
W_NUM_PROPERTIES = f"{{{WORD_NAMESPACE}}}numPr"

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
DATE_PATTERN = re.compile(
    r"(?:19|20)\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
    re.IGNORECASE,
)
SECTION_NAMES = {
    "summary": "summary",
    "profile": "summary",
    "professional summary": "summary",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment history": "experience",
    "projects": "projects",
    "selected projects": "projects",
    "project experience": "projects",
    "education": "education",
    "academic background": "education",
    "skills": "skills",
    "technical skills": "skills",
    "core skills": "skills",
    "languages": "languages",
    "certifications": "additional",
    "achievements": "additional",
    "additional information": "additional",
}
CUSTOM_SECTION_NAMES = {
    "awards": "Awards",
    "honors": "Honors",
    "publications": "Publications",
    "patents": "Patents",
    "volunteering": "Volunteering",
    "volunteer experience": "Volunteer Experience",
    "professional memberships": "Professional Memberships",
    "professional affiliations": "Professional Affiliations",
    "open source": "Open Source",
    "speaking": "Speaking",
    "conferences": "Conferences",
    "military service": "Military Service",
    "security clearance": "Security Clearance",
    "interests": "Interests",
}


class ResumeImportError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedResume:
    media_type: str
    text: str
    warning: str | None
    checksum: str


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_blank_text=False,
        huge_tree=False,
    )


def _clean_lines(values: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for value in values:
        line = re.sub(r"[ \t\u00a0]+", " ", value).strip()
        if line:
            lines.append(line)
    return lines


def _extract_docx(payload: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_MEMBERS:
                raise ResumeImportError("The DOCX contains too many archive members.")
            if any(info.flag_bits & 0x1 for info in infos):
                raise ResumeImportError("Encrypted DOCX files are not supported.")
            expanded_size = sum(info.file_size for info in infos)
            if expanded_size > MAX_DOCX_EXPANDED_BYTES:
                raise ResumeImportError("The expanded DOCX is too large to process safely.")
            names = {info.filename for info in infos}
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ResumeImportError("This file is not a valid DOCX document.")
            if any(name.casefold().endswith("vbaproject.bin") for name in names):
                raise ResumeImportError("Macro-enabled Word documents are not supported.")
            document = archive.read("word/document.xml")
    except zipfile.BadZipFile as error:
        raise ResumeImportError("This file is not a valid DOCX document.") from error

    try:
        root = etree.fromstring(document, _parser())
    except etree.XMLSyntaxError as error:
        raise ResumeImportError("The DOCX document content is malformed.") from error

    paragraphs: list[str] = []
    for paragraph in root.iter(W_PARAGRAPH):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == W_TEXT and node.text:
                parts.append(node.text)
            elif node.tag == W_TAB:
                parts.append("\t")
            elif node.tag == W_BREAK:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            is_list = paragraph.find(f".//{W_NUM_PROPERTIES}") is not None
            paragraphs.append(f"• {text}" if is_list and not text.startswith("•") else text)
    return "\n".join(_clean_lines(paragraphs))


def _extract_pdf(payload: bytes) -> tuple[str, str | None]:
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
    except Exception as error:
        raise ResumeImportError("This file is not a readable PDF document.") from error
    if reader.is_encrypted:
        raise ResumeImportError("Password-protected PDF files are not supported.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ResumeImportError(f"PDF files are limited to {MAX_PDF_PAGES} pages.")

    pages: list[str] = []
    try:
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except Exception as error:
        raise ResumeImportError("The PDF text could not be extracted safely.") from error
    text = "\n".join(_clean_lines("\n".join(pages).splitlines()))
    if not text:
        return "", "No selectable text was found. This PDF may need OCR before import."
    return text, None


def extract_resume(filename: str, payload: bytes) -> ExtractedResume:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf" and payload.startswith(b"%PDF-"):
        text, warning = _extract_pdf(payload)
        media_type = PDF_MEDIA_TYPE
    elif suffix == ".docx" and payload.startswith(b"PK"):
        text = _extract_docx(payload)
        warning = None
        media_type = DOCX_MEDIA_TYPE
    elif suffix not in {".docx", ".pdf"}:
        raise ResumeImportError("Only DOCX and PDF resume files are accepted.")
    else:
        raise ResumeImportError("The file content does not match its extension.")

    if text and len(text) < 40:
        warning = "Very little resume text was extracted. Review it before importing."
    return ExtractedResume(
        media_type=media_type,
        text=text,
        warning=warning,
        checksum=hashlib.sha256(payload).hexdigest(),
    )


def _heading_key(line: str) -> str | None:
    normalized = re.sub(r"[^a-z ]", "", line.casefold()).strip()
    if len(normalized) > 40:
        return None
    return SECTION_NAMES.get(normalized)


def _custom_heading(line: str) -> str | None:
    normalized = re.sub(r"[^a-z ]", "", line.casefold()).strip()
    return CUSTOM_SECTION_NAMES.get(normalized)


def normalize_resume_text(text: str) -> dict[str, object]:
    lines = _clean_lines(text.splitlines())
    if not lines:
        return {
            "full_name": "",
            "headline": "",
            "contact_line": "",
            "summary": "",
            "sections": {},
        }

    email = next((match.group(0) for line in lines if (match := EMAIL_PATTERN.search(line))), "")
    phone = next((match.group(0) for line in lines if (match := PHONE_PATTERN.search(line))), "")
    links = [line for line in lines if "linkedin.com/" in line.casefold()][:1]
    contact_parts = [value for value in (email, phone, *links) if value]

    first_heading = next(
        (
            index
            for index, line in enumerate(lines)
            if _heading_key(line) or _custom_heading(line)
        ),
        len(lines),
    )
    header = [
        line
        for line in lines[:first_heading]
        if not EMAIL_PATTERN.search(line)
        and not PHONE_PATTERN.search(line)
        and "linkedin.com/" not in line.casefold()
    ]
    full_name = header[0] if header else lines[0]
    headline = header[1] if len(header) > 1 else ""

    sections: dict[str, list[str]] = {}
    custom_sections: list[dict[str, object]] = []
    current = "additional"
    current_custom: dict[str, object] | None = None
    for line in lines[first_heading:]:
        heading = _heading_key(line)
        if heading:
            current = heading
            current_custom = None
            sections.setdefault(current, [])
            continue
        custom_heading = _custom_heading(line)
        if custom_heading:
            current_custom = {"title": custom_heading, "lines": []}
            custom_sections.append(current_custom)
            continue
        if current_custom is not None:
            custom_lines = current_custom["lines"]
            assert isinstance(custom_lines, list)
            custom_lines.append(line)
            continue
        sections.setdefault(current, []).append(line)

    summary_lines = sections.get("summary", [])
    if not summary_lines:
        summary_lines = header[2:]
    summary = " ".join(summary_lines[:4])
    return {
        "full_name": full_name[:160],
        "headline": headline[:200],
        "contact_line": " | ".join(contact_parts)[:300],
        "summary": summary[:2_000],
        "sections": sections,
        "custom_sections": custom_sections,
    }


def draft_payload(
    *,
    extracted_text: str,
    display_name: str,
    target_role: str | None,
) -> dict[str, object]:
    normalized = normalize_resume_text(extracted_text)
    return {
        "display_name": display_name,
        "target_role": target_role,
        "template_id": "ats-classic",
        "extracted_text": extracted_text,
        **normalized,
    }


def resume_plain_text(draft: dict[str, object]) -> str:
    """Create a durable text transcript from structured manual-entry content."""
    values = [
        str(draft.get("full_name") or ""),
        str(draft.get("headline") or ""),
        str(draft.get("contact_line") or ""),
    ]
    summary = str(draft.get("summary") or "").strip()
    if summary:
        values.extend(["Professional Summary", summary])
    sections = draft.get("sections")
    if isinstance(sections, dict):
        for key, title in (
            ("experience", "Experience"),
            ("projects", "Projects"),
            ("education", "Education"),
            ("skills", "Skills"),
            ("languages", "Languages"),
            ("additional", "Additional Information"),
        ):
            lines = sections.get(key)
            if isinstance(lines, list) and lines:
                values.append(title)
                values.extend(str(line) for line in lines)
    custom_sections = draft.get("custom_sections")
    if isinstance(custom_sections, list):
        for custom in custom_sections:
            if not isinstance(custom, dict):
                continue
            title = str(custom.get("title") or "").strip()
            lines = custom.get("lines")
            if title and isinstance(lines, list) and lines:
                values.append(title)
                values.extend(str(line) for line in lines)
    return "\n".join(value.strip() for value in values if value.strip())


def unmapped_resume_content(draft: dict[str, object]) -> list[str]:
    """Return source lines not represented by any editable field."""
    source = str(draft.get("extracted_text") or "")
    if not source.strip():
        return []

    def normalized(value: object) -> str:
        return re.sub(r"\s+", " ", str(value).lstrip("•-–* ").strip()).casefold()

    represented = {
        normalized(draft.get("full_name")),
        normalized(draft.get("headline")),
        normalized(draft.get("contact_line")),
        normalized(draft.get("summary")),
    }
    sections = draft.get("sections")
    if isinstance(sections, dict):
        for lines in sections.values():
            if isinstance(lines, list):
                represented.update(normalized(line) for line in lines)
    custom_sections = draft.get("custom_sections")
    if isinstance(custom_sections, list):
        for custom in custom_sections:
            if not isinstance(custom, dict):
                continue
            represented.add(normalized(custom.get("title")))
            lines = custom.get("lines")
            if isinstance(lines, list):
                represented.update(normalized(line) for line in lines)
    represented.discard("")

    unmatched: list[str] = []
    for line in _clean_lines(source.splitlines()):
        if _heading_key(line) or _custom_heading(line):
            continue
        candidate = normalized(line)
        if not candidate:
            continue
        if candidate in represented or any(
            len(candidate) >= 4 and candidate in value for value in represented
        ):
            continue
        unmatched.append(line)
    return unmatched[:100]


def encode_json(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def decode_json(payload: bytes) -> dict[str, object]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Stored resume payload is invalid.")
    return value


def _entry_blocks(lines: list[str], maximum: int) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for index, line in enumerate(lines):
        is_bullet = line.startswith(("•", "-", "–"))
        nearby = lines[max(0, index - 1) : index + 2]
        starts_entry = (
            current
            and not is_bullet
            and any(DATE_PATTERN.search(value) for value in nearby)
            and any(item.startswith(("•", "-", "–")) for item in current)
        )
        if starts_entry and len(blocks) + 1 < maximum:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks[:maximum]


def _split_entry(block: list[str], bullet_limit: int) -> dict[str, object]:
    plain = [line for line in block if not line.startswith(("•", "-", "–"))]
    bullets = [line.lstrip("•-– ") for line in block if line.startswith(("•", "-", "–"))]
    date = next((line for line in plain if DATE_PATTERN.search(line)), "")
    title_lines = [line for line in plain if line != date]
    return {
        "title": title_lines[0] if title_lines else "",
        "meta": " | ".join(title_lines[1:3]),
        "date": date,
        "bullets": bullets[:bullet_limit],
        "technologies": "",
    }


def standard_template_values(draft: dict[str, object]) -> dict[str, str]:
    sections = draft.get("sections")
    if not isinstance(sections, dict):
        sections = {}

    tags = {
        "profile.fullName",
        "profile.headline",
        "profile.contactLine",
        "summary.text",
        "experience.axelyn.role",
        "experience.axelyn.date",
        "experience.axelyn.meta",
        "experience.axelyn.highlight.1",
        "experience.axelyn.highlight.2",
        "experience.axelyn.highlight.3",
        "experience.axelyn.highlight.4",
        "experience.axelyn.technologies",
        "experience.armo.role",
        "experience.armo.date",
        "experience.armo.meta",
        "experience.armo.highlight.1",
        "experience.armo.highlight.2",
        "experience.armo.technologies",
        "education.utm.qualification",
        "education.utm.date",
        "education.utm.meta",
        "language.english.name",
        "language.english.proficiency",
        "language.malay.name",
        "language.malay.proficiency",
    }
    for prefix, bullet_count in (
        ("project.monitorscape", 3),
        ("project.memora", 2),
    ):
        tags.update({f"{prefix}.title", f"{prefix}.date", f"{prefix}.role", f"{prefix}.technologies"})
        tags.update(f"{prefix}.highlight.{index}" for index in range(1, bullet_count + 1))
    tags.update(
        {
            "project.aria.title",
            "project.aria.date",
            "project.aria.role",
            "project.aria.highlight.1",
            "project.aria.highlight.2.part1",
            "project.aria.highlight.2.part2",
            "project.aria.highlight.3",
            "project.aria.technologies",
        }
    )
    tags.update(f"engineeringPractice.{index}" for index in range(1, 5))
    for name in ("programming", "backend", "data", "cloud", "reliability", "ai", "softwareEngineering"):
        tags.update({f"skills.{name}.label", f"skills.{name}.items"})
    values = {tag: "" for tag in tags}
    values.update(
        {
            "profile.fullName": str(draft.get("full_name") or ""),
            "profile.headline": str(draft.get("headline") or draft.get("target_role") or ""),
            "profile.contactLine": str(draft.get("contact_line") or ""),
            "summary.text": str(draft.get("summary") or ""),
        }
    )

    experience_lines = [str(value) for value in sections.get("experience", [])] if isinstance(sections.get("experience"), list) else []
    experiences = [_split_entry(block, 4) for block in _entry_blocks(experience_lines, 2)]
    for index, key in enumerate(("axelyn", "armo")):
        if index >= len(experiences):
            break
        entry = experiences[index]
        prefix = f"experience.{key}"
        values[f"{prefix}.role"] = str(entry["title"])
        values[f"{prefix}.meta"] = str(entry["meta"])
        values[f"{prefix}.date"] = str(entry["date"])
        values[f"{prefix}.technologies"] = str(entry["technologies"])
        limit = 4 if index == 0 else 2
        for bullet_index, bullet in enumerate(entry["bullets"][:limit], 1):
            values[f"{prefix}.highlight.{bullet_index}"] = str(bullet)

    project_lines = [str(value) for value in sections.get("projects", [])] if isinstance(sections.get("projects"), list) else []
    projects = [_split_entry(block, 3) for block in _entry_blocks(project_lines, 3)]
    project_keys = ("monitorscape", "aria", "memora")
    for index, entry in enumerate(projects):
        prefix = f"project.{project_keys[index]}"
        values[f"{prefix}.title"] = str(entry["title"])
        values[f"{prefix}.role"] = str(entry["meta"])
        values[f"{prefix}.date"] = str(entry["date"])
        values[f"{prefix}.technologies"] = str(entry["technologies"])
        bullets = [str(value) for value in entry["bullets"]]
        if project_keys[index] == "aria" and len(bullets) > 1:
            midpoint = min(len(bullets[1]), 123)
            values[f"{prefix}.highlight.2.part1"] = bullets[1][:midpoint]
            values[f"{prefix}.highlight.2.part2"] = bullets[1][midpoint:]
            values[f"{prefix}.highlight.1"] = bullets[0]
            if len(bullets) > 2:
                values[f"{prefix}.highlight.3"] = bullets[2]
        else:
            for bullet_index, bullet in enumerate(bullets[:3], 1):
                values[f"{prefix}.highlight.{bullet_index}"] = bullet

    education = [str(value) for value in sections.get("education", [])] if isinstance(sections.get("education"), list) else []
    if education:
        values["education.utm.qualification"] = education[0]
        values["education.utm.meta"] = " | ".join(education[1:3])
        values["education.utm.date"] = next((line for line in education if DATE_PATTERN.search(line)), "")

    skills = [str(value) for value in sections.get("skills", [])] if isinstance(sections.get("skills"), list) else []
    skill_names = ("programming", "backend", "data", "cloud", "reliability", "ai", "softwareEngineering")
    for index, line in enumerate(skills[: len(skill_names)]):
        label, separator, items = line.partition(":")
        name = skill_names[index]
        values[f"skills.{name}.label"] = label if separator else "Skills"
        values[f"skills.{name}.items"] = items.strip() if separator else line

    additional = [str(value).lstrip("•-– ") for value in sections.get("additional", [])] if isinstance(sections.get("additional"), list) else []
    for index, line in enumerate(additional[:4], 1):
        values[f"engineeringPractice.{index}"] = line
    return values
