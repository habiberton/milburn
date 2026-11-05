from pathlib import Path
import re
import subprocess


def git(path, *arguments):
    return subprocess.run(("git", *arguments), cwd=path, capture_output=True,
                          text=True, check=True).stdout.strip()


def test_dependency_environment_key_is_shared_across_worktrees_and_changes_with_declaration(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "pyproject.toml").write_text('[project]\nname="example"\nversion="0.1"\n')
    git(repo, "add", "."); git(repo, "commit", "-qm", "base")
    worktree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-qb", "test-branch", str(worktree))
    script = Path(__file__).resolve().parents[3] / "scripts/dev-env.sh"

    def key_path(directory):
        completed = subprocess.run((str(script), "--check"), cwd=directory,
                                   capture_output=True, text=True, check=False)
        assert completed.returncode == 1
        match = re.search(r"not ready at (.+?) \(run scripts/dev-env.sh\)", completed.stderr)
        assert match, completed.stderr
        return Path(match.group(1))

    first = key_path(repo)
    assert first == key_path(worktree)
    assert worktree not in first.parents
    (worktree / "pyproject.toml").write_text('[project]\nname="example"\nversion="0.2"\n')
    assert first != key_path(worktree)
