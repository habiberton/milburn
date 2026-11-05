import pytest

from milburn.agents.harness import Harness
from milburn.app.project import DEFAULT_CONFIG, ProjectError, parse_config
from milburn.domain import CoderOutcome, CoderResult
from milburn.domain.errors import DomainError

GOOD = DEFAULT_CONFIG.format(default_branch="main")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('delivery = "local-only"', 'delivery = "yolo"', "delivery"),
        ('harness = "codex"', 'harness = "gemini"', "harness"),
        ('[roles.tester]\nharness = "claude-code"', '[roles.tester]\nharness = "codex"', "different harness"),
        ('independence = "other-than-coder"', 'independence = "maybe"', "independence"),
        ("[project]", "[project]\nsurprise = 1", "unknown keys"),
        ("[roles.coder]", "[roles.coder]\nmodel = \"a b\"", "model"),
        ('default_branch = "main"', 'default_branch = ""', "default_branch"),
    ],
)
def test_invalid_config_is_refused(old: str, new: str, message: str) -> None:
    assert old in GOOD
    with pytest.raises(ProjectError, match=message):
        parse_config(GOOD.replace(old, new, 1), {})


def test_unparseable_and_incomplete_config_is_refused() -> None:
    with pytest.raises(ProjectError, match="invalid"):
        parse_config("[project", {})
    with pytest.raises(ProjectError, match="roles"):
        parse_config('[project]\ndefault_branch = "main"\n', {})


def test_same_harness_is_allowed_only_when_independence_is_any() -> None:
    text = GOOD.replace('[roles.tester]\nharness = "claude-code"', '[roles.tester]\nharness = "codex"')
    config = parse_config(text.replace('"other-than-coder"', '"any"'), {})
    assert config.coder.harness is config.tester.harness is Harness.CODEX


def test_default_config_and_executable_overrides() -> None:
    config = parse_config(GOOD, {"MILBURN_CODEX_EXECUTABLE": "/x/codex"})
    assert config.delivery == "local-only"
    assert config.executables[Harness.CODEX] == "/x/codex"
    assert config.executables[Harness.CLAUDE_CODE] == "claude"


def _coder(outcome: CoderOutcome, commits: tuple[str, ...]) -> CoderResult:
    return CoderResult(
        attempt_id="a1", issue_number=1, outcome=outcome, head_sha="abc",
        progress_path="progress.txt", commits=commits, files_changed=(),
        test_claims=(), risks=(),
    )


def test_commit_ids_are_still_validated() -> None:
    with pytest.raises(DomainError):
        _coder(CoderOutcome.CANDIDATE, ("not an id",))


@pytest.mark.parametrize("outcome", list(CoderOutcome))
def test_non_candidates_may_have_no_commits_g21(outcome: CoderOutcome) -> None:
    assert _coder(outcome, ()).commits == ()
