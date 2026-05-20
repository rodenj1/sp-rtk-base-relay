#!/bin/bash
# Developer-environment bootstrap for sp-rtk-base-relay.
#
# Idempotent — safe to re-run.  Does NOT touch system services; that is
# tools/install.sh's job.  See CONTRIBUTING.md for the full workflow.
#
# Steps:
#   1. Sync the uv-managed venv with --all-extras (matches CI).
#   2. Install pre-commit hooks (pre-commit, commit-msg, pre-push stages)
#      when the working tree is a git checkout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { printf "${GREEN}[INFO]${NC}  %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
error() { printf "${RED}[ERROR]${NC} %s\n" "$1" >&2; }

# 1. uv must be available.
if ! command -v uv >/dev/null 2>&1; then
    error "uv not found.  Install from https://docs.astral.sh/uv/ and re-run."
    exit 1
fi
info "uv detected: $(uv --version)"

# 2. Sync the dev environment.
info "Syncing dev environment with --all-extras (this can take a minute on first run)…"
uv sync --all-extras

# 3. Install pre-commit hooks only if this is a git checkout — keeps the
#    script useful when someone runs it from an unzipped source archive.
if [[ -d "$REPO_ROOT/.git" ]]; then
    info "Installing pre-commit hooks (pre-commit, commit-msg, pre-push)…"
    uv run pre-commit install \
        --install-hooks \
        --hook-type pre-commit \
        --hook-type commit-msg \
        --hook-type pre-push
    info "Pre-commit hooks installed."
else
    warn "Not a git checkout — skipping pre-commit hook install."
fi

# 4. Quick sanity check — list installed hooks.
if [[ -d "$REPO_ROOT/.git" ]]; then
    echo ""
    info "Installed hook scripts:"
    ls -1 "$REPO_ROOT/.git/hooks/" | grep -vE '\.sample$' | sed 's/^/  - /' || true
fi

echo ""
info "Dev environment ready."
echo ""
echo "Try it out:"
echo "  uv run pytest tests/unit -q          # full unit suite"
echo "  uv run ruff check .                  # lint"
echo "  uv run pre-commit run --all-files    # run every hook against every file"
echo "  uv run cz commit                     # guided Conventional Commit prompt"
echo ""
echo "See CONTRIBUTING.md for the full workflow."
