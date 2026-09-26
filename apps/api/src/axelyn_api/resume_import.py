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
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s|,;]+|(?:linkedin|github)\.com/[^\s|,;]+",
    re.IGNORECASE,
)
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
}
CUSTOM_SECTION_NAMES = {
    "languages": "Languages",
    "language": "Languages",
    "certifications": "Certifications",
    "certification": "Certifications",
    "achievements": "Achievements",
    "additional information": "Additional Information",
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
            "email_address": "",
            "phone_number": "",
            "location": "",
            "linkedin_url": "",
            "portfolio_url": "",
            "github_url": "",
            "other_professional_link": "",
            "contact_line": "",
            "summary": "",
            "sections": {},
        }

    email = next((match.group(0) for line in lines if (match := EMAIL_PATTERN.search(line))), "")
    phone = next((match.group(0) for line in lines if (match := PHONE_PATTERN.search(line))), "")
    urls = [
        value
        if value.casefold().startswith(("http://", "https://"))
        else f"https://{value}"
        for line in lines
        for match in URL_PATTERN.finditer(line)
        if (value := match.group(0).rstrip(".)"))
    ]
    linkedin_url = next((url for url in urls if "linkedin.com/" in url.casefold()), "")
    github_url = next((url for url in urls if "github.com/" in url.casefold()), "")
    portfolio_url = next(
        (url for url in urls if url not in {linkedin_url, github_url}),
        "",
    )
    other_link = next(
        (url for url in urls if url not in {linkedin_url, github_url, portfolio_url}),
        "",
    )
    location = next(
        (
            part.strip()
            for line in lines
            if EMAIL_PATTERN.search(line)
            or PHONE_PATTERN.search(line)
            or URL_PATTERN.search(line)
            for part in line.split("|")
            if part.strip()
            and not EMAIL_PATTERN.search(part)
            and not PHONE_PATTERN.search(part)
            and not URL_PATTERN.search(part)
        ),
        "",
    )
    contact_parts = [
        value
        for value in (
            email,
            phone,
            linkedin_url,
            github_url,
            portfolio_url,
            other_link,
        )
        if value
    ]

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
        and not URL_PATTERN.search(line)
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
        "email_address": email[:254],
        "phone_number": phone[:60],
        "location": location[:200],
        "linkedin_url": linkedin_url[:500],
        "portfolio_url": portfolio_url[:500],
        "github_url": github_url[:500],
        "other_professional_link": other_link[:500],
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


def _display_month(value: object) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(r"([0-9]{4})-(0[1-9]|1[0-2])", raw)
    if not match:
        return raw
    month_names = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return f"{month_names[int(match.group(2)) - 1]} {match.group(1)}"


def experience_entry_lines(entry: object) -> list[str]:
    """Flatten one structured role into a stable ATS-readable line sequence."""
    if not isinstance(entry, dict):
        return []
    job_title = str(entry.get("job_title") or "").strip()
    company_name = str(entry.get("company_name") or "").strip()
    substantive_values = (
        job_title,
        company_name,
        str(entry.get("location") or "").strip(),
        str(entry.get("start_date") or "").strip(),
        str(entry.get("end_date") or "").strip(),
        str(entry.get("responsibilities") or "").strip(),
        str(entry.get("achievements") or "").strip(),
    )
    if not any(substantive_values):
        return []
    title = " | ".join(value for value in (job_title, company_name) if value)
    details = " | ".join(
        value
        for value in (
            str(entry.get("employment_type") or "").strip(),
            str(entry.get("work_arrangement") or "").strip(),
            str(entry.get("location") or "").strip(),
        )
        if value
    )

    start_date = _display_month(entry.get("start_date"))
    end_date = (
        "Present"
        if entry.get("currently_working_here")
        else _display_month(entry.get("end_date"))
    )
    date = " – ".join(value for value in (start_date, end_date) if value)
    responsibilities = _clean_lines(
        str(entry.get("responsibilities") or "").splitlines()
    )
    achievements = [
        f"• {line.lstrip('•-–* ').strip()}"
        for line in _clean_lines(str(entry.get("achievements") or "").splitlines())
        if line.lstrip("•-–* ").strip()
    ]
    return [
        value
        for value in (title, details, date, *responsibilities, *achievements)
        if value
    ]


