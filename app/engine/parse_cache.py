"""Small deterministic cache for successful structured prompt parses."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock
from typing import Any


PROMPT_VERSION = "prompt_v3"


class ParseCache:
    """Thread-safe bounded LRU cache keyed by prompt, context, model and prompt version."""

    def __init__(self, max_entries: int = 256):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self._lock = RLock()

    @staticmethod
    def key(instruction: str, context: dict[str, Any], model: str, prompt_version: str = PROMPT_VERSION) -> str:
        context_digest = sha256(
            json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()
        payload = json.dumps(
            {"instruction": instruction.strip(), "context_digest": context_digest, "model": model, "prompt_version": prompt_version},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._entries:
                return None
            self._entries.move_to_end(key)
            return deepcopy(self._entries[key])

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = deepcopy(value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


parse_cache = ParseCache()
