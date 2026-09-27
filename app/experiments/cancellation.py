"""Catchable live-run cancellation shared by the CLI and process owner."""

import threading
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LiveCancellation:
    event: threading.Event = field(default_factory=threading.Event)
    signal_name: Literal["SIGINT", "SIGTERM"] | None = None

    def request(self, signal_name: Literal["SIGINT", "SIGTERM"]) -> None:
        if not self.event.is_set():
            self.signal_name = signal_name
            self.event.set()
