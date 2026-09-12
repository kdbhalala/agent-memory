"""The `/agi-init` slash command, emitted in each assistant's own command format.

One canonical playbook (INIT_PLAYBOOK) is rendered into every format a coding
assistant recognizes, so `/agi-init` exists in whichever tool the developer
opens. The assistant — not a regex — reads the repository and writes the
project's rules/ and context/ files, because judgement about what a codebase
actually IS beats file-extension counting.

Formats verified against each tool's own docs (September 2026):

  Claude Code   .claude/commands/<name>.md          MD + YAML frontmatter, $ARGUMENTS
  Cursor        .cursor/commands/<name>.md          MD
  OpenCode      .opencode/commands/<name>.md        MD + YAML frontmatter, $ARGUMENTS
  Codex         .codex/prompts/<name>.md            MD + YAML frontmatter, $ARGUMENTS
  Gemini/agy    .gemini/commands/<name>.toml        TOML: description + prompt, {{args}}
  Windsurf      .windsurf/workflows/<name>.md       MD workflow, invoked /<name>
  Cline         .clinerules/workflows/<name>.md     MD workflow, invoked /<name>.md
  Roo Code      .roo/commands/<name>.md             MD
  Hermes        .hermes/skills/<name>/SKILL.md      SKILL.md + YAML frontmatter

Zero external dependencies (stdlib only).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

COMMAND_NAME = "agi-init"
DESCRIPTION = "Analyze this repository and write its agent-memory rules/ and context/ files."

# --- The playbook -------------------------------------------------------------
# Written for the assistant executing it. It says what to inspect, what to write,
# and — most importantly — what NOT to do: no placeholder prose, no invented facts.

INIT_PLAYBOOK = """\
Initialize this repository for agent-memory. You are writing the files that every
future assistant session in this repo will read first, so accuracy matters more
than coverage.

## 1. Analyze the repository

Optional head start — deterministic facts, no tokens spent rediscovering them:

```bash
agi-memory analyze --json
```

It reports languages, manifests, package manager, build/test/run commands, test
layout, schema surfaces, and CI. Treat it as a starting point, not the answer:
it reads file names, you read code.

Then investigate what only reading can tell you:

- What this project **does**, in one paragraph, from the README and the entrypoints.
- The real architecture: module boundaries, layers, the direction dependencies flow.
- Invariants a newcomer would violate — things true in the code that no file states.
- How data is modeled and where it is persisted.
- How the project is actually run, built, and verified. Prefer commands you found
  in a manifest, Makefile, or CI workflow over commands you assume work.
- Conventions visible in the git history and the existing code (commit style,
  error handling, test style, naming).

## 2. Write the files

Write these, creating directories as needed. Skip a file that already exists
unless the user asked you to overwrite it — say which ones you skipped.

- `rules/architecture.md` — what the project is, its components and boundaries,
  and its invariants. This is the file that prevents architectural mistakes.
- `rules/testing-qa.md` — the exact verification commands, where tests live,
  what CI runs, and the standard to hold.
- `rules/memory-discipline.md` — when to call `memory_recall` / `memory_record`
  for this project specifically.
- `context/data-model.md` — entities, schemas, storage, ownership boundaries.
- `context/runbook.md` — run, build, verify, deploy, and known failure modes.
- `AGENTS.md` and `CLAUDE.md` — a short executive index: what the project is,
  the stack, where code lives, the verify command, and links to the files above.
  Keep both identical and under roughly 60 lines; they are loaded every session,
  so every line costs context in perpetuity.

## 3. Rules for the content

- Every claim must be grounded in something you read. No invented endpoints,
  no aspirational architecture, no "best practices" the project does not follow.
- Where you could not determine something, write one line naming what is missing
  instead of filling the space with generic advice. An honest gap is useful; a
  plausible-sounding placeholder is a trap for the next session.
- Prefer specifics: real paths, real commands, real module names.
- No restating what the code already makes obvious.

## 4. Record what you learned

Persist the durable conclusions so they survive this session:

- `memory_record(text, title, project="<project>", category="architecture")` for
  each significant architectural finding.
- `memory_pin(key, content, category="architecture", project="<project>")` for
  invariants that must never be violated.

## 5. Report

