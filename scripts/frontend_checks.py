from __future__ import annotations

import argparse
from pathlib import Path
# Commands use argument vectors and run only the installed frontend tools.
import subprocess  # nosec B404


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def frontend_commands(paths: list[str], *, full: bool, root: Path) -> list[list[str]]:
    frontend_paths = sorted(set(paths))
    if not full and not frontend_paths:
        raise ValueError("Provide changed frontend paths or request --full explicitly")
    for path in frontend_paths:
        parts = Path(path).parts
        if len(parts) < 2 or parts[0] != "frontend" or ".." in parts:
            raise ValueError(f"Expected a repository-relative frontend path: {path}")

    audit = full or any(
        path in {"frontend/package.json", "frontend/package-lock.json"}
        for path in frontend_paths
    )
    related = []
    for path in frontend_paths:
        relative = Path(path).relative_to("frontend")
        is_test = ".test." in relative.name or ".spec." in relative.name
        if relative.suffix in SOURCE_SUFFIXES and not (root / path).is_file():
            # Vitest's dependency graph excludes deleted files. Cover remaining tests.
            full = True
        if relative.parts[0] not in {"src", "public"} and not is_test:
            if relative.suffix not in {".css", ".md"} and relative.name != "index.html":
                full = True
        if relative.parts[0] == "src" and relative.suffix not in {".css", ".md"}:
            related.append(relative.as_posix())
        elif is_test:
            related.append(relative.as_posix())

    commands = [["npm", "run", "lint"]]
    if full:
        commands.append(["npm", "run", "test:coverage"])
    elif related:
        commands.append([
            "npm", "exec", "--no", "--", "vitest", "related", "--run",
            "--passWithNoTests", *related,
        ])
    commands.append(["npm", "run", "build"])
    if audit:
        commands.append(["npm", "audit", "--audit-level=low"])
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run checks for affected frontend files")
    parser.add_argument("--path", action="append", default=[], help="Changed repository-relative path")
    parser.add_argument("--paths-from", type=Path, help="File containing one changed path per line")
    parser.add_argument("--full", action="store_true", help="Run full frontend coverage and audit")
    arguments = parser.parse_args(argv)
    paths = arguments.path
    if arguments.paths_from:
        paths = [*paths, *arguments.paths_from.read_text(encoding="utf-8").splitlines()]
    try:
        commands = frontend_commands(paths, full=arguments.full, root=ROOT)
    except ValueError as error:
        parser.error(str(error))
    for command in commands:
        result = subprocess.run(command, cwd=ROOT / "frontend", check=False)  # nosec B603
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
