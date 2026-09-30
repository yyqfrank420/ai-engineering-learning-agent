from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("frontend_checks", ROOT / "scripts/frontend_checks.py")
frontend_checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontend_checks)


@pytest.fixture
def runner(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    calls = []
    monkeypatch.setattr(frontend_checks, "ROOT", tmp_path)

    def run(argv, *, cwd, check):
        calls.append(argv)
        assert cwd == tmp_path / "frontend"
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(frontend_checks.subprocess, "run", run)
    return tmp_path, calls


def add_file(root, path):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")


def test_sources_and_changed_tests_run_related_once(runner):
    root, calls = runner
    source = "frontend/src/feature.tsx"
    test = "frontend/src/feature.test.tsx"
    for path in (source, test):
        add_file(root, path)
    assert frontend_checks.main(["--path", source, "--path", test, "--path", source]) == 0
    assert calls == [
        ["npm", "run", "lint"],
        ["npm", "exec", "--no", "--", "vitest", "related", "--run", "--passWithNoTests",
         "src/feature.test.tsx", "src/feature.tsx"],
        ["npm", "run", "build"],
    ]


@pytest.mark.parametrize("path", ["frontend/src/layout.css", "frontend/public/icon.svg", "frontend/index.html"])
def test_presentation_paths_do_not_run_unrelated_tests(runner, path):
    _, calls = runner
    assert frontend_checks.main(["--path", path]) == 0
    assert calls == [["npm", "run", "lint"], ["npm", "run", "build"]]


@pytest.mark.parametrize("path", [
    "frontend/vitest.config.ts", "frontend/vitest.setup.ts", "frontend/vite.config.ts",
    "frontend/tsconfig.app.json", "frontend/eslint.config.js", "frontend/vercel.json",
    "frontend/src/deleted.ts", "frontend/src/deleted.test.tsx",
])
def test_shared_configuration_and_deletions_run_full_coverage(runner, path):
    _, calls = runner
    assert frontend_checks.main(["--path", path]) == 0
    assert calls == [
        ["npm", "run", "lint"], ["npm", "run", "test:coverage"], ["npm", "run", "build"],
    ]


@pytest.mark.parametrize("arguments", [
    ["--full"], ["--path", "frontend/package.json"], ["--path", "frontend/package-lock.json"],
])
def test_explicit_full_and_dependency_changes_preserve_audit(runner, arguments):
    _, calls = runner
    assert frontend_checks.main(arguments) == 0
    assert calls == [
        ["npm", "run", "lint"], ["npm", "run", "test:coverage"],
        ["npm", "run", "build"], ["npm", "audit", "--audit-level=low"],
    ]


def test_paths_file_and_explicit_paths_are_combined(runner):
    root, calls = runner
    add_file(root, "frontend/src/feature.test.ts")
    path_file = root / "paths.txt"
    path_file.write_text("frontend/src/feature.test.ts\n", encoding="utf-8")
    assert frontend_checks.main(["--paths-from", str(path_file), "--path", "frontend/src/layout.css"]) == 0
    assert calls[1][-1] == "src/feature.test.ts"


@pytest.mark.parametrize("arguments", [[], ["--path", "frontend"], ["--path", "backend/main.py"], ["--path", "frontend/../backend/main.py"]])
def test_unscoped_or_invalid_requests_fail_without_commands(runner, arguments):
    _, calls = runner
    with pytest.raises(SystemExit) as error:
        frontend_checks.main(arguments)
    assert error.value.code == 2
    assert calls == []


def test_command_failure_stops_remaining_checks(runner, monkeypatch):
    root, calls = runner
    add_file(root, "frontend/src/feature.ts")

    def fail(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(frontend_checks.subprocess, "run", fail)
    assert frontend_checks.main(["--path", "frontend/src/feature.ts"]) == 7
    assert calls == [["npm", "run", "lint"]]
