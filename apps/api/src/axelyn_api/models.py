"""Versioned request and response models for the public HTTP contract."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator


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


ForgeOutput = Literal["resume", "cover-letter"]


class ForgeBriefCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_role: str = Field(min_length=2, max_length=160)
    company: Optional[str] = Field(default=None, max_length=160)
    job_description: str = Field(min_length=100, max_length=20000)
    career_evidence: str = Field(min_length=100, max_length=30000)
    outputs: List[ForgeOutput] = Field(min_length=1, max_length=2)
    consent: Literal[True]

    @field_validator("outputs")
    @classmethod
    def outputs_are_unique(cls, value: List[ForgeOutput]) -> List[ForgeOutput]:
        if len(value) != len(set(value)):
            raise ValueError("outputs must not contain duplicates")
        return value


class ForgeBriefAnalysis(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    matched_keywords: List[str]
    gap_keywords: List[str]
    evidence_highlights: List[str]
    recommendations: List[str]


class ForgeBriefAccepted(ForgeBriefAnalysis):
    id: str
    status: Literal["ready"]
    created_at: str
    target_role: str
    company: Optional[str]
    outputs: List[ForgeOutput]


ResumeSourceStatus = Literal["needs_review", "needs_ocr", "ready"]
RESUME_SECTION_NAMES = {
    "summary",
    "experience",
    "projects",
    "education",
    "skills",
    "languages",
    "additional",
}


class ResumeDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(default="", max_length=160)
    headline: str = Field(default="", max_length=200)
    contact_line: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=2_000)
    extracted_text: str = Field(default="", max_length=100_000)
    sections: dict[str, List[str]] = Field(default_factory=dict)

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


class ResumeImportItem(BaseModel):
    filename: str
    status: Literal["stored", "rejected"]
    source: Optional[ResumeSourceSummary] = None
    error: Optional[str] = None


class ResumeImportResponse(BaseModel):
    items: List[ResumeImportItem]


class ResumeDraftUpdate(ResumeDraft):
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
