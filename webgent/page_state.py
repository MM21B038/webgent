from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PageSnapshotState:
    url: str
    title: str
    dialog_count: int
    last_scope_ref: str | None = None

    @classmethod
    def from_signals(cls, signals: dict[str, Any]) -> PageSnapshotState:
        return cls(
            url=signals["url"],
            title=signals["title"],
            dialog_count=signals["dialog_count"],
        )

    def sync_from_signals(self, signals: dict[str, Any]) -> None:
        self.url = signals["url"]
        self.title = signals["title"]
        self.dialog_count = signals["dialog_count"]
