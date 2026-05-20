# Active Context

## Current Work Focus

**Primary Objective**: SP-RTK-Base-Relay v2.1 COMPLETE + project renamed + CI added + v2.1 observability expansion + new Grafana dashboard + PyPI release pipeline + **history scrub for public release (May 20, 2026)** → Next: flip repo to public, draft GitHub Release `v2.1.0` to trigger first PyPI publish, sp-base integration

### History Scrub for Public Release (May 20, 2026)

Before going public the codebase + history were swept for live secrets/identifiers. Six tokens were replaced everywhere they appeared:

| Original | Replacement | Notes |
|---|---|---|
| `dae5` | `your_password` | RTCM caster password (rotated on the caster before the rewrite). Replaced with `\bdae5\b` regex so the coincidental `8ca8dae51…` hex inside `uv.lock`'s pytest_asyncio wheel SHA-256 is left intact. |
| `RODEN01` | `your_mountpoint` | RTCM mountpoint / username. |
| `91.186.9.136` | `rtcm.example.com` | RTCM caster IP. |
| `98:D3:51:FE:FE:E4` | `00:11:22:33:44:55` | Bluetooth GPS MAC (colon form). |
| `98_D3_51_FE_FE_E4` | `00_11_22_33_44_55` | Same MAC as it appears inside BlueZ DBus paths like `/org/bluez/hci0/dev_98_D3_51_FE_FE_E4` — the leading `\b` was dropped from this pattern because `_` is a regex word char, so the preceding `_` in `dev_98` would have suppressed the match. |
| `RTK_BASE_ROD` | `RTK_GPS_BASE` | Bluetooth device name. |

Sequence (all on `main`, May 20, 2026):

1. **Pre-flight backups** — local mirror clone at `/opt/development/sp-rtk-base-relay-backup.git`, annotated tag `v2.1.0-pre-scrub`, branch `pre-history-scrub-backup` pushed to origin, live config saved to `/opt/development/sp-rtk-base-relay.local-config.bak.yaml`.
2. **Current-tree scrub** (commit `4cc62da`):
   - `git mv config.bluetooth-gps.yaml config.bluetooth-gps.example.yaml`, then redacted.
   - `config.bluetooth-gps.yaml` added to `.gitignore` so the live file stays untracked.
   - Bulk `sed -i` across 25 files (config templates, docs, 3 source modules, 9 test files, 4 Bluetooth tool scripts, the systemd unit).
   - `uv.lock` was reverted from `HEAD` because the bulk sed had clobbered the pytest_asyncio hex hash (hex-collision).
   - Full gate green: `1143 tests pass`, ruff lint + format + mypy strict + pyright strict all clean.
3. **History rewrite** — `git filter-repo --replace-text /tmp/secrets-scrub.txt --force` rewrote 86 commits across all refs in ~1.5 s. A second filter-repo pass was needed for the `98_D3_51_FE_FE_E4` BlueZ form (the leading `\b` issue above). All five real-secret tokens now scrub-clean across every reachable ref locally.
4. **Force-push** — `main` `87f94e1` → `5bd8a89`, `v2.1.0` tag `87f94e1` → `3c1c3c7`. Deleted the `v2.1.0-pre-scrub` tag and `pre-history-scrub-backup` branch from origin.
5. **Live config restored** — `config.bluetooth-gps.yaml` copied back from the backup; the file holds the *pre-rotation* password and must be hand-edited to the new credential before restarting the service.

**Known residual exposure (accepted)**: GitHub's `refs/pull/1/head … refs/pull/6/head` PR refs still point at the original pre-scrub commits and therefore continue to serve the real credentials to anyone who fetches those refs directly. PR refs are server-managed; `git push --delete` cannot remove them. Mitigations in place: caster password rotated (the `dae5` value is invalidated), MAC + Bluetooth device name are low-value identifiers, PR refs are an obscure access path. We're accepting this residual exposure and proceeding to public.

### PyPI Release Pipeline (May 20, 2026)

`.github/workflows/release.yml` added — fires on `release: published`, gated on tag↔`pyproject.toml` version match, re-runs full lint + matrix tests (3.10/3.11/3.12/3.13), builds sdist+wheel, `twine check --strict`, publishes via **Trusted Publishing (OIDC)** to the `pypi` GitHub environment (no token secrets), sigstore-signs the artifacts, and attaches `.tar.gz` / `.whl` / `.sigstore` bundles back to the GitHub Release.

