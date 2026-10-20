"""Optional Google Gemini Cloud Natural-Language Planner for video editor tools."""

import json
import os
import time
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.engine.capability_registry import capability_registry
from app.providers.base import BaseInstructionAdapter


class GeminiProviderError(RuntimeError):
    """Actionable Gemini cloud provider configuration or request error."""


class GeminiInstructionAdapter(BaseInstructionAdapter):
    """Adapter for Google Gemini models via direct REST API with JSON output."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = (api_key or settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = (model or settings.GEMINI_MODEL or "gemini-2.5-flash").strip()
        self.timeout = timeout if timeout is not None else settings.GEMINI_TIMEOUT_SECONDS

    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "GEMINI_API_KEY is not configured. Set GEMINI_API_KEY to enable Gemini planning."
        return True, f"Gemini provider is configured using model '{self.model}'."

    def plan_prompt(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send prompt to Gemini API and receive validated structured editing plan."""
        clean = instruction.strip()
        if not clean:
            raise GeminiProviderError("Instruction is empty.")
        if not self.api_key:
            raise GeminiProviderError("GEMINI_API_KEY is not configured.")

        tools = capability_registry.tools()
        system_instruction = (
            "You are the natural-language planning layer for an existing professional video editing engine. "
            "Understand the user's complete request, including style requirements, corrections, multiple edits, "
            "aspect ratios, audio adjustments, and multilingual wording.\n"
            "Return an ordered list of typed actions using ONLY the registered tools and their exact parameters.\n"
            "Return only explicitly requested or directly necessary edits. Never invent tools or output raw shell commands.\n"
            "Output must be a strict JSON object with this exact shape:\n"
            "{\n"
            '  "actions": [\n'
            '    {\n'
            '      "operation": "<tool_name>",\n'
            '      "parameters": { ... },\n'
            '      "description": "<short description>"\n'
            "    }\n"
            "  ],\n"
            '  "unsupported": ["<list of any requested edits that are not supported>"],\n'
            '  "clarification": "<concise clarification question if genuinely needed, else empty string>"\n'
            "}\n"
        )

        user_content = (
            f"Registered editor tools:\n{json.dumps(tools, ensure_ascii=False, indent=2)}\n\n"
            f"Current media and timeline context:\n{json.dumps(context, ensure_ascii=False, default=str, indent=2)}\n\n"
            f"User request:\n{clean}"
        )

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_instruction}\n\n{user_content}"}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
                "maxOutputTokens": 2048,
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(2 * 1024 * 1024).decode("utf-8")
            response_json = json.loads(raw)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", "replace")[:500]
            raise GeminiProviderError(f"Gemini API returned HTTP {exc.code}: {error_body}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise GeminiProviderError(f"Failed to connect to Gemini API: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GeminiProviderError("Gemini API returned unparseable response.") from exc

        # Extract generated content
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise GeminiProviderError("Gemini returned no candidates.")
        first_candidate = candidates[0]
        content_parts = first_candidate.get("content", {}).get("parts", [])
        if not content_parts or "text" not in content_parts[0]:
            raise GeminiProviderError("Gemini candidate did not contain text.")

        raw_text = content_parts[0]["text"].strip()
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise GeminiProviderError("Gemini output was not valid JSON.") from exc

        actions = parsed.get("actions", [])
        unsupported = parsed.get("unsupported", [])
        clarification = parsed.get("clarification", "")

        if not isinstance(actions, list):
            actions = []
        if not isinstance(unsupported, list):
            unsupported = []
        if not isinstance(clarification, str):
            clarification = ""

        # Validate action objects
        validated_actions = []
        for act in actions:
            if isinstance(act, dict) and "operation" in act:
                op_name = str(act["operation"]).strip().lower()
                params = act.get("parameters", {})
                desc = act.get("description", clean)
                validated_actions.append({
                    "operation": op_name,
                    "parameters": params if isinstance(params, dict) else {},
                    "description": str(desc)[:500],
                })

        return {
            "actions": validated_actions,
            "unsupported": [str(u) for u in unsupported if u],
            "clarification": clarification.strip(),
        }
