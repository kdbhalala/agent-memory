"""Deterministic project analysis.

Reads a repository and reports the facts that are cheap to establish exactly:
stack, source layout, real build/test commands, test layout, data-model
surfaces, CI. Exposed as `agi-memory analyze [--json]` and used by the
`/agi-init` slash command as a starting fact sheet — the assistant then reads
the code itself for everything judgement is required for.

Zero external dependencies (stdlib only).
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bootstrap import detect_project_name, extract_readme_context

# Directories never worth walking; also keeps vendored code out of the census.
IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", "target", "out", ".next", ".nuxt", ".cache", "vendor",
    "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".idea",
    ".vscode", ".gradle", "Pods", ".dart_tool", ".terraform", "site-packages",
    ".codegraph", ".agi-memory", ".agent-memory",
}

LANGUAGE_BY_EXT: Dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".dart": "Dart", ".rb": "Ruby", ".php": "PHP",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".swift": "Swift",
    ".cs": "C#", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".m": "Objective-C", ".mm": "Objective-C", ".scala": "Scala", ".ex": "Elixir",
    ".exs": "Elixir", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".sql": "SQL", ".vue": "Vue", ".svelte": "Svelte", ".lua": "Lua", ".r": "R",
}

# Files that describe persisted or wire-format data — the data-model surface.
SCHEMA_PATTERNS = [
    ("prisma/schema.prisma", "Prisma schema"),
    ("schema.rb", "Rails schema"),
    ("db/schema.rb", "Rails schema"),
    ("openapi.yaml", "OpenAPI spec"),
    ("openapi.json", "OpenAPI spec"),
    ("swagger.yaml", "OpenAPI spec"),
]
SCHEMA_DIR_NAMES = {"migrations", "migration", "schemas", "schema", "models", "entities"}
SCHEMA_EXTS = {".sql": "SQL DDL", ".proto": "Protobuf", ".graphql": "GraphQL SDL", ".gql": "GraphQL SDL"}

MAX_WALK_FILES = 20000


def _iter_files(repo: Path):
    """Walk the repo, skipping ignored and hidden directories. Bounded."""
    seen = 0
    stack = [repo]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir():
                    if name in IGNORE_DIRS or (name.startswith(".") and name not in {".github"}):
                        continue
                    stack.append(entry)
                elif entry.is_file():
                    seen += 1
                    if seen > MAX_WALK_FILES:
                        return
                    yield entry
            except OSError:
                continue


def _read(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _git(repo: Path, *args: str, timeout: int = 5) -> str:
    try:
        res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)
        return res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        return ""


def detect_languages(files: List[Path]) -> List[tuple]:
    """(language, file_count) ordered by count, languages with real presence only."""
    counts: Counter = Counter()
    for f in files:
        lang = LANGUAGE_BY_EXT.get(f.suffix.lower())
        if lang:
            counts[lang] += 1
    return counts.most_common(8)


def detect_stack(repo: Path) -> Dict[str, Any]:
    """Manifests present, plus the commands they imply. Commands read from the
    manifest where the manifest declares them (npm scripts, Makefile targets)."""
    manifests: List[str] = []
    build: List[str] = []
    test: List[str] = []
    run: List[str] = []
    package_manager: Optional[str] = None

    pkg_json = repo / "package.json"
    if pkg_json.exists():
        manifests.append("package.json")
        pm = "npm"
        for lock, name in ((("pnpm-lock.yaml",), "pnpm"), (("yarn.lock",), "yarn"),
                           (("bun.lockb", "bun.lock"), "bun")):
            if any((repo / lf).exists() for lf in lock):
                pm = name
                break
        package_manager = pm
        try:
            data = json.loads(_read(pkg_json))
            scripts = data.get("scripts") or {}
            if isinstance(scripts, dict):
                for key in ("build", "compile"):
                    if key in scripts:
                        build.append(f"{pm} run {key}")
                for key in ("test", "test:unit", "e2e", "test:e2e"):
                    if key in scripts:
                        test.append(f"{pm} run {key}" if key != "test" or pm != "npm" else "npm test")
                for key in ("dev", "start", "serve"):
                    if key in scripts:
                        run.append(f"{pm} run {key}")
                for key in ("lint", "typecheck", "type-check"):
                    if key in scripts:
                        build.append(f"{pm} run {key}")
        except (json.JSONDecodeError, TypeError):
            pass

    if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        manifests.append("pyproject.toml" if (repo / "pyproject.toml").exists() else "setup.py")
        if (repo / "tests").is_dir() or list(repo.glob("test_*.py")) or list(repo.glob("tests/*.py")):
            test.append("pytest")
    if (repo / "requirements.txt").exists():
        manifests.append("requirements.txt")
    if (repo / "Cargo.toml").exists():
        manifests.append("Cargo.toml")
        build.append("cargo build")
        test.append("cargo test")
    if (repo / "go.mod").exists():
        manifests.append("go.mod")
        build.append("go build ./...")
        test.append("go test ./...")
    if (repo / "pubspec.yaml").exists():
        manifests.append("pubspec.yaml")
        test.append("flutter test")
        run.append("flutter run")
    if (repo / "Gemfile").exists():
        manifests.append("Gemfile")
        test.append("bundle exec rspec")
    if (repo / "composer.json").exists():
        manifests.append("composer.json")
        test.append("composer test")
    if (repo / "pom.xml").exists():
        manifests.append("pom.xml")
        build.append("mvn package")
        test.append("mvn test")
    for gradle in ("build.gradle", "build.gradle.kts"):
        if (repo / gradle).exists():
            manifests.append(gradle)
            build.append("./gradlew build")
            test.append("./gradlew test")
            break

    for mk in ("Makefile", "makefile", "justfile"):
        mk_path = repo / mk
        if mk_path.exists():
            manifests.append(mk)
            runner = "just" if mk == "justfile" else "make"
            targets = re.findall(r"^([a-zA-Z][\w.-]*)\s*:(?!=)", _read(mk_path, 20_000), re.MULTILINE)
            for target in targets[:12]:
                cmd = f"{runner} {target}"
                if target in ("test", "tests", "check"):
                    test.append(cmd)
                elif target in ("build", "compile", "all", "install"):
                    build.append(cmd)
                elif target in ("run", "dev", "serve", "start"):
                    run.append(cmd)

    def dedupe(seq: List[str]) -> List[str]:
        return list(dict.fromkeys(seq))

    return {
        "manifests": dedupe(manifests),
        "package_manager": package_manager,
        "build_commands": dedupe(build),
        "test_commands": dedupe(test),
        "run_commands": dedupe(run),
        "containerized": any((repo / f).exists() for f in
                             ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml")),
    }


def detect_source_dirs(repo: Path, files: List[Path]) -> List[tuple]:
    """(top-level dir, code file count) — where the code actually lives."""
    counts: Counter = Counter()
    for f in files:
        if f.suffix.lower() not in LANGUAGE_BY_EXT:
            continue
        try:
            rel = f.relative_to(repo)
        except ValueError:
            continue
        counts[rel.parts[0] if len(rel.parts) > 1 else "."] += 1
    return counts.most_common(10)


def detect_schema_surfaces(repo: Path, files: List[Path]) -> List[str]:
    """Files and directories that define persisted or wire-format data."""
    found: List[str] = []
    for rel, label in SCHEMA_PATTERNS:
        if (repo / rel).exists():
            found.append(f"`{rel}` — {label}")
    dirs: Counter = Counter()
    ext_hits: Counter = Counter()
    for f in files:
        try:
            rel = f.relative_to(repo)
        except ValueError:
            continue
        label = SCHEMA_EXTS.get(f.suffix.lower())
        if label:
            ext_hits[(str(rel.parent), label)] += 1
        if rel.parent.name.lower() in SCHEMA_DIR_NAMES:
            dirs[str(rel.parent)] += 1
    for (parent, label), n in ext_hits.most_common(5):
        found.append(f"`{parent}/` — {n} {label} file(s)")
    for parent, n in dirs.most_common(5):
        entry = f"`{parent}/` — {n} file(s)"
        if not any(parent in existing for existing in found):
            found.append(entry)
    return found[:8]


def detect_ci(repo: Path) -> List[str]:
    ci: List[str] = []
    wf_dir = repo / ".github" / "workflows"
    if wf_dir.is_dir():
        for wf in sorted(wf_dir.glob("*.y*ml"))[:8]:
            ci.append(f".github/workflows/{wf.name}")
    for other in (".gitlab-ci.yml", ".circleci/config.yml", "azure-pipelines.yml", ".travis.yml"):
        if (repo / other).exists():
            ci.append(other)
    return ci


def detect_test_layout(repo: Path, files: List[Path]) -> List[str]:
    """Directories holding tests, by count."""
    counts: Counter = Counter()
    for f in files:
        if f.suffix.lower() not in LANGUAGE_BY_EXT:
            continue
        try:
            rel = f.relative_to(repo)
        except ValueError:
            continue
        parts = [p.lower() for p in rel.parts]
        name = rel.name.lower()
        is_test = (
            any(p in ("test", "tests", "spec", "specs", "__tests__") for p in parts[:-1])
            or name.startswith("test_")
            or any(name.endswith(sfx) for sfx in ("_test.py", "_test.go", "_test.rs",
                                                  ".test.ts", ".test.tsx", ".test.js",
                                                  ".spec.ts", ".spec.tsx", ".spec.js"))
        )
        if is_test:
            counts[str(rel.parent)] += 1
    return [f"`{d}/` — {n} test file(s)" for d, n in counts.most_common(6)]


def detect_git_facts(repo: Path) -> Dict[str, Any]:
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    log = _git(repo, "log", "-80", "--pretty=%s")
    types: Counter = Counter()
    for line in log.splitlines():
        m = re.match(r"^(feat|fix|refactor|perf|docs|test|chore|ci|build|style)\b", line.strip())
        if m:
            types[m.group(1)] += 1
    recent = [l.strip() for l in log.splitlines()[:5] if l.strip()]
    return {
        "branch": branch or None,
        "commit_types": types.most_common(6),
        "recent_commits": recent,
        "conventional": sum(types.values()) >= max(3, len(log.splitlines()) // 3),
    }


def analyze_project(repo_dir: Path | str = ".") -> Dict[str, Any]:
    """Full read of a repository. Every field is derived from files on disk;
    nothing is guessed. Missing evidence yields an empty list, not a placeholder."""
    repo = Path(repo_dir).resolve()
    files = list(_iter_files(repo))
    readme = extract_readme_context(repo) or {}
    stack = detect_stack(repo)
    return {
        "name": detect_project_name(repo),
        "root": str(repo),
        "file_count": len(files),
        "languages": detect_languages(files),
        "source_dirs": detect_source_dirs(repo, files),
        "test_layout": detect_test_layout(repo, files),
        "schema_surfaces": detect_schema_surfaces(repo, files),
        "ci": detect_ci(repo),
        "git": detect_git_facts(repo),
        "readme_title": readme.get("title", "").replace("Architecture Overview: ", "") or None,
        "readme_summary": (readme.get("text") or "").strip() or None,
        **stack,
    }


# --- Markdown renderers -------------------------------------------------------
# Each renderer states what was found and, where nothing was found, says so and
# names what to fill in. An empty section is honest; invented prose is not.

_UNKNOWN = "_Not detected during analysis — fill this in._"


def _bullets(items: List[str], empty: str = _UNKNOWN) -> str:
    return "\n".join(f"- {i}" for i in items) if items else empty


def _commands(items: List[str], empty: str) -> str:
    return "```bash\n" + "\n".join(items) + "\n```" if items else empty


def render_architecture(a: Dict[str, Any]) -> str:
    langs = [f"{lang} — {n} file(s)" for lang, n in a["languages"]]
    dirs = [f"`{d}/` — {n} source file(s)" for d, n in a["source_dirs"] if d != "."]
    summary = a["readme_summary"]
    if summary:
        summary = "\n".join(summary.splitlines()[:12])
    return f"""# Architecture & System Design ({a['name']})

