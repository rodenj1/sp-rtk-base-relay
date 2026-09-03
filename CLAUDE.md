# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SP-Base-Relay (v2.1) is a Python service **and embeddable library** that relays RTCM correction data from a single GPS input (TCP / serial / Bluetooth) to multiple output destinations simultaneously (Sure-Path, NTRIP v1.0/v2.0, TCP rebroadcast). Each destination runs in its own thread with an independent queue so a failure in one cannot affect the others.

## Environment

- Python 3.10+ (modern type hints: `dict`, `list`, `X | None` — never `typing.Dict`/`List`/`Optional`)
- `uv` for package management — always invoke tools with `uv run ...`
- Type checkers: `pyright` (strict mode, canonical per `.clinerules/Development Rules.md`) + `mypy` (strict, secondary). The Bluetooth modules (`core/bluetooth_manager`, `core/input_sources/bluetooth_input`) relax mypy strict because `dbus-fast` uses dynamic `__getattr__` on `ProxyInterface` that mypy can't model — pyright handles it.

## Common commands

```bash
# One-shot dev setup (venv + dev deps + pre-commit hooks)
./tools/install-dev.sh

# Run the service in foreground
uv run sp-rtk-base-relay --config config.yaml --foreground

# Validate / generate config
uv run sp-rtk-base-relay --config config.yaml --validate
uv run sp-rtk-base-relay --generate-config > config.yaml

# Tests
uv run pytest                                            # unit suite (default)
uv run pytest --cov=src/sp_rtk_base_relay --cov-report=html
uv run pytest tests/integration --no-cov                 # hardware integration
uv run pytest tests/unit/test_broadcast_hub.py -q        # single file

# Type-check / lint
uv run pyright src/
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Full pre-commit pipeline
uv run pre-commit run --all-files
```

Default `pytest` enforces `--cov-fail-under=70` and excludes `integration/` and `manual/` via `norecursedirs`. Coverage in practice runs ~88% (1,143 tests).

## Architecture

```
[Input Source] ──▶ [BroadcastHub] ──┬──▶ [SurePath Thread]   ──▶ Sure-Path server
  TCP / Serial       fan-out +      │──▶ [NTRIP Thread]      ──▶ RTK2go / Onocoy / rtkdirect
  / Bluetooth        per-dest filter│──▶ [TCP Srv Thread]    ──▶ LAN rover clients
                                    └──▶ Prometheus metrics (per-destination labels)
```

### Entry points: service vs. library

There are **two** ways to use this code:

1. **Service** (`src/sp_rtk_base_relay/main.py`) — `SPBaseRelayService` orchestrates everything: loads YAML config, builds input source + destinations + hub via factories, owns its own signal handlers, runs a 1 Hz health/metrics loop. This is the `sp-rtk-base-relay` CLI entry point.
2. **Library** (`src/sp_rtk_base_relay/engine.py`) — `RelayEngine` is the v2.1 embeddable façade. External apps (like `sp-rtk-base`) construct one programmatically, call `start([DestinationConfig, ...])`, `add_destination()` / `remove_destination()` while running, and read `get_status()` (typed `RelayStatus` snapshot). Subscribes to events via `subscribe_events()` → `EventSubscription`.

Both paths build on the same `BroadcastHub` + `DestinationFactory` + `InputSourceFactory` machinery in `core/`.

### Core components (`src/sp_rtk_base_relay/core/`)

- `broadcast_hub.py` — the heart of v2. Reads from the input source, parses RTCM frames, fans out filtered copies to each destination's queue, owns reconnection. Each destination has an independent queue so backpressure / errors in one don't propagate.
- `message_filter.py` — per-destination RTCM filtering: `pass_all` (zero overhead), `allowlist`, `blocklist` by message ID.
- `destinations/` — `base_destination.py` is the ABC (owns its queue + stats + thread). `destination_factory.py` is a registry-based factory; `surepath_destination.py`, `ntrip_destination.py`, `tcp_server_destination.py` are the three built-in destination types. Importing `core.destinations` registers all builders as a side effect (see `main.py` and `engine.py` — the `_destinations_registry` import is load-bearing, `# pyright: ignore[reportUnusedImport]`).
- `input_sources/` — `base_input.py` ABC + `tcp_input.py`, `serial_input.py`, `bluetooth_input.py`. Factory in `input_factory.py`.
- `bluetooth_manager.py` — self-healing BlueZ recovery via `dbus-fast`. Reconnects without manual intervention when the adapter or device disappears.
- `connection_states.py` — connection state machine used by destinations.
- `rtcm_decoder.py` (top-level) — RTCM 3.x frame parser; called by `BroadcastHub` to slice the byte stream into frames.

### Configuration

`config.py` defines pydantic-validated dataclasses: `Config` → `InputConfig`, `DestinationConfig[]`, `MetricsConfig`, `LoggingConfig`. Destinations are a **list** in v2 — v1's `server:` single-destination key triggers an explicit migration error message (see `ConfigManager` in `config.py`).

### v1 → v2 breaking change

Anywhere you see `server:`-shaped logic, it's v1 legacy and should error out with a migration message. v2's invariant is `destinations: [...]` always, even for a single destination.

### Metrics

`metrics.py` — `MetricsCollector` runs the Prometheus HTTP server (configurable port, default 8080) and exposes per-destination counters/gauges with `{destination="..."}` labels. Updated once per second from the service's main loop via `update_all(destinations, hub, input_connected, input_source, engine_running)`.

## Hard rules

- **Never reintroduce the six scrubbed identifier strings** — not in code, not in tests, not in docstrings, not in comments, not in fixtures. They were removed from history on 2026-05-20 to make this repo safe for public release. `.gitleaks.toml` will block them at commit time, but assume the rule yourself first — the hook is a safety net, not the policy.
- **`destinations: [...]` is the only valid v2 config shape.** Any code that sees a `server:` key must error with the v1 migration message (handled by `ConfigManager` in `config.py`). Do not add accidental v1 fallbacks.
- **The `_destinations_registry` import in `main.py` / `engine.py` is load-bearing** — it has the `# pyright: ignore[reportUnusedImport]` on it precisely because removing it (or auto-formatting it away) breaks the destination factory registry.

### Deeper context

The Cline `memory-bank/` and `docs/` together cover everything the surface guide doesn't. Read on demand, not by default.

- `memory-bank/activeContext.md` — current release / patch context (last update tracked v2.1.1 → v2.1.2 work).
- `memory-bank/progress.md` — release-by-release lessons; **grep first** for a topic before reading top-to-bottom.
- `docs/v2.1-architecture-plan.md` — the embeddable-facade design (shipped; retained for design rationale).
- `docs/relay-engine-api-spec.md` — full `RelayEngine` API reference; matches `engine.py`.
- `docs/release-process.md` — tag → CI → PyPI Trusted Publishing flow.

## Conventions

- Conventional Commits 1.0.0 enforced by commitizen (`commit-msg` hook). Allowed types: `feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert, release, security`. See `CONTRIBUTING.md` and `[tool.commitizen.customize]` in `pyproject.toml`.
- Pre-commit pipeline runs in three stages: `pre-commit` (ruff + gitleaks, <5s), `commit-msg` (commitizen), `pre-push` (mypy strict + pyright strict + full unit suite with `--no-cov`).
- Releases: bump `version` in `pyproject.toml` + `src/sp_rtk_base_relay/__init__.py`, run `uv lock`, push a `vX.Y.Z` tag, publish a GitHub Release. `.github/workflows/release.yml` re-runs tests + builds + publishes to PyPI via Trusted Publishing (OIDC). See `docs/release-process.md`.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical five labels used as-is: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
