from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy.orm import Session

from ..models import ItemAnswer, Paper, PaperAttempt
from .bank import Item, Part, bank


def freeze_paper(paper: Paper, *, require_complete: bool = True) -> None:
    """Capture once. Missing legacy items remain explicitly unavailable forever."""
    if paper.items_snapshot_json is not None:
        return
    slugs = json.loads(paper.slugs_json or "[]")
    missing = [slug for slug in slugs if slug not in bank.items]
    if missing and require_complete:
        raise ValueError("题库中找不到：" + ", ".join(missing))
    if require_complete and any(bank.items[slug].subject != paper.subject for slug in slugs):
        raise ValueError("试卷中存在科目不一致的题目")
    paper.items_snapshot_json = json.dumps(
        {slug: asdict(bank.items[slug]) if slug in bank.items else None for slug in slugs},
        ensure_ascii=False,
    )


def paper_item(paper: Paper, slug: str) -> Item | None:
    if not paper.released_at:
        return bank.items.get(slug) if slug in json.loads(paper.slugs_json or "[]") else None
    try:
        encoded = paper.items_snapshot_json or "{}"
        if getattr(paper, "_snapshot_source", None) != encoded:
            # A request may look up every part for an entire class. Decode
            # the immutable snapshot once per ORM instance, not per answer.
            items = {}
            for key, raw in json.loads(encoded).items():
                if isinstance(raw, dict):
                    items[key] = Item(**{**raw, "parts": [Part(**part) for part in raw["parts"]]})
            paper._snapshot_items = items
            paper._snapshot_source = encoded
        return paper._snapshot_items.get(slug)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def context_item(db: Session, context_type: str, context_id: int, slug: str) -> Item | None:
    if context_type == "paper":
        attempt = db.get(PaperAttempt, context_id)
        return paper_item(attempt.paper, slug) if attempt and attempt.paper else None
    if context_type == "challenge":
        return bank.items.get(slug)
    return None


def backfill_legacy_papers(db: Session) -> None:
    """One-time best-effort recovery from the bank available at upgrade."""
    from sqlalchemy import select

    papers = db.scalars(select(Paper).where(Paper.released_at.is_not(None), Paper.items_snapshot_json.is_(None))).all()
    for paper in papers:
        freeze_paper(paper, require_complete=False)
        data = json.loads(paper.items_snapshot_json)
        # If the recorded part or maximum contradicts today's bank, we
        # know the original was different. Preserve scores, don't guess.
        evidence = db.execute(select(ItemAnswer.item_slug, ItemAnswer.part_id, ItemAnswer.max_score)
                              .join(PaperAttempt, PaperAttempt.id == ItemAnswer.context_id)
                              .where(PaperAttempt.paper_id == paper.id, ItemAnswer.context_type == "paper",
                                     ItemAnswer.user_id == PaperAttempt.user_id).distinct())
        for slug, part_id, maximum in evidence:
            raw = data.get(slug)
            if raw and not any(p["id"] == part_id and p["points"] == maximum for p in raw["parts"]):
                data[slug] = None
        paper.items_snapshot_json = json.dumps(data, ensure_ascii=False)
    if papers:
        db.commit()
