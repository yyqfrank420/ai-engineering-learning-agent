from __future__ import annotations

import json
import subprocess
from argparse import Namespace

import pytest

from scripts import ci_runner


@pytest.fixture
def reviewed_repo(tmp_path, monkeypatch, request):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    path = getattr(request, "param", "frontend/src/App.tsx")
    source = tmp_path / path
    source.parent.mkdir(parents=True)
    source.write_text("original display\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    before = git("rev-parse", f"HEAD:{path}")
    manifest = ci_runner.load_manifest()
    manifest["impact"]["reviewed_presentation_changes"] = [
        {
            "path": path,
            "before_blob": before,
            "after_blob": "a" * 40,
            "reason": "Remove redundant presentation status.",
            "verification": "Offline component checks and rendered fixture inspection passed.",
        }
    ]
    monkeypatch.setattr(ci_runner, "ROOT", tmp_path)
    return git, source, path, base, manifest


def finish_change(repo):
    git, source, path, base, manifest = repo
    git("add", "-A")
    git("commit", "-qm", "presentation")
    after = (
        git("rev-parse", f"HEAD:{path}")
        if source.exists() or source.is_symlink()
        else ci_runner.ZERO_SHA
    )
    manifest["impact"]["reviewed_presentation_changes"][0]["after_blob"] = after
    return ci_runner.classify_paths(
        ci_runner._git_changed_paths(base, "HEAD"), manifest, base=base, head="HEAD"
    )


@pytest.mark.parametrize("delete", [False, True])
def test_exact_reviewed_modification_or_deletion_skips_paid_calls(
    reviewed_repo, delete
):
    _, source, _, _, manifest = reviewed_repo
    if delete:
        source.unlink()
    else:
        source.write_text("plain display\n")
    result = finish_change(reviewed_repo)
    assert result["ai_impact"] is False
    assert (
        result["reasons"]["reviewed_presentation_changes"]
        == manifest["impact"]["reviewed_presentation_changes"]
    )


def test_path_only_classification_cannot_use_a_review(reviewed_repo):
    _, source, path, _, manifest = reviewed_repo
    source.write_text("plain display\n")
    finish_change(reviewed_repo)
    assert ci_runner.classify_paths([path], manifest)["ai_impact"] is True


@pytest.mark.parametrize("field", ["before_blob", "after_blob"])
def test_stale_content_pair_stays_generation_impacting(reviewed_repo, field):
    _, source, path, base, manifest = reviewed_repo
    source.write_text("plain display\n")
    finish_change(reviewed_repo)
    manifest["impact"]["reviewed_presentation_changes"][0][field] = "f" * 40
    result = ci_runner.classify_paths([path], manifest, base=base, head="HEAD")
    assert result["ai_impact"] is True
    assert result["reasons"]["reviewed_presentation_changes"] == []


def test_review_does_not_hide_additional_runtime_changes(reviewed_repo):
    _, source, _, _, _ = reviewed_repo
    source.write_text("plain display\n")
    runtime = source.parents[2] / "backend/agent/prompt.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("new generation behavior\n")
    result = finish_change(reviewed_repo)
    assert result["ai_paths"] == ["backend/agent/prompt.py"]


@pytest.mark.parametrize("change", ["rename", "type", "mode"])
def test_review_cannot_exempt_rename_type_or_mode_changes(reviewed_repo, change):
    _, source, _, _, _ = reviewed_repo
    if change == "rename":
        source.rename(source.with_name("Renamed.tsx"))
    elif change == "type":
        source.unlink()
        source.symlink_to("Other.tsx")
    else:
        source.write_text("plain display\n")
        source.chmod(0o755)
    result = finish_change(reviewed_repo)
    assert result["ai_impact"] is True
    assert result["reasons"]["reviewed_presentation_changes"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "backend/agent/prompt.py"),
        ("path", "frontend/src/../App.tsx"),
        ("before_blob", "abc"),
        ("before_blob", ci_runner.ZERO_SHA),
        ("after_blob", None),
        ("reason", ""),
        ("verification", " "),
    ],
)
def test_malformed_review_fails_closed(reviewed_repo, field, value):
    _, _, path, _, manifest = reviewed_repo
    manifest["impact"]["reviewed_presentation_changes"][0][field] = value
    with pytest.raises(ValueError):
        ci_runner.classify_paths([path], manifest)


def test_duplicate_review_is_rejected(reviewed_repo):
    _, _, path, _, manifest = reviewed_repo
    records = manifest["impact"]["reviewed_presentation_changes"]
    records.append(dict(records[0]))
    with pytest.raises(ValueError):
        ci_runner.classify_paths([path], manifest)


def test_impact_command_uses_revision_evidence(reviewed_repo, capsys):
    _, source, _, base, manifest = reviewed_repo
    source.write_text("plain display\n")
    finish_change(reviewed_repo)
    ci_runner.impact_command(
        Namespace(
            event_file=None,
            paths_from=None,
            base=base,
            head="HEAD",
            github_output=False,
        ),
        manifest,
    )
    result = json.loads(capsys.readouterr().out)
    assert result["ai_impact"] is False
    assert len(result["reasons"]["reviewed_presentation_changes"]) == 1


