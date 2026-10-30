import pytest

from gauntlet.release import ReleaseError, release_id

BASE = {
    "app": "trialbridge",
    "prompt": {
        "system": "You match patients to clinical trials.",
        "template_ref": "eligibility_v3",
    },
    "model": {"provider": "anthropic", "name": "claude-sonnet"},
    "params": {"temperature": 0.0, "max_tokens": 800},
}


def test_release_id_is_stable_across_key_order():
    reordered = {
        "params": {"max_tokens": 800, "temperature": 0.0},
        "model": {"name": "claude-sonnet", "provider": "anthropic"},
        "prompt": BASE["prompt"],
        "app": "trialbridge",
    }
    assert release_id(BASE) == release_id(reordered)
    assert release_id(BASE).startswith("rel_")


def test_any_behaviour_change_changes_the_id():
    changed = {**BASE, "params": {**BASE["params"], "temperature": 0.2}}
    assert release_id(changed) != release_id(BASE)


def test_missing_keys_rejected():
    with pytest.raises(ReleaseError):
        release_id({"app": "x"})


@pytest.mark.parametrize("key", ["api_key", "OPENAI_API_KEY", "db_password", "secret"])
def test_inline_secrets_rejected(key):
    doc = {**BASE, "model": {**BASE["model"], key: "sk-123"}}
    with pytest.raises(ReleaseError):
        release_id(doc)


def test_secret_references_allowed():
    doc = {**BASE, "model": {**BASE["model"], "api_key_ref": "secretsmanager:prod/anthropic"}}
    assert release_id(doc).startswith("rel_")


def test_nested_list_secrets_rejected():
    doc = {**BASE, "tools": [{"name": "search", "auth_token": "abc"}]}
    with pytest.raises(ReleaseError):
        release_id(doc)