Companion changes:
- `pyproject.toml`: Development Status `3 - Alpha` → `4 - Beta`.
- `docs/release-process.md`: full runbook covering the one-time PyPI pending-publisher registration, `pypi` environment creation, per-release checklist, and troubleshooting (tag mismatch, pre-release rejection, transient PyPI errors, re-run via `workflow_dispatch`).
- `README.md`: added Release workflow badge + PyPI version / Python-versions / monthly-downloads badges + "Releasing" section pointing at the runbook.
- Memory bank updated.

User must complete two manual one-time steps before the first release runs:
1. PyPI → Your account → Publishing → **Add a pending publisher** for `sp-rtk-base-relay` with workflow `release.yml` and environment `pypi`.
2. GitHub repo Settings → Environments → create environment named `pypi` (no required reviewers needed unless desired).

Then drafting + publishing a GitHub Release for tag `v2.1.0` triggers the pipeline end-to-end (~5–8 min).

---



**Status**: v2.1 Phases 0–5 COMPLETE. Project renamed `sp-base-relay` → `sp-rtk-base-relay` on `main` (April 21, 2026, commit `f9c2a35`). GitHub Actions CI workflow added and **GREEN** on `main` (April 21, 2026, run 24759164665) — lint + matrix unit tests on Python 3.10/3.11/3.12/3.13 + build all passing. Phase 6 (cleanup) pending. sp-base integration next.

### Metrics v2.1 expansion + Grafana v2.1 dashboard (April 22, 2026)

Following the v2.1 architecture refactor (RelayEngine + EventBus + BroadcastHub), the metrics surface was widened to expose every new component. `MetricsCollector` now also publishes input-source, hub, event-bus, engine and per-destination metadata families — 23 new metrics total, additive over v2.0.

Added metrics (all under `sp_rtk_base_relay_*`):
- **Engine**: `engine_running_status`.
- **Input source**: `input_info{source_type}`, `input_connected_since_timestamp`, `input_bytes_received_total`, `input_messages_received_total`, `input_reconnect_attempts_total`, `input_reconnect_successes_total`.
- **Hub**: `hub_bytes_received_total`, `hub_chunks_received_total`, `hub_chunks_distributed_total`, `hub_frames_parsed_total`, `hub_no_data_warnings_total`, `hub_registered_destinations_count`.
- **Event bus**: `events_emitted_total{event_type}`, `events_dropped_total`, `event_subscribers_count`, `event_ring_buffer_depth`.
- **Destination metadata**: `dest_info{destination,type,filter_mode}`, `dest_enabled`, `dest_running`, `dest_connected_since_timestamp`, `dest_last_send_timestamp`, `dest_connection_failures_total`.

Wiring:
- `metrics.py` — extended `MetricsCollector.update_all()` signature with `input_source`, `event_bus`, `engine_running` kwargs; added push-model `record_event(event_type)`. Delta-based counter semantics preserved (test_metrics 100 % line coverage).
- `events.py` — `EventBus` takes optional `metrics_collector`; every published event bumps `events_emitted_total{event_type}`. Drop counter derived live in `update_all()` from `EventBus.total_events_dropped`.
- `engine.py` — `RelayEngine(metrics_collector=...)` forwards the collector to its EventBus and exposes `update_metrics()` helper that calls `update_all()` with the hub/input/event-bus/engine refs.
- `main.py` — existing `_update_metrics()` now passes `input_source` and `engine_running` through to the collector so input-source + engine metrics populate even when running via main.py (pre-RelayEngine wiring).
- Old dashboard archived to `templates/archive/grafana_dashboard_v1.json`.

Grafana v2.1 dashboard (`templates/grafana_dashboard.json`):
- schemaVersion 41 (Grafana 11.x), UID `sp-rtk-base-relay-v2-1`, 27 panels across 8 rows.
- Rows: Service Overview · Hub Throughput · Per-Destination Health · Per-Destination Throughput · Drops/Filters/Queues · Connection Reliability · TCP-Server Destinations · Event Bus.
- Template variables: `DS_PROMETHEUS` (datasource), `destination` + `dest_type` (multi-select) using `label_values(sp_rtk_base_relay_dest_info, ...)`.
- Joined destination-health table uses Grafana's `joinByField` transformation to merge five queries keyed on the `destination` label.

