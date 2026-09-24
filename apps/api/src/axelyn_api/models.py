"""Versioned request and response models for the public HTTP contract."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


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