List the files you created, the files you skipped, and anything you could not
determine and want the user to fill in.
"""

ARGUMENT_NOTE = """
If arguments were provided, treat them as a focus or a constraint for this run
(for example a subdirectory to analyze, or "only refresh testing-qa.md").
"""


# --- Per-format renderers -----------------------------------------------------

def _md_frontmatter(body: str, args_token: str = "$ARGUMENTS") -> str:
    return (
        "---\n"
        f"description: {DESCRIPTION}\n"
        "argument-hint: [optional focus, e.g. a subdirectory]\n"
        "---\n\n"
        f"{body}\n{ARGUMENT_NOTE}\nArguments: {args_token}\n"
    )


def _md_plain(body: str, args_token: str = "$ARGUMENTS") -> str:
    return (
        f"# /{COMMAND_NAME}\n\n{DESCRIPTION}\n\n{body}\n{ARGUMENT_NOTE}\n"
        f"Arguments: {args_token}\n"
    )


def _toml(body: str) -> str:
    """Gemini CLI / Antigravity. TOML with a multi-line basic string, so any
    embedded double quote or backslash must be escaped."""
    escaped = body.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return (
        f'description = "{DESCRIPTION}"\n\n'
        f'prompt = """\n{escaped}\n{ARGUMENT_NOTE}\nArguments: {{{{args}}}}\n"""\n'
    )


def _workflow(body: str) -> str:
    """Windsurf / Cline workflow: title, description, then the steps."""
    return (
        f"---\ndescription: {DESCRIPTION}\n---\n\n"
        f"# {COMMAND_NAME}\n\n{body}\n{ARGUMENT_NOTE}\n"
    )


def _skill(body: str) -> str:
    """Hermes / Codex skill: SKILL.md with name + description frontmatter."""
    return (
        "---\n"
        f"name: {COMMAND_NAME}\n"
        f"description: {DESCRIPTION} Use when setting up agent-memory in a repository, "
        "or when the project's rules/ and context/ files are missing or stale.\n"
        "---\n\n"
        f"# {COMMAND_NAME}\n\n{body}\n"
    )


# (tool label, relative path from project root, renderer)
PROJECT_TARGETS: List[Tuple[str, str, str]] = [
    ("Claude Code", f".claude/commands/{COMMAND_NAME}.md", "md_frontmatter"),
    ("Cursor", f".cursor/commands/{COMMAND_NAME}.md", "md_plain"),
    ("OpenCode", f".opencode/commands/{COMMAND_NAME}.md", "md_frontmatter"),
    ("OpenAI Codex", f".codex/prompts/{COMMAND_NAME}.md", "md_frontmatter"),
    ("Antigravity / Gemini", f".gemini/commands/{COMMAND_NAME}.toml", "toml"),
    ("Windsurf", f".windsurf/workflows/{COMMAND_NAME}.md", "workflow"),
    ("Cline", f".clinerules/workflows/{COMMAND_NAME}.md", "workflow"),
    ("Roo Code", f".roo/commands/{COMMAND_NAME}.md", "md_plain"),
    ("Hermes Agent", f".hermes/skills/{COMMAND_NAME}/SKILL.md", "skill"),
]

RENDERERS = {
    "md_frontmatter": _md_frontmatter,
    "md_plain": _md_plain,
    "toml": _toml,
    "workflow": _workflow,
    "skill": _skill,
}


def render(fmt: str, project: str | None = None) -> str:
    body = INIT_PLAYBOOK.replace("<project>", project) if project else INIT_PLAYBOOK
    return RENDERERS[fmt](body).strip() + "\n"


def user_scope_targets() -> List[Tuple[str, Path, str]]:
    """(tool label, absolute path, format) for user-scope command locations."""
    home = Path.home()
    return [
        ("Claude Code", home / ".claude" / "commands" / f"{COMMAND_NAME}.md", "md_frontmatter"),
        ("Cursor", home / ".cursor" / "commands" / f"{COMMAND_NAME}.md", "md_plain"),
        ("OpenCode", home / ".config" / "opencode" / "commands" / f"{COMMAND_NAME}.md", "md_frontmatter"),
        ("OpenAI Codex", home / ".codex" / "prompts" / f"{COMMAND_NAME}.md", "md_frontmatter"),
        ("Antigravity / Gemini", home / ".gemini" / "commands" / f"{COMMAND_NAME}.toml", "toml"),
        ("Windsurf", home / ".codeium" / "windsurf" / "global_workflows" / f"{COMMAND_NAME}.md", "workflow"),
        ("Cline", home / "Documents" / "Cline" / "Workflows" / f"{COMMAND_NAME}.md", "workflow"),
        ("Hermes Agent", home / ".hermes" / "skills" / COMMAND_NAME / "SKILL.md", "skill"),
    ]


def install_init_command(target_dir: Path | str = ".", project: str | None = None,
                         scope: str = "project", force: bool = False) -> Dict[str, str]:
    """Write /agi-init in every assistant's command format. Returns path -> status."""
    results: Dict[str, str] = {}

    if scope == "user":
        entries = [(label, path, fmt) for label, path, fmt in user_scope_targets()]
    else:
        root = Path(target_dir).resolve()
        entries = [(label, root / rel, fmt) for label, rel, fmt in PROJECT_TARGETS]

    for label, path, fmt in entries:
        try:
            if path.exists() and not force:
                results[str(path)] = f"skipped (exists) — {label}"
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render(fmt, project), encoding="utf-8")
            results[str(path)] = f"written — {label}"
        except OSError as e:
            results[str(path)] = f"failed ({e}) — {label}"
    return results


def demo() -> None:
    """Self-check: every format renders, and the TOML stays parseable."""
    try:
        import tomllib  # 3.11+; parse check skipped on 3.10
    except ModuleNotFoundError:
        tomllib = None

    for fmt in RENDERERS:
        out = render(fmt, project="demo-proj")
        assert "rules/architecture.md" in out, fmt
        assert "<project>" not in out, fmt
        assert len(out) > 500, fmt

    if tomllib is not None:
        parsed = tomllib.loads(render("toml", "demo-proj"))
        assert parsed["description"] == DESCRIPTION
        assert "rules/architecture.md" in parsed["prompt"]
        assert "{{args}}" in parsed["prompt"]

    for fmt in ("md_frontmatter", "workflow", "skill"):
        assert render(fmt).startswith("---\n"), fmt

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        res = install_init_command(tmp, project="demo-proj")
        assert len(res) == len(PROJECT_TARGETS)
        assert all(v.startswith("written") for v in res.values()), res
        again = install_init_command(tmp, project="demo-proj")
        assert all(v.startswith("skipped") for v in again.values()), again
        forced = install_init_command(tmp, project="demo-proj", force=True)
        assert all(v.startswith("written") for v in forced.values()), forced
    print(f"init_command OK: {len(PROJECT_TARGETS)} formats"
          f"{', TOML parses' if tomllib else ' (TOML parse skipped: needs 3.11+)'}")


if __name__ == "__main__":
    demo()
