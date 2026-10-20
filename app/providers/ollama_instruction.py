"""Local Ollama natural-language planner for deterministic editor tools."""

import json
import re
import time
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import settings
from app.engine.capability_registry import capability_registry


class OllamaProviderError(RuntimeError):
    """Actionable local-provider configuration or request error."""


class OllamaInstructionAdapter:
    TRANSIENT_RETRY_DELAYS_SECONDS = (0.25, 0.75)
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        api_key: str | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model if model is not None else settings.OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else settings.OLLAMA_TIMEOUT_SECONDS
        self.api_key = (api_key if api_key is not None else settings.OLLAMA_API_KEY or "").strip()
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise OllamaProviderError("OLLAMA_BASE_URL must be an HTTP(S) URL without embedded credentials.")
        self.is_cloud = parsed.hostname.lower() == "ollama.com"
        if not self.model.strip():
            raise OllamaProviderError("Set OLLAMA_MODEL to a model already installed in Ollama.")

    def _request_json(self, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
        for attempt in range(len(self.TRANSIENT_RETRY_DELAYS_SECONDS) + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(self.MAX_RESPONSE_BYTES + 1)
                if len(raw) > self.MAX_RESPONSE_BYTES:
                    raise OllamaProviderError("Ollama response exceeded the 2 MiB safety limit.")
                parsed = json.loads(raw.decode("utf-8"))
                break
            except HTTPError as exc:
                if exc.code >= 500 and attempt < len(self.TRANSIENT_RETRY_DELAYS_SECONDS):
                    time.sleep(self.TRANSIENT_RETRY_DELAYS_SECONDS[attempt])
                    continue
                error_message = ""
                try:
                    error_data = json.loads(exc.read(4096).decode("utf-8", "replace"))
                    if isinstance(error_data, dict) and isinstance(error_data.get("error"), str):
                        error_message = error_data["error"][:500]
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
                if exc.code == 404 and "model" in error_message.lower() and "not found" in error_message.lower():
                    raise OllamaProviderError(
                        f"Configured Ollama model '{self.model}' is not installed. Pull it with `ollama pull {self.model}`, "
                        "or choose an installed model in OLLAMA_MODEL."
                    ) from exc
                if exc.code in (401, 403):
                    raise OllamaProviderError("Ollama rejected the API key. Check OLLAMA_API_KEY in your service environment.") from exc
                if exc.code == 410 and self.is_cloud:
                    raise OllamaProviderError(
                        f"Ollama Cloud no longer serves the configured model '{self.model}' (HTTP 410). "
                        "Update OLLAMA_MODEL in Render to a currently available cloud model, then redeploy."
                    ) from exc
                raise OllamaProviderError(f"Ollama returned HTTP {exc.code} for {path}.") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < len(self.TRANSIENT_RETRY_DELAYS_SECONDS):
                    time.sleep(self.TRANSIENT_RETRY_DELAYS_SECONDS[attempt])
                    continue
                raise OllamaProviderError(
                    f"Cannot reach Ollama at {self.base_url}. Start Ollama and verify OLLAMA_BASE_URL. ({exc})"
                ) from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OllamaProviderError("Ollama returned an invalid JSON response.") from exc
        if not isinstance(parsed, dict):
            raise OllamaProviderError("Ollama returned an unexpected response shape.")
        return parsed

    def is_available(self) -> tuple[bool, str]:
        if self.is_cloud:
            if not self.api_key:
                return False, "OLLAMA_API_KEY is missing. Add your Ollama Cloud key in the service environment."
            return True, f"Ollama Cloud is configured with model '{self.model}'."
        try:
            tags = self._request_json("/api/tags")
        except OllamaProviderError as exc:
            return False, str(exc)
        models = tags.get("models")
        if not isinstance(models, list):
            return False, "Ollama /api/tags did not return a model list. Update Ollama and retry."

        def canonical_model_name(name: str) -> str:
            model_name, separator, tag = name.rpartition(":")
            if not separator:
                model_name, tag = name, "latest"
            return f"{model_name}:{tag}"

        names = {
            canonical_model_name(str(entry.get("name", "")))
            for entry in models
            if isinstance(entry, dict) and entry.get("name")
        }
        if canonical_model_name(self.model) not in names:
            return False, f"Model '{self.model}' is not installed in Ollama. Install it locally or choose another OLLAMA_MODEL."
        return True, f"Ollama is reachable and model '{self.model}' is installed."

    @staticmethod
    def _schema_lowercase(value):
        """Convert the shared registry schema into standard JSON Schema casing."""
        if isinstance(value, dict):
            return {
                key: (item.lower() if key == "type" and isinstance(item, str) else OllamaInstructionAdapter._schema_lowercase(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [OllamaInstructionAdapter._schema_lowercase(item) for item in value]
        return value

    @staticmethod
    def _candidate_tool_names(instruction: str) -> set[str] | None:
        """Return likely tools for schema-constrained decoding; None means broad fallback."""
        text = instruction.casefold()
        candidates: set[str] = set()
        has_time = bool(re.search(r"\d|\b(?:second|seconds|minute|minutes|hour|hours|at|from|between)\b", text))
        if re.search(r"\b(?:cut|trim|delete|remove|take out|edit out)\b", text):
            candidates.update({"cut_range", "remove_phrase"})
            if has_time:
                candidates.add("cut_range")
            if re.search(r"\b(?:filler|fillers|um|uh)\b", text):
                candidates.add("remove_filler_words")
            if re.search(r"\b(?:silence|silences|pause|pauses)\b", text):
                candidates.add("remove_silence")
        if re.search(r"\b(?:keep|retain)\b", text): candidates.add("keep_range")
        if re.search(r"\b(?:reorder|swap)\b", text): candidates.add("reorder_sections")
        if re.search(r"\b(?:speed|faster|slower|slow down|speed up|accelerate)\b", text): candidates.add("speed_change")
        if re.search(r"\b(?:mute|silence|quiet)\b", text): candidates.add("mute")
        if re.search(r"\bbleep\b", text): candidates.add("bleep")
        if re.search(r"\b(?:caption|captions|subtitle|subtitles|karaoke)\b", text):
            candidates.update({"add_caption", "generate_captions", "set_caption_style", "set_caption_mode"})
        if re.search(r"\b(?:overlay|title|text)\b", text): candidates.add("add_text_overlay")
        if re.search(r"\b(?:music|bgm|duck|ducking)\b", text):
            candidates.update({"add_background_music", "audio_ducking"})
        if re.search(r"\b(?:cinematic|color|colour|sepia|grayscale|warm|cool)\b", text): candidates.add("color_grade")
        if re.search(r"\b(?:preset|educational)\b", text): candidates.add("apply_preset")
        if re.search(r"\b(?:fade|crossfade|cross-fade|dissolve|transition)\b", text): candidates.add("add_transition")
        if re.search(r"\b(?:aspect|vertical|landscape|square|reel|short)\b", text):
            candidates.update({"set_aspect_ratio", "create_reel"})
        if re.search(r"\b(?:rotate|mirror|flip)\b|\bturn\s+(?:the\s+)?(?:video|clip|footage)\b", text): candidates.add("video_transform")
        if re.search(r"\bblur\b", text): candidates.add("blur_region")
        if re.search(r"\b(?:normalize|normalise|level audio)\b", text): candidates.add("audio_normalize")
        if re.search(r"\b(?:noise reduction|denoise|de-noise|background noise)\b", text): candidates.add("audio_denoise")
        if re.search(r"\bundo\b", text): candidates.add("undo")
        if re.search(r"\bredo\b", text): candidates.add("redo")
        if re.search(r"\b(?:restore|reset|revert)\b", text): candidates.add("restore_edit")
        # Unknown language, novel editing verbs, and compound requests that do
        # not map safely keep the complete registry available to the model.
        return candidates or None

    def plan_prompt(self, instruction: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Plan all supported edits as typed tool calls, with no executable code."""
        clean = instruction.strip()
        if not clean:
            raise OllamaProviderError("Instruction is empty.")
        if len(clean) > 4000:
            raise OllamaProviderError("Instruction is too long for local planning (maximum 4000 characters).")

        all_tools = capability_registry.tools()
        candidate_names = self._candidate_tool_names(clean)
        tools = (
            [tool for tool in all_tools if tool["name"] in candidate_names]
            if candidate_names is not None else all_tools
        )
        action_variants = []
        for tool in tools:
            action_variants.append({
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": [tool["name"]]},
                    "parameters": self._schema_lowercase(
                        capability_registry.parameter_json_schema(tool["name"])
                    ),
                    "description": {"type": "string"},
                },
                "required": ["operation", "parameters", "description"],
                "additionalProperties": False,
            })
        schema = {
            "type": "object",
            "properties": {
                "actions": {"type": "array", "maxItems": 30, "items": {"oneOf": action_variants}},
                "unsupported": {"type": "array", "items": {"type": "string"}},
                "clarification": {"type": "string"},
            },
            "required": ["actions", "unsupported", "clarification"],
            "additionalProperties": False,
        }
        prompt = (
            "You are the natural-language planning layer for an existing video editor. Understand the COMPLETE request, including "
            "paraphrases, multiple edits, and non-English wording. Return every requested supported edit as an ordered typed action "
            "using ONLY the registered tools and each tool's exact parameters below. Parameters are specific to their operation. "
            "Return only edits explicitly requested; never add captions, overlays, speed changes, or styling as unsolicited extras. "
            "Preserve numbers, quoted text, and user constraints. Use supplied "
            "transcript word IDs/timestamps for spoken-word targets. Infer safe ordinary defaults; ask one concise clarification when "
            "a necessary choice cannot be inferred. Report unsupported requested effects explicitly. Never invent tools, claim edits "
            "were applied, output code, or create FFmpeg arguments. Do not omit supported parts of a compound request. Return JSON only.\n"
            "Examples: ‘make it black and white’ means one color_grade action with preset grayscale. ‘Add a smooth fade-in and fade-out’ means one add_transition action with transition_type fade_in_out and duration 1.0.\n"
            f"Registered tools: {json.dumps(tools, ensure_ascii=False)}\n"
            f"Media/timeline context: {json.dumps(context, ensure_ascii=False, default=str)}\n"
            f"Complete user request:\n{clean}"
        )
        if self.is_cloud:
            result = self._request_json("/api/chat", {
                "model": self.model,
                "stream": False,
                "format": schema,
                "options": {"num_predict": 1024, "temperature": 0},
                "messages": [{"role": "user", "content": prompt}],
            })
            message = result.get("message")
            raw = message.get("content") if isinstance(message, dict) else None
        else:
            result = self._request_json("/api/generate", {
                "model": self.model,
                "stream": False,
                "format": schema,
                "options": {"num_predict": 1024, "temperature": 0},
                "prompt": prompt,
            })
            raw = result.get("response")
        if not isinstance(raw, str):
            raise OllamaProviderError("Ollama response is missing its generated JSON text.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaProviderError("Ollama did not return a valid structured plan; no edits were applied.") from exc
        actions = parsed.get("actions") if isinstance(parsed, dict) else None
        unsupported = parsed.get("unsupported") if isinstance(parsed, dict) else None
        clarification = parsed.get("clarification", "") if isinstance(parsed, dict) else None
        if not isinstance(actions, list) or len(actions) > 30:
            raise OllamaProviderError("Ollama returned an invalid action list; no edits were applied.")
        if not isinstance(unsupported, list) or any(not isinstance(item, str) or len(item) > 1000 for item in unsupported):
            raise OllamaProviderError("Ollama returned invalid unsupported-operation details.")
        if not isinstance(clarification, str):
            raise OllamaProviderError("Ollama returned an invalid clarification.")
        if len(unsupported) > 30 or len(clarification) > 1000:
            raise OllamaProviderError("Ollama returned an oversized clarification or unsupported-operation list.")
        for action in actions:
            if (
                not isinstance(action, dict)
                or not isinstance(action.get("operation"), str)
                or not isinstance(action.get("parameters"), dict)
                or not isinstance(action.get("description"), str)
                or len(action["description"]) > 1000
            ):
                raise OllamaProviderError("Ollama returned a malformed action; no edits were applied.")
        return {"actions": actions, "unsupported": unsupported, "clarification": clarification}

    def split_prompt(self, instruction: str) -> List[str]:
        """Compatibility API for older callers; descriptions still come from typed plans."""
        plan = self.plan_prompt(instruction, {})
        descriptions = [action["description"].strip() for action in plan["actions"]]
        descriptions.extend(item.strip() for item in plan["unsupported"] if item.strip())
        if not descriptions and plan["clarification"]:
            descriptions.append(plan["clarification"].strip())
        return descriptions
