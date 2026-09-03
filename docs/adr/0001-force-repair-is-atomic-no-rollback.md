---
status: accepted
---

# Force-repair discards the bond unconditionally and never rolls back on partial failure

When a device's configured PIN changes after it's already bonded, BlueZ's `Paired` fast path (`pair_device()`'s `if paired: return True`) makes the new PIN irrelevant forever unless the stale bond is explicitly removed. We added `force_repair(mac_address, pin)` as one atomic operation — `RemoveDevice()` → re-pair with the given PIN → trust — rather than exposing removal and pairing as two separate calls a caller could invoke out of order or leave half-done.

We deliberately chose **no retry and no rollback**: if the removal succeeds but the re-pair then fails, the device is left unbonded and disconnected rather than restored to its prior (believed-wrong) PIN. This matches every other failure path in `BluetoothManager` (raise `BluetoothError`, no automatic recovery) — and restoring the old bond isn't actually safer, since the caller invoked force-repair precisely because they believe that PIN is wrong.

## Consequences

Failures raise `BluetoothError` tagged with which stage failed (remove / pair / trust), so a caller — notably `sp-rtk-base`'s cross-repo "Force re-pair" UI — can tell "still safely bonded, retry is free" apart from "now unbonded, retry may need attention," without needing rollback logic on either side.