@pytest.mark.parametrize("same_file", [False, True])
def test_synthetic_merge_must_preserve_reviewed_content(reviewed_repo, same_file):
    git, source, path, _, manifest = reviewed_repo
    source.write_text("original display\n" + "unchanged\n" * 12 + "original runtime\n")
    git("add", "-A")
    git("commit", "-qm", "independent sections")
    base = git("rev-parse", "HEAD")
    record = manifest["impact"]["reviewed_presentation_changes"][0]
    record["before_blob"] = git("rev-parse", f"HEAD:{path}")
    git("checkout", "-qb", "presentation")
    source.write_text(source.read_text().replace("original display", "plain display"))
    git("add", "-A")
    git("commit", "-qm", "presentation")
    pr_head = git("rev-parse", "HEAD")
    record["after_blob"] = git("rev-parse", f"HEAD:{path}")
    git("checkout", "-qb", "updated-main", base)
    if same_file:
        source.write_text(source.read_text().replace("original runtime", "new runtime"))
    else:
        source.with_name("Other.tsx").write_text("independent main change\n")
    git("add", "-A")
    git("commit", "-qm", "independent main change")
    main_head = git("rev-parse", "HEAD")
    git("merge", "--no-ff", "-m", "synthetic PR merge", pr_head)
    result = ci_runner.classify_paths([path], manifest, base=main_head, head=pr_head)
    assert result["ai_impact"] is same_file
    assert len(result["reasons"]["reviewed_presentation_changes"]) == (
        0 if same_file else 1
    )


def test_reviewed_deletion_must_also_be_absent_in_checkout(reviewed_repo):
    git, source, path, base, manifest = reviewed_repo
    source.unlink()
    finish_change(reviewed_repo)
    pr_head = git("rev-parse", "HEAD")
    source.write_text("replacement runtime\n")
    git("add", "-A")
    git("commit", "-qm", "checkout contains replacement")
    result = ci_runner.classify_paths([path], manifest, base=base, head=pr_head)
    assert result["ai_impact"] is True
    assert result["reasons"]["reviewed_presentation_changes"] == []


def test_reviewed_checkout_must_preserve_regular_file_mode(reviewed_repo):
    git, source, path, base, manifest = reviewed_repo
    source.write_text("plain display\n")
    finish_change(reviewed_repo)
    pr_head = git("rev-parse", "HEAD")
    source.chmod(0o755)
    git("add", "-A")
    git("commit", "-qm", "checkout mode changed")
    result = ci_runner.classify_paths([path], manifest, base=base, head=pr_head)
    assert result["ai_impact"] is True
    assert result["reasons"]["reviewed_presentation_changes"] == []


@pytest.mark.parametrize(
    "reviewed_repo",
    ["frontend/package.json", "frontend/package-lock.json", "frontend/index.html"],
    indirect=True,
)
def test_exact_reviewed_metadata_modification_skips_paid_calls(reviewed_repo):
    _, source, _, _, _ = reviewed_repo
    source.write_text("reviewed metadata presentation change\n")
    assert finish_change(reviewed_repo)["ai_impact"] is False


@pytest.mark.parametrize(
    "reviewed_repo",
    ["frontend/package.json", "frontend/package-lock.json", "frontend/index.html"],
    indirect=True,
)
@pytest.mark.parametrize("field", ["before_blob", "after_blob"])
def test_metadata_additions_and_deletions_are_rejected(reviewed_repo, field):
    _, _, path, _, manifest = reviewed_repo
    manifest["impact"]["reviewed_presentation_changes"][0][field] = ci_runner.ZERO_SHA
    with pytest.raises(ValueError):
        ci_runner.classify_paths([path], manifest)


@pytest.mark.parametrize(
    "change",
    ["valid", "stale", "checkout", "symlink", "mode", "checkout_symlink", "checkout_mode"],
)
def test_reviewed_css_addition_requires_exact_regular_content(reviewed_repo, change):
    git, _, _, _, manifest = reviewed_repo
    base = git("rev-parse", "HEAD")
    path = "frontend/src/components/GraphCanvas/Presentation.css"
    source = ci_runner.ROOT / path
    source.parent.mkdir(parents=True)
    source.write_text(".presentation { color: white; }\n")
    if change == "symlink":
        source.unlink()
        source.symlink_to("Other.css")
    elif change == "mode":
        source.chmod(0o755)
    record = manifest["impact"]["reviewed_presentation_changes"][0]
    record.update(path=path, before_blob=ci_runner.ZERO_SHA)
    finish_change((git, source, path, base, manifest))
    pr_head = git("rev-parse", "HEAD")
    if change == "stale":
        record["after_blob"] = "f" * 40
    elif change in {"checkout", "checkout_symlink", "checkout_mode"}:
        if change == "checkout":
            source.write_text(".presentation { color: red; }\n")
        elif change == "checkout_symlink":
            source.unlink()
            source.symlink_to("Other.css")
        else:
            source.chmod(0o755)
        git("add", "-A")
        git("commit", "-qm", "checkout changed")
    result = ci_runner.classify_paths([path], manifest, base=base, head=pr_head)
    assert result["ai_impact"] is (change != "valid")
    assert len(result["reasons"]["reviewed_presentation_changes"]) == (change == "valid")


def test_new_tsx_is_rejected(reviewed_repo):
    _, _, path, _, manifest = reviewed_repo
    manifest["impact"]["reviewed_presentation_changes"][0]["before_blob"] = ci_runner.ZERO_SHA
    with pytest.raises(ValueError):
        ci_runner.classify_paths([path], manifest)


@pytest.mark.parametrize(
    "metadata_path",
    ["frontend/package.json", "frontend/package-lock.json", "frontend/index.html"],
)
def test_source_review_does_not_hide_unaudited_metadata(reviewed_repo, metadata_path):
    _, source, _, _, _ = reviewed_repo
    source.write_text("plain display\n")
    metadata = ci_runner.ROOT / metadata_path
    metadata.write_text("additional generation dependency or configuration\n")
    result = finish_change(reviewed_repo)
    assert result["ai_paths"] == [metadata_path]
