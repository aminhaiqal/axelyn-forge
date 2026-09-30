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
ResumeEmploymentType = Literal[
    "",
    "Full-time",
    "Part-time",
    "Contract",
    "Freelance",
    "Internship",
    "Self-employed",
]
ResumeWorkArrangement = Literal["", "On-site", "Hybrid", "Remote"]
ResumeEducationLevel = Literal[
    "",
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
    "",
    "Personal Project",
    "Client Project",
    "Commercial Product",
    "Academic Project",
    "Open Source",
    "Research Project",
    "Internal Company Project",
]
ResumeProjectStatus = Literal[
    "",
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
    employment_type: ResumeEmploymentType = ""
    location: str = Field(default="", max_length=160)
    work_arrangement: ResumeWorkArrangement = ""
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
    responsibilities: str = ""
    achievements: str = ""

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
    education_level: ResumeEducationLevel = ""
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
    relevant_coursework: str = ""
    thesis_title: str = Field(default="", max_length=300)
    thesis_description: str = ""
    academic_achievements: str = ""
    activities: str = ""
    relevant_skills: str = ""

    @model_validator(mode="after")
    def current_study_has_no_end_date(self) -> Self:
        if self.currently_studying_here:
            self.end_date = ""
        return self


class ResumeProjectEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_name: str = Field(default="", max_length=200)
    project_type: ResumeProjectType = ""
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
    problem: str = ""
    description: str = ""
    audience: str = ""
    personal_contribution: str = ""
    responsibilities: str = ""
    technologies: str = ""
    challenge: str = ""
    deliverables: str = ""
    impact: str = ""
    metrics: str = ""
    project_status: ResumeProjectStatus = ""

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
    def lines_are_clean(cls, value: List[str]) -> List[str]:
        cleaned = []
        for line in value:
            normalized = line.strip()
            if normalized:
                cleaned.append(normalized)
        return cleaned


class ResumeDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    template_id: Literal["ats-classic"] = "ats-classic"
    full_name: str = Field(default="", max_length=160)
    headline: str = Field(default="", max_length=200)
    email_address: str = Field(default="", max_length=254)
    phone_number: str = Field(default="", max_length=60)
    location: str = Field(default="", max_length=200)
    linkedin_url: str = Field(default="", max_length=500)
    portfolio_url: str = Field(default="", max_length=500)
    github_url: str = Field(default="", max_length=500)
    other_professional_link: str = Field(default="", max_length=500)
    contact_line: str = Field(default="", max_length=300)
    summary: str = ""
    extracted_text: str = ""
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
    def sections_are_clean(
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
    "resume_docx",
    "resume_pdf",
    "resume_json",
    "resume_schema",
    "resume_manifest",
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


JobApplicationStatus = Literal[
    "saved",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
]


class JobApplicationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    job_url: Optional[str] = Field(default=None, max_length=1_000)
    location: Optional[str] = Field(default=None, max_length=200)
    work_arrangement: Optional[ResumeWorkArrangement] = None
    employment_type: Optional[ResumeEmploymentType] = None
    status: JobApplicationStatus = "saved"
    applied_on: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$",
    )
    next_action_on: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$",
    )
    notes: Optional[str] = Field(default=None, max_length=10_000)
    resume_source_id: str = Field(min_length=1, max_length=80)

    @field_validator(
        "job_url",
        "location",
        "applied_on",
        "next_action_on",
        "notes",
        mode="before",
    )
    @classmethod
    def blank_values_are_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("job_url")
    @classmethod
    def job_url_is_http(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = _HTTP_URL_ADAPTER.validate_python(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("job URL must use http or https")
        return str(parsed)


class JobApplicationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    job_url: Optional[str] = Field(default=None, max_length=1_000)
    location: Optional[str] = Field(default=None, max_length=200)
    work_arrangement: Optional[ResumeWorkArrangement] = None
    employment_type: Optional[ResumeEmploymentType] = None
    status: JobApplicationStatus
    applied_on: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$",
    )
    next_action_on: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$",
    )
    notes: Optional[str] = Field(default=None, max_length=10_000)
    resume_source_id: Optional[str] = Field(default=None, max_length=80)

    _blank_values_are_none = field_validator(
        "job_url",
        "location",
        "applied_on",
        "next_action_on",
        "notes",
        "resume_source_id",
        mode="before",
    )(JobApplicationCreate.blank_values_are_none.__func__)
    _job_url_is_http = field_validator("job_url")(
        JobApplicationCreate.job_url_is_http.__func__
    )


