from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="student", index=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    subjects_json: Mapped[str] = mapped_column(String(256), default="*")
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    runs: Mapped[list["ChallengeRun"]] = relationship(back_populates="user")
    attempts: Mapped[list["PaperAttempt"]] = relationship(back_populates="user")
    memberships: Mapped[list["StudentGroupMember"]] = relationship(back_populates="user")

    @property
    def subjects(self) -> list[str]:
        raw = (self.subjects_json or "*").strip() or "*"
        if raw in {"*", "all"}:
            return ["*"]
        ids = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]
        return ids or ["*"]


class StudentGroup(Base):
    __tablename__ = "student_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="group", index=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("student_groups.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    parent: Mapped["StudentGroup | None"] = relationship(
        back_populates="children",
        remote_side=[id],
        foreign_keys=[parent_id],
    )
    children: Mapped[list["StudentGroup"]] = relationship(
        back_populates="parent",
        foreign_keys=[parent_id],
    )
    memberships: Mapped[list["StudentGroupMember"]] = relationship(back_populates="group")
    audiences: Mapped[list["PaperAudience"]] = relationship(back_populates="group")


class StudentGroupMember(Base):
    __tablename__ = "student_group_members"
    __table_args__ = (UniqueConstraint("user_id", "group_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("student_groups.id"), index=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    group: Mapped[StudentGroup] = relationship(back_populates="memberships")


class ChallengeRun(Base):
    __tablename__ = "challenge_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(32), index=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    slugs_json: Mapped[str] = mapped_column(Text)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="runs")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(32), index=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="homework")
    slugs_json: Mapped[str] = mapped_column(Text)
    allow_revise: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    sections_json: Mapped[str] = mapped_column(Text, default="[]")
    items_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    grading_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scores_released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    attempts: Mapped[list["PaperAttempt"]] = relationship(back_populates="paper")
    audiences: Mapped[list["PaperAudience"]] = relationship(back_populates="paper")


class PaperAudience(Base):
    __tablename__ = "paper_audiences"
    __table_args__ = (UniqueConstraint("paper_id", "group_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("student_groups.id"), index=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    paper: Mapped[Paper] = relationship(back_populates="audiences")
    group: Mapped[StudentGroup] = relationship(back_populates="audiences")


class PaperAttempt(Base):
    __tablename__ = "paper_attempts"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    paper: Mapped[Paper] = relationship(back_populates="attempts")
    user: Mapped[User] = relationship(back_populates="attempts")


class ItemAnswer(Base):
    __tablename__ = "item_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "context_type", "context_id", "item_slug", "part_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    context_type: Mapped[str] = mapped_column(String(16), index=True)
    context_id: Mapped[int] = mapped_column(Integer, index=True)
    item_slug: Mapped[str] = mapped_column(String(80), index=True)
    part_id: Mapped[str] = mapped_column(String(32))
    value_json: Mapped[str] = mapped_column(Text, default="null")
    photos_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=0)
    llm_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    override_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