> Detected automatically. Run `/agi-init` to have the assistant read the code
> and replace this with a real architectural description.

## What this project is

{summary or _UNKNOWN}

## Languages

{_bullets(langs)}

## Source layout

{_bullets(dirs, "_Single-directory project._")}

## Toolchain

{_bullets([f"`{m}`" for m in a["manifests"]], "_No package manifest detected._")}
{f"- Package manager: `{a['package_manager']}`" if a.get("package_manager") else ""}
{"- Containerized (Dockerfile / compose present)" if a.get("containerized") else ""}

## Invariants

_Record the non-negotiable rules here — layer boundaries, dependency limits,
data-ownership rules. Pin the critical ones with `memory_pin` so they survive
context compaction._
"""


def render_testing(a: Dict[str, Any]) -> str:
    return f"""# Testing & QA Standards ({a['name']})

> Detected automatically. Run `/agi-init` for an assistant-written version.

## Verification commands

{_commands(a["test_commands"], "_No test runner detected — add the command that verifies this project._")}

## Build & static checks

{_commands(a["build_commands"], "_No build command detected._")}

## Where tests live

{_bullets(a["test_layout"], "_No test files detected._")}

## CI

{_bullets([f"`{c}`" for c in a["ci"]], "_No CI configuration detected._")}