Docs: `docs/metrics-guide.md` updated to **v2.1** with five new metric tables and a rewritten Grafana section (layout, variables, import steps).

Verification: `uv run pytest tests/unit/ -q` → **1143 tests pass, 89.78 % coverage**. `metrics.py` 100 %, `engine.py` 99 %, `events.py` 100 %. Dashboard JSON validates (`json.load`) as schemaVersion 41 / 27 panels / 3 vars.

### CI Added (April 21, 2026)

`.github/workflows/ci.yml` — 3 jobs:
- **lint** (py3.12): ruff check + ruff format --check + mypy + pyright (blocking); pylint (advisory).
- **test** (matrix: 3.10/3.11/3.12/3.13, `fail-fast: false`): `uv sync --locked --all-extras` → `uv run pytest` with XML/HTML/JUnit coverage; uploads artifacts. Coverage badge updates on push to main via Gist + shields.io (gated on `GIST_SECRET`).
- **build** (py3.12): `uv build` → dist artifact.

Triggers: push to main, PRs to main, manual dispatch. `concurrency.cancel-in-progress: true`. All actions pinned to full SHAs.

Supporting changes (commit `d411db9`):
- `pyproject.toml`: added py3.13 classifier, removed `black`, added `ruff>=0.6.0` + `[tool.ruff]` config (line-length 88, py310 target, E/W/F/I/B/UP/N/SIM/RUF rule sets, legacy baseline `ignore` list).
- Auto-applied `ruff check --fix` + `ruff format` across 74 files; 1,117 tests still pass, coverage 89.35%.
- `docs/ci-setup.md` — workflow overview + one-time Gist/PAT setup for coverage badge.
- `README.md` — CI + coverage + ruff badges added; title updated to `SP-RTK-Base-Relay`.

Follow-up fix (commit `d6fb14f`) — resolved pre-existing mypy/pyright strict errors surfaced by the new CI:
- Added mypy module override for `bluetooth_manager` + `bluetooth_input` (dbus-fast `ProxyInterface` uses runtime `__getattr__` for `call_*` methods — mypy cannot follow; pyright unaffected).
- Cast `ProxyInterface` → `Any` at two pyright errors in `bluetooth_manager.py` (`call_set`/`call_get`) with explanatory comments.
- Annotated `HeartbeatMonitor.socket` attribute so mypy no longer marks defensive None-check as unreachable.
- Simplified redundant poison-pill check in `TcpServerDestination._broadcast_loop`.
- Fixed `repr` of non-utf8 auth response bytes (`{response!r}`).
- Added `dbus_fast` to mypy `ignore_missing_imports`.
- Misc pyright-strict annotation clean-ups in `config.py`, `logger.py`, `serial_input.py`, `tcp_input.py`, `rtcm_client.py`.
- All local checks clean: ruff + ruff format + mypy strict + pyright strict; 1,117 tests pass at 89.34% coverage. CI green.

Node.js 24 upgrade (commit `bbb9e98`) — addressed GitHub's Node.js 20 deprecation warnings surfaced on the first green run:
- `actions/checkout` v5.0.0 → **v6.0.2** (SHA `de0fac2e…`).
- `actions/upload-artifact` v4.6.2 → **v6.0.0** (SHA `b7c566a7…`) — v6 is the first release that defaults to Node 24 and requires Actions runner ≥ 2.327.1.
- `schneegans/dynamic-badges-action` v1.7.0 → **v1.8.0** (SHA `0e50b8ba…`) — (subsequently removed when switching to Codecov).
- `astral-sh/setup-uv@v8.1.0` already runs on Node 24; unchanged.
- Verified clean via run **24759388902** — success with no deprecation warnings.

Coverage badge migrated to **Codecov**, iterated through three configurations before settling on token auth:

