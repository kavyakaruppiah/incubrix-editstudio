import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from app.models.operation import OperationProposal, OperationType


class ParserRegistry:
    """Registry of deterministic rule-based pattern parsers for editing instructions."""

    def __init__(self):
        self._parsers: List[Tuple[OperationType, re.Pattern, Callable[[re.Match], Dict[str, Any]]]] = []

    def register(self, op_type: OperationType, pattern: str, extractor: Callable[[re.Match], Dict[str, Any]]) -> None:
        compiled = re.compile(pattern, re.IGNORECASE)
        self._parsers.append((op_type, compiled, extractor))

    def parse(self, text: str) -> Optional[OperationProposal]:
        clean_text = text.strip()
        for op_type, pattern, extractor in self._parsers:
            match = pattern.search(clean_text)
            if match:
                try:
                    params = extractor(match)
                    return OperationProposal(
                        operation_type=op_type,
                        parameters=params,
                        provenance="deterministic_parser",
                        confidence=1.0,
                    )
                except Exception:
                    continue
        return None


def parse_timestamp(s: str) -> float:
    """Convert timestamp format ('00:15', '01:23.5', '12.5s', '15') to seconds."""
    s = s.strip().rstrip("sS")
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
    return float(s)
