"""Atomic group lifecycles, ownership, and races across repository adapters."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest

from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    utcnow,
)
from agentgate.evaluator.versioning import (
    clone_evaluator_version_to_draft,
    publish_evaluator_draft,
)

TEAM = "group-test-team"


def group(group_id="parent", child_ids=("relevance", "accuracy")):
    now = utcnow()
    parent = Evaluator(id=group_id, name="回答质量", created_at=now, updated_at=now,
                       user_team_id=TEAM)
    children = []
    for child_id in child_ids:
        identity = Evaluator(id=f"{group_id}-{child_id}", name=child_id,
                             owner_evaluator_id=parent.id, created_at=now,
                             updated_at=now, user_team_id=TEAM)
        draft = EvaluatorDraft(
            id=f"draft-{identity.id}", evaluator_id=identity.id,
            kind=EvaluatorKind.LLM_JUDGE, dimension="answer", metric=child_id,
            implementation_id="answer_quality", config={
                "model": {"provider_id": "deepseek", "model_id": "deepseek-v4-pro"},
                "instruction": f"Evaluate {child_id}: {{{{input}}}} {{{{output}}}}",
            }, created_at=now, updated_at=now, user_team_id=TEAM,
        )
        children.append((identity, draft))
    draft = EvaluatorDraft(
        id=f"draft-{group_id}", evaluator_id=parent.id, kind=EvaluatorKind.LLM_GROUP,
        dimension="answer", metric="overall_quality", implementation_id="llm_group",
        children=tuple(EvaluatorRef(evaluator_id=child.id, evaluator_version="1", weight=1 / len(children))
                       for child, _ in children), combination=CombinationPolicy.WEIGHTED_SCORE,
        created_at=now, updated_at=now, user_team_id=TEAM,
    )
    return parent, draft, children


def save(repository, value, *, previous=None):
    parent, draft, children = value
    repository.save_evaluator_group_draft(
        parent, draft, children,
        expected_updated_at=previous[1].updated_at if previous and previous[1] else None,
        expected_evaluator_updated_at=previous[0].updated_at if previous else None,
        user_team_id=TEAM,
    )


def publications(value, version=1):
    parent, draft, children = value
    return tuple(publish_evaluator_draft(identity, item, version)
                 for identity, item in ((parent, draft), *children))


def revise(value, *, name="新名称", child_ids=None):
    parent, draft, children = value
    now = max(utcnow(), parent.updated_at, draft.updated_at) + timedelta(microseconds=1)
    selected = children if child_ids is None else [pair for pair in children if pair[0].id in child_ids]
    return (
        parent.model_copy(update={"name": name, "updated_at": now}),
        draft.model_copy(update={"updated_at": now, "children": tuple(
            ref.model_copy(update={"weight": 1 / len(selected)})
            for ref in draft.children if ref.evaluator_id in {item.id for item, _ in selected}
        )}),
        selected,
    )


def test_group_save_and_publish_preserve_exact_versions(repository):
    value = group()
    save(repository, value)
    parent, draft, children = value
    expected = publications(value)
    repository.publish_evaluator_group_draft(
        draft.id, expected, expected_updated_at=draft.updated_at, user_team_id=TEAM,
    )

    for spec in expected:
        assert repository.get_evaluator_version(spec.id, "1", user_team_id=TEAM) == spec
        assert repository.get_evaluator_draft(spec.id, user_team_id=TEAM) is None
        assert repository.get_evaluator(spec.id, user_team_id=TEAM).enabled
    assert expected[0].children[0].evaluator_version == "1"
    assert repository.get_evaluator(parent.id, user_team_id="other-team") is None
    assert repository.get_evaluator(children[0][0].id, user_team_id=TEAM).owner_evaluator_id == parent.id


def test_group_create_rolls_back_when_late_child_draft_conflicts(repository):
    outsider, outsider_draft, _ = group("outsider")
    repository.save_evaluator_with_draft(outsider, outsider_draft)
    parent, draft, children = group()
    child, item = children[-1]
    children[-1] = (child, item.model_copy(update={"id": outsider_draft.id}))
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        save(repository, (parent, draft, children))
    assert repository.get_evaluator(parent.id, user_team_id=TEAM) is None
    for identity, _ in children:
        assert repository.get_evaluator(identity.id, user_team_id=TEAM) is None
    assert repository.get_evaluator_draft(outsider.id, user_team_id=TEAM) == outsider_draft


def test_group_save_rejects_stale_identity_and_draft(repository):
    original = group()
    save(repository, original)
    current = revise(original)
    save(repository, current, previous=original)
    with pytest.raises(ValueError, match="changed"):
        save(repository, revise(original, name="过期修改"), previous=original)
    with pytest.raises(ValueError, match="draft changed"):
        save(repository, revise(current), previous=(current[0], original[1], current[2]))
    assert repository.get_evaluator(original[0].id, user_team_id=TEAM) == current[0]
    assert repository.get_evaluator_draft(original[0].id, user_team_id=TEAM) == current[1]


def test_group_child_changes_must_advance_parent_draft_revision(repository):
    value = group()
    save(repository, value)
    child, item = value[2][0]
    changed = item.model_copy(update={"metric": "another_metric", "updated_at": utcnow()})
    children = [(child, changed), *value[2][1:]]
    with pytest.raises(ValueError, match="advance updated_at"):
        save(repository, (value[0], value[1], children), previous=value)
    assert repository.get_evaluator_draft(child.id, user_team_id=TEAM) == item


def test_group_cannot_reparent_existing_child_or_change_its_team(repository):
    value = group()
    save(repository, value)
    child = value[2][0][0]
    for field, new_value in (("owner_evaluator_id", "another-parent"),
                             ("user_team_id", "another-team")):
        with pytest.raises(ValueError, match="immutable"):
            repository.save_evaluator(child.model_copy(update={field: new_value}))
    assert repository.get_evaluator(child.id, user_team_id=TEAM) == child


def test_group_rejects_missing_publication_and_wrong_child_version(repository):
    value = group()
    save(repository, value)
    with pytest.raises(ValueError, match="all child publications"):
        repository.publish_evaluator_group_draft(
            value[1].id, publications(value)[:-1],
            expected_updated_at=value[1].updated_at, user_team_id=TEAM,
        )
    parent, draft, children = revise(value)
    draft = draft.model_copy(update={"children": tuple(ref.model_copy(update={
        "evaluator_version": "2",
    }) for ref in draft.children)})
    with pytest.raises(ValueError, match="child version changed"):
        save(repository, (parent, draft, children), previous=value)
    assert repository.get_evaluator_draft(parent.id, user_team_id=TEAM) == value[1]


@pytest.mark.parametrize("mismatch", ["parent-team", "child-team", "child-owner", "draft-team"])
def test_group_save_rejects_ownership_mismatches(repository, mismatch):
    parent, draft, children = group()
    if mismatch == "parent-team":
        parent = parent.model_copy(update={"user_team_id": "other-team"})
    else:
        child, item = children[0]
        if mismatch == "child-team":
            child = child.model_copy(update={"user_team_id": "other-team"})
        elif mismatch == "child-owner":
            child = child.model_copy(update={"owner_evaluator_id": "another-parent"})
        else:
            item = item.model_copy(update={"user_team_id": "other-team"})
        children[0] = child, item
    with pytest.raises(ValueError):
        save(repository, (parent, draft, children))
    assert repository.list_evaluators(include_disabled=True, user_team_id=TEAM) == []


def test_group_publication_rejects_stale_child_and_cross_team_atomically(repository):
    value = group()
    save(repository, value)
    expected = publications(value)
    with pytest.raises(ValueError, match="unknown Evaluator group"):
        repository.publish_evaluator_group_draft(
            value[1].id, expected, expected_updated_at=value[1].updated_at,
            user_team_id="other-team",
        )
    _child, draft = value[2][-1]
    changed = draft.model_copy(update={"metric": "changed", "updated_at": utcnow()})
    repository.save_evaluator_draft(changed)
    with pytest.raises(ValueError, match="current draft"):
        repository.publish_evaluator_group_draft(
            value[1].id, expected, expected_updated_at=value[1].updated_at, user_team_id=TEAM,
        )
    for spec in expected:
        assert repository.list_evaluator_versions(spec.id, user_team_id=TEAM) == []
        assert repository.get_evaluator_draft(spec.id, user_team_id=TEAM) is not None


def test_group_remove_and_discard_clean_up_only_unpublished_children(repository):
    original = group(child_ids=("relevance", "accuracy", "conciseness"))
    save(repository, original)
    reduced = revise(original, child_ids={original[2][0][0].id, original[2][1][0].id})
    save(repository, reduced, previous=original)
    removed = original[2][-1][0]
    assert repository.get_evaluator(removed.id, user_team_id=TEAM) is None
    repository.delete_evaluator_draft(reduced[0].id, reduced[1].id, user_team_id=TEAM)
    assert repository.get_evaluator(reduced[0].id, user_team_id=TEAM) is not None
    assert repository.get_evaluator_draft(reduced[0].id, user_team_id=TEAM) is None
    for child, _ in reduced[2]:
        assert repository.get_evaluator(child.id, user_team_id=TEAM) is None


def test_group_publish_checks_revision_even_when_published_content_is_identical(repository):
    original = group()
    save(repository, original)
    current = revise(original, name=original[0].name)
    save(repository, current, previous=original)
    assert publications(current) == publications(original)
    with pytest.raises(ValueError, match="draft changed"):
        repository.publish_evaluator_group_draft(
            original[1].id, publications(current), expected_updated_at=original[1].updated_at,
            user_team_id=TEAM,
        )
    assert repository.get_evaluator_draft(current[0].id, user_team_id=TEAM) == current[1]
    assert repository.list_evaluator_versions(current[0].id, user_team_id=TEAM) == []


def test_group_parent_delete_cleans_unpublished_owned_children(repository):
    value = group()
    save(repository, value)
    with pytest.raises(ValueError):
        repository.delete_unpublished_evaluator(value[0].id, user_team_id="other-team")
    repository.delete_unpublished_evaluator(value[0].id, user_team_id=TEAM)
    assert repository.list_evaluators(include_disabled=True, user_team_id=TEAM) == []


def test_discard_group_checks_revision_and_team_before_cleaning_children(repository):
    original = group()
    save(repository, original)
    current = revise(original)
    save(repository, current, previous=original)
    for draft, team in ((original[1], TEAM), (current[1], "another-team")):
        with pytest.raises(ValueError):
            repository.discard_evaluator_group_draft(
                current[0].id, draft.id, draft.updated_at, user_team_id=team,
            )
    assert repository.get_evaluator_draft(current[0].id, user_team_id=TEAM) == current[1]
    for identity, draft in current[2]:
        assert repository.get_evaluator_draft(identity.id, user_team_id=TEAM) == draft
    repository.discard_evaluator_group_draft(
        current[0].id, current[1].id, current[1].updated_at, user_team_id=TEAM,
    )
    assert repository.list_evaluators(include_disabled=True, user_team_id=TEAM) == []


def test_group_new_version_keeps_removed_child_publications(repository):
    original = group()
    save(repository, original)
    first = publications(original)
    repository.publish_evaluator_group_draft(
        original[1].id, first, expected_updated_at=original[1].updated_at, user_team_id=TEAM,
    )
    now = utcnow()
    parent = repository.get_evaluator(original[0].id, user_team_id=TEAM)
    child = repository.get_evaluator(original[2][0][0].id, user_team_id=TEAM)
    parent_draft = clone_evaluator_version_to_draft(parent, first[0], "parent-v2", now)
    parent_draft = parent_draft.model_copy(update={"children": (
        EvaluatorRef(evaluator_id=child.id, evaluator_version="2", weight=1),
    )})
    child_draft = clone_evaluator_version_to_draft(child, first[1], "child-v2", now)
    second_value = parent, parent_draft, [(child, child_draft)]
    save(repository, second_value, previous=(parent, None, []))
    second = publications(second_value, version=2)
    repository.publish_evaluator_group_draft(
        parent_draft.id, second, expected_updated_at=parent_draft.updated_at, user_team_id=TEAM,
    )
    assert repository.get_evaluator_version(parent.id, "1", user_team_id=TEAM) == first[0]
    assert repository.get_evaluator_version(first[2].id, "1", user_team_id=TEAM) == first[2]
    assert repository.get_evaluator(first[2].id, user_team_id=TEAM) is not None
    assert repository.list_evaluator_versions(parent.id, user_team_id=TEAM) == [second[0], first[0]]
    published_parent = repository.get_evaluator(parent.id, user_team_id=TEAM)
    published_child = repository.get_evaluator(child.id, user_team_id=TEAM)
    now = utcnow()
    third_draft = clone_evaluator_version_to_draft(published_parent, second[0], "parent-v3", now)
    third_draft = third_draft.model_copy(update={"children": (
        EvaluatorRef(evaluator_id=child.id, evaluator_version="3", weight=1),
    )})
    third_child_draft = clone_evaluator_version_to_draft(published_child, second[1], "child-v3", now)
    save(repository, (published_parent, third_draft, [(published_child, third_child_draft)]),
         previous=(published_parent, None, []))
    repository.discard_evaluator_group_draft(
        parent.id, third_draft.id, third_draft.updated_at, user_team_id=TEAM,
    )
    assert repository.get_evaluator(parent.id, user_team_id=TEAM) == published_parent
    assert repository.get_evaluator_draft(parent.id, user_team_id=TEAM) is None
    assert repository.get_evaluator_draft(child.id, user_team_id=TEAM) is None
    assert repository.list_evaluator_versions(parent.id, user_team_id=TEAM) == [second[0], first[0]]


@pytest.mark.parametrize("operation", ["save", "publish"])
def test_only_one_group_writer_wins(repository, operation):
    original = group()
    save(repository, original)
    barrier = Barrier(2)

    def compete(index):
        barrier.wait()
        try:
            if operation == "save":
                save(repository, revise(original, name=f"修改 {index}"), previous=original)
            else:
                repository.publish_evaluator_group_draft(
                    original[1].id, publications(original),
                    expected_updated_at=original[1].updated_at, user_team_id=TEAM,
                )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(compete, range(2))) == [False, True]
    if operation == "publish":
        assert len(repository.list_evaluator_versions(original[0].id, user_team_id=TEAM)) == 1


def test_archived_identity_cannot_be_revived_and_keeps_publications(repository):
    value = group()
    save(repository, value)
    expected = publications(value)
    repository.publish_evaluator_group_draft(
        value[1].id, expected, expected_updated_at=value[1].updated_at,
        user_team_id=TEAM,
    )
    parent = repository.get_evaluator(value[0].id, user_team_id=TEAM)
    archived = parent.model_copy(update={
        "archived": True, "enabled": False, "updated_at": utcnow(),
    })
    repository.save_evaluator(archived)
    repository.save_evaluator(archived)

    for changes in ({"archived": False}, {"enabled": True}, {"name": "revived"}):
        with pytest.raises(ValueError, match="archived Evaluator"):
            repository.save_evaluator(archived.model_copy(update={
                **changes, "updated_at": utcnow(),
            }))
    assert repository.get_evaluator(parent.id, user_team_id=TEAM) == archived
    for spec in expected:
        assert repository.get_evaluator_version(spec.id, "1", user_team_id=TEAM) == spec


@pytest.mark.parametrize("operation", ["save-draft", "publish-single"])
def test_archived_child_rejects_prepared_draft_mutations(repository, operation):
    value = group()
    save(repository, value)
    child, draft = value[2][0]
    prepared = publish_evaluator_draft(child, draft, 1)
    archived = child.model_copy(update={"archived": True, "updated_at": utcnow()})
    repository.save_evaluator(archived)

    with pytest.raises(ValueError, match="archived Evaluator"):
        if operation == "save-draft":
            repository.save_evaluator_draft(draft.model_copy(update={
                "metric": "changed", "updated_at": utcnow(),
            }))
        else:
            repository.publish_evaluator_draft(draft.id, prepared)
    assert repository.get_evaluator(child.id, user_team_id=TEAM) == archived
    assert repository.get_evaluator_draft(child.id, user_team_id=TEAM) == draft
    assert repository.list_evaluator_versions(child.id, user_team_id=TEAM) == []


@pytest.mark.parametrize("archive_child", [False, True])
def test_group_publication_rejects_archived_member_atomically(repository, archive_child):
    value = group()
    save(repository, value)
    prepared = publications(value)
    identity = value[2][0][0] if archive_child else value[0]
    repository.save_evaluator(identity.model_copy(update={
        "archived": True, "updated_at": utcnow(),
    }))

    with pytest.raises(ValueError, match="archived Evaluator"):
        repository.publish_evaluator_group_draft(
            value[1].id, prepared, expected_updated_at=value[1].updated_at,
            user_team_id=TEAM,
        )
    for child, draft in ((value[0], value[1]), *value[2]):
        assert repository.get_evaluator_draft(child.id, user_team_id=TEAM) == draft
        assert repository.list_evaluator_versions(child.id, user_team_id=TEAM) == []
