---
status: accepted
---

# BluetoothManager does not claim BlueZ's default pairing agent

Constructing a `BluetoothManager` used to call `RequestDefaultAgent`
unconditionally on every construction, seizing BlueZ's system-wide default
pairing agent from whoever held it — another `BluetoothManager`, a desktop
pairing agent, a `bluetoothctl` session left open in another terminal.
Nothing in this project's purpose requires taking that from anyone, and the
call never helped in the common single-manager case: `AgentManager1`'s
`RegisterAgent` already makes the registering connection the default when
the default-agent queue is empty (BlueZ commit `9213ff764`, first in
**5.51**, the floor this project supports). `RequestDefaultAgent` only ever
*moves* a connection to the head of a queue that already has someone in it —
which is exactly the theft.

So `_async_register_agent` calls `RegisterAgent` as before and stops there.
`BluetoothManager.__init__` gains `claim_default_agent: bool = False`;
`RequestDefaultAgent` is issued only when it's `True`. This repo's own
long-lived manager (`bluetooth_input.py`'s construction site) opts in,
since the relay is the process that should hold the default on its own
machine. An integrator like `sp-rtk-base` constructing a throwaway manager
for a UI scan leaves the default alone.

**Acknowledged limitation:** a manager cannot *decline* becoming the
default. With an empty queue, registering makes you the default whether or
not `claim_default_agent` is set. This change makes the default **stable**
— first constructed wins, no churn — not **chosen**. Only
`claim_default_agent=True` makes it chosen.

**Invariant, unchanged by this decision:** the per-instance agent stays on
the per-instance bus. If the agent were ever moved to a different bus
connection than the one issuing `Pair()`, every outgoing pairing would stop
being sender-attributed and start depending on the default-agent stack —
reintroducing the exact bug this project mistakenly believed it had found
before BlueZ's dispatch rule was traced to source. Any future refactor
toward a shared agent object must not move it off the bus that pairs.

## Consequences

A pairing that arrives with no local `Pair()` call in flight — a
caller-less pairing — is now visibly rejected by whichever manager (if any)
holds the default, with a message naming the caller-less case explicitly,
distinct from a wrong-PIN rejection. This is a narrowing of what the fix
addresses, not a widening: `#29` (the pairing agent auto-accepting
caller-less confirmation/authorization requests) is a separate, still-open
concern.

`connect_device()` gains an ephemeral `pin` argument, following
`pair_device()`'s no-retention pattern, for the one route in this codebase
that can reach the caller-less path. Supplying `pin` on a manager
constructed with `claim_default_agent=False` raises `BluetoothError`
immediately: such a manager could never receive the caller-less PIN
request that argument exists to answer, since that request is always
routed to whichever connection currently holds the default.
