"""Deterministically render protected Case evidence into Judge requests."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypeAlias

from agentgate.domain import Case, Trace, canonical_json

from .contract import response_instructions
from .model_protocol import JudgeRequest

JudgeInputSelection: TypeAlias = Literal[
    "final_output",
    "output_and_tools",
    "full_trajectory",
]
RedactValue: TypeAlias = Callable[[Any], Any]
_INPUT_SELECTIONS = frozenset(
    {"final_output", "output_and_tools", "full_trajectory"}
)
_TEMPLATE_VARIABLE = re.compile(r"\{\{([^{}]*)\}\}")
_PROMPT_VARIABLES = frozenset({"input", "output"})


def validate_prompt_template(template: str) -> tuple[str, ...]:
    """Validate supported evidence placeholders without inspecting their values."""

    if not isinstance(template, str) or not template.strip():
        raise ValueError("Judge prompt template must not be blank")
    variables = tuple(match.group(1).strip() for match in _TEMPLATE_VARIABLE.finditer(template))
    unknown = set(variables).difference(_PROMPT_VARIABLES)
    if unknown:
        raise ValueError(f"unknown Judge prompt variables: {', '.join(sorted(unknown))}")
    return variables


def _behavior_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attributes.items()
        if not key.startswith("agentgate.")
    }


def _tool_calls(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "arguments": _behavior_attributes(span.attributes),
            "name": span.name,
            "status": span.status,
        }
        for span in sorted(trace.spans, key=lambda item: item.sequence)
        if span.operation_type == "tool"
    ]


def _trajectory(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "attributes": _behavior_attributes(span.attributes),
            "events": span.events,
            "name": span.name,
            "operation_type": span.operation_type,
            "sequence": span.sequence,
            "status": span.status,
        }
        for span in sorted(trace.spans, key=lambda item: item.sequence)
    ]


def select_material(
    case: Case,
    trace: Trace,
    input_selection: JudgeInputSelection,
) -> dict[str, Any]:
    """Select case-level behavior while excluding correlation bookkeeping."""

    if input_selection not in _INPUT_SELECTIONS:
        raise ValueError(f"unknown Judge input selection: {input_selection}")
    if trace.case_id != case.id:
        raise ValueError("Trace and Case identities do not match")

    material: dict[str, Any] = {
        "turn_inputs": [
            {"index": index, "input": turn.input}
            for index, turn in enumerate(case.turns)
        ],
        "final_output": trace.final_output,
    }
    if input_selection in {"output_and_tools", "full_trajectory"}:
        material["tool_calls"] = _tool_calls(trace)
    if input_selection == "full_trajectory":
        material["trajectory"] = _trajectory(trace)
        material["final_state"] = trace.final_state
    return material


def render_bounded_evidence(material: Any, max_input_chars: int) -> str:
    """Render canonical evidence or a valid JSON envelope with a bounded prefix."""

    if isinstance(max_input_chars, bool) or not isinstance(max_input_chars, int):
        raise ValueError("max_input_chars must be a positive integer")
    if max_input_chars < 1:
        raise ValueError("max_input_chars must be a positive integer")

    rendered = canonical_json(material)
    if len(rendered) <= max_input_chars:
        return rendered

    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    envelope = {
        "content_sha256": digest,
        "prefix": "",
        "truncated": True,
    }
    minimum = canonical_json(envelope)
    if len(minimum) > max_input_chars:
        raise ValueError(
            f"max_input_chars must be at least {len(minimum)} for truncated evidence"
        )

    prefix_length = max_input_chars - len(minimum)
    while prefix_length >= 0:
        envelope["prefix"] = rendered[:prefix_length]
        bounded = canonical_json(envelope)
        if len(bounded) <= max_input_chars:
            return bounded
        prefix_length -= len(bounded) - max_input_chars
    raise AssertionError("bounded evidence size calculation failed")


def build_judge_request(
    *,
    model_id: str,
    instruction: str,
    rubric: Mapping[str, Any],
    case: Case,
    trace: Trace,
    input_selection: JudgeInputSelection,
    pass_threshold: float,
    temperature: float,
    seed: int | None,
    max_output_tokens: int,
    timeout_seconds: float,
    max_input_chars: int,
    redact: RedactValue,
    user_prompt: str | None = None,
    render_template: bool = False,
) -> JudgeRequest:
    """Build one secret-free, case-level request for a Judge provider."""

    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Judge instruction must not be blank")
    if not isinstance(rubric, Mapping) or not rubric:
        raise ValueError("Judge rubric must not be empty")
    if not callable(redact):
        raise TypeError("Judge prompt requires a redaction callable")
    if not isinstance(render_template, bool):
        raise ValueError("Judge render_template must be a boolean")  # noqa: TRY004
    if isinstance(max_input_chars, bool) or not isinstance(max_input_chars, int) or max_input_chars < 1:
        raise ValueError("max_input_chars must be a positive integer")
    if user_prompt is not None and (not isinstance(user_prompt, str) or not user_prompt.strip()):
        raise ValueError("Judge user prompt must not be blank")

    variables = validate_prompt_template(instruction) if render_template else ()
    if render_template and user_prompt is not None:
        variables += validate_prompt_template(user_prompt)

    protected_instruction = redact(instruction.strip())
    protected_user_prompt = redact(user_prompt) if user_prompt is not None else None
    protected_rubric = redact(rubric)
    protected_material = redact(select_material(case, trace, input_selection))
    if not isinstance(protected_instruction, str):
        raise TypeError("Judge redactor must return text for instruction input")
    if protected_user_prompt is not None and not isinstance(protected_user_prompt, str):
        raise TypeError("Judge redactor must return text for user prompt input")

    # Every occurrence and the canonical evidence share one budget. Repeated
    # placeholders cannot multiply the amount of execution data sent to the model.
    evidence_budget = max_input_chars // (len(variables) + 1)
    evidence = render_bounded_evidence(protected_material, evidence_budget)
    if variables:
        if not isinstance(protected_material, Mapping):
            raise TypeError("Judge redactor must return an object for evidence input")
        values = {
            "input": protected_material["turn_inputs"],
            "output": protected_material["final_output"],
        }
        rendered = {
            name: render_bounded_evidence(values[name], evidence_budget)
            for name in set(variables)
        }
        # A single substitution pass leaves placeholder-looking execution data inert.
        protected_instruction = _TEMPLATE_VARIABLE.sub(
            lambda match: rendered[match.group(1).strip()], protected_instruction
        )
        if protected_user_prompt is not None:
            protected_user_prompt = _TEMPLATE_VARIABLE.sub(
                lambda match: rendered[match.group(1).strip()], protected_user_prompt
            )

    system_prompt = "\n\n".join(
        (
            protected_instruction,
            f"Rubric:\n{canonical_json(protected_rubric)}",
            response_instructions(pass_threshold),
        )
    )
    rendered_user_prompt = (
        (protected_user_prompt or "Evaluate this Agent execution against the rubric.") + "\n"
        f"Evidence selection: {input_selection}\n\n"
        f"Evidence:\n{evidence}"
    )
    return JudgeRequest(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=rendered_user_prompt,
        temperature=temperature,
        seed=seed,
        max_output_tokens=max_output_tokens,
        response_format="json_object",
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "JudgeInputSelection",
    "RedactValue",
    "build_judge_request",
    "render_bounded_evidence",
    "select_material",
    "validate_prompt_template",
]
