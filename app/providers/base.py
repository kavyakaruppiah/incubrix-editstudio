"""Base adapter interface for natural-language video editing plan providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseInstructionAdapter(ABC):
    """Abstract provider interface for interpreting video editing instructions into structured plans."""

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Return (is_available, status_message)."""
        pass

    @abstractmethod
    def plan_prompt(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a validated plan dictionary with keys: 'actions', 'unsupported', 'clarification'."""
        pass