1. **Initial (OIDC)** — commit `c4182cd` switched to `codecov/codecov-action@v6.0.0` with `use_oidc: true` + separate `codecov/test-results-action@v1.2.1`.  Workflow ran green but badge showed "unknown" and `app.codecov.io/gh/rodenj1/sp-rtk-base-relay` returned 404.
2. **Consolidation** — commit `59b904b` cleared the `codecov/test-results-action` deprecation annotation by calling `codecov-action` twice instead (second invocation with `report_type: test_results`).  Run `24759889898` green; badge still broken.
3. **Final (token auth)** — commit `f1926f6`.  Root cause: `sp-rtk-base-relay` is a **private repo**, and Codecov's OIDC tokenless upload is public-repo-only.  Every OIDC upload was being rejected with HTTP 500 by `ingest.codecov.io` (visible only via `gh run view --log` — the action itself was silent because `fail_ci_if_error: false`).  Run `24760379477` on `f1926f6` shows the fix working:
   ```
   info -- Your upload is now processing. When finished, results will be
   available at: https://app.codecov.io/github/rodenj1/sp-rtk-base-relay/
                 commit/f1926f6f137b440089f9c9beaf0cd295f0f666ed
   info -- Process Upload complete
   ```

Final configuration:
- `codecov/codecov-action@v6.0.0` (SHA `57e3a136…`) invoked twice (coverage + test-results), both with `token: ${{ secrets.CODECOV_TOKEN }}`.
- `CODECOV_TOKEN` repository secret set via `gh secret set CODECOV_TOKEN` (upload token from app.codecov.io onboarding page).  Note: this UUID was exposed in chat history during setup and should be **rotated via Codecov → Settings → Coverage** when convenient.
- `id-token: write` permission removed from the `test` job (no longer needed).
- README badge uses the separate read-only **badge token** `T5XTVO92KQ` as `?token=...` query param — safe to commit, grants read-only access to the badge SVG for this single branch only.
- `docs/ci-setup.md` fully rewritten to document the private-repo token flow (upload token vs badge token), with a short section on how to swap back to OIDC if the repo ever goes public.

**Codecov setup complete.** Badge renders live coverage percentage from latest successful upload; dashboard at <https://app.codecov.io/github/rodenj1/sp-rtk-base-relay> shows commit-by-commit trend, flaky-test analytics, and PR coverage comments.

**Previous**: v2.1 merged to `main` via PR #5 → PR #6 (`origin/main` at `313f951`). Prior v2.0 work at commit 8f4f79a.
**Branch**: `main` (all v2.1 work merged; working directly on main going forward)

### Final Rename Closeout (May 14, 2026)

Closed out the last cosmetic loose ends from the April 21 rename:

- **Local working directory** renamed: `/opt/development/sp-base-relay` → `/opt/development/sp-rtk-base-relay` (`mv` from `/tmp`, no in-tree path references existed so nothing else to update).
- **`.venv` rebuilt** with `uv sync --all-extras` so absolute paths in `pyvenv.cfg` + console-script shebangs point at the new directory. Resolves the project as `sp-rtk-base-relay==2.1.0` from the new path.
- **Console script verified**: `uv run sp-rtk-base-relay --help` works from new dir; default config path now reads `/etc/sp-rtk-base-relay/config.yaml` (already correct since April).
- **Full test sweep** from new path: `uv run pytest tests/unit -q` → **1,143 passed, 89.69% coverage**.
- **Prometheus consumers**: confirmed no external scrapers; namespace `sp_rtk_base_relay_*` was already in place in `metrics.py` (line 121, default `namespace=` kwarg) and both `templates/grafana_dashboard.json` (current) and `templates/archive/grafana_dashboard_v1.json` (archived).
- **Host systemd**: `systemctl list-unit-files` shows no installed `sp-base-relay.service` or `sp-rtk-base-relay.service` — nothing to update on the host.
- **Stale VS Code/Cline workspace entry** (`{"/opt/development/sp-base-relay": …}` in Cline globalStorage) is purely cosmetic; reopening VS Code at the new path registers the new workspace automatically.

**The rename is now 100% complete** — code, package, console script, systemd unit name, GitHub repo, Prometheus namespace, Grafana dashboards, working directory, and venv all aligned on `sp-rtk-base-relay`.

### Rename Summary (April 21, 2026)

The project was renamed from `sp-base-relay` → `sp-rtk-base-relay` to more accurately reflect its purpose (providing RTCM corrections for RTK base stations) in preparation for public release. Commit `f9c2a35` on `main`.

