from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Sequence

from .models import CollectedKeyword, KeywordCollectStatus, ParsedKeywordList, PreviousVersion


@dataclass(frozen=True)
class ChangeDecision:
    status: KeywordCollectStatus
    content_hash: str
    is_changed: bool
    effective_snapshot_id: int | None


def content_hash(keywords: Sequence[CollectedKeyword]) -> str:
    payload = json.dumps(
        [keyword.normalized_keyword for keyword in keywords],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def decide_change(previous: PreviousVersion | None, parsed: ParsedKeywordList) -> ChangeDecision:
    current_hash = content_hash(parsed.keywords)
    unchanged = previous is not None and previous.content_hash == current_hash
    return ChangeDecision(
        status=(
            KeywordCollectStatus.SUCCESS
            if parsed.keywords
            else KeywordCollectStatus.EMPTY
        ),
        content_hash=current_hash,
        is_changed=not unchanged,
        effective_snapshot_id=(previous.effective_snapshot_id if unchanged else None),
    )