class JobApplicationSummary(BaseModel):
    id: str
    company_name: str
    job_title: str
    job_url: Optional[str]
    location: Optional[str]
    work_arrangement: Optional[ResumeWorkArrangement]
    employment_type: Optional[ResumeEmploymentType]
    status: JobApplicationStatus
    applied_on: Optional[str]
    next_action_on: Optional[str]
    notes: Optional[str]
    resume_source_id: Optional[str]
    resume_name: str
    resume_target_role: Optional[str]
    created_at: str
    updated_at: str


class InterviewBriefRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    job_description: Optional[str] = Field(default=None, max_length=20_000)
    focus: Optional[str] = Field(default=None, max_length=1_000)

    @field_validator("job_description", "focus", mode="before")
    @classmethod
    def blank_values_are_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class InterviewCoverageItem(BaseModel):
    requirement: str
    assessment: Literal["strong", "partial", "gap"]
    rationale: str
    evidence: List[str]


class InterviewQuestion(BaseModel):
    question: str
    interviewer_intent: str
    answer_plan: str
    evidence: List[str]


class InterviewBrief(BaseModel):
    id: str
    application_id: str
    role_summary: str
    positioning: str
    coverage: List[InterviewCoverageItem]
    questions: List[InterviewQuestion]
    questions_to_ask: List[str]
    preparation_actions: List[str]
    facts_to_confirm: List[str]
    model: str
    created_at: str
    updated_at: str


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


class JobMatchSummary(BaseModel):
    id: str
    source_id: str
    resume_name: str
    target_role: str
    company: Optional[str]
    match_percentage: int = Field(ge=0, le=100)
    match_state: JobMatchState
    match_label: Literal["Match", "Some match", "No match"]
    has_documents: bool
    created_at: str


class JobMatchDocumentSummary(BaseModel):
    id: str
    match_id: str
    filename: str
    media_type: str
    created_at: str


class JobMatchDocumentBundle(BaseModel):
    documents: List[JobMatchDocumentSummary]


class JobMatchDetail(JobMatchResult):
    documents: List[JobMatchDocumentSummary]


ForgeAIClaimStatus = Literal["verified", "user_confirmed", "needs_evidence", "gap"]
ForgeAIThreadStatus = Literal["active", "ready"]


class ForgeAICitation(BaseModel):
    id: str
    label: str


class ForgeAIMemoryFact(BaseModel):
    fact: str
    source: Literal["resume", "user"]
    evidence_ids: List[str]


class ForgeAIMemory(BaseModel):
    summary: str
    confirmed_facts: List[ForgeAIMemoryFact]
    rejected_claims: List[str]
    open_questions: List[str]
    decisions: List[str]


class ForgeAIMessage(BaseModel):
    id: str
    thread_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: List[ForgeAICitation]
    claim_status: ForgeAIClaimStatus
    model: Optional[str]
    created_at: str


class ForgeAIEnhancementEvidence(BaseModel):
    id: str
    label: str
    source: Literal["resume", "user_confirmed"]


class ForgeAIEnhancementOperation(BaseModel):
    target: str
    section: str
    before: str | List[str]
    after: str | List[str]
    evidence: List[ForgeAIEnhancementEvidence]


class ForgeAIEnhancementResult(BaseModel):
    projected_score: int = Field(ge=0, le=100)
    overview: str
    changed_sections: List[str]
    operations: List[ForgeAIEnhancementOperation]
    gaps: List[str]
    documents: List[JobMatchDocumentSummary]
    model: str


class ForgeAIThreadSummary(BaseModel):
    id: str
    match_id: str
    source_id: str
    target_role: str
    company: Optional[str]
    resume_name: str
    baseline_score: int = Field(ge=0, le=100)
    current_score: int = Field(ge=0, le=100)
    status: ForgeAIThreadStatus
    memory_version: int = Field(ge=1)
    message_count: int = Field(ge=0)
    created_at: str
    updated_at: str


class ForgeAIThreadDetail(ForgeAIThreadSummary):
    match_state: JobMatchState
    match_label: Literal["Match", "Some match", "No match"]
    missing_keywords: List[str]
    matched_keywords: List[str]
    memory: ForgeAIMemory
    messages: List[ForgeAIMessage]
    documents: List[JobMatchDocumentSummary]


class ForgeAIThreadCreate(BaseModel):
    match_id: str = Field(min_length=1)


class ForgeAIMessageCreate(BaseModel):
    content: str = Field(min_length=1)