Changes:
- Python package directory: `src/sp_base_relay/` → `src/sp_rtk_base_relay/` (`git mv`, history preserved)
- Console script: `sp-base-relay` → `sp-rtk-base-relay`
- systemd unit: `tools/systemd/sp-base-relay.service` → `sp-rtk-base-relay.service`
- `pyproject.toml`: `name`, `[project.scripts]`, `[project.urls]`, pytest `--cov=` path updated
- Global string replacement across 82 tracked text files (src/, tests/, docs/, memory-bank/, tools/, templates/, examples/, README, configs)
- `uv.lock` regenerated for `sp-rtk-base-relay==2.1.0`
- GitHub repo renamed via `gh repo rename`; `origin` remote updated to `https://github.com/rodenj1/sp-rtk-base-relay.git`
- All **1,117** unit tests pass, coverage **89.49%**
- Deployment note: existing installations must `sudo systemctl disable --now sp-base-relay && sudo systemctl daemon-reload`, then reinstall via `tools/install.sh` to pick up the renamed `sp-rtk-base-relay.service`.


### v2.1 Implementation Summary

v2.1 enhances sp-rtk-base-relay to be usable as a **Python dependency** by the sp-base web UI project. The core purpose remains unchanged: RTCM relay.

Architecture plan: `docs/v2.1-architecture-plan.md`
UI integration plan: `docs/ublox_gps_webui_planning.md` (historical — plans now in sp-base memory bank)
API spec: `docs/relay-engine-api-spec.md`

### v2.1 Development Phases

| Phase | Deliverable | Status | Tests |
|---|---|---|---|
| P0 | Feature branch + version bump 2.1.0 | ✅ COMPLETE | — |
| P1 | Event Bus system (`events.py`) | ✅ COMPLETE | 31 tests |
| P2 | Typed status snapshots (`status.py`) | ✅ COMPLETE | 16 tests |
| P3 | Dynamic destination management (`broadcast_hub.py`) | ✅ COMPLETE | 67 tests |
| P4 | RelayEngine facade (`engine.py`) + `__init__.py` exports | ✅ COMPLETE | 27 tests |
| P5 | Documentation & API spec | ✅ COMPLETE | — |
| P6 | Cleanup (remove probe tools, docs polish) | 📋 TODO | — |

**Total unit tests**: 1,106 passing

### Next Steps
1. **First PyPI release**:
   - Register pending publisher on pypi.org (project `sp-rtk-base-relay`, owner `rodenj1`, repo `sp-rtk-base-relay`, workflow `release.yml`, environment `pypi`).
   - Create the `pypi` environment in the GitHub repo settings.
   - Commit + push the release pipeline branch, draft GitHub Release `v2.1.0`, publish to trigger `release.yml`.
   - Verify `pip install sp-rtk-base-relay==2.1.0` works post-publish.
   - See `docs/release-process.md` for the full runbook.
2. **(Optional) Rotate `CODECOV_TOKEN`** via Codecov → Settings → Coverage — the UUID was exposed in chat history during setup. Not urgent (private repo, Codecov only), but good hygiene.
3. **Phase 6**: sp-rtk-base-relay cleanup (remove probe_gps.py, revert pyubx2, README, integration tests)
4. **Lint baseline cleanup**: address items in `[tool.ruff.lint.ignore]` legacy baseline in follow-up PRs, then remove the ignores one-by-one

---

## Important Patterns and Preferences

### v2.1 Implemented Patterns
- **Facade Pattern**: RelayEngine wraps BroadcastHub + events + status
- **Observer/Pub-Sub Pattern**: EventBus with subscriber queues + ring buffer
- **Copy-on-Read Pattern**: Thread-safe destination list in broadcast loop
- **Builder Pattern**: `build_relay_status()` constructs frozen snapshots

### Existing Patterns (Unchanged)
- Strategy Pattern (InputSource, BaseDestination ABCs)
- Registry Pattern (DestinationFactory)
- Fan-Out Pattern (BroadcastHub → N queues)
- A+ Pattern (Threading + asyncio for TCP server)

### Code Quality Standards
- Python 3.10+ with type hints (modern syntax: `dict`, `list`, `X | None`)
- >90% unit test coverage using Pytest
- Zero pylance/pyright issues in strict mode
- PEP8 standards
- UV package management
