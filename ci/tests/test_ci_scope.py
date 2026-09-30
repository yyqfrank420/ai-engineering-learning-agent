from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ci_runner


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    git(tmp_path, "init", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Scope tests")
    git(tmp_path, "config", "user.email", "scope-tests@example.invalid")
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    for name in ("tracked.txt", "restored.txt", "rename.txt", "deleted.txt"):
        (tmp_path / name).write_text("baseline\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Baseline")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(tmp_path, "switch", "-c", "change")
    monkeypatch.setattr(ci_runner, "ROOT", tmp_path)
    return tmp_path


def test_local_scope_unions_committed_index_worktree_and_untracked_paths(repository):
    (repository / "committed.txt").write_text("branch\n", encoding="utf-8")
    git(repository, "add", "committed.txt")
    git(repository, "commit", "-m", "Branch change")
    (repository / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(repository, "add", "staged.txt")
    (repository / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
    whitespace_path = " untracked \tname.txt"
    (repository / whitespace_path).write_text("untracked\n", encoding="utf-8")
    (repository / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (repository / "restored.txt").write_text("index change\n", encoding="utf-8")
    git(repository, "add", "restored.txt")
    (repository / "restored.txt").write_text("baseline\n", encoding="utf-8")

    assert ci_runner._local_changed_paths() == sorted(
        ["committed.txt", "staged.txt", "tracked.txt", whitespace_path, "restored.txt"]
    )


def test_local_scope_includes_both_rename_paths_and_deleted_files(repository):
    git(repository, "mv", "rename.txt", "renamed.txt")
    (repository / "deleted.txt").unlink()

    assert ci_runner._local_changed_paths() == ["deleted.txt", "rename.txt", "renamed.txt"]


def test_explicit_head_excludes_uncommitted_changes(repository):
    (repository / "tracked.txt").write_text("working change\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("working change\n", encoding="utf-8")

    assert ci_runner._local_changed_paths("origin/main", "HEAD") == []


def test_endpoint_diff_detects_changes_removed_by_force_push(repository):
    baseline = git(repository, "rev-parse", "HEAD")
    (repository / "lost.txt").write_text("old branch\n", encoding="utf-8")
    git(repository, "add", "lost.txt")
    git(repository, "commit", "-m", "Old branch head")
    previous_head = git(repository, "rev-parse", "HEAD")
    git(repository, "reset", "--hard", baseline)
    (repository / "new.txt").write_text("replacement branch\n", encoding="utf-8")
    git(repository, "add", "new.txt")
    git(repository, "commit", "-m", "Replacement branch head")

    assert ci_runner._git_changed_paths(previous_head, "HEAD") == ["new.txt"]
    assert ci_runner._git_changed_paths(previous_head, "HEAD", merge_base=False) == [
        "lost.txt", "new.txt"
    ]


def test_missing_local_baseline_raises(repository):
    git(repository, "update-ref", "-d", "refs/remotes/origin/main")

    with pytest.raises(subprocess.CalledProcessError):
        ci_runner._local_changed_paths()


@pytest.fixture
def offline_cli(monkeypatch):
    manifest = {"offline_groups": [{"name": "backend-core"}]}
    calls = []
    monkeypatch.setattr(ci_runner, "load_manifest", lambda: manifest)
    monkeypatch.setattr(
        ci_runner, "run_offline",
        lambda manifest, group, *, paths: calls.append((manifest, group, paths)),
    )
    return manifest, calls


def test_offline_cli_defaults_to_local_changes(monkeypatch, offline_cli):
    manifest, calls = offline_cli
    monkeypatch.setattr(sys, "argv", ["ci_runner", "offline"])
    monkeypatch.setattr(ci_runner, "_local_changed_paths", lambda: ["backend/config.py"])

    ci_runner.main()

    assert calls == [(manifest, None, ["backend/config.py"])]


@pytest.mark.parametrize("scope", [["--full"], ["--group", "backend-core"]])
def test_explicit_offline_scope_skips_local_discovery(monkeypatch, offline_cli, scope):
    manifest, calls = offline_cli
    monkeypatch.setattr(sys, "argv", ["ci_runner", "offline", *scope])

    def unexpected_discovery(*args, **kwargs):
        pytest.fail("Explicit full/group scope must not discover local paths")

    monkeypatch.setattr(ci_runner, "_local_changed_paths", unexpected_discovery)

    ci_runner.main()

    assert calls == [(manifest, "backend-core" if "--group" in scope else None, None)]


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["--full", "--base", "origin/main"], "--full cannot be combined"),
        (["--full", "--paths-from", "paths.txt"], "--full cannot be combined"),
        (["--full", "--event-file", "event.json"], "--full cannot be combined"),
        (["--head", "HEAD"], "--head requires --base"),
        (["--base", "main", "--paths-from", "paths.txt"], "Choose one"),
        (["--event-file", "event.json", "--paths-from", "paths.txt"], "Choose one"),
    ],
)
def test_offline_cli_rejects_conflicting_scope(monkeypatch, offline_cli, arguments, message):
    _, calls = offline_cli
    monkeypatch.setattr(sys, "argv", ["ci_runner", "offline", *arguments])

    with pytest.raises(ValueError, match=message):
        ci_runner.main()

    assert calls == []
