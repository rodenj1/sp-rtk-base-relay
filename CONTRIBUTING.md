# Contributing to sp-rtk-base-relay

Thanks for your interest in contributing!  This document covers the local
development workflow — environment setup, pre-commit hooks, commit-message
style, and how to run the test/lint gates that CI enforces.

## Quickstart

```bash
git clone https://github.com/rodenj1/sp-rtk-base-relay.git
cd sp-rtk-base-relay

# Install dev environment (Python venv via uv, dev dependencies, pre-commit hooks).
# Requires uv: https://docs.astral.sh/uv/
./tools/install-dev.sh
```

`tools/install-dev.sh` runs `uv sync --all-extras` and, when a `.git`
directory is present, installs the project's pre-commit hooks
(`pre-commit`, `commit-msg`, and `pre-push` stages).

> **Note**: `tools/install.sh` (without the `-dev`) is the **production
> systemd installer** that creates a system user and registers the
> service.  Contributors should use `tools/install-dev.sh`.

If you prefer to wire the hooks manually:

```bash
uv sync --all-extras
uv run pre-commit install \
    --install-hooks \
    --hook-type pre-commit \
    --hook-type commit-msg \
    --hook-type pre-push
```

## Pre-commit pipeline

Hooks run in three stages, fastest-first.  The full configuration lives
in [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

### `pre-commit` (every `git commit`, fast — target <5 s)

- **pre-commit-hooks**: trailing whitespace, EOF newline, merge-conflict
  markers, YAML/TOML syntax, files >500 KB, line-ending normalisation,
  case-insensitive name collisions.
- **ruff**: lint with `--fix` (auto-corrects) and `ruff format`.
- **gitleaks**: secret diff scan.  Custom rules in
  [`.gitleaks.toml`](.gitleaks.toml) explicitly forbid the six identifier
  strings that were scrubbed from history on May 20, 2026 — they must
  never re-enter the repo, even as docstring examples.

### `commit-msg` (every `git commit`, validates the message)

- **commitizen** enforces [Conventional Commits 1.0.0]
  (https://www.conventionalcommits.org/en/v1.0.0/).
  See **Commit Message Format** below for the full rule set.

### `pre-push` (once before `git push`, slow OK)

- **mypy** (strict mode, `src/` only).
- **pyright** (strict mode, `src/` only).
- **pytest** (full unit suite at `tests/unit/`, with `--no-cov` so the
  70 % coverage gate from `pyproject.toml` doesn't apply at push time;
  CI still enforces it on the matrix run).

### Bypassing hooks (emergencies only)

```bash
git commit --no-verify
git push   --no-verify
```

CI will still run the equivalent of `pre-commit run --all-files` plus the
full matrix tests, so `--no-verify` only buys you a deferred failure.

## Commit Message Format

We follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

### Allowed types

| Type       | Use for                                                |
|------------|--------------------------------------------------------|
| `feat`     | A new feature                                          |
| `fix`      | A bug fix                                              |
| `docs`     | Documentation only                                     |
| `style`    | Formatting/whitespace only (no logic change)           |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf`     | Performance improvement                                |
| `test`     | Adding or correcting tests                             |
| `build`    | Build system or external dependencies                  |
| `ci`       | CI configuration files and scripts                     |
| `chore`    | Other changes that don't modify src or test files      |
| `revert`   | Reverts a previous commit                              |
| `release`  | Version bump / release publish                         |
| `security` | Security-sensitive change (scrub, dependency CVE, etc.)|

### Scope (optional, free-form)

Use a short lowercase identifier indicating the area touched, e.g.
`feat(engine):`, `fix(bluetooth):`, `ci(release):`, `docs(memory-bank):`.

### Subject line

- Max 72 characters.
- Imperative mood ("add", not "added"/"adds").
- No trailing period.
- Lowercase first letter after the colon.

### Examples

```
feat(engine): add hot-swap support for destinations
fix(bluetooth): handle DBus reconnect when adapter disappears
docs(release-process): document private-repo sigstore workaround
ci(pre-commit): add hooks for secrets, lint, tests, and commit-msg
release: bump 2.1.0 -> 2.1.1 + fix sigstore on private repos
security: scrub historical credentials from repo and rewrite history
```

### Breaking changes

Append `!` after type/scope and add a `BREAKING CHANGE:` footer:

```
feat(engine)!: rename RelayEngine.start to RelayEngine.start_async

BREAKING CHANGE: RelayEngine.start is now an async method; callers
must `await engine.start()`.  Synchronous callers should use the
new RelayEngine.start_blocking() helper.
```

### Use `cz commit` if you like a guided prompt

```bash
uv run cz commit
```

Commitizen will walk you through type/scope/subject/body/footer
interactively.  Optional — handwritten messages that pass the check
are perfectly fine.

## What CI enforces

The `.github/workflows/ci.yml` pipeline runs:

1. **pre-commit** — `pre-commit run --all-files`, catches `--no-verify`
   bypasses.
2. **lint** — ruff check, ruff format check, mypy strict, pyright strict,
   pylint (advisory).
3. **test** — pytest matrix on Python 3.10 / 3.11 / 3.12 / 3.13 with
   coverage; uploads to Codecov.
4. **build** — `uv build` + artifact upload.

A green CI run is required to merge into `main`.

## Releases

Releases are cut by:

1. Bumping `version` in `pyproject.toml` and `src/sp_rtk_base_relay/__init__.py`.
2. Updating `uv.lock` (`uv lock`).
3. Pushing a `vX.Y.Z` tag and creating a GitHub Release.

The `.github/workflows/release.yml` workflow then verifies the tag matches
`pyproject.toml`, re-runs lint + tests + build, publishes to PyPI via
Trusted Publishing (OIDC), and attaches sigstore-signed artifacts to the
Release.  Full runbook in [`docs/release-process.md`](docs/release-process.md).

Optional: use commitizen to automate the bump + changelog:

```bash
uv run cz bump
```

This reads `[tool.commitizen]` in `pyproject.toml`, computes the next
SemVer version from your commit history (`feat:` → minor, `fix:` →
patch, `BREAKING CHANGE` → major), updates both version files, writes
`CHANGELOG.md`, commits, and tags.  You then `git push --follow-tags`
and create the GitHub Release in the UI.
