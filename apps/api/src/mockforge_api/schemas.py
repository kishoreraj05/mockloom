"""Request and response bodies of the management API. The TypeScript client is generated from these."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any, Literal

from mockforge_engine.limits import MAX_DELAY_MS
from mockforge_engine.rules import Then, When
from pydantic import BaseModel, Field, field_validator

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    spec_text: str | None = None
    rules: list[RuleIn] = Field(default_factory=list, description="Created with the workspace; needs spec_text.")

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        if value is not None and not _SLUG.match(value):
            raise ValueError("Slugs use lowercase letters, digits and hyphens")
        return value


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    seed: int | None = None
    validation_mode: Literal["strict", "off"] | None = None


class WorkspaceOut(BaseModel):
    id: str
    slug: str
    name: str
    seed: int
    validation_mode: str
    created_at: dt.datetime
    active_version: int | None
    route_count: int
    rule_count: int
    spec_title: str | None
    mock_path: str


class SpecIssueOut(BaseModel):
    severity: Literal["error", "warning"]
    message: str
    path: str | None = None
    line: int | None = None


class SpecText(BaseModel):
    text: str


class SpecValidation(BaseModel):
    ok: bool
    issues: list[SpecIssueOut]
    title: str | None = None
    openapi_version: str | None = None
    route_count: int = 0


class SpecSaved(BaseModel):
    version: int
    changed: bool
    issues: list[SpecIssueOut]
    route_count: int
    orphaned_rules: list[str]
    restored_rules: list[str]


class SpecVersionOut(BaseModel):
    version: int
    content_hash: str
    created_at: dt.datetime
    active: bool


class SpecOut(BaseModel):
    version: int
    text: str


class ParameterOut(BaseModel):
    name: str
    location: str
    required: bool
    schema_: Any = Field(default=None, alias="schema")
    example: Any = Field(default=None, description="A dummy value that passes this parameter's validation.")


class ResponseOut(BaseModel):
    status: str
    description: str
    content_types: list[str]


class RouteSummary(BaseModel):
    key: str
    method: str
    path: str
    summary: str
    tag: str
    rule_count: int
    has_chaos: bool


class RouteDetail(RouteSummary):
    description: str
    parameters: list[ParameterOut]
    body_required: bool
    body_content_types: list[str]
    sample_body: Any = None
    responses: list[ResponseOut]


class ResponseSample(BaseModel):
    status: str
    content_type: str | None
    body: Any = None
    # Schema with the spec's components beside it, ready for Monaco's JSON language service.
    schema_: Any = Field(default=None, alias="schema")


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    route: str
    priority: int = 100
    enabled: bool = True
    when: When = Field(default_factory=When)
    then: Then = Field(default_factory=Then)


class RuleOut(BaseModel):
    id: str
    name: str
    route: str
    priority: int
    enabled: bool
    orphaned: bool
    when: dict[str, Any]
    then: dict[str, Any]


class ChaosIn(BaseModel):
    route_key: str | None = None
    latency_min_ms: Annotated[int, Field(ge=0, le=MAX_DELAY_MS)] = 0
    latency_max_ms: Annotated[int, Field(ge=0, le=MAX_DELAY_MS)] = 0
    error_rate: Annotated[float, Field(ge=0, le=1)] = 0.0
    forced_status: Annotated[int, Field(ge=100, le=599)] | None = None
    offline: bool = False


class ChaosOut(ChaosIn):
    pass


class LogEntry(BaseModel):
    id: str
    ts: dt.datetime
    method: str
    path: str
    status: int
    route_key: str | None
    rule_id: str | None
    rule_name: str | None
    source: str
    chaos: list[str]
    duration_ms: float
    overhead_ms: float
    request: dict[str, Any]
    response: dict[str, Any]


class Problem(BaseModel):
    title: str
    detail: str
    issues: list[SpecIssueOut] = []


WorkspaceCreate.model_rebuild()
