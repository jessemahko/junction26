"""Response models = the frozen API contract (plan §6.2). Fields beyond the plan are additive.
Dates are ISO-8601 UTC strings; `to`/`until` = null means "still in the article"."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ArticleSummary(_M):
    page_id: int
    title: str
    revisions: int
    first_rev: str | None
    last_rev: str | None
    n_sentences: int


class Sentence(_M):
    hash: str
    text: str
    position: int
    since: str | None = None
    editor: str | None = None
    rev_id: int | None = None


class AsOf(_M):
    page_id: int
    title: str
    rev_id: int
    timestamp: str | None
    editor: str | None
    anonymous: bool
    comment: str | None
    sentences: list[Sentence]


class DiffSentence(_M):
    hash: str
    text: str
    editor: str | None
    rev_id: int | None


class Diff(_M):
    added: list[DiffSentence]
    removed: list[DiffSentence]
    kept: int


class Contested(_M):
    hash: str
    text: str
    position: int
    lives: int
    rewrites: int
    total_days_alive: float | None
    since: str | None
    first_seen: str | None
    editor: str | None


class Period(_M):
    from_: str | None = Field(alias="from", serialization_alias="from")
    to: str | None
    editor: str | None
    anonymous: bool
    rev_id: int | None
    removed_by: str | None
    removed_by_anonymous: bool | None
    removed_rev: int | None
    removed_comment: str | None


class EditWar(_M):
    hash: str
    text: str
    lives: int
    periods: list[Period]


class RevisionTick(_M):
    rev_id: int
    timestamp: str | None
    editor: str | None
    anonymous: bool
    comment: str | None
    minor: bool
    n_sentences: int
    is_revert: bool


class Ancestor(_M):
    hash: str
    text: str
    editor: str | None
    anonymous: bool
    rev_id: int | None
    from_: str | None = Field(alias="from", serialization_alias="from")
    to: str | None
    depth: int
    tone: str | None
    neutrality: float | None
    event_name: str | None


class About(_M):
    hash: str
    text: str
    event_from: int
    event_to: int

