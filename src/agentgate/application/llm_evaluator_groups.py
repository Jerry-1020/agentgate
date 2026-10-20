"""Atomic authoring and publication of owned LLM evaluator groups."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSpec,
    utcnow,
)
from agentgate.evaluator.hybrid import LLMGroupEvaluator
from agentgate.evaluator.versioning import (
    create_evaluator_draft,
    replace_evaluator_draft,
)
from agentgate.evaluator.versioning import (
    publish_evaluator_draft as build_publication,
)
from agentgate.server.user_context import get_user_info

from .evaluator_management import (
    EvaluatorCatalogConflict,
    EvaluatorDraftNotFound,
    EvaluatorManagement,
)


@dataclass(frozen=True)
class LLMGroupChildInput:
    id: str | None
    name: str
    description: str
    template_id: str | None
    weight: float
    definition: EvaluatorDraft


@dataclass(frozen=True)
class LLMGroupChildSnapshot:
    evaluator: Evaluator
    definition: EvaluatorDraft | EvaluatorSpec
    description: str
    template_id: str | None
    weight: float


@dataclass(frozen=True)
class LLMGroupSnapshot:
    evaluator: Evaluator
    definition: EvaluatorDraft | EvaluatorSpec
    latest_version: str | None
    has_draft: bool
    viewing_draft: bool
    children: tuple[LLMGroupChildSnapshot, ...]


def read_llm_group(
    management: EvaluatorManagement,
    evaluator_id: str,
    version: str | None = None,
) -> LLMGroupSnapshot:
    parent = management._user_evaluator(evaluator_id, allow_archived=True)
    repository = management.repository
    team = parent.user_team_id
    current = repository.get_evaluator_draft(evaluator_id, user_team_id=team)
    latest = repository.get_latest_evaluator_version(evaluator_id, user_team_id=team)
    definition = management.get_version(evaluator_id, version) if version else current or latest
    if definition is None:
        raise EvaluatorDraftNotFound("LLM group has no draft or publication")
    if definition.kind != EvaluatorKind.LLM_GROUP:
        raise ValueError("Evaluator is not an LLM group")
    viewing_draft = isinstance(definition, EvaluatorDraft)
    children = []
    metadata = definition.config["child_metadata"]
    for ref in definition.children:
        child = management.get_evaluator(ref.evaluator_id)
        if child.owner_evaluator_id != parent.id:
            raise EvaluatorCatalogConflict("LLM group child belongs to another evaluator")
        child_definition = (
            repository.get_evaluator_draft(child.id, user_team_id=team)
            if viewing_draft
            else management.get_version(child.id, ref.evaluator_version)
        )
        if child_definition is None:
            raise EvaluatorCatalogConflict("LLM group child draft is missing")
        child_metadata = metadata[child.id]
        children.append(
            LLMGroupChildSnapshot(
                evaluator=child,
                definition=child_definition,
                description=child_metadata["description"],
                template_id=child_metadata["template_id"],
                weight=ref.weight,
            )
        )
    confirmed_parent = management.get_evaluator(evaluator_id)
    confirmed_draft = repository.get_evaluator_draft(evaluator_id, user_team_id=team)
    confirmed_latest = repository.get_latest_evaluator_version(evaluator_id, user_team_id=team)
    draft_revision = (current.id, current.updated_at) if current else None
    confirmed_revision = (
        (confirmed_draft.id, confirmed_draft.updated_at) if confirmed_draft else None
    )
    if (
        confirmed_parent.updated_at != parent.updated_at
        or confirmed_revision != draft_revision
        or (confirmed_latest.version if confirmed_latest else None)
        != (latest.version if latest else None)
    ):
        raise EvaluatorCatalogConflict("LLM group changed while reading; reload before editing")
    return LLMGroupSnapshot(
        evaluator=parent,
        definition=definition,
        latest_version=latest.version if latest else None,
        has_draft=current is not None,
        viewing_draft=viewing_draft,
        children=tuple(children),
    )


def save_llm_group(
    management: EvaluatorManagement,
    *,
    name: str,
    description: str,
    pass_threshold: float,
    children: Sequence[LLMGroupChildInput],
    evaluator_id: str | None = None,
    based_on_version: str | None = None,
    expected_draft_id: str | None = None,
    expected_draft_updated_at: datetime | None = None,
) -> LLMGroupSnapshot:
    repository = management.repository
    now = utcnow()
    info = get_user_info()
    team = info.user_team_id if info else ""
    author = {
        "user_team_id": team,
        "user_id": info.user_id if info else "",
        "user_name": info.user_name if info else "",
    }
    current = None
    existing_parent = None
    base = None
    allowed_child_ids: set[str] = set()
    if evaluator_id is None:
        if (
            based_on_version is not None
            or expected_draft_id is not None
            or expected_draft_updated_at is not None
        ):
            raise ValueError("new LLM groups cannot reference a previous draft or version")
        parent = Evaluator(
            name=name.strip(),
            description=description.strip(),
            created_at=now,
            updated_at=now,
            **author,
        )
    else:
        existing_parent = management._user_evaluator(evaluator_id)
        current = repository.get_evaluator_draft(evaluator_id, user_team_id=team)
        latest = repository.get_latest_evaluator_version(evaluator_id, user_team_id=team)
        if current is not None:
            if current.kind != EvaluatorKind.LLM_GROUP:
                raise ValueError("Evaluator is not an LLM group")
            if current.id != expected_draft_id or current.updated_at != expected_draft_updated_at:
                raise EvaluatorCatalogConflict("LLM group draft changed; reload before saving")
            if based_on_version is not None and based_on_version != current.based_on_version:
                raise EvaluatorCatalogConflict(
                    "cannot replace an existing LLM group draft with another version"
                )
            allowed_child_ids = {ref.evaluator_id for ref in current.children}
        else:
            if expected_draft_id is not None or expected_draft_updated_at is not None:
                raise EvaluatorCatalogConflict(
                    "LLM group draft no longer exists; reload before saving"
                )
            base = (
                management.get_version(evaluator_id, based_on_version)
                if based_on_version
                else latest
            )
            if base is None or base.kind != EvaluatorKind.LLM_GROUP:
                raise ValueError("Evaluator is not a published LLM group")
            allowed_child_ids = {ref.evaluator_id for ref in base.children}
        parent = Evaluator.model_validate(
            {
                **existing_parent.model_dump(),
                "name": name.strip(),
                "description": description.strip(),
                "updated_at": now,
            }
        )

    supplied_ids = [child.id for child in children if child.id is not None]
    if len(supplied_ids) != len(set(supplied_ids)):
        raise ValueError("LLM group child IDs must be unique")
    if not set(supplied_ids).issubset(allowed_child_ids):
        raise EvaluatorCatalogConflict("LLM group cannot adopt another evaluator's child")

    saved_children = []
    refs = []
    metadata = {}
    for item in children:
        if item.definition.kind != EvaluatorKind.LLM_JUDGE:
            raise ValueError("LLM group children must be LLM Judge Evaluators")
        if item.id is None:
            child = Evaluator(
                name=item.name.strip(),
                description=item.description.strip(),
                owner_evaluator_id=parent.id,
                created_at=now,
                updated_at=now,
                **author,
            )
            child_current = None
            child_latest = None
        else:
            stored = management.get_evaluator(item.id)
            if stored.owner_evaluator_id != parent.id:
                raise EvaluatorCatalogConflict("LLM group child belongs to another evaluator")
            child = Evaluator.model_validate(
                {
                    **stored.model_dump(),
                    "name": item.name.strip(),
                    "description": item.description.strip(),
                    "updated_at": now,
                }
            )
            child_current = repository.get_evaluator_draft(child.id, user_team_id=team)
            child_latest = repository.get_latest_evaluator_version(child.id, user_team_id=team)
        body = item.definition.model_dump(
            include={
                "kind",
                "dimension",
                "metric",
                "severity",
                "implementation_id",
                "implementation_version",
                "config",
                "children",
                "combination",
            }
        )
        child_draft = (
            replace_evaluator_draft(child_current, now, **body)
            if child_current is not None
            else create_evaluator_draft(child, str(uuid4()), now, **body, **author)
        )
        if child_current is None and child_latest is not None:
            child_base_version = (
                next(
                    (
                        ref.evaluator_version
                        for ref in base.children
                        if ref.evaluator_id == child.id
                    ),
                    child_latest.version,
                )
                if base
                else child_latest.version
            )
            child_draft = child_draft.model_copy(update={"based_on_version": child_base_version})
        next_version = str(int(child_latest.version) + 1) if child_latest else "1"
        refs.append(
            EvaluatorRef(evaluator_id=child.id, evaluator_version=next_version, weight=item.weight)
        )
        metadata[child.id] = {"description": child.description, "template_id": item.template_id}
        saved_children.append((child, child_draft))

    group_body = {
        "kind": EvaluatorKind.LLM_GROUP,
        "dimension": "answer",
        "metric": f"llm_group_{parent.id}",
        "severity": "standard",
        "implementation_id": "llm_group",
        "implementation_version": "1",
        "config": {
            "pass_threshold": pass_threshold,
            "description": parent.description,
            "child_metadata": metadata,
        },
        "children": tuple(refs),
        "combination": CombinationPolicy.WEIGHTED_SCORE,
    }
    draft = (
        replace_evaluator_draft(current, now, **group_body)
        if current is not None
        else create_evaluator_draft(parent, str(uuid4()), now, **group_body, **author)
    )
    if current is None and base is not None:
        draft = draft.model_copy(update={"based_on_version": base.version})
    LLMGroupEvaluator().validate_spec(draft)
    try:
        repository.save_evaluator_group_draft(
            parent,
            draft,
            tuple(saved_children),
            expected_updated_at=current.updated_at if current else None,
            expected_evaluator_updated_at=existing_parent.updated_at if existing_parent else None,
            user_team_id=team,
        )
    except ValueError as error:
        raise EvaluatorCatalogConflict(
            "LLM group changed while saving; reload before saving"
        ) from error
    return read_llm_group(management, parent.id)


def publish_llm_group(
    management: EvaluatorManagement,
    evaluator_id: str,
    *,
    expected_draft_id: str,
    expected_draft_updated_at: datetime,
) -> LLMGroupSnapshot:
    management._user_evaluator(evaluator_id)
    snapshot = read_llm_group(management, evaluator_id)
    if not snapshot.viewing_draft:
        raise EvaluatorCatalogConflict("LLM group has no draft to publish")
    draft = snapshot.definition
    assert isinstance(draft, EvaluatorDraft)
    if draft.id != expected_draft_id or draft.updated_at != expected_draft_updated_at:
        raise EvaluatorCatalogConflict("LLM group draft changed; reload before publishing")
    next_version = int(snapshot.latest_version) + 1 if snapshot.latest_version else 1
    parent_spec = build_publication(snapshot.evaluator, draft, next_version)
    management._validate_supported_spec(parent_spec)
    children = []
    for ref, child in zip(draft.children, snapshot.children, strict=True):
        assert isinstance(child.definition, EvaluatorDraft)
        published = build_publication(child.evaluator, child.definition, int(ref.evaluator_version))
        management._validate_supported_spec(published)
        children.append(published)
    management._validate_child_composition(parent_spec, children)
    try:
        management.repository.publish_evaluator_group_draft(
            draft.id,
            (parent_spec, *children),
            expected_updated_at=expected_draft_updated_at,
            user_team_id=snapshot.evaluator.user_team_id,
        )
    except ValueError as error:
        raise EvaluatorCatalogConflict(
            "LLM group changed during publication; reload before publishing"
        ) from error
    return read_llm_group(management, evaluator_id, parent_spec.version)


def discard_llm_group_draft(
    management: EvaluatorManagement,
    evaluator_id: str,
    *,
    expected_draft_id: str,
    expected_draft_updated_at: datetime,
) -> None:
    management._user_evaluator(evaluator_id)
    snapshot = read_llm_group(management, evaluator_id)
    if not snapshot.viewing_draft:
        raise EvaluatorDraftNotFound("LLM group has no active draft")
    if (
        snapshot.definition.id != expected_draft_id
        or snapshot.definition.updated_at != expected_draft_updated_at
    ):
        raise EvaluatorCatalogConflict("LLM group draft changed; reload before discarding")
    try:
        management.repository.discard_evaluator_group_draft(
            evaluator_id,
            expected_draft_id,
            expected_draft_updated_at,
            user_team_id=snapshot.evaluator.user_team_id,
        )
    except ValueError as error:
        raise EvaluatorCatalogConflict(
            "LLM group changed while discarding; reload before discarding"
        ) from error
