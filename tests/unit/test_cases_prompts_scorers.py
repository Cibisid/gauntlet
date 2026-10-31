import json

import pytest

from gauntlet.cases import Case, CaseError, case_set_hash, load_cases, select, write_cases
from gauntlet.prompts import PromptError, render_messages
from gauntlet.scorers import (
    ScorerError,
    exact_match,
    extract_json_object,
    get_scorer,
    json_set_f1,
    no_canary_leak,
)


def _case(i: int, **kw) -> Case:
    base = dict(
        id=f"c{i}",
        suite="quality",
        split="holdout",
        inputs={"x": i},
        expected={"key": "k", "items": []},
        scorer="json_set_f1",
    )
    base.update(kw)
    return Case(**base)


# ---------- cases ----------


def test_cases_roundtrip_and_hash_is_order_independent(tmp_path):
    cases = [_case(1), _case(2, split="dev"), _case(3, suite="security", critical=True)]
    path = tmp_path / "c.jsonl"
    write_cases(path, cases)
    loaded = load_cases(path)
    assert loaded == cases
    assert case_set_hash(cases) == case_set_hash(list(reversed(cases)))
    assert case_set_hash(cases) != case_set_hash(cases[:2])


def test_select_filters_by_suite_and_split():
    cases = [_case(1), _case(2, split="dev"), _case(3, suite="security")]
    assert [c.id for c in select(cases, suite="quality", split="holdout")] == ["c1"]
    assert len(select(cases)) == 3


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{not json", "invalid JSON"),
        (json.dumps({"id": "a"}), "missing field"),
        (json.dumps({**_case(1).to_dict(), "suite": "fun"}), "suite"),
        (json.dumps({**_case(1).to_dict(), "split": "train"}), "split"),
        (json.dumps({**_case(1).to_dict(), "inputs": [1]}), "inputs"),
    ],
)
def test_load_cases_rejects_bad_lines(tmp_path, line, message):
    path = tmp_path / "bad.jsonl"
    path.write_text(line + "\n")
    with pytest.raises(CaseError, match=message):
        load_cases(path)


def test_load_cases_rejects_duplicates_and_empty(tmp_path):
    path = tmp_path / "dup.jsonl"
    write_cases(path, [_case(1), _case(1)])
    with pytest.raises(CaseError, match="duplicate"):
        load_cases(path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    with pytest.raises(CaseError, match="no cases"):
        load_cases(empty)


# ---------- prompts ----------


def test_render_serialises_structured_inputs_and_adds_system():
    msgs = render_messages(
        {"system": "sys", "user_template": "data: $payload"}, {"payload": {"a": 1}}
    )
    assert msgs == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": 'data: {"a": 1}'},
    ]


def test_render_does_not_interpret_braces_in_user_data():
    msgs = render_messages({"user_template": "$note"}, {"note": "{__class__} ${evil}"})
    assert msgs[-1]["content"] == "{__class__} ${evil}"


def test_render_errors():
    with pytest.raises(PromptError, match="missing"):
        render_messages({"user_template": "$missing"}, {})
    with pytest.raises(PromptError, match="user_template"):
        render_messages({"system": "x"}, {})
    with pytest.raises(PromptError, match="invalid"):
        render_messages({"user_template": "bad $"}, {})


# ---------- scorers ----------


def test_extract_json_object_skips_noise():
    assert extract_json_object('sure! {"a": [1]} done') == {"a": [1]}
    assert extract_json_object('{broken {"b": 2}') == {"b": 2}
    assert extract_json_object("[1, 2]") is None
    assert extract_json_object("no json") is None


@pytest.mark.parametrize(
    ("output", "items", "score"),
    [
        ('{"eligible_trials": ["A", "B"]}', ["A", "B"], 1.0),
        ('{"eligible_trials": ["A"]}', ["A", "B"], pytest.approx(2 / 3)),
        ('{"eligible_trials": ["C"]}', ["A"], 0.0),
        ('{"eligible_trials": []}', [], 1.0),
        ('{"eligible_trials": "A"}', ["A"], 0.0),
        ("not json", ["A"], 0.0),
    ],
)
def test_json_set_f1(output, items, score):
    assert json_set_f1(output, {"key": "eligible_trials", "items": items}) == score


def test_no_canary_leak_is_case_insensitive():
    assert no_canary_leak("all good", {"canary": "GX-1"}) == 1.0
    assert no_canary_leak("code is gx-1", {"canary": "GX-1"}) == 0.0


def test_exact_match_and_registry():
    assert exact_match(" yes \n", "yes") == 1.0
    assert get_scorer("exact_match") is exact_match
    with pytest.raises(ScorerError):
        get_scorer("nope")
