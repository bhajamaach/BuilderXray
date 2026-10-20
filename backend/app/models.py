from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

class Source(BaseModel):
    id: str
    label: str
    status: Literal['ok','partial','not_checked','running','failed']
    reason: str | None = None
    checked_at: datetime | None = None
    url: str | None = None
class Claim(BaseModel):
    id: str
    text: str
    source_id: str
    source_url: str
    snippet: str | None = None
class Project(BaseModel):
    name: str
    rera_no: str | None = None
    original_possession: date | None = None
    current_possession: date | None = None
    revisions: int | None = None
    claim_ids: list[str] = []
class Complaint(BaseModel):
    ref: str | None = None
    project: str | None = None
    filed_on: date | None = None
    status: Literal['pending','resolved','unknown']
    claim_id: str
class NewsItem(BaseModel):
    title: str
    outlet: str
    published: date | None = None
    tag: Literal['delay','fraud','litigation','neutral']
    reason: str
    claim_id: str
class Flag(BaseModel):
    label: str
    severity: str
    claim_ids: list[str] = []
class Report(BaseModel):
    id: str
    builder_query: str
    builder_name: str
    state: Literal['Haryana','Delhi'] = 'Haryana'
    mode: Literal['live','saved']
    generated_at: datetime
    verdict: Literal['low','medium','high','unknown']
    score: int = 0
    flags: list[Flag] = []
    projects: list[Project] = []
    complaints: list[Complaint] = []
    news: list[NewsItem] = []
    sources: list[Source] = []
    claims: list[Claim] = []
    summary: str
    summary_claim_ids: list[str] = []

class CheckRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    state: Literal['Haryana','Delhi'] = 'Haryana'
    mode: Literal['auto','live','saved'] = 'auto'
    passcode: str | None = None
