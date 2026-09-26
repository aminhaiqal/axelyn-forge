"""Versioned request and response models for the public HTTP contract."""

from typing import List, Literal, Optional, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)


_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class Service(BaseModel):
    id: str
    name: str
    summary: str
    deliverables: List[str]


class ServiceRequestCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    service_id: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: Optional[str] = Field(default=None, max_length=160)
    project_summary: str = Field(min_length=30, max_length=4000)
    job_posting_url: Optional[HttpUrl] = None
    timeline: Optional[str] = Field(default=None, max_length=120)
    consent: Literal[True]


class ServiceRequestAccepted(BaseModel):
    id: str
    service_id: str
    status: Literal["received"]
    created_at: str
    message: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["axelyn-forge-api"]
    version: str


class AuthenticatedUser(BaseModel):
    user_id: str


class RoleAlignmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_role: str = Field(min_length=2, max_length=160)
    company: Optional[str] = Field(default=None, max_length=160)
    job_description: str = Field(min_length=100, max_length=20000)
    career_evidence: str = Field(min_length=100, max_length=30000)


class RoleAlignmentAnalysis(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    matched_keywords: List[str]
    gap_keywords: List[str]
    evidence_highlights: List[str]
    recommendations: List[str]

ResumeSourceStatus = Literal["needs_review", "needs_ocr", "ready"]
ResumeTemplateId = Literal["ats-classic"]
ResumeEmploymentType = Literal[
    "Full-time",
    "Part-time",
    "Contract",
    "Freelance",
    "Internship",
    "Self-employed",
]
ResumeWorkArrangement = Literal["On-site", "Hybrid", "Remote"]
ResumeEducationLevel = Literal[
    "Secondary School",
    "Diploma",
    "Foundation",
    "Bachelor’s Degree",
    "Master’s Degree",
    "Doctorate / PhD",
    "Professional Qualification",
    "Other",
]
ResumeProjectType = Literal[
    "Personal Project",
    "Client Project",
    "Commercial Product",
    "Academic Project",
    "Open Source",
    "Research Project",
    "Internal Company Project",
]
ResumeProjectStatus = Literal[
    "Live / Production",
    "In Development",
    "Prototype",
    "Completed",
    "Discontinued",
]
RESUME_SECTION_NAMES = {
    "summary",
    "experience",
    "projects",
    "education",
    "skills",
    "languages",
    "additional",
}


class ResumeExperienceEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(default="", max_length=160)
    job_title: str = Field(default="", max_length=160)
    employment_type: ResumeEmploymentType = "Full-time"
    location: str = Field(default="", max_length=160)
    work_arrangement: ResumeWorkArrangement = "On-site"
    start_date: str = Field(
        default="",
        max_length=7,
        pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$",
    )
    end_date: str = Field(
        default="",
        max_length=7,
        pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$",
    )
    currently_working_here: bool = False
    responsibilities: str = Field(default="", max_length=10_000)
    achievements: str = Field(default="", max_length=10_000)

    @model_validator(mode="after")
    def current_role_has_no_end_date(self) -> Self:
        if self.currently_working_here:
            self.end_date = ""
        return self


class ResumeEducationEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution_name: str = Field(default="", max_length=200)
    qualification: str = Field(default="", max_length=200)
    field_of_study: str = Field(default="", max_length=200)
    education_level: ResumeEducationLevel = "Bachelor’s Degree"
    location: str = Field(default="", max_length=160)
    start_date: str = Field(
        default="",
        max_length=7,
        pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$",
    )
    end_date: str = Field(
        default="",
        max_length=7,
        pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$",
    )
    currently_studying_here: bool = False
    gpa: str = Field(default="", max_length=80)
    honours: str = Field(default="", max_length=160)
    relevant_coursework: str = Field(default="", max_length=2_000)
    thesis_title: str = Field(default="", max_length=300)
    thesis_description: str = Field(default="", max_length=4_000)
    academic_achievements: str = Field(default="", max_length=4_000)
    activities: str = Field(default="", max_length=4_000)
    relevant_skills: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def current_study_has_no_end_date(self) -> Self:
        if self.currently_studying_here:
            self.end_date = ""
        return self


class ResumeProjectEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_name: str = Field(default="", max_length=200)
    project_type: ResumeProjectType = "Personal Project"
    role: str = Field(default="", max_length=160)
    project_url: str = Field(default="", max_length=500)
    repository_url: str = Field(default="", max_length=500)
    start_date: str = Field(
        default="",
        max_length=7,
        pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$",
    )
    end_date: str = Field(
        default="",
        max_length=7,
        pattern=r"^(?:|[0-9]{4}-(?:0[1-9]|1[0-2]))$",
    )
    currently_working_on_project: bool = False
    problem: str = Field(default="", max_length=4_000)
    description: str = Field(default="", max_length=4_000)
    audience: str = Field(default="", max_length=2_000)
    personal_contribution: str = Field(default="", max_length=8_000)
    responsibilities: str = Field(default="", max_length=8_000)
    technologies: str = Field(default="", max_length=4_000)
    challenge: str = Field(default="", max_length=4_000)
    deliverables: str = Field(default="", max_length=8_000)
    impact: str = Field(default="", max_length=8_000)
    metrics: str = Field(default="", max_length=4_000)
    project_status: ResumeProjectStatus = "In Development"

    @model_validator(mode="after")
    def current_project_has_no_end_date(self) -> Self:
        if self.currently_working_on_project:
            self.end_date = ""
        return self


class ResumeSkillCategory(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str = Field(min_length=1, max_length=80)
    skills: List[str] = Field(min_length=1, max_length=50)

    @field_validator("skills")
    @classmethod
    def skills_are_clean_and_unique(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        seen: set[str] = set()
        for skill in value:
            normalized = skill.strip()
            if len(normalized) > 100:
                raise ValueError("skills are limited to 100 characters each")
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                cleaned.append(normalized)
        if not cleaned:
            raise ValueError("add at least one skill")
        return cleaned


class ResumeCustomSection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=80)
    lines: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("lines")
    @classmethod
    def lines_are_bounded(cls, value: List[str]) -> List[str]:
        cleaned = []
        for line in value:
            normalized = line.strip()
            if len(normalized) > 2_000:
                raise ValueError("custom section lines are limited to 2,000 characters")
            if normalized:
                cleaned.append(normalized)
        return cleaned


class ResumeDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    template_id: ResumeTemplateId = "ats-classic"
    full_name: str = Field(default="", max_length=160)
    headline: str = Field(default="", max_length=200)
    email_address: str = Field(default="", max_length=254)
    phone_number: str = Field(default="", max_length=60)
    location: str = Field(default="", max_length=200)
    linkedin_url: str = Field(default="", max_length=500)
    portfolio_url: str = Field(default="", max_length=500)
    github_url: str = Field(default="", max_length=500)
    other_professional_link: str = Field(default="", max_length=500)
    profile_photo_filename: str = Field(default="", max_length=180)
    profile_photo_media_type: Literal[
        "", "image/jpeg", "image/png", "image/webp"
    ] = ""
    contact_line: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=2_000)
    extracted_text: str = Field(default="", max_length=100_000)
    sections: dict[str, List[str]] = Field(default_factory=dict)
    experience_entries: List[ResumeExperienceEntry] = Field(
        default_factory=list,
        max_length=30,
    )
    education_entries: List[ResumeEducationEntry] = Field(
        default_factory=list,
        max_length=20,
    )
    project_entries: List[ResumeProjectEntry] = Field(
        default_factory=list,
        max_length=30,
    )
    skill_categories: List[ResumeSkillCategory] = Field(
        default_factory=list,
        max_length=30,
    )
    custom_sections: List[ResumeCustomSection] = Field(
        default_factory=list,
        max_length=12,
    )

    @field_validator("email_address")
    @classmethod
    def optional_email_is_valid(cls, value: str) -> str:
        if value:
            _EMAIL_ADAPTER.validate_python(value)
        return value

    @field_validator(
        "linkedin_url",
        "portfolio_url",
        "github_url",
        "other_professional_link",
    )
    @classmethod
    def optional_professional_url_is_valid(cls, value: str) -> str:
        if value:
            _HTTP_URL_ADAPTER.validate_python(value)
        return value

    @field_validator("sections")
    @classmethod
    def sections_are_bounded(
        cls, value: dict[str, List[str]]
    ) -> dict[str, List[str]]:
        unknown = set(value) - RESUME_SECTION_NAMES
        if unknown:
            raise ValueError(f"unsupported resume section: {sorted(unknown)[0]}")
        if sum(len(lines) for lines in value.values()) > 500:
            raise ValueError("resume sections are limited to 500 lines")
        cleaned: dict[str, List[str]] = {}
        for section, lines in value.items():
            cleaned[section] = []
            for line in lines:
                normalized = line.strip()
                if len(normalized) > 2_000:
                    raise ValueError("resume section lines are limited to 2,000 characters")
                if normalized:
                    cleaned[section].append(normalized)
        return cleaned


class ResumeSourceSummary(BaseModel):
    id: str
    display_name: str
    target_role: Optional[str]
    original_filename: str
    media_type: str
    byte_size: int
    status: ResumeSourceStatus
    warning: Optional[str]
    created_at: str
    updated_at: str


class ResumeSourceDetail(ResumeSourceSummary):
    draft: ResumeDraft
    unmapped_content: List[str] = Field(default_factory=list)


class ResumeTemplateSummary(BaseModel):
    id: ResumeTemplateId
    name: str
    description: str
    density: Literal["comfortable", "balanced", "compact"]


class ResumeImportItem(BaseModel):
    filename: str
    status: Literal["stored", "rejected"]
    source: Optional[ResumeSourceSummary] = None
    error: Optional[str] = None


class ResumeImportResponse(BaseModel):
    items: List[ResumeImportItem]


ResumeSourceArtifactKind = Literal[
    "source_docx",
    "sdt_template",
    "resume_json",
    "resume_schema",
]


class ResumePackageSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    target_role: Optional[str] = None
    original_filename: str


class ResumeSourcePackage(BaseModel):
    """Portable structured representation generated from an imported Word source."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_document: Literal[
        "https://forge.axelyn.com/schemas/resume-source-v1.schema.json"
    ] = Field(
        default="https://forge.axelyn.com/schemas/resume-source-v1.schema.json",
        alias="$schema",
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    source: ResumePackageSource
    resume: ResumeDraft
    rendered_sections: dict[str, List[str]]
    template_values: dict[str, str]


class ResumeSourceArtifactSummary(BaseModel):
    id: str
    source_id: str
    kind: ResumeSourceArtifactKind
    filename: str
    media_type: str
    byte_size: int
    created_at: str
    updated_at: str


class ResumeDraftUpdate(ResumeDraft):
    template_id: Literal["ats-classic"] = "ats-classic"
    full_name: str = Field(min_length=2, max_length=160)
    email_address: str = Field(min_length=3, max_length=254)
    phone_number: str = Field(min_length=5, max_length=60)
    location: str = Field(min_length=2, max_length=200)
    display_name: str = Field(min_length=1, max_length=160)
    target_role: Optional[str] = Field(default=None, max_length=160)


class ResumeAcceptRequest(ResumeDraftUpdate):
    variant_name: str = Field(min_length=1, max_length=160)


class ResumeVariantSummary(BaseModel):
    id: str
    source_id: str
    name: str
    target_role: Optional[str]
    status: Literal["ready"]
    created_at: str
    updated_at: str


class GeneratedDocumentSummary(BaseModel):
    id: str
    variant_id: str
    filename: str
    media_type: str
    template_id: str
    template_version: str
    created_at: str


class GeneratedDocumentBundle(BaseModel):
    documents: List[GeneratedDocumentSummary]


JobMatchState = Literal["match", "some_match", "no_match"]


class JobMatchAnalysis(BaseModel):
    match_percentage: int = Field(ge=0, le=100)
    match_state: JobMatchState
    match_label: Literal["Match", "Some match", "No match"]
    matched_keywords: List[str]
    missing_keywords: List[str]
    evidence_highlights: List[str]
    reasons: List[str]
    recommendations: List[str]
    can_generate: bool


class JobMatchResult(JobMatchAnalysis):
    id: str
    source_id: str
    resume_name: str
    target_role: str
    company: Optional[str]
    created_at: str


class JobMatchDocumentSummary(BaseModel):
    id: str
    match_id: str
    filename: str
    media_type: str
    created_at: str


class JobMatchDocumentBundle(BaseModel):
    documents: List[JobMatchDocumentSummary]
