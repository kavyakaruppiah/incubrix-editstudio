import copy
import re
import uuid
from typing import Any, Dict, List, Optional
from app.config import settings
from app.engine.instruction_parser import InstructionParser, ClarificationNeeded
from app.models.operation import OperationProposal, OperationType
from app.engine.capability_registry import capability_registry
from app.engine.timeline_engine import TimelineEngine
from app.engine.parse_cache import parse_cache
from app.services.instruction_service import instruction_service
from app.services.timeline_service import timeline_service
from app.services.media_service import media_service
from app.providers.ollama_instruction import OllamaInstructionAdapter, OllamaProviderError
from app.providers.gemini_instruction import GeminiInstructionAdapter, GeminiProviderError


class AIPlanService:
    def __init__(self):
        self.parser = InstructionParser()

    def generate_plan(self, media_id: str, prompt: str) -> Dict[str, Any]:
        """
        Interprets natural-language prompt (single or compound instructions)
        into a validated structured edit plan.
        """
        engine = timeline_service.get_engine(media_id)
        if not engine:
            raise ValueError(f"Media '{media_id}' not found")

        timeline = engine.timeline
        media_dur = timeline.total_output_duration
        source_meta = timeline.source_metadata

        raw_prompt = prompt.strip()
        if not raw_prompt:
            raise ValueError("Empty prompt provided")

        # Ollama returns typed tools; rules remain an offline fallback.
        provider = settings.INSTRUCTION_PROVIDER.strip().lower()
        provider_notice = None
        structured_actions = None
        unsupported_requests: List[str] = []
        clarification = None
        fallback_compound_blocked = False
        if provider == "rules":
            clauses = self._split_compound_prompt(raw_prompt)
        elif provider == "gemini":
            try:
                gemini_adapter = GeminiInstructionAdapter()
                avail, msg = gemini_adapter.is_available()
                if not avail:
                    raise GeminiProviderError(msg)
                planner_context = self._planner_context(timeline, raw_prompt)
                response = gemini_adapter.plan_prompt(raw_prompt, planner_context)
                structured_actions = response["actions"]
                unsupported_requests = response["unsupported"]
                clarification = response.get("clarification") or None
                clauses = []
                provider_notice = f"Interpreted using Google Gemini ({settings.GEMINI_MODEL})."
            except GeminiProviderError as exc:
                fallback_prompt = self._normalize_compound_synonyms(raw_prompt)
                clauses = self._split_compound_prompt(fallback_prompt)
                provider = "rules_fallback"
                provider_notice = f"Gemini planning unavailable ({exc}). Using offline rules fallback."
        elif provider in ("auto", "ollama"):
            try:
                if provider == "auto" and not settings.OLLAMA_MODEL.strip():
                    raise OllamaProviderError("Ollama is not configured. Set OLLAMA_MODEL to use local AI planning.")
                # Prefer an exact deterministic match before asking a local model.
                direct = None
                compound_actions = None
                paired_fade = bool(re.fullmatch(
                    r"\s*(?:please\s+)?(?:add|apply)\s+(?:a\s+)?(?:smooth\s+)?"
                    r"fade[- ]in\s+(?:and\s+)?fade[- ]out(?:\s+(?:of\s+)?[\d.]+s?)?\s*[.!]?\s*",
                    raw_prompt,
                    re.IGNORECASE,
                ))
                if self._looks_compound(raw_prompt) and not paired_fade:
                    compound_actions = self._parse_supported_compound(raw_prompt, timeline)
                if compound_actions:
                    structured_actions = compound_actions
                    clauses = []
                    provider = "rules_fast_path"
                    response = None
                elif paired_fade or not self._looks_compound(raw_prompt):
                    try:
                        direct = self.parser.parse_instruction(raw_prompt, timeline)
                    except Exception:
                        direct = None
                if compound_actions:
                    pass
                elif direct is not None:
                    structured_actions = [{
                        "operation": direct.operation_type.value,
                        "parameters": direct.parameters,
                        "description": raw_prompt,
                    }]
                    clauses = []
                    provider = "rules_fast_path"
                    response = None
                else:
                    response = True
                if response is not None:
                    planner_context = self._planner_context(timeline, raw_prompt)
                    response = self._plan_with_local_models(raw_prompt, planner_context)
                    structured_actions = response["actions"]
                    unsupported_requests = response["unsupported"]
                    clarification = response.get("clarification") or None
                    clauses = []
                    provider = "ollama"
            except OllamaProviderError as exc:
                # Explicit Ollama mode must not silently call a billable Gemini API.
                # In auto mode, Gemini remains a preferred cloud fallback.
                avail = False
                if provider == "auto":
                    gemini_adapter = GeminiInstructionAdapter()
                    avail, _ = gemini_adapter.is_available()
                if avail:
                    try:
                        planner_context = self._planner_context(timeline, raw_prompt)
                        response = gemini_adapter.plan_prompt(raw_prompt, planner_context)
                        structured_actions = response["actions"]
                        unsupported_requests = response["unsupported"]
                        clarification = response.get("clarification") or None
                        clauses = []
                        provider = "gemini"
                        provider_notice = f"Local Ollama was unavailable; planned using Google Gemini ({settings.GEMINI_MODEL})."
                    except Exception:
                        avail = False
                if not avail or structured_actions is None:
                    fallback_prompt = self._normalize_compound_synonyms(raw_prompt)
                    clauses = self._split_compound_prompt(fallback_prompt)
                    provider = "rules_fallback"
                    provider_notice = (
                        f"Ollama planning could not interpret this request ({exc}). This preview uses the built-in "
                        "parser; verify each suggested operation before approving."
                    )
                    if self._looks_compound(fallback_prompt) and len(clauses) <= 1:
                        clauses = []
                        unsupported_requests.append(raw_prompt)
                        fallback_compound_blocked = True
        else:
            raise ValueError("INSTRUCTION_PROVIDER must be 'auto', 'rules', 'ollama', or 'gemini'.")

        operations: List[Dict[str, Any]] = []
        warnings: List[str] = [provider_notice] if provider_notice else []
        if clarification:
            operations.append({
                "id": f"plan_op_{uuid.uuid4().hex[:6]}",
                "type": "needs_clarification",
                "name": "Clarification Required",
                "description": clarification,
                "parameters": {},
                "validation_status": "warning",
                "validation_message": "Answer this question and submit the request again.",
            })
        for unsupported in unsupported_requests:
            operations.append({
                "id": f"plan_op_{uuid.uuid4().hex[:6]}",
                "type": "unsupported_or_invalid",
                "name": "Unsupported capability",
                "description": unsupported,
                "parameters": {},
                "validation_status": "unsupported",
                "validation_message": (
                    "Local AI planning is unavailable and the built-in parser could not safely interpret every part of this compound request. "
                    "No edits from this request were applied; configure Ollama and retry."
                    if fallback_compound_blocked
                    else "This request is not currently backed by an editing tool."
                ),
            })
            warnings.append(f"Unsupported capability: {unsupported}")
        target_aspect_ratio = timeline.video_effects.aspect_ratio or "original"
        if re.search(r"vertical|9:16", raw_prompt, re.IGNORECASE):
            target_aspect_ratio = "9:16"
        elif re.search(r"square|1:1", raw_prompt, re.IGNORECASE):
            target_aspect_ratio = "1:1"
        elif re.search(r"landscape|16:9", raw_prompt, re.IGNORECASE):
            target_aspect_ratio = "16:9"

        target_duration = media_dur

        for action in structured_actions or []:
            op_name = action["operation"].strip().lower()
            params = action["parameters"]
            description = action["description"].strip() or op_name
            validation_error = capability_registry.validate(op_name, params)
            if validation_error:
                operations.append({
                    "id": f"plan_op_{uuid.uuid4().hex[:6]}",
                    "type": "unsupported_or_invalid",
                    "name": description[:80],
                    "description": description,
                    "parameters": params,
                    "validation_status": "unsupported",
                    "validation_message": validation_error,
                })
                warnings.append(validation_error)
                continue
            try:
                prop = OperationProposal(
                    operation_type=OperationType(op_name),
                    parameters=params,
                    provenance="ollama_tool_plan",
                    confidence=1.0,
                )
                op_info = self._format_proposal(prop, timeline, description)
                op_info["id"] = f"plan_op_{uuid.uuid4().hex[:6]}"
                op_info["execution_mode"] = "structured"
                operations.append(op_info)
                if prop.operation_type in (OperationType.SET_ASPECT_RATIO, OperationType.CREATE_REEL):
                    if params.get("aspect_ratio"):
                        target_aspect_ratio = params["aspect_ratio"]
                if "target_duration" in params:
                    target_duration = params["target_duration"]
                elif "target_duration_s" in params:
                    target_duration = params["target_duration_s"]
            except (ValueError, TypeError) as exc:
                operations.append({
                    "id": f"plan_op_{uuid.uuid4().hex[:6]}",
                    "type": "unsupported_or_invalid",
                    "name": description[:80],
                    "description": description,
                    "parameters": params,
                    "validation_status": "unsupported",
                    "validation_message": f"Invalid tool proposal: {exc}",
                })

        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue

            # Check for title requests specifically
            title_match = re.search(r"(?:add\s+)?(?:opening\s+|closing\s+)?\btitle\b(?:\s+card\b)?(?:\s+(?:saying|text|with text)?\s*[\"'](?P<txt>[^\"']+)[\"']|\s+saying\s+(?P<txt_bare>[^,\.]+))?", clause, re.IGNORECASE)
            if title_match and re.search(r"\btitle\b", clause, re.IGNORECASE):
                title_text = (title_match.group("txt") or title_match.group("txt_bare") or "Title").strip()
                is_closing = "closing" in clause.lower() or "finish" in clause.lower() or "end" in clause.lower()
                op_id = f"plan_op_{uuid.uuid4().hex[:6]}"
                operations.append({
                    "id": op_id,
                    "type": "add_title",
                    "name": "Add Closing Title" if is_closing else "Add Opening Title",
                    "description": f"Add title overlay '{title_text}' at {'end of video' if is_closing else 'beginning (0.0s - 3.5s)'}",
                    "parameters": {
                        "text": title_text,
                        "position": "center",
                        "timing": "closing" if is_closing else "opening",
                        "start_seconds": max(0.0, media_dur - 3.5) if is_closing else 0.0,
                        "end_seconds": media_dur if is_closing else min(3.5, media_dur),
                    },
                    "validation_status": "valid",
                    "validation_message": "Supported text overlay renderer",
                })
                continue

            try:
                prop = self.parser.parse_instruction(clause, timeline)
                op_id = f"plan_op_{uuid.uuid4().hex[:6]}"
                op_info = self._format_proposal(prop, timeline, clause)
                op_info["id"] = op_id
                operations.append(op_info)

                if prop.operation_type in (OperationType.SET_ASPECT_RATIO, OperationType.CREATE_REEL):
                    ar = prop.parameters.get("aspect_ratio")
                    if ar:
                        target_aspect_ratio = ar
                if "target_duration" in prop.parameters:
                    target_duration = prop.parameters["target_duration"]
                elif "target_duration_s" in prop.parameters:
                    target_duration = prop.parameters["target_duration_s"]

            except ClarificationNeeded as e:
                # Add as clarification item
                operations.append({
                    "id": f"plan_op_{uuid.uuid4().hex[:6]}",
                    "type": "needs_clarification",
                    "name": "Clarification Required",
                    "description": e.question,
                    "parameters": {"options": [opt.model_dump() for opt in e.options]},
                    "validation_status": "warning",
                    "validation_message": "Phrase appears multiple times; user choice needed before execution.",
                })
            except Exception as e:
                # Unsupported or vague instruction
                err_msg = str(e)
                operations.append({
                    "id": f"plan_op_{uuid.uuid4().hex[:6]}",
                    "type": "unsupported_or_invalid",
                    "name": f"Instruction: '{clause[:40]}...'",
                    "description": clause,
                    "parameters": {},
                    "validation_status": "unsupported",
                    "validation_message": err_msg,
                })
                warnings.append(f"Clause '{clause}' could not be parsed: {err_msg}")

        # Compute estimated duration after cuts
        estimated_duration = target_duration
        cut_duration = 0.0
        for op in operations:
            if op.get("type") in ("cut_range", "cut_time") and op.get("validation_status") == "valid":
                p = op.get("parameters", {})
                st = p.get("start", p.get("start_time", 0.0))
                et = p.get("end", p.get("end_time", 0.0))
                if et > st:
                    cut_duration += (et - st)
        if cut_duration > 0:
            estimated_duration = max(1.0, round(media_dur - cut_duration, 2))

        return {
            "media_id": media_id,
            "original_prompt": prompt,
            "target_duration_seconds": round(estimated_duration, 2),
            "original_duration_seconds": round(media_dur, 2),
            "aspect_ratio": target_aspect_ratio,
            "operations_count": len(operations),
            "supported_count": sum(1 for o in operations if o.get("validation_status") == "valid"),
            "operations": operations,
            "warnings": warnings,
            "provider_notice": provider_notice,
            "status": "ready_for_review",
            "instruction_provider": provider,
        }

    def _plan_with_local_models(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Use small local models as a quality fallback, only when the primary plan is incomplete."""
        primary = settings.OLLAMA_MODEL.strip()
        fallback_models = [
            name.strip() for name in settings.OLLAMA_FALLBACK_MODELS.split(",") if name.strip()
        ]
        model_names = list(dict.fromkeys([primary, *fallback_models]))
        best_response = None
        best_score = float("-inf")
        last_error = None

        for index, model_name in enumerate(model_names):
            cache_key = parse_cache.key(prompt, context, model=model_name)
            response = parse_cache.get(cache_key)
            if response is None:
                try:
                    adapter = OllamaInstructionAdapter() if index == 0 else OllamaInstructionAdapter(model=model_name)
                    response = adapter.plan_prompt(prompt, context)
                    parse_cache.put(cache_key, response)
                except OllamaProviderError as exc:
                    last_error = exc
                    # A dead or timing-out Ollama server cannot be helped by
                    # loading more models; return to the fast deterministic fallback.
                    if "cannot reach ollama" in str(exc).lower():
                        break
                    continue

            response = copy.deepcopy(response)
            response["actions"] = [
                action for action in response["actions"]
                if self._model_action_matches_request(prompt, action["operation"])
            ]
            valid_actions = sum(
                1 for action in response["actions"]
                if capability_registry.validate(action["operation"], action["parameters"]) is None
            )
            if valid_actions:
                requested = re.sub(r"[^\w\s]", "", prompt.casefold()).strip()
                response["unsupported"] = [
                    item for item in response["unsupported"]
                    if re.sub(r"[^\w\s]", "", item.casefold()).strip() != requested
                ]
                # The planner contract asks for a question. Ignore explanatory
                # commentary mistakenly placed in its clarification field.
                if response.get("clarification") and "?" not in response["clarification"]:
                    response["clarification"] = ""
            # Prefer more executable operations while penalizing model guesses
            # and unnecessary clarification. Keep the best usable plan if every
            # model returns a partial answer.
            score = valid_actions * 10 - len(response["unsupported"]) - (2 if response.get("clarification") else 0)
            if score > best_score:
                best_response, best_score = response, score
            complete = (
                not response["unsupported"]
                and not response.get("clarification")
                and valid_actions == len(response["actions"])
                and bool(response["actions"])
            )
            if complete:
                return response

        if best_response is not None:
            return best_response
        if last_error:
            raise last_error
        raise OllamaProviderError("No configured local model returned a usable plan.")

    @staticmethod
    def _model_action_matches_request(prompt: str, operation: str) -> bool:
        """Drop common high-risk extras a small planner may invent unprompted."""
        cues = {
            "cut_range": r"cut|trim|remove|delete|take\s+out|edit\s+out|crop\s+out",
            "keep_range": r"keep|retain|only\s+use|save\s+from",
            "remove_phrase": r"remove|cut|delete|take\s+out|edit\s+out|word|phrase",
            "reorder_sections": r"reorder|rearrange|swap|move\s+(?:the\s+)?(?:clips?|sections?)",
            "color_grade": r"colou?r|warm|cool|black\s*(?:and|&)\s*white|sepia|grayscale|grey\s*scale|monochrome|cinematic|film\s+look|vibrant|saturat|desaturat|brightness|contrast|gamma|tone|grade|filter|visual\s+look|aesthetic|paal[- ]?vannam|karuppu\s+vellai|vellai\s+karuppu",
            "apply_preset": r"preset|cinematic|educational|reel\s+look|film\s+look",
            "set_caption_style": r"caption|subtitle|font|typograph|outline|text\s+style",
            "set_caption_mode": r"caption|subtitle|karaoke|word[- ]by[- ]word|highlight\s+(?:each|every|spoken)\s+word",
            "add_caption": r"caption|subtitle|subtitles|word[- ]aligned\s+text",
            "generate_captions": r"caption|subtitle|transcript|spoken\s+words\s+on\s+screen",
            "add_text_overlay": r"title|text\s+overlay|overlay\s+text|intro|outro|opening\s+card|closing\s+card|welcome\s+card|write\s+.+\s+on\s+screen",
            "set_aspect_ratio": r"aspect\s+ratio|vertical|portrait|square|landscape|9:16|16:9|1:1",
            "create_reel": r"reel|short|vertical|portrait|square|9:16|aspect\s+ratio",
            "speed_change": r"speed|faster|slower|slow[- ]motion|fast[- ]forward|pacing",
            "add_transition": r"fade|transition|cross[- ]?fade|dissolve",
            "blur_region": r"blur|background\s+soften",
            "video_transform": r"rotate|turn\s+the\s+video|mirror|flip",
            "add_background_music": r"music|soundtrack|background\s+audio|song",
            "audio_ducking": r"duck|lower\s+(?:the\s+)?music|music\s+under\s+(?:speech|voice)",
            "audio_normalize": r"normaliz|audio\s+level|loudness|volume\s+level",
            "audio_denoise": r"noise|wind|hiss|hum|background\s+sound",
            "mute": r"mute|silence\s+(?:the\s+)?audio|remove\s+audio",
            "bleep": r"bleep|censor|beep\s+out",
            "remove_silence": r"silence|pause|dead\s+air|long\s+gap",
            "remove_filler_words": r"filler|um\b|uh\b|hesitation",
            "undo": r"undo|reverse\s+(?:that|the\s+last\s+edit)|go\s+back\s+one\s+step",
            "redo": r"redo|repeat\s+(?:that|the\s+last\s+edit)|restore\s+the\s+undone\s+edit",
            "restore_edit": r"restore|revert\s+to|recover|version\s+\d|revision\s+\d",
        }
        cue = cues.get(operation)
        return cue is None or bool(re.search(cue, prompt, re.IGNORECASE))

    def apply_plan(self, media_id: str, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes approved operations from the plan sequentially on the timeline engine.
        """
        engine = timeline_service.get_engine(media_id)
        if not engine:
            raise ValueError(f"Timeline for '{media_id}' not found")

        # A reviewed plan is one user action: keep a rollback point so a later
        # rejected operation cannot leave earlier edits committed on their own.
        original_timeline = engine.timeline.model_copy(deep=True)
        original_snapshots = copy.deepcopy(engine.snapshots)
        original_redo_stack = copy.deepcopy(engine.redo_stack)
        applied_ops = []
        errors = []
        skipped_ops = []

        for op in operations:
            if op.get("validation_status", "valid") != "valid":
                skipped_ops.append(
                    f"{op.get('description') or op.get('name') or op.get('type', 'operation')}: "
                    f"{op.get('validation_message') or 'This part needs clarification or is not supported.'}"
                )
                continue

            op_type = op.get("type")
            params = op.get("parameters", {})

            # Unsupported entries are informational plan items, not a reason to
            # cancel independent, validated operations in the same request.
            if op_type in ("unsupported_or_invalid", "needs_clarification"):
                skipped_ops.append(
                    f"{op.get('description') or op.get('name') or op_type}: "
                    f"{op.get('validation_message') or 'No matching editing capability is available.'}"
                )
                continue

            if op.get("execution_mode") == "structured":
                validation_error = capability_registry.validate(op_type or "", params)
                if validation_error:
                    errors.append(f"Could not apply '{op.get('description') or op_type}': {validation_error}")
                    break

            try:
                if op_type == "add_title":
                    txt = params.get("text", "Title")
                    st = params.get("start_seconds", 0.0)
                    et = params.get("end_seconds", 3.5)
                    pos = params.get("position", "center")
                    engine.apply_add_text_overlay(
                        text=txt,
                        position=pos,
                        source_start=st,
                        source_end=et,
                    )
                    applied_ops.append(f"Added title '{txt}'")
                    continue

                # Standard instruction processing via reconstructed command
                cmd = op.get("description") or op.get("name")
                if not cmd:
                    errors.append(f"Operation '{op_type or 'unknown'}' has no instruction text")
                    break
                if op.get("execution_mode") == "structured":
                    operation = OperationType(op_type)
                    proposal = OperationProposal(
                        operation_type=operation,
                        parameters=params,
                        provenance="approved_ai_plan",
                    )
                    res = instruction_service.process_proposal(media_id, proposal)
                else:
                    res = instruction_service.process_instruction(media_id, cmd)
                if res.status.value == "applied":
                    applied_ops.append(cmd)
                else:
                    errors.append(f"Could not apply '{cmd}': {res.message}")
                    break
            except Exception as e:
                errors.append(f"Failed '{op.get('description') or op_type or 'operation'}': {str(e)}")
                break

        if errors:
            engine.timeline = original_timeline
            engine.snapshots = original_snapshots
            engine.redo_stack = original_redo_stack
            timeline_service.save_timeline(original_timeline)
            applied_ops.clear()
        else:
            timeline_service.save_timeline(engine.timeline)

        tl = engine.timeline

        return {
            "media_id": media_id,
            "revision": tl.revision,
            "total_output_duration": round(tl.total_output_duration, 2),
            "applied_count": len(applied_ops),
            "applied_operations": applied_ops,
            "errors": errors,
            "skipped_count": len(skipped_ops),
            "skipped_operations": skipped_ops,
            "status": (
                "rejected" if errors
                else "partial" if applied_ops and skipped_ops
                else "unsupported" if skipped_ops or not applied_ops
                else "applied"
            ),
        }

    def _split_compound_prompt(self, text: str) -> List[str]:
        """Split commands only at top level, keeping quoted phrases and decimal times intact."""
        command = (
            r"cut|delete|remove|trim|keep|reorder|swap|speed|slow|mute|bleep|"
            r"add|apply|use|create|make|set|change|generate|auto|highlight|karaoke|"
            r"undo|redo|restore|reset|revert|start\s+over|give|blur|normalize|"
            r"enable|disable|cross[- ]?fade|dissolve|denoise|reduce|rotate|turn|mirror|flip"
        )
        separator = re.compile(
            rf"(?:;|\n|\.(?=\s+(?:{command})\b)|,\s*(?:(?:and\s+then|then|also|and)\s+)?(?=(?:{command})\b)|"
            rf"\s+(?:and\s+then|then|also|and)\s+(?=(?:{command})\b))",
            re.IGNORECASE,
        )
        clauses: List[str] = []
        start = 0
        quote: str | None = None
        escaped = False
        index = 0
        while index < len(text):
            char = text[index]
            if escaped:
                escaped = False
            elif char == "\\" and quote:
                escaped = True
            elif quote and char == quote:
                quote = None
            elif not quote and char in ("'", '"'):
                quote = char
            if not quote:
                match = separator.match(text, index)
                if match:
                    clause = text[start:index].strip(" ,.;\n\t")
                    if clause:
                        clauses.append(clause)
                    start = match.end()
                    index = start
                    continue
            index += 1
        tail = text[start:].strip(" ,.;\n\t")
        if tail:
            clauses.append(tail)
        return clauses

    def _parse_supported_compound(self, prompt: str, timeline) -> List[Dict[str, Any]] | None:
        """Parse fully supported compound edits in order against a virtual timeline.

        This avoids asking a small language model to guess required range
        parameters and ensures relative edits (for example, the final seconds
        after an earlier keep) use the duration at that point in the request.
        The caller's timeline is never mutated.
        """
        clauses = self._split_compound_prompt(prompt)
        if len(clauses) < 2:
            return None
        virtual = TimelineEngine(timeline.model_copy(deep=True))
        actions: List[Dict[str, Any]] = []
        for clause in clauses:
            try:
                proposal = self.parser.parse_instruction(clause, virtual.timeline)
            except Exception:
                return None
            operation = proposal.operation_type.value
            parameters = dict(proposal.parameters)
            if operation == OperationType.CUT_TIME.value:
                operation = OperationType.CUT_RANGE.value
                parameters.setdefault("start", parameters.get("start_time"))
                parameters.setdefault("end", parameters.get("end_time"))
                parameters.setdefault("time_basis", "current_timeline")
            error = capability_registry.validate(operation, parameters)
            if error:
                return None
            actions.append({"operation": operation, "parameters": parameters, "description": clause})
            try:
                if operation == OperationType.KEEP_RANGE.value:
                    virtual.apply_keep_range(parameters["start"], parameters["end"], parameters.get("time_basis", "current_timeline"))
                elif operation == OperationType.CUT_RANGE.value:
                    virtual.apply_cut(parameters["start"], parameters["end"], time_basis=parameters.get("time_basis", "current_timeline"))
                elif operation == OperationType.SPEED_CHANGE.value:
                    virtual.apply_speed_change(parameters["start"], parameters["end"], parameters["speed"], time_basis=parameters.get("time_basis", "current_timeline"))
            except (ValueError, KeyError, TypeError):
                return None
        return actions

    @staticmethod
    def _normalize_compound_synonyms(text: str) -> str:
        """Collapse common synonymous silence-removal wording into one action."""
        return re.sub(
            r"\b(remove|cut|delete|clean)\s+(?:all\s+)?silence\s+and\s+(?:all\s+)?long\s+pauses\b",
            r"\1 all long pauses",
            text,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _looks_compound(text: str) -> bool:
        """Conservative guard used only when local AI planning is unavailable."""
        return bool(re.search(
            r"[,;\n]|\b(?:and|then|also|while|plus|as\s+well\s+as)\b|(?:அப்புறம்|பிறகு|மேலும்|ப்பறம்)",
            text,
            re.IGNORECASE,
        ))

    def _planner_context(self, timeline, prompt: str = "") -> Dict[str, Any]:
        """Select bounded, request-relevant transcript context for local planning."""
        words = timeline.transcript.words
        transcript, selection = self._select_transcript_context(words, prompt)
        return {
            "duration_seconds": timeline.total_output_duration,
            "source_duration_seconds": timeline.source_metadata.duration,
            "width": timeline.source_metadata.width,
            "height": timeline.source_metadata.height,
            "frame_rate": timeline.source_metadata.frame_rate,
            "audio_present": timeline.source_metadata.audio_present,
            "aspect_ratio": timeline.video_effects.aspect_ratio,
            "transcript_language": timeline.transcript.language,
            "transcript_words": transcript,
            "transcript_truncated": len(words) > len(transcript),
            "transcript_word_count": len(words),
            "transcript_selection": selection,
            "metadata": timeline.source_metadata.model_dump(),
        }

    @staticmethod
    def _select_transcript_context(words, prompt: str, max_words: int = 1200):
        """Keep semantic search context distributed over long transcripts.

        Ordinary visual/audio edits do not need transcript payload. Content-based
        edits receive matching word windows (including speaker and confidence),
        while broad semantic requests receive evenly distributed excerpts so a
        relevant passage late in a 60-minute source is not silently omitted.
        """
        if not words:
            return [], "empty"
        tokens = set(re.findall(r"[a-z0-9']+", prompt.casefold()))
        ignored = {
            "a", "an", "the", "to", "of", "on", "in", "at", "from", "for", "with", "and", "or", "then",
            "please", "video", "clip", "audio", "edit", "editing", "make", "it", "this", "that", "my", "me",
            "cut", "trim", "delete", "remove", "mute", "bleep", "add", "apply", "set", "change", "keep",
            "speed", "faster", "slower", "up", "down", "seconds", "second", "sec", "s", "x", "from", "when",
            "pannu", "sey", "maathu", "podu", "kudu", "la", "va", "ai",
        }
        query_terms = tokens - ignored
        content_intent = bool(tokens & {
            "say", "says", "said", "mention", "mentions", "talk", "talks", "about", "part", "phrase", "word",
            "sentence", "speaker", "guest", "host", "boring", "silence", "pause", "filler", "fillers", "caption",
            "subtitle", "subtitles", "transcript", "pricing", "price", "cost", "fee", "fees", "job", "old",
        })
        if not content_intent:
            return [], "omitted_irrelevant"

        aliases = {
            "pricing": {"pricing", "price", "prices", "cost", "costs", "fee", "fees", "charge", "charges"},
            "price": {"pricing", "price", "prices", "cost", "costs", "fee", "fees", "charge", "charges"},
            "cost": {"pricing", "price", "prices", "cost", "costs", "fee", "fees", "charge", "charges"},
        }
        expanded_terms = set(query_terms)
        for term in query_terms:
            expanded_terms.update(aliases.get(term, set()))
        matched_indices = [
            index for index, word in enumerate(words)
            if set(re.findall(r"[a-z0-9']+", word.text.casefold())) & expanded_terms
        ]
        radius = 5
        if matched_indices:
            max_centers = max(1, max_words // (radius * 2 + 1))
            if len(matched_indices) > max_centers:
                stride = (len(matched_indices) - 1) / max(1, max_centers - 1)
                matched_indices = [matched_indices[round(i * stride)] for i in range(max_centers)]
            selected = sorted({
                i for center in matched_indices
                for i in range(max(0, center - radius), min(len(words), center + radius + 1))
            })
            selection = "matched_windows"
        else:
            # Evenly sample contiguous excerpts across the whole clip when the
            # request is semantic but contains no literal transcript match.
            windows = max(1, max_words // 12)
            if len(words) <= max_words:
                selected = list(range(len(words)))
            else:
                selected_set = set()
                for window in range(windows):
                    center = round(window * (len(words) - 1) / max(1, windows - 1))
                    selected_set.update(range(max(0, center - 5), min(len(words), center + 7)))
                selected = sorted(selected_set)[:max_words]
            selection = "distributed_excerpts"

        transcript = []
        for index in selected[:max_words]:
            word = words[index]
            item = {"id": word.id, "text": word.text, "start": word.start, "end": word.end}
            if word.speaker is not None:
                item["speaker"] = word.speaker
            if word.confidence is not None:
                item["confidence"] = word.confidence
            if word.warnings:
                item["warnings"] = word.warnings
            transcript.append(item)
        return transcript, selection

    def _format_proposal(self, prop, timeline, raw_clause: str) -> Dict[str, Any]:
        op_type = prop.operation_type.value
        p = prop.parameters

        names = {
            "cut_range": "Cut Time Range",
            "keep_range": "Keep Time Range",
            "remove_phrase": "Remove Spoken Phrase",
            "speed_change": "Change Playback Speed",
            "mute": "Mute Audio Segment",
            "bleep": "Censor Bleep Tone",
            "add_caption": "Add Anchored Caption",
            "generate_captions": "Generate Subtitles",
            "remove_filler_words": "Cut Hesitation Fillers",
            "remove_silence": "Remove Long Pauses",
            "add_background_music": "Mix Background Music",
            "color_grade": "Apply Color Grade",
            "set_caption_style": "Style Subtitles",
            "set_caption_mode": "Set Caption Mode",
            "add_transition": "Add Fade Transition",
            "set_aspect_ratio": "Change Canvas Aspect Ratio",
            "create_reel": "Create Social Reel",
            "blur_region": "Blur Background Region",
            "apply_preset": "Apply Video Preset",
            "audio_ducking": "Enable Speech Audio Ducking",
            "audio_normalize": "Loudness Normalization",
            "audio_denoise": "Reduce Background Noise",
            "video_transform": "Rotate or Mirror Video",
            "undo": "Undo Last Change",
            "redo": "Redo Last Undone Edit",
            "restore_edit": "Restore Version",
        }

        name = names.get(op_type, op_type.replace("_", " ").title())
        desc = raw_clause

        # Calculate timestamps if available
        timestamps = {}
        if "start" in p and "end" in p:
            timestamps = {"start": round(p["start"], 2), "end": round(p["end"], 2)}
        elif "start_time" in p and "end_time" in p:
            timestamps = {"start": round(p["start_time"], 2), "end": round(p["end_time"], 2)}

        return {
            "type": op_type,
            "name": name,
            "description": desc,
            "parameters": p,
            "timestamps": timestamps,
            "validation_status": (
                "unsupported"
                if op_type == "generate_captions"
                and p.get("language") == "en"
                and timeline.transcript.words
                and timeline.transcript.language
                and not str(timeline.transcript.language).lower().startswith("en")
                else "unsupported"
                if op_type == "audio_denoise" and not timeline.source_metadata.audio_present
                else "valid"
            ),
            "validation_message": (
                "English translation is not available for the current non-English transcript."
                if op_type == "generate_captions"
                and p.get("language") == "en"
                and timeline.transcript.words
                and timeline.transcript.language
                and not str(timeline.transcript.language).lower().startswith("en")
                else "Uses the existing English transcript to generate word-aligned subtitles."
                if op_type == "generate_captions" and p.get("language") == "en"
                else "Audio noise reduction requires an audio stream in the source video."
                if op_type == "audio_denoise" and not timeline.source_metadata.audio_present
                else "Validated against media timeline capabilities"
            ),
        }


plan_service = AIPlanService()
