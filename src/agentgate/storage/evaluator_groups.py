"""Validation shared by atomic evaluator-group persistence operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from agentgate.domain import Evaluator, EvaluatorDraft, EvaluatorSource, EvaluatorSpec


def validate_identity_update(value: Evaluator, stored: Evaluator | None) -> None:
    if value.source != EvaluatorSource.USER:
        raise ValueError("only user Evaluators can be persisted")
    if stored is None:
        return
    if stored.archived and value != stored:
        raise ValueError("archived Evaluator cannot be modified")
    for field in ("source", "created_at", "user_team_id", "owner_evaluator_id"):
        if getattr(value, field) != getattr(stored, field):
            raise ValueError(f"Evaluator {field} is immutable")
    if value.updated_at < stored.updated_at:
        raise ValueError("cannot save a stale Evaluator")


def validate_draft_update(
    value: EvaluatorDraft,
    evaluator: Evaluator,
    stored: EvaluatorDraft | None,
) -> None:
    if evaluator.archived:
        raise ValueError("archived Evaluator cannot have a draft updated")
    if value.evaluator_id != evaluator.id or value.user_team_id != evaluator.user_team_id:
        raise ValueError("EvaluatorDraft must belong to Evaluator and its team")
    if value.created_at < evaluator.created_at:
        raise ValueError("EvaluatorDraft cannot precede Evaluator creation")
    if stored is None:
        return
    for field in ("id", "evaluator_id", "created_at", "based_on_version", "user_team_id"):
        if getattr(value, field) != getattr(stored, field):
            raise ValueError(f"EvaluatorDraft {field} is immutable")
    if value.updated_at < stored.updated_at:
        raise ValueError("cannot save a stale EvaluatorDraft")


def validate_group_draft(
    parent: Evaluator,
    draft: EvaluatorDraft,
    children: Sequence[tuple[Evaluator, EvaluatorDraft]],
    *,
    stored_parent: Evaluator | None,
    stored_draft: EvaluatorDraft | None,
    expected_updated_at: datetime | None,
    expected_evaluator_updated_at: datetime | None,
    user_team_id: str,
) -> None:
    if parent.user_team_id != user_team_id or parent.owner_evaluator_id is not None:
        raise ValueError("unknown Evaluator group")
    if stored_parent is not None and stored_parent.user_team_id != user_team_id:
        raise ValueError("unknown Evaluator group")
    if (stored_parent.updated_at if stored_parent else None) != expected_evaluator_updated_at:
        raise ValueError("Evaluator group changed; reload before saving")
    if (stored_draft.updated_at if stored_draft else None) != expected_updated_at:
        raise ValueError("Evaluator group draft changed; reload before saving")
    validate_identity_update(parent, stored_parent)
    validate_draft_update(draft, parent, stored_draft)
    if stored_parent is not None and parent != stored_parent and parent.updated_at <= stored_parent.updated_at:
        raise ValueError("Evaluator group update must advance updated_at")
    # The parent draft is the revision token for changes to any owned child.
    if stored_draft is not None and draft.updated_at <= stored_draft.updated_at:
        raise ValueError("Evaluator group draft update must advance updated_at")
    if draft.kind.value != "llm_group":
        raise ValueError("Evaluator group requires llm_group draft")
    child_ids = [child.id for child, _ in children]
    if len(set(child_ids)) != len(child_ids) or parent.id in child_ids:
        raise ValueError("Evaluator group child identities must be unique")
    if set(child_ids) != {ref.evaluator_id for ref in draft.children}:
        raise ValueError("Evaluator group draft references must match all owned children")
    draft_ids = [draft.id, *(item.id for _, item in children)]
    if len(set(draft_ids)) != len(draft_ids):
        raise ValueError("Evaluator group draft identities must be unique")
    for child, child_draft in children:
        if child.owner_evaluator_id != parent.id or child.user_team_id != user_team_id:
            raise ValueError("Evaluator group child owner and team must match parent")
        if child_draft.kind.value != "llm_judge":
            raise ValueError("Evaluator group children must be LLM evaluators")
        validate_draft_update(child_draft, child, None)


def validate_group_publications(
    publications: Sequence[EvaluatorSpec],
    identities: Mapping[str, Evaluator],
    *,
    user_team_id: str,
) -> None:
    if not publications or publications[0].kind.value != "llm_group":
        raise ValueError("Evaluator group publication must start with its parent")
    parent, *children = publications
    if len({item.id for item in publications}) != len(publications):
        raise ValueError("Evaluator group publications must have unique identities")
    expected = {(ref.evaluator_id, ref.evaluator_version) for ref in parent.children}
    if expected != {(child.id, child.version) for child in children}:
        raise ValueError("Evaluator group references must match all child publications")
    for publication in publications:
        identity = identities.get(publication.id)
        if identity is None or identity.user_team_id != user_team_id or publication.user_team_id != user_team_id:
            raise ValueError("unknown Evaluator group")
        if identity.archived:
            raise ValueError("archived Evaluator cannot be published")
        owner = None if publication.id == parent.id else parent.id
        if identity.owner_evaluator_id != owner:
            raise ValueError("Evaluator group publication has a different child owner")
        if publication.id != parent.id and publication.kind.value != "llm_judge":
            raise ValueError("Evaluator group children must be LLM evaluators")