## Standard

Run the verification commands above before every commit. A failing suite blocks
the commit — fix the implementation, not the test, unless the test is provably wrong.
"""


def render_data_model(a: Dict[str, Any]) -> str:
    return f"""# Data Model & Schema Specifications ({a['name']})

> Detected automatically. Run `/agi-init` for an assistant-written version.

## Schema surfaces found

{_bullets(a["schema_surfaces"], "_No schema, migration, or IDL files detected._")}

## Entities

_Document the core entities, their relationships, and their ownership boundaries
here. Anything an assistant would otherwise have to infer by reading migrations
belongs in this file._
"""


def render_runbook(a: Dict[str, Any]) -> str:
    git = a["git"]
    convention = ""
    if git["commit_types"]:
        top = ", ".join(f"`{t}` ({n})" for t, n in git["commit_types"])
        convention = (f"Commit history uses Conventional Commits: {top}."
                      if git["conventional"] else f"Common commit prefixes: {top}.")
    return f"""# Operational Runbook ({a['name']})

> Detected automatically. Run `/agi-init` for an assistant-written version.

## Run locally

{_commands(a["run_commands"], "_No dev/start command detected._")}

## Build

{_commands(a["build_commands"], "_No build command detected._")}

## Verify

{_commands(a["test_commands"], "_No test command detected._")}

