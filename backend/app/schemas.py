from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)


class RegisterIn(LoginIn):
    subjects: list[str] = Field(default_factory=list)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    grade: int | None = None
    display_name: str = ""
    subjects: list[str] = Field(default_factory=lambda: ["*"])

    model_config = {"from_attributes": True}


class StudentIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)
    grade: int | None = Field(default=None, ge=1, le=12)
    display_name: str = Field(default="", max_length=64)
    group_ids: list[int] = Field(default_factory=list)


class StudentPatchIn(BaseModel):
    display_name: str = Field(default="", max_length=64)
    grade: int | None = Field(default=None, ge=1, le=12)
    group_ids: list[int] | None = None


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = "group"
    grade: int | None = Field(default=None, ge=1, le=12)
    parent_id: int | None = None


class MemberIn(BaseModel):
    student_id: int


class PaperAudienceIn(BaseModel):
    group_id: int
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class PaperWindowIn(BaseModel):
    opens_at: datetime
    closes_at: datetime
    audiences: list[PaperAudienceIn] = Field(default_factory=list)


class ChallengeStartIn(BaseModel):
    subject: str | None = None
    grade: int | None = None
    difficulty: str | None = None
    tags: list[str] = Field(default_factory=list)
    resume: bool = False


class DraftIn(BaseModel):
    parts: dict[str, object] = Field(default_factory=dict)


class AssembleSectionIn(BaseModel):
    id: str
    count: int = Field(default=0, ge=0, le=50)
    heading: str = ""


class AssembleIn(BaseModel):
    subject: str
    grade: int | None = None
    types: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    count: int = Field(default=0, ge=0, le=50)
    kind: str = "homework"
    duration_minutes: int = Field(default=0, ge=0, le=24 * 60)
    sections: list[AssembleSectionIn] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PasteIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class PlainItemIn(BaseModel):
    subject: str
    type: str = "blank"
    stem: str = Field(min_length=1)
    answer: str = ""
    grade: int | None = None
    difficulty: str = "medium"
    title: str = ""
    tags: list[str] = Field(default_factory=list)


class GradeIn(BaseModel):
    answer_id: int
    score: float = 0
    comment: str = ""
    regrade: bool = False


class ItemPartEditIn(BaseModel):
    id: str = "main"
    type: str
    stem: str = ""
    points: float = 0
    choices: list[dict[str, str]] = Field(default_factory=list)
    answer: Any = None
    reference: str = ""
    rubric: list[dict[str, Any]] = Field(default_factory=list)
    tolerance: float = 0
    unit: str = ""
    allow_photo: bool = False


class ItemEditIn(BaseModel):
    title: str = ""
    subject: str | None = None
    grade: int | None = None
    difficulty: str = "medium"
    tags: list[str] = Field(default_factory=list)
    points: float | None = None
    left_md: str = ""
    allow_photo: bool = False
    parts: list[ItemPartEditIn] = Field(default_factory=list)


class LlmSettingsIn(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    chat_path: str = "/chat/completions"
    keep_key: bool = False
    enable_thinking: bool = False
    reasoning_effort: str = "none"
