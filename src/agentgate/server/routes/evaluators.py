"""Evaluator Catalog identity, draft, and publication endpoints."""

from __future__ import annotations

from datetime import datetime
from threading import BoundedSemaphore
from time import perf_counter
from typing import Annotated, Any, NoReturn, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agentgate.application import (
    BuiltinEvaluatorMutation,
    EvaluatorCatalogConflict,
    EvaluatorDraftNotFound,
    EvaluatorNotFound,
    EvaluatorVersionNotFound,
)
from agentgate.application.llm_evaluator_groups import (
    LLMGroupChildInput,
    LLMGroupSnapshot,
    discard_llm_group_draft,
    publish_llm_group,
    read_llm_group,
    save_llm_group,
)
from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    EvaluatorSource,
    EvaluatorSpec,
)
from agentgate.evaluator.models import EvaluatorError
from agentgate.evaluator.rule.code import run_code_with_evidence, validate_code_config
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_conflict, raise_not_found, raise_unprocessable
from agentgate.storage.evaluation_query_models import RelatedEvaluationTaskPage, RelatedTaskCursor

router = APIRouter(prefix="/api/evaluators", tags=["evaluators"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftDefinitionRequest(_RequestModel):
    kind: EvaluatorKind = EvaluatorKind.RULE
    dimension: str
    metric: str
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD
    implementation_id: str
    implementation_version: str = "1"
    config: dict[str, Any] = Field(default_factory=dict)
    children: tuple[EvaluatorRef, ...] = ()
    combination: CombinationPolicy | None = None


class CreateEvaluatorRequest(_RequestModel):
    name: str
    description: str = ""
    draft: DraftDefinitionRequest


class CodeValidationRequest(_RequestModel):
    config: dict[str, Any]


@router.post("/code/validate")
def validate_code(request: CodeValidationRequest) -> dict[str, bool]:
    """Static validation only: no sample data and no rule execution."""
    try:
        validate_code_config(request.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"valid": True}


@router.get("/code/trace-targets")
def code_trace_targets(dependencies: Dependencies, mode: Literal["external", "inbank"],
                       offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    from agentgate.server.user_context import get_user_info
    info = get_user_info()
    return dependencies.repository.list_code_trace_choices(
        user_team_id=info.user_team_id if info else "", mode=mode, offset=offset, limit=limit)


@router.get("/code/traces")
def code_traces(dependencies: Dependencies, mode: Literal["external", "inbank"],
                source_id: str, target_id: str, version: str,
                offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    from agentgate.server.user_context import get_user_info
    info = get_user_info()
    return dependencies.repository.list_code_trace_choices(
        user_team_id=info.user_team_id if info else "", mode=mode, offset=offset, limit=limit,
        source_id=source_id, target_id=target_id, version=version)


@router.get("/code/trace-data")
def code_trace_data(dependencies: Dependencies, mode: Literal["external", "inbank"],
                    run_id: str, case_id: str):
    try:
        return dependencies.results.code_trace_data(run_id, case_id, mode)
    except LookupError as exc:
        raise_not_found(exc)
    except ValueError as exc:
        raise_unprocessable(exc)


class CodeTrialRequest(_RequestModel):
    config: dict[str, Any]
    turn_data: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None


_code_trial_slots = BoundedSemaphore(2)


@router.post("/code/try-run")
def try_code(request: CodeTrialRequest) -> dict[str, Any]:
    """Run supplied data only; never execute an Agent or persist evaluation records."""
    try:
        validate_code_config(request.config)
        if request.config.get("input_format") == "trace-v1":
            if request.trace is None or request.turn_data is not None:
                raise ValueError("Trace 规则需要 trace 对象")
            data = target = request.trace
            if not isinstance(data.get("turn_outcomes"), dict) or any(
                not isinstance(t, dict) or (t.get("input") is not None and not isinstance(t["input"], dict))
                for t in data["turn_outcomes"].values()
            ):
                raise ValueError("turn_outcomes 必须为轮次对象；input 为对象或 null")
            if any(not isinstance(data.get(k), str) or not data[k]
                   for k in ("trace_id", "run_id", "case_id")):
                raise ValueError("Trace 需要 trace_id、run_id、case_id")
            if any(not isinstance(data.get(k), dict) for k in ("final_output", "final_state")):
                raise ValueError("Trace 需要 final_output 和 final_state 对象")
        else:
            if request.turn_data is None or request.trace is not None:
                raise ValueError("旧规则需要 turn_data 对象")
            data = request.turn_data
            for field in ("evaluate_dataset_fields", "evaluate_target_output_fields", "ext"):
                if not isinstance(data.get(field), dict):
                    raise ValueError(f"测试数据的 {field} 必须为 JSON 对象")
            dataset, target = data["evaluate_dataset_fields"], data["evaluate_target_output_fields"]
            if not isinstance(dataset.get("input"), dict) or not isinstance(dataset.get("expectations"), list):
                raise ValueError("样本字段需要 input 对象和 expectations 数组")
            if any(not isinstance(target.get(key), dict) for key in ("actual_output", "final_state")):
                raise ValueError("实际输出字段需要 actual_output 和 final_state 对象")
        spans = target.get("spans")
        if not isinstance(spans, list) or any(
            not isinstance(span, dict) or not isinstance(span.get("span_id"), str)
            or not span["span_id"] or not isinstance(span.get("attributes", {}), dict)
            for span in spans
        ):
            raise ValueError("spans 必须为对象数组，每项需要非空字符串 span_id；attributes 必须为对象")
        if len({span["span_id"] for span in spans}) != len(spans):
            raise ValueError("测试数据的 span_id 不可重复")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not _code_trial_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="试运行繁忙，请稍后重试")
    started = perf_counter()
    try:
        if any(span.get("operation_type") == "turn" and
               "agentgate.execution.error" in span.get("attributes", {}) for span in spans):
            return {"outcome": "error", "score": None, "span_ids": [],
                    "reason": "Trace 中存在 Agent 执行异常，无法产生有效评分",
                    "duration_ms": (perf_counter() - started) * 1000}
        if any(span.get("operation_type") == "turn"
               and span.get("attributes", {}).get("inbank.evidence_mode") == "output_only"
               for span in spans):
            return {
                "outcome": "not_applicable", "score": None, "span_ids": [],
                "reason": "Trace 证据不足（output_only），与正式任务一致跳过 Code 检查",
                "duration_ms": (perf_counter() - started) * 1000,
            }
        try:
            output = run_code_with_evidence(request.config["source"], data)
            return {
                "outcome": "pass" if output["score"] >= request.config["pass_threshold"] else "fail",
                "score": output["score"], "reason": output["reason"],
                "span_ids": output.get("span_ids", []),
                "duration_ms": (perf_counter() - started) * 1000,
            }
        except (ValueError, TypeError, KeyError, RuntimeError, TimeoutError, OSError, RecursionError) as exc:
            return {
                "outcome": "error", "score": None, "span_ids": [],
                "reason": str(exc)[:2000] or type(exc).__name__,
                "duration_ms": (perf_counter() - started) * 1000,
            }
    finally:
        _code_trial_slots.release()


class UpdateEvaluatorRequest(_RequestModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None


class CreateDraftRequest(_RequestModel):
    based_on_version: str | None = None


class EvaluatorSummary(BaseModel):
    id: str
    name: str
    description: str
    source: EvaluatorSource
    enabled: bool
    created_at: datetime
    updated_at: datetime
    latest_version: str | None
    kind: EvaluatorKind | None
    dimension: str | None
    metric: str | None
    severity: EvaluatorSeverity | None
    implementation_id: str | None
    implementation_version: str | None
    has_draft: bool
    child_count: int = 0


class EvaluatorDetail(BaseModel):
    evaluator: Evaluator
    latest: EvaluatorSpec | None
    draft: EvaluatorDraft | None


class CreatedEvaluator(BaseModel):
    evaluator: Evaluator
    draft: EvaluatorDraft


class LLMGroupChildRequest(_RequestModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    template_id: str | None = None
    weight: float = Field(gt=0, le=1, strict=True)
    definition: DraftDefinitionRequest


class LLMGroupRequest(_RequestModel):
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    pass_threshold: float = Field(default=0.8, ge=0, le=1, strict=True)
    children: tuple[LLMGroupChildRequest, ...] = Field(min_length=1, max_length=32)
    based_on_version: str | None = None
    expected_draft_id: str | None = None
    expected_draft_updated_at: datetime | None = None


class LLMGroupRevisionRequest(_RequestModel):
    expected_draft_id: str
    expected_draft_updated_at: datetime


class LLMGroupChildDetail(BaseModel):
    evaluator: Evaluator
    definition: EvaluatorDraft | EvaluatorSpec
    description: str
    template_id: str | None
    weight: float


class LLMGroupDetail(BaseModel):
    evaluator: Evaluator
    definition: EvaluatorDraft | EvaluatorSpec
    latest_version: str | None
    has_draft: bool
    viewing_draft: bool
    children: list[LLMGroupChildDetail]


def _group_detail(snapshot: LLMGroupSnapshot) -> LLMGroupDetail:
    return LLMGroupDetail(
        evaluator=snapshot.evaluator,
        definition=snapshot.definition,
        latest_version=snapshot.latest_version,
        has_draft=snapshot.has_draft,
        viewing_draft=snapshot.viewing_draft,
        children=[
            LLMGroupChildDetail(
                evaluator=item.evaluator,
                definition=item.definition,
                description=item.description,
                template_id=item.template_id,
                weight=item.weight,
            )
            for item in snapshot.children
        ],
    )


def _save_group(
    request: LLMGroupRequest, dependencies: ServerDependencies, evaluator_id: str | None = None
) -> LLMGroupDetail:
    return _group_detail(
        save_llm_group(
            dependencies.evaluators,
            evaluator_id=evaluator_id,
            name=request.name,
            description=request.description,
            pass_threshold=request.pass_threshold,
            based_on_version=request.based_on_version,
            expected_draft_id=request.expected_draft_id,
            expected_draft_updated_at=request.expected_draft_updated_at,
            children=tuple(
                LLMGroupChildInput(
                    id=item.id,
                    name=item.name,
                    description=item.description,
                    template_id=item.template_id,
                    weight=item.weight,
                    definition=EvaluatorDraft(
                        evaluator_id=item.id or "new", **item.definition.model_dump()
                    ),
                )
                for item in request.children
            ),
        )
    )


def _raise_catalog_error(error: Exception) -> NoReturn:
    if isinstance(
        error,
        (EvaluatorNotFound, EvaluatorDraftNotFound, EvaluatorVersionNotFound),
    ):
        raise_not_found(error)
    if isinstance(error, (EvaluatorCatalogConflict, BuiltinEvaluatorMutation)):
        raise_conflict(error)
    raise_unprocessable(error)


def _draft_or_none(
    evaluator: Evaluator,
    dependencies: ServerDependencies,
) -> EvaluatorDraft | None:
    if evaluator.source == EvaluatorSource.BUILTIN or evaluator.archived:
        return None
    try:
        return dependencies.evaluators.get_draft(evaluator.id)
    except EvaluatorDraftNotFound:
        return None


def _detail(
    evaluator: Evaluator,
    dependencies: ServerDependencies,
) -> EvaluatorDetail:
    versions = dependencies.evaluators.list_versions(evaluator.id)
    return EvaluatorDetail(
        evaluator=evaluator,
        latest=versions[0] if versions else None,
        draft=_draft_or_none(evaluator, dependencies),
    )


def _summary(detail: EvaluatorDetail) -> EvaluatorSummary:
    definition = detail.latest or detail.draft
    return EvaluatorSummary(
        **detail.evaluator.model_dump(),
        latest_version=detail.latest.version if detail.latest else None,
        kind=definition.kind if definition else None,
        dimension=definition.dimension if definition else None,
        metric=definition.metric if definition else None,
        severity=definition.severity if definition else None,
        implementation_id=definition.implementation_id if definition else None,
        implementation_version=(definition.implementation_version if definition else None),
        has_draft=detail.draft is not None,
        child_count=len(definition.children) if definition else 0,
    )


@router.get("")
def list_evaluators(
    dependencies: Dependencies,
    include_disabled: bool = False,
) -> list[EvaluatorSummary]:
    try:
        return [
            _summary(_detail(evaluator, dependencies))
            for evaluator in dependencies.evaluators.list_evaluators(
                include_disabled=include_disabled
            )
        ]
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("", status_code=201)
def create_evaluator(
    request: CreateEvaluatorRequest,
    dependencies: Dependencies,
) -> CreatedEvaluator:
    try:
        evaluator, draft = dependencies.evaluators.create_evaluator(
            request.name,
            request.description,
            **request.draft.model_dump(),
        )
        return CreatedEvaluator(evaluator=evaluator, draft=draft)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("/llm-groups", status_code=201)
def create_llm_group(request: LLMGroupRequest, dependencies: Dependencies) -> LLMGroupDetail:
    try:
        return _save_group(request, dependencies)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/llm-group")
def llm_group_detail(
    evaluator_id: str, dependencies: Dependencies, version: str | None = None
) -> LLMGroupDetail:
    try:
        return _group_detail(read_llm_group(dependencies.evaluators, evaluator_id, version))
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.put("/{evaluator_id}/llm-group/draft")
def update_llm_group_draft(
    evaluator_id: str, request: LLMGroupRequest, dependencies: Dependencies
) -> LLMGroupDetail:
    try:
        return _save_group(request, dependencies, evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("/{evaluator_id}/llm-group/publish")
def publish_llm_group_draft(
    evaluator_id: str, request: LLMGroupRevisionRequest, dependencies: Dependencies
) -> LLMGroupDetail:
    try:
        return _group_detail(
            publish_llm_group(dependencies.evaluators, evaluator_id, **request.model_dump())
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.delete("/{evaluator_id}/llm-group/draft", status_code=204)
def delete_llm_group_draft(
    evaluator_id: str, request: LLMGroupRevisionRequest, dependencies: Dependencies
) -> None:
    try:
        discard_llm_group_draft(dependencies.evaluators, evaluator_id, **request.model_dump())
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}")
def evaluator_detail(
    evaluator_id: str,
    dependencies: Dependencies,
) -> EvaluatorDetail:
    try:
        return _detail(
            dependencies.evaluators.get_evaluator(evaluator_id),
            dependencies,
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.patch("/{evaluator_id}")
def update_evaluator(
    evaluator_id: str,
    request: UpdateEvaluatorRequest,
    dependencies: Dependencies,
) -> Evaluator:
    provided = request.model_fields_set
    if not provided:
        raise HTTPException(
            status_code=422,
            detail="Evaluator update must contain at least one field",
        )
    if any(getattr(request, field_name) is None for field_name in provided):
        raise HTTPException(
            status_code=422,
            detail="Evaluator update fields cannot be null",
        )
    try:
        return dependencies.evaluators.update_evaluator(
            evaluator_id,
            **request.model_dump(exclude_unset=True),
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.delete("/{evaluator_id}", status_code=204)
def delete_evaluator(evaluator_id: str, dependencies: Dependencies) -> None:
    try:
        dependencies.evaluators.delete_evaluator(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/versions")
def list_versions(
    evaluator_id: str,
    dependencies: Dependencies,
) -> list[EvaluatorSpec]:
    try:
        return list(dependencies.evaluators.list_versions(evaluator_id))
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/versions/{version}")
def evaluator_version(
    evaluator_id: str,
    version: str,
    dependencies: Dependencies,
) -> EvaluatorSpec:
    try:
        return dependencies.evaluators.get_version(evaluator_id, version)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.get("/{evaluator_id}/versions/{version}/related-tasks")
def evaluator_related_tasks(
    evaluator_id: str,
    version: str,
    dependencies: Dependencies,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> RelatedEvaluationTaskPage:
    try:
        dependencies.evaluators.get_version(evaluator_id, version)
        position = RelatedTaskCursor.decode(cursor) if cursor is not None else None
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)
    return dependencies.evaluation_queries.related_tasks(
        evaluator_id, version, limit=limit, cursor=position,
    )


@router.get("/{evaluator_id}/drafts/current")
def current_draft(
    evaluator_id: str,
    dependencies: Dependencies,
) -> EvaluatorDraft:
    try:
        return dependencies.evaluators.get_draft(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("/{evaluator_id}/drafts", status_code=201)
def create_draft(
    evaluator_id: str,
    request: CreateDraftRequest,
    dependencies: Dependencies,
) -> EvaluatorDraft:
    try:
        return dependencies.evaluators.create_draft(
            evaluator_id,
            request.based_on_version,
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.put("/{evaluator_id}/drafts/current")
def replace_draft(
    evaluator_id: str,
    request: DraftDefinitionRequest,
    dependencies: Dependencies,
) -> EvaluatorDraft:
    try:
        return dependencies.evaluators.replace_draft(
            evaluator_id,
            **request.model_dump(),
        )
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.delete("/{evaluator_id}/drafts/current", status_code=204)
def discard_draft(evaluator_id: str, dependencies: Dependencies) -> None:
    try:
        dependencies.evaluators.discard_draft(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)


@router.post("/{evaluator_id}/drafts/publish")
def publish_draft(
    evaluator_id: str,
    dependencies: Dependencies,
) -> EvaluatorSpec:
    try:
        return dependencies.evaluators.publish_draft(evaluator_id)
    except (EvaluatorError, ValueError) as error:
        _raise_catalog_error(error)