def education_entry_lines(entry: object) -> list[str]:
    """Flatten one structured qualification into ATS-readable resume lines."""
    if not isinstance(entry, dict):
        return []
    substantive_keys = (
        "institution_name",
        "qualification",
        "field_of_study",
        "location",
        "start_date",
        "end_date",
        "gpa",
        "honours",
        "relevant_coursework",
        "thesis_title",
        "thesis_description",
        "academic_achievements",
        "activities",
        "relevant_skills",
    )
    if not any(str(entry.get(key) or "").strip() for key in substantive_keys):
        return []

    qualification = " | ".join(
        value
        for value in (
            str(entry.get("qualification") or "").strip(),
            str(entry.get("field_of_study") or "").strip(),
        )
        if value
    )
    institution = " | ".join(
        value
        for value in (
            str(entry.get("institution_name") or "").strip(),
            str(entry.get("location") or "").strip(),
        )
        if value
    )
    end_date = (
        "Present"
        if entry.get("currently_studying_here")
        else _display_month(entry.get("end_date"))
    )
    date = " – ".join(
        value
        for value in (_display_month(entry.get("start_date")), end_date)
        if value
    )
    details = " | ".join(
        value
        for value in (
            str(entry.get("education_level") or "").strip(),
            date,
            f"GPA / CGPA: {str(entry.get('gpa') or '').strip()}"
            if str(entry.get("gpa") or "").strip()
            else "",
            str(entry.get("honours") or "").strip(),
        )
        if value
    )
    lines = [qualification, institution, details]
    optional_fields = (
        ("Relevant coursework", "relevant_coursework"),
        ("Final year project / thesis", "thesis_title"),
        ("Project / thesis description", "thesis_description"),
    )
    for label, key in optional_fields:
        value = str(entry.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    for achievement in _clean_lines(
        str(entry.get("academic_achievements") or "").splitlines()
    ):
        value = achievement.lstrip("•-–* ").strip()
        if value:
            lines.append(f"• {value}")
    for label, key in (
        ("Activities & societies", "activities"),
        ("Relevant skills learned", "relevant_skills"),
    ):
        value = str(entry.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    return [line for line in lines if line]


def project_entry_lines(entry: object) -> list[str]:
    """Flatten one structured project into ATS-readable resume lines."""
    if not isinstance(entry, dict):
        return []
    substantive_keys = (
        "project_name",
        "role",
        "project_url",
        "repository_url",
        "start_date",
        "end_date",
        "problem",
        "description",
        "audience",
        "personal_contribution",
        "responsibilities",
        "technologies",
        "challenge",
        "deliverables",
        "impact",
        "metrics",
    )
    if not any(str(entry.get(key) or "").strip() for key in substantive_keys):
        return []

    title = " | ".join(
        value
        for value in (
            str(entry.get("project_name") or "").strip(),
            str(entry.get("role") or "").strip(),
        )
        if value
    )
    details = " | ".join(
        value
        for value in (
            str(entry.get("project_type") or "").strip(),
            str(entry.get("project_status") or "").strip(),
        )
        if value
    )
    end_date = (
        "Present"
        if entry.get("currently_working_on_project")
        else _display_month(entry.get("end_date"))
    )
    date = " – ".join(
        value
        for value in (_display_month(entry.get("start_date")), end_date)
        if value
    )
    links = " | ".join(
        value
        for value in (
            f"Project: {str(entry.get('project_url') or '').strip()}"
            if str(entry.get("project_url") or "").strip()
            else "",
            f"Repository: {str(entry.get('repository_url') or '').strip()}"
            if str(entry.get("repository_url") or "").strip()
            else "",
        )
        if value
    )
    lines = [title, details, date, links]
    for label, key in (
        ("Problem", "problem"),
        ("Project", "description"),
        ("Built for", "audience"),
        ("Personal contribution", "personal_contribution"),
        ("Responsibilities", "responsibilities"),
        ("Technologies", "technologies"),
        ("Most challenging part", "challenge"),
        ("Built / implemented", "deliverables"),
        ("Result / impact", "impact"),
        ("Measurable results", "metrics"),
    ):
        values = _clean_lines(str(entry.get(key) or "").splitlines())
        for value in values:
            cleaned = value.lstrip("•-–* ").strip()
            if cleaned:
                lines.append(f"• {label}: {cleaned}")
    return [line for line in lines if line]


def skill_category_lines(entry: object) -> list[str]:
    """Flatten one structured skill category into an ATS-readable line."""
    if not isinstance(entry, dict):
        return []
    category = str(entry.get("category") or "").strip()
    raw_skills = entry.get("skills")
    if not category or not isinstance(raw_skills, list):
        return []
    skills = [str(skill).strip() for skill in raw_skills if str(skill).strip()]
    if not skills:
        return []
    return [f"{category}: {', '.join(skills)}"]


def resume_contact_line(draft: dict[str, object]) -> str:
    """Build the public-facing identity line from structured contact fields."""
    values: list[str] = []
    seen: set[str] = set()
    for field in (
        "email_address",
        "phone_number",
        "location",
        "linkedin_url",
        "portfolio_url",
        "github_url",
        "other_professional_link",
    ):
        value = str(draft.get(field) or "").strip()
        key = value.casefold()
        if value and key not in seen:
            values.append(value)
            seen.add(key)
    if values:
        return " | ".join(values)
    return str(draft.get("contact_line") or "").strip()


def rendered_resume_sections(draft: dict[str, object]) -> dict[str, list[str]]:
    """Flatten structured and imported content into stable template line groups."""
    sections = draft.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    rendered: dict[str, list[str]] = {}
    for key, entry_key, formatter in (
        ("experience", "experience_entries", experience_entry_lines),
        ("education", "education_entries", education_entry_lines),
        ("projects", "project_entries", project_entry_lines),
        ("skills", "skill_categories", skill_category_lines),
    ):
        lines: list[str] = []
        entries = draft.get(entry_key)
        if isinstance(entries, list):
            for entry in entries:
                lines.extend(formatter(entry))
        legacy = sections.get(key)
        if isinstance(legacy, list):
            lines.extend(str(line).strip() for line in legacy if str(line).strip())
        rendered[key] = lines
    for key in ("languages", "additional"):
        legacy = sections.get(key)
        rendered[key] = (
            [str(line).strip() for line in legacy if str(line).strip()]
            if isinstance(legacy, list)
            else []
        )
    return rendered


def sdt_template_line(value: object) -> str:
    """Return the exact text stored inside one standard-template content control."""
    line = str(value).strip()
    if line.startswith(("•", "-", "–", "*")):
        cleaned = line.lstrip("•-–* ").strip()
        return f"• {cleaned}" if cleaned else ""
    return line


def sdt_template_values(draft: dict[str, object]) -> dict[str, str]:
    """Map every generated SDT tag to the text initially displayed in Word."""
    values = {"resume.full_name": str(draft.get("full_name") or "Your name")}
    headline = str(draft.get("headline") or draft.get("target_role") or "").strip()
    contact = resume_contact_line(draft)
    summary = str(draft.get("summary") or "").strip()
    for tag, value in (
        ("resume.headline", headline),
        ("resume.contact_line", contact),
        ("resume.summary", summary),
    ):
        if value:
            values[tag] = value
    for section, lines in rendered_resume_sections(draft).items():
        for index, line in enumerate(lines):
            value = sdt_template_line(line)
            if value:
                values[f"rendered_sections.{section}.{index}"] = value
    custom_sections = draft.get("custom_sections")
    if isinstance(custom_sections, list):
        for section_index, custom in enumerate(custom_sections):
            if not isinstance(custom, dict):
                continue
            lines = custom.get("lines")
            if not isinstance(lines, list):
                continue
            for line_index, line in enumerate(lines):
                value = sdt_template_line(line)
                if value:
                    values[
                        f"resume.custom_sections.{section_index}.lines.{line_index}"
                    ] = value
    return values


def resume_plain_text(draft: dict[str, object]) -> str:
    """Create a durable text transcript from structured manual-entry content."""
    values = [
        str(draft.get("full_name") or ""),
        str(draft.get("headline") or ""),
        resume_contact_line(draft),
    ]
    summary = str(draft.get("summary") or "").strip()
    if summary:
        values.extend(["Professional Summary", summary])
    sections = draft.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    experience_entries = draft.get("experience_entries")
    legacy_experience = sections.get("experience")
    if (
        isinstance(experience_entries, list) and experience_entries
    ) or (
        isinstance(legacy_experience, list) and legacy_experience
    ):
        values.append("Experience")
        if isinstance(experience_entries, list):
            for entry in experience_entries:
                values.extend(experience_entry_lines(entry))
        if isinstance(legacy_experience, list):
            values.extend(str(line) for line in legacy_experience)
    education_entries = draft.get("education_entries")
    legacy_education = sections.get("education")
    if (
        isinstance(education_entries, list) and education_entries
    ) or (
        isinstance(legacy_education, list) and legacy_education
    ):
        values.append("Education")
        if isinstance(education_entries, list):
            for entry in education_entries:
                values.extend(education_entry_lines(entry))
        if isinstance(legacy_education, list):
            values.extend(str(line) for line in legacy_education)
    project_entries = draft.get("project_entries")
    legacy_projects = sections.get("projects")
    if (
        isinstance(project_entries, list) and project_entries
    ) or (
        isinstance(legacy_projects, list) and legacy_projects
    ):
        values.append("Projects")
        if isinstance(project_entries, list):
            for entry in project_entries:
                values.extend(project_entry_lines(entry))
        if isinstance(legacy_projects, list):
            values.extend(str(line) for line in legacy_projects)
    skill_categories = draft.get("skill_categories")
    legacy_skills = sections.get("skills")
    if (
        isinstance(skill_categories, list) and skill_categories
    ) or (
        isinstance(legacy_skills, list) and legacy_skills
    ):
        values.append("Skills")
        if isinstance(skill_categories, list):
            for category in skill_categories:
                values.extend(skill_category_lines(category))
        if isinstance(legacy_skills, list):
            values.extend(str(line) for line in legacy_skills)
    for key, title in (
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
        normalized(resume_contact_line(draft)),
        normalized(draft.get("summary")),
    }
    represented.update(
        normalized(draft.get(field))
        for field in (
            "email_address",
            "phone_number",
            "location",
            "linkedin_url",
            "portfolio_url",
            "github_url",
            "other_professional_link",
        )
    )
    sections = draft.get("sections")
    if isinstance(sections, dict):
        for lines in sections.values():
            if isinstance(lines, list):
                represented.update(normalized(line) for line in lines)
    experience_entries = draft.get("experience_entries")
    if isinstance(experience_entries, list):
        for entry in experience_entries:
            if not isinstance(entry, dict):
                continue
            represented.update(
                normalized(line) for line in experience_entry_lines(entry)
            )
            for value in entry.values():
                if isinstance(value, str):
                    represented.update(
                        normalized(line) for line in value.splitlines()
                    )
    education_entries = draft.get("education_entries")
    if isinstance(education_entries, list):
        for entry in education_entries:
            if not isinstance(entry, dict):
                continue
            represented.update(
                normalized(line) for line in education_entry_lines(entry)
            )
            for value in entry.values():
                if isinstance(value, str):
                    represented.update(
                        normalized(line) for line in value.splitlines()
                    )
    project_entries = draft.get("project_entries")
    if isinstance(project_entries, list):
        for entry in project_entries:
            if not isinstance(entry, dict):
                continue
            represented.update(
                normalized(line) for line in project_entry_lines(entry)
            )
            for value in entry.values():
                if isinstance(value, str):
                    represented.update(
                        normalized(line) for line in value.splitlines()
                    )
    skill_categories = draft.get("skill_categories")
    if isinstance(skill_categories, list):
        for category in skill_categories:
            if not isinstance(category, dict):
                continue
            represented.update(
                normalized(line) for line in skill_category_lines(category)
            )
            represented.add(normalized(category.get("category")))
            skills = category.get("skills")
            if isinstance(skills, list):
                represented.update(normalized(skill) for skill in skills)
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
            "profile.contactLine": resume_contact_line(draft),
            "summary.text": str(draft.get("summary") or ""),
        }
    )

    experience_lines: list[str] = []
    structured_experience = draft.get("experience_entries")
    if isinstance(structured_experience, list):
        for entry in structured_experience:
            experience_lines.extend(experience_entry_lines(entry))
    if isinstance(sections.get("experience"), list):
        experience_lines.extend(str(value) for value in sections["experience"])
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

    projects: list[dict[str, object]] = []
    structured_projects = draft.get("project_entries")
    if isinstance(structured_projects, list):
        for project in structured_projects:
            if not isinstance(project, dict):
                continue
            project_end = (
                "Present"
                if project.get("currently_working_on_project")
                else _display_month(project.get("end_date"))
            )
            project_date = " – ".join(
                value
                for value in (
                    _display_month(project.get("start_date")),
                    project_end,
                )
                if value
            )
            project_bullets: list[str] = []
            for key in (
                "personal_contribution",
                "deliverables",
                "impact",
                "metrics",
                "description",
                "responsibilities",
                "problem",
            ):
                for line in _clean_lines(str(project.get(key) or "").splitlines()):
                    value = line.lstrip("•-–* ").strip()
                    if value:
                        project_bullets.append(value)
            projects.append(
                {
                    "title": str(project.get("project_name") or "").strip(),
                    "meta": " | ".join(
                        value
                        for value in (
                            str(project.get("role") or "").strip(),
                            str(project.get("project_type") or "").strip(),
                            str(project.get("project_status") or "").strip(),
                        )
                        if value
                    ),
                    "date": project_date,
                    "bullets": project_bullets,
                    "technologies": str(project.get("technologies") or "").strip(),
                }
            )
    project_lines = (
        [str(value) for value in sections.get("projects", [])]
        if isinstance(sections.get("projects"), list)
        else []
    )
    projects.extend(
        _split_entry(block, 3) for block in _entry_blocks(project_lines, 3)
    )
    project_keys = ("monitorscape", "aria", "memora")
    for index, entry in enumerate(projects[: len(project_keys)]):
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

    structured_education = draft.get("education_entries")
    first_education = (
        structured_education[0]
        if isinstance(structured_education, list)
        and structured_education
        and isinstance(structured_education[0], dict)
        else None
    )
    education: list[str] = []
    if first_education is not None:
        values["education.utm.qualification"] = " | ".join(
            value
            for value in (
                str(first_education.get("qualification") or "").strip(),
                str(first_education.get("field_of_study") or "").strip(),
            )
            if value
        )
        values["education.utm.meta"] = " | ".join(
            value
            for value in (
                str(first_education.get("institution_name") or "").strip(),
                str(first_education.get("location") or "").strip(),
                str(first_education.get("honours") or "").strip(),
            )
            if value
        )
        education_end = (
            "Present"
            if first_education.get("currently_studying_here")
            else _display_month(first_education.get("end_date"))
        )
        values["education.utm.date"] = " – ".join(
            value
            for value in (
                _display_month(first_education.get("start_date")),
                education_end,
            )
            if value
        )
    else:
        education = (
            [str(value) for value in sections.get("education", [])]
            if isinstance(sections.get("education"), list)
            else []
        )
    if first_education is None and education:
        values["education.utm.qualification"] = education[0]
        values["education.utm.meta"] = " | ".join(education[1:3])
        values["education.utm.date"] = next((line for line in education if DATE_PATTERN.search(line)), "")

    skill_names = (
        "programming",
        "backend",
        "data",
        "cloud",
        "reliability",
        "ai",
        "softwareEngineering",
    )
    category_slots = {
        "Programming Language": "programming",
        "Framework": "backend",
        "Database": "data",
        "Cloud": "cloud",
        "DevOps": "reliability",
        "AI / ML": "ai",
        "Frontend": "softwareEngineering",
    }
    used_skill_slots: set[str] = set()
    structured_skills = draft.get("skill_categories")
    if isinstance(structured_skills, list):
        for skill_category in structured_skills:
            if not isinstance(skill_category, dict):
                continue
            category = str(skill_category.get("category") or "").strip()
            raw_items = skill_category.get("skills")
            if not category or not isinstance(raw_items, list):
                continue
            items = ", ".join(
                str(item).strip() for item in raw_items if str(item).strip()
            )
            if not items:
                continue
            name = category_slots.get(category, "")
            if not name or name in used_skill_slots:
                name = next(
                    (candidate for candidate in skill_names if candidate not in used_skill_slots),
                    "",
                )
            if not name:
                break
            used_skill_slots.add(name)
            values[f"skills.{name}.label"] = category
            values[f"skills.{name}.items"] = items

    skills = (
        [str(value) for value in sections.get("skills", [])]
        if isinstance(sections.get("skills"), list)
        else []
    )
    for line in skills:
        name = next(
            (candidate for candidate in skill_names if candidate not in used_skill_slots),
            "",
        )
        if not name:
            break
        used_skill_slots.add(name)
        label, separator, items = line.partition(":")
        values[f"skills.{name}.label"] = label if separator else "Skills"
        values[f"skills.{name}.items"] = items.strip() if separator else line

    additional = [str(value).lstrip("•-– ") for value in sections.get("additional", [])] if isinstance(sections.get("additional"), list) else []
    for index, line in enumerate(additional[:4], 1):
        values[f"engineeringPractice.{index}"] = line
    return values