## Repository conventions

{f"- Default branch: `{git['branch']}`" if git["branch"] else "- Not a git repository."}
{f"- {convention}" if convention else ""}
{"- Deploys via container image (Dockerfile / compose present)." if a.get("containerized") else ""}

## Troubleshooting

_Record failure modes and their fixes here as they come up, and mirror the
durable ones into memory with `memory_record`._
"""


def render_structure_section(a: Dict[str, Any]) -> str:
    """The project-specific navigation block embedded in AGENTS.md / CLAUDE.md."""
    lines: List[str] = []
    if a["readme_summary"]:
        first = a["readme_summary"].splitlines()[0].strip()
        if first:
            lines.append(first)
    if a["languages"]:
        langs = ", ".join(f"{lang} ({n})" for lang, n in a["languages"][:4])
        lines.append(f"**Stack**: {langs}")
    if a["manifests"]:
        lines.append(f"**Manifests**: {', '.join('`' + m + '`' for m in a['manifests'])}")
    if a["source_dirs"]:
        dirs = ", ".join(f"`{d}/`" for d, _ in a["source_dirs"] if d != ".")
        if dirs:
            lines.append(f"**Source**: {dirs}")
    if a["test_commands"]:
        lines.append(f"**Verify**: `{a['test_commands'][0]}`")
    if a["run_commands"]:
        lines.append(f"**Run**: `{a['run_commands'][0]}`")
    return "\n\n".join(lines) if lines else "_No stack detected — add a package manifest, then run `/agi-init`._"


def main(argv: List[str] | None = None) -> None:
    """CLI: agi-memory analyze [PATH] [--json]"""
    import argparse

    parser = argparse.ArgumentParser(prog="agi-memory analyze",
                                     description="Report detected stack, commands, and layout for a repository.")
    parser.add_argument("path", nargs="?", default=".", help="Repository directory (default: current)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    facts = analyze_project(args.path)
    if args.json:
        print(json.dumps(facts, indent=2, default=str))
        return

    def line(label: str, value: str) -> None:
        print(f"  {label:<18} {value}")

    print(f"\nProject: {facts['name']}  ({facts['file_count']} files scanned)")
    line("Languages", ", ".join(f"{l} ({n})" for l, n in facts["languages"]) or "none detected")
    line("Manifests", ", ".join(facts["manifests"]) or "none detected")
    if facts.get("package_manager"):
        line("Package manager", facts["package_manager"])
    line("Source", ", ".join(f"{d}/" for d, _ in facts["source_dirs"] if d != ".") or "root only")
    line("Verify", " | ".join(facts["test_commands"]) or "not detected")
    line("Build", " | ".join(facts["build_commands"]) or "not detected")
    line("Run", " | ".join(facts["run_commands"]) or "not detected")
    line("Tests", ", ".join(facts["test_layout"]) or "none detected")
    line("Data model", ", ".join(facts["schema_surfaces"]) or "none detected")
    line("CI", ", ".join(facts["ci"]) or "none detected")
    if facts["git"]["branch"]:
        line("Branch", facts["git"]["branch"])
    print()


def demo() -> None:
    """Self-check: analysis of this repository must find its own real facts."""
    here = Path(__file__).resolve().parents[2]
    a = analyze_project(here)
    assert a["name"], "project name not detected"
    assert any(lang == "Python" for lang, _ in a["languages"]), a["languages"]
    assert "pyproject.toml" in a["manifests"], a["manifests"]
    assert a["test_layout"], "tests/ not detected in this repo"
    for render in (render_architecture, render_testing, render_data_model, render_runbook):
        out = render(a)
        assert a["name"] in out and len(out) > 100, render.__name__
    assert "Python" in render_structure_section(a)
    print(f"analyze_project OK: {a['name']} | {a['languages'][:3]} | tests={len(a['test_layout'])}")


if __name__ == "__main__":
    import sys
    if "--self-check" in sys.argv:
        demo()
    else:
        main()
