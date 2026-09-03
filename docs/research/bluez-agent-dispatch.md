# BlueZ `Agent1` dispatch: which registered agent gets `RequestPinCode`?

Research findings for [issue #24](https://github.com/rodenj1/sp-rtk-base-relay/issues/24)
(part of map [#23](https://github.com/rodenj1/sp-rtk-base-relay/issues/23), originating bug
[#22](https://github.com/rodenj1/sp-rtk-base-relay/issues/22)).

**Date:** 2026-09-03
**Method:** read BlueZ's own C source and its D-Bus API documentation. No secondary sources
were used, and no hardware was exercised.

## Sources

All quotes are verbatim from the upstream BlueZ git tree
(<https://github.com/bluez/bluez>, mirror of `git.kernel.org/pub/scm/bluetooth/bluez.git`),
checked out at commit `ed3d4c3f91b2a1a73ff8b8ffc6a1e83d34488dfd`
(`git describe` = `5.87-117-ged3d4c3f9`, 2026-08-27).

| File | What it settles |
|---|---|
| `src/device.c` — `pair_device()`, `bonding_request_new()`, `new_auth()` | outgoing-pairing dispatch |
| `src/agent.c` — `agent_get()`, `agent_create()`, `add_default_agent()`, `remove_default_agent()`, `register_agent()`, `unregister_agent()`, `request_default()` | agent registry and default-agent stack |
| `src/adapter.c` — `start_discovery()`, `stop_discovery()`, `discovery_stop()`, `pin_code_request_callback()` | discovery sessions, legacy-PIN path |
| `doc/org.bluez.AgentManager.rst`, `doc/org.bluez.Agent.rst`, `doc/org.bluez.Adapter.rst` | the documented contract (these `.rst` files replaced the older `doc/agent-api.txt` / `doc/adapter-api.txt`; same content, new format) |

Where behaviour changed historically the deciding commit is named and dated, and the first
release tag containing it is given (from `git tag --contains`).

---

## 1. The dispatch rule (main question)

**Neither hypothesis in isolation. The rule is: the agent registered by the D-Bus sender that
called `Device1.Pair()` wins, and the default agent is only a fallback for a sender that has
registered no agent of its own.**

The deciding code is three hops.

### Hop 1 — `Pair()` resolves the agent from the message sender

`src/device.c`, `pair_device()` (the handler bound to `Device1.Pair`, registered as
`{ GDBUS_ASYNC_METHOD("Pair", NULL, NULL, pair_device) }`):

```c
	sender = dbus_message_get_sender(msg);

	agent = agent_get(sender);
	if (agent)
		io_cap = agent_get_io_capability(agent);
	else
		io_cap = MGMT_IO_CAPABILITY_NOINPUTNOOUTPUT;

	bonding = bonding_request_new(msg, device, bdaddr_type, agent);
```

The agent is resolved **once, at `Pair()` time**, from the caller's unique bus name, and
stashed on the bonding request (`src/device.c`, `bonding_request_new()`):

```c
	if (agent)
		bonding->agent = agent_ref(agent);
```

### Hop 2 — `agent_get()` prefers the owner's own agent, then falls back to the default

`src/agent.c`:

```c
struct agent *agent_get(const char *owner)
{
	struct agent *agent;

	if (owner) {
		agent = g_hash_table_lookup(agent_list, owner);
		if (agent)
			return agent_ref(agent);
	}

	if (!queue_isempty(default_agents))
		return agent_ref(queue_peek_head(default_agents));

	return NULL;
}
```

`agent_list` is keyed by **owner (unique bus name) alone** — see `register_agent()`:
`g_hash_table_replace(agent_list, agent->owner, agent)`. `default_agents` is a queue whose
**head is the current default agent**.

### Hop 3 — the PIN callback reuses the bonding request's agent

`src/device.c`, `new_auth()`, which every `device_request_*` / `device_confirm_*` entry point
goes through (`device_request_pincode()`, `device_request_passkey()`,
`device_confirm_passkey()`, `device_notify_pincode()`, …):

```c
	if (device->bonding && device->bonding->agent)
		agent = agent_ref(device->bonding->agent);
	else
		agent = agent_get(NULL);

	if (!agent) {
		error("No agent available for request type %d", type);
		return NULL;
	}
```

`device_request_pincode()` then calls `agent_request_pincode(auth->agent, ...)`, which sends
`org.bluez.Agent1.RequestPinCode` to `agent->owner` at `agent->path`.

### Corroborating documentation

`doc/org.bluez.AgentManager.rst`, `RegisterAgent`:

> Every application can register its own agent and for all actions triggered by that
> application its agent is used.
>
> It is not required by an application to register an agent. If an application does chooses to
> not register an agent, the default agent is used.
>
> An application can only register one agent. Multiple agents per application is not supported.

That is the same rule stated prose-side, and it has been in the BlueZ agent API docs since the
BlueZ 5 API was written.

### What this means for #22

`BluetoothManager` performs `bus.export(...)` + `RegisterAgent` + `RequestDefaultAgent` and
`Device1.Pair()` **on the same `AioMessageBus`** (`self._bus`, see
`src/sp_rtk_base_relay/core/bluetooth_manager.py:297-302` and `:570`). One connection, one
unique bus name. So for manager **B**:

- `agent_get(sender)` finds B's own agent in `agent_list` and never reaches the
  `default_agents` fallback;
- `bonding->agent` is B's agent;
- `RequestPinCode` is dispatched back to **B**, whatever manager A did with
  `RequestDefaultAgent`.

**#22's step-4 repro is therefore wrong.** An outgoing `B.pair_device()` is not misrouted to A.
The failure #22 describes cannot occur on that path.

Residual ways an *outgoing* `Pair()` could still be misrouted, all of which require a
precondition the current code does not create:

1. B's `RegisterAgent` failed or was never issued (`_async_register_agent()` raised and was
   swallowed) — then `agent_get(sender)` falls through to the default agent, which may be A.
2. B issues `Pair()` on a different D-Bus connection from the one that registered the agent.
   Not the case today (single `self._bus`), but it is the invariant the fix must preserve —
   any refactor that puts the agent on a shared/module-level bus while `Pair()` stays on the
   per-instance bus would *create* the #22 bug rather than fix it.
3. B's agent registration was torn down (bus disconnect / `UnregisterAgent`) while a pairing
   was still in flight.

**Confidence: high** for BlueZ 5.x. The code path is short, unconditional, and unchanged across
every 5.x release checked (see §5). No hardware verification is required to establish the rule;
a hardware test would only be worth running to confirm that `dbus-fast`'s `AioMessageBus`
really does send `RegisterAgent` and `Pair()` over one connection with one unique name — which
is a `dbus-fast` question, not a BlueZ one, and is evident from the single `self._bus` object.

---

## 2. Sub-question 1 — does `RequestDefaultAgent` supersede silently? Does `UnregisterAgent`
of the default promote anyone?

### Supersession is silent, and there is no notification API

`src/agent.c`, `request_default()` ends with `add_default_agent(agent)`:

```c
static bool add_default_agent(struct agent *agent)
{
	if (queue_peek_head(default_agents) == agent)
		return true;

	queue_remove(default_agents, agent);

	if (!queue_push_head(default_agents, agent))
		return false;

	DBG("Default agent set to %s %s", agent->owner, agent->path);

	btd_adapter_foreach(set_io_cap, agent);

	return true;
}
```

The previously-default agent is **not** called, **not** released, and **not** removed — it is
simply no longer at the head of the queue. `org.bluez.Agent1` has no "you are no longer the
default" method to call; the only lifecycle method is `Release()`, and per
`doc/org.bluez.Agent.rst`:

> This method gets called when **bluetoothd(8)** unregisters the agent.

The upstream commit that introduced the queue says so outright — commit `123db1e88`,
"agent: Allow to stack default agents" (2014-04-28, first in **5.19**):

> There is no API for notifying agent that it is no longer default one. This can lead to
> situation when ie. console agent (bluetoothctl) is set as default leaving UI agent
> unfunctional after bluetoothctl exited.
>
> This patch adds stacking of default agents in case more then one agent requested being
> default.

### `UnregisterAgent` of the default **does** promote the next agent

`src/agent.c`, `unregister_agent()` calls `agent_disconnect()`, which calls
`remove_default_agent()`:

```c
static void remove_default_agent(struct agent *agent)
{
	if (queue_peek_head(default_agents) != agent) {
		queue_remove(default_agents, agent);
		return;
	}

	queue_remove(default_agents, agent);

	agent = queue_peek_head(default_agents);
	if (agent)
		DBG("Default agent set to %s %s", agent->owner, agent->path);
	else
		DBG("Default agent cleared");

	btd_adapter_foreach(set_io_cap, agent);
}
```

The same function runs when the agent's **bus connection drops**: `agent_create()` installs
`g_dbus_add_disconnect_watch(..., agent_disconnect, ...)`, and `agent_disconnect()` calls
`remove_default_agent()` before removing the agent from `agent_list`. So both
`UnregisterAgent` and a plain `bus.disconnect()` promote the next agent in the stack.

Traced for the #22 scenario (B constructed first, then A):

| Step | `default_agents` (head first) | Default |
|---|---|---|
| B registers (queue empty → `add_default_agent`) | `[B]` | B |
| B calls `RequestDefaultAgent` (already head → no-op) | `[B]` | B |
| A registers (queue non-empty → `queue_push_tail`) | `[B, A]` | B |
| A calls `RequestDefaultAgent` (`queue_remove` + `queue_push_head`) | `[A, B]` | A |
| A `close()`s — `UnregisterAgent` or bus disconnect | `[B]` | **B (promoted automatically)** |

**This contradicts note 3 of map #23** ("After a short-lived UI manager supersedes the relay's
manager and then closes, the system is left with **no default agent at all** — permanent for
the life of the relay process"). On BlueZ ≥ 5.19 that is not what happens: B is still in the
stack and is promoted back to default the moment A goes away. The system is left with *no*
default agent only if every registered agent has gone away.

Two further notes from the same code:

- **Registration alone makes you the default when nobody else holds it.** `agent_create()`:
  `if (queue_isempty(default_agents)) add_default_agent(agent); else queue_push_tail(...)`.
  Introduced by commit `9213ff764`, "agent: Make the first agent to register the default"
  (2018-07-27, first in **5.51**). Before 5.51 a lone `RegisterAgent` without
  `RequestDefaultAgent` left the system with no default agent at all.
- **`Release()` is not called on `UnregisterAgent`.** `unregister_agent()` →
  `agent_disconnect()` clears `agent->watch` *before* `g_hash_table_remove()` reaches
  `agent_destroy()`, and `agent_destroy()` only calls `agent_release()` when `agent->watch > 0`.
  In practice `Release()` arrives only when bluetoothd itself tears down
  (`btd_agent_cleanup()`).

---

## 3. Sub-question 2 — incoming (device-initiated) pairing

**Device-initiated pairing always goes to the current default agent** (head of
`default_agents`). There is no sender to attribute it to.

The mechanism is the `device->bonding` branch in `new_auth()` quoted above. `device->bonding`
is set in exactly one place in the whole tree:

```
$ grep -n "device->bonding = \|bonding_request_new(" src/device.c
3229:static struct bonding_req *bonding_request_new(DBusMessage *msg,
3338:		bonding->device->bonding = NULL;
3397:	bonding = bonding_request_new(msg, device, bdaddr_type, agent);
3406:	device->bonding = bonding;
```

Lines 3397/3406 are inside `pair_device()`. So **only an explicit `Device1.Pair()` creates a
bonding request**; every other route into the agent — a remote device initiating pairing, or
pairing/security elevation triggered as a side effect of `Device1.Connect()` or of a profile's
security requirement — has `device->bonding == NULL` and therefore takes
`agent = agent_get(NULL)` → head of `default_agents`.

The same is true of every other agent consumer in the tree. Outside `pair_device()`, every
call site passes `NULL`:

```
$ grep -rn "agent_get(" src/*.c | grep -v agent_get_io
src/agent.c:247:struct agent *agent_get(const char *owner)
src/adapter.c:7786:	return agent_get(NULL);        /* adapter_get_agent() */
src/adapter.c:7976:	auth->agent = agent_get(NULL); /* service authorization (AuthorizeService) */
src/adapter.c:9648:	agent = agent_get(NULL);       /* adapter init: seed adapter IO capability */
src/device.c:3391:	agent = agent_get(sender);     /* Device1.Pair() -- the only sender-attributed one */
src/device.c:7650:	agent = agent_get(NULL);       /* new_auth() fallback */
```

Two knock-on consequences worth carrying into the spec:

- **IO capability.** For an outgoing `Pair()`, the IO capability sent to the kernel is the
  *Pair() caller's* agent capability, per-request (`pair_device()` → `adapter_create_bonding(...,
  io_cap)` → `MGMT_OP_PAIR_DEVICE` with `cp.io_cap = io_cap`). For incoming pairing there is no
  per-request capability: the adapter-wide IO capability is used, and that is set from the
  **default** agent by `btd_adapter_foreach(set_io_cap, agent)` whenever the default changes.
  So while A holds the default, incoming pairings are negotiated with A's capability *and*
  answered by A.
- **Legacy PIN plugins only run for outgoing pairings.** `src/adapter.c`,
  `pin_code_request_callback()`: `iter = device_bonding_iter(device); if (iter == NULL) pinlen = 0;`
  — the in-process PIN-callback chain is consulted only when a bonding request exists.
  Device-initiated pairing goes straight to `device_request_pincode()` → default agent.

So the surviving half of #22 is real and is exactly the device-initiated case: if A holds the
default and the GPS receiver initiates the pairing, `RequestPinCode` lands on A's empty
`_pending_pins` and is rejected.

---

## 4. Sub-question 3 — is `StartDiscovery`/`StopDiscovery` refcounted per D-Bus sender?

**Yes. Per-sender discovery sessions, and one client's `StopDiscovery` cannot cut short
another client's scan.**

`doc/org.bluez.Adapter.rst`:

> **StartDiscovery** — Use **StopDiscovery** to release the sessions acquired. […] Each client
> can request a single device discovery session per adapter.
>
> **StopDiscovery** — Stops device discovery session started by **StartDiscovery**. Note that a
> discovery procedure is shared between all discovery sessions thus calling StopDiscovery will
> only release a single session and discovery will stop when all sessions from all clients have
> finished.

The code backs this exactly. `src/adapter.c`, `start_discovery()` keys the session on the
sender and installs a disconnect watch:

```c
	const char *sender = dbus_message_get_sender(msg);
	...
	is_discovering = get_discovery_client(adapter, sender, &client);

	/*
	 * Every client can only start one discovery, if the client
	 * already started a discovery then return an error.
	 */
	if (is_discovering)
		return btd_error_busy(msg);
	...
	client = g_new0(struct discovery_client, 1);
	client->adapter = adapter;
	client->owner = g_strdup(sender);
	client->watch = g_dbus_add_disconnect_watch(dbus_conn, sender,
						discovery_disconnect, client,
						NULL);
	adapter->discovery_list = g_slist_prepend(adapter->discovery_list, client);
```

`stop_discovery()` only ever touches the calling sender's own client:

```c
	list = g_slist_find_custom(adapter->discovery_list, sender,
						compare_sender);
	if (!list)
		return btd_error_failed(msg, "No discovery started");

	client = list->data;
```

and `discovery_stop()` refuses to send `MGMT_OP_STOP_DISCOVERY` while any other client remains:

```c
static int discovery_stop(struct discovery_client *client)
{
	struct btd_adapter *adapter = client->adapter;
	struct mgmt_cp_stop_discovery cp;

	/* Check if there are more client discovering */
	if (g_slist_next(adapter->discovery_list)) {
		discovery_remove(client);
		update_discovery_filter(adapter);
		return 0;
	}
	...
```

Practical notes for two live managers on one `hci0`:

- `StopDiscovery` from a sender that never started one returns
  `org.bluez.Error.Failed: "No discovery started"` — harmless to the other manager, but it is
  an error the caller must be ready to swallow.
- A second `StartDiscovery` from the *same* sender returns `org.bluez.Error.InProgress`
  (`btd_error_busy()` → `ERROR_INTERFACE ".InProgress"`), not success. Ten call sites in
  `bluetooth_manager.py` on one bus means the manager must tolerate `InProgress` from its own
  re-entrant scans.
- Discovery **filters are merged and shared**: both `start_discovery()` and
  `discovery_stop()` call `update_discovery_filter(adapter)`, which recomputes the union across
  all clients and may restart the hardware scan (`trigger_start_discovery(adapter, 0)`). So
  A's `SetDiscoveryFilter` changes the scan parameters (transport, RSSI threshold, duplicate
  reporting) B actually gets, and A starting or stopping can cause a brief restart of the
  underlying inquiry. The *session* is safe; the *scan parameters* and continuity are not
  fully isolated.
- The `Discovering` property is adapter-global, so B cannot use it to learn whether *its own*
  session is live.

**Verdict for map #23's "not yet specified" item:** the refcounting assumption is confirmed,
so this does not need to graduate into its own ticket. The filter-merging and `InProgress`
caveats are worth a line in the spec but are not the same class of hazard.

---

## 5. Version applicability

| Behaviour | Holds from | Deciding commit |
|---|---|---|
| `Pair()` resolves the agent by `dbus_message_get_sender()`, falling back to the default | **5.0** (2012-12) | `cab6bfb7a` "core: Add agent_get function", `45ffca3e6` "core: Look up correct IO capability with Device.Pair" |
| `new_auth()` prefers `device->bonding->agent`, else the default | 5.x throughout | `2ca379593`, `6af5715cc` |
| Per-sender discovery sessions; `StopDiscovery` releases only the caller's session | **5.2** (2013-01) | `407579a96` "core: Fix multiple issues with discovery handling" |
| Default agents are a **stack**; unregistering the default promotes the next | **5.19** (2014-04) | `123db1e88` "agent: Allow to stack default agents" |
| First `RegisterAgent` becomes the default without `RequestDefaultAgent` | **5.51** (2018-07) | `9213ff764` "agent: Make the first agent to register the default" |

Verification that the deciding functions are byte-identical across the releases this project
will meet in the field:

```
$ for t in 5.19 5.50 5.55 5.66 5.79 5.82 HEAD; do
    git show $t:src/agent.c | sed -n '/^struct agent \*agent_get/,/^}/p' | md5sum; done
0e2a2ed04c076d79114d6e4b9a1f6596   # identical for every tag, 5.19 through HEAD
```

`remove_default_agent()` is likewise identical 5.19 → 5.82; the only difference at HEAD is the
rename `adapter_foreach()` → `btd_adapter_foreach()` (commit `c24f0b487`, cosmetic).
`pair_device()` still contains `agent_get(sender)` in 5.55, 5.66, 5.79 and 5.82, and
`discovery_stop()`'s "more client discovering" early-return is present in 5.50 through HEAD.

Distro relevance: Raspberry Pi OS Bullseye ships BlueZ 5.55, Bookworm 5.66, Trixie 5.79+.
**All of them are ≥ 5.51, so every behaviour above — including the automatic promotion on
unregister — applies unchanged.**

**Behaviour that changed, and would bite an older target:** on BlueZ **< 5.19** there was a
single `static struct agent *default_agent`, and `agent_disconnect()` did
`if (agent == default_agent) set_default_agent(NULL);` — i.e. unregistering the default really
did leave the system with none, exactly as map #23 note 3 assumes. That is a 2014-and-earlier
behaviour and is not reachable on any supported target here.

---

## 6. Ambiguity check

The source is **not** ambiguous on the main question or on sub-questions 1 and 3. The relevant
functions are short, branch-free on the paths that matter, and stable across a decade of
releases. The wording in `doc/org.bluez.AgentManager.rst` says the same thing independently.

The one thing this desk research cannot settle from BlueZ's source is whether `dbus-fast`'s
`AioMessageBus` really presents a single unique bus name for both the `RegisterAgent` call and
the later `Device1.Pair()` call — that is a `dbus-fast` property. It is a single
`MessageBus` object with a single socket (`bluetooth_manager.py:244`), and proxies obtained
from it send on it, so the answer is almost certainly yes; but if the spec wants belt-and-braces
it is a one-line check (`bus.unique_name`) rather than a hardware test.

---

## 7. Consequences for map #23

1. **#22's headline repro (steps 1–5) does not reproduce.** Outgoing `B.pair_device()` is
   answered by B's own agent regardless of who holds the default. The bug report's premise
   ("BlueZ dispatches `RequestPinCode` to whoever last called `RequestDefaultAgent`") is false
   for outgoing pairing.
2. **The real bug is narrower: device-initiated pairing.** When the receiver initiates, the
   default agent answers. If A holds the default and only B knows the PIN, the pairing is
   rejected — the silent, wrong-PIN-looking failure #22 describes, on a path #22 did not name.
3. **The `close()` hole (map note 3) does not exist as described on BlueZ ≥ 5.19.** Removing A
   promotes B back to default automatically, via `remove_default_agent()`, on both
   `UnregisterAgent` and bus disconnect. The system is left with no default agent only if *all*
   agents are gone.
4. **Discovery contention is a non-issue** at the session level (confirmed refcounting); the
   live caveats are shared/merged discovery filters and `org.bluez.Error.InProgress` on a
   same-sender re-entrant `StartDiscovery`.
5. **A design constraint for #22's suggested fix option 1** ("one agent per process"): BlueZ
   allows exactly one agent per D-Bus connection (`register_agent()` returns
   `org.bluez.Error.AlreadyExists` for a second registration from the same sender), and one
   outstanding request per agent — `agent_request_pincode()` opens with
   `if (agent->request) return -EBUSY;`, and requests time out after
   `REQUEST_TIMEOUT (60 * 1000)`. A single shared agent therefore serialises concurrent PIN
   requests; a second concurrent pairing needing a PIN is rejected rather than queued. (This
   limit already applies per-manager today.) Also, if the shared agent lives on a *different*
   bus connection from the one issuing `Pair()`, every outgoing pairing stops being
   sender-attributed and starts depending on the default-agent stack — which would introduce
   the very bug #22 thought it had found. **Whatever object owns the agent must own the same
   `MessageBus` that issues `Pair()`.**

---

## 6. Follow-up (2026-09-03): which pairings are actually *caller-less*?

Added while resolving [issue #25](https://github.com/rodenj1/sp-rtk-base-relay/issues/25). §3 established
that any pairing with `device->bonding == NULL` goes to the default agent, but left open *which
concrete operations* produce that state. Two were outstanding: `Device1.Connect()` on an unbonded
device, and an inbound RFCOMM connection.

**Method:** same as above — BlueZ C source only, no hardware. Read at commit
`ed3d4c3f91b2a1a73ff8b8ffc6a1e83d34488dfd` (master HEAD, 2026-08-27, post-5.85), the same tree §1-§5
used.

### 6.1 `Device1.Connect()` on an unbonded device — **yes, and it reaches the default agent**

`dev_connect()` (`src/device.c:2824`) settles it in its own opening guard:

```c
	if (dev->bonding)
		return btd_error_in_progress(msg);
```

`Connect()` *refuses to run while bonding*, which proves it never creates a bonding request of its
own. So `device->bonding` is NULL for the whole call, and `new_auth()` takes the `agent_get(NULL)`
branch quoted in §1 hop 3.

The chain that gets there:

`dev_connect` → `device_connect_profiles` (`src/device.c:2763`) → `connect_next`
(`src/device.c:2329`) → `btd_service_connect` (`src/service.c:341`) → `profile->connect(service)`
(`src/service.c:374`). For SPP the profile is an *external* one registered through
`ProfileManager1.RegisterProfile` — there is no `profiles/serial/` in modern BlueZ — so it lands in
`connect_io()` (`src/profile.c:1629`):

```c
		conn->proto = BTPROTO_RFCOMM;
		io = bt_io_connect(ext_connect, conn, NULL, &gerr,
					BT_IO_OPT_SOURCE_BDADDR, src,
					BT_IO_OPT_DEST_BDADDR, dst,
					BT_IO_OPT_SEC_LEVEL, ext->sec_level,   /* :1651 */
					BT_IO_OPT_CHANNEL, conn->chan,
```

`ext->sec_level` defaults to **MEDIUM** (`ext_set_defaults`, `src/profile.c:2224`), and the SPP entry
in `defaults[]` (`src/profile.c:2094`) sets no `sec_level`, so SPP keeps MEDIUM. Only
`RequireAuthentication=false` lowers it to `BT_IO_SEC_LOW` (`src/profile.c:2317`). `set_sec_level()`
(`btio/btio.c:476`) turns that into a `BT_SECURITY` sockopt, and with no link key the kernel starts
authentication and emits `MGMT_EV_PIN_CODE_REQUEST`.

`pin_code_request_callback()` (`src/adapter.c:8522`) then has **no bonding check and no trusted
check** — with `device->bonding == NULL`, `device_bonding_iter()` returns NULL so the autopair
plugin's PIN callback is skipped, and it falls straight through to `device_request_pincode()`
(`:8582`) → `new_auth()` → **default agent**.

A corroborating smoking gun in `device_confirm_passkey()` (`src/device.c:7705`), which handles the
SSP form of the same case explicitly:

```c
	if (confirm_hint) {
		if (device->bonding != NULL) {
			/* We know the client has indicated the intent to pair ... auto-accept */
			btd_adapter_confirm_reply(..., TRUE);
			return 0;
		}
		err = agent_request_authorization(auth->agent, device, confirm_cb, auth, NULL);
```

BlueZ auto-accepts only when a bonding request exists; with none, it prompts the default agent via
`RequestAuthorization`.

The same holds for a device whose bond was removed externally — nothing on this path consults bonded
state.

### 6.2 Inbound RFCOMM — **yes, and it fires two independent gates**

`ext_start_servers()` (`src/profile.c:1391`) opens the listeners with the same `ext->sec_level`
(`:1465` for RFCOMM, `:1425` for L2CAP), so an inbound connect from an unbonded peer authenticates
*before* the socket is handed up — the identical `pin_code_request_callback` → `new_auth` chain, and
again `device->bonding` is NULL, so again the **default agent**.

Separately, `ext_confirm()` (`src/profile.c:1272`) calls `btd_request_authorization()`
(`src/profile.c:1309`), reaching `process_auth_queue()` (`src/adapter.c:7944`):

```c
		if (btd_device_is_trusted(device) == TRUE) {     /* :7967 */
			auth->cb(NULL, auth->user_data);         /* skip agent entirely */
			goto next;
		}
		...
		auth->agent = agent_get(NULL);                   /* :7976  → DEFAULT agent */
```

Note this path never consults `device->bonding` at all — it is hardcoded `agent_get(NULL)`.

### 6.3 Consequences

- **`Trusted` is not protection against a PIN request.** It short-circuits only `AuthorizeService`
  (`src/adapter.c:7967`). `pin_code_request_callback` contains no trusted check, so
  `RequestPinCode` / `RequestConfirmation` fire regardless.
- **`RequireAuthentication=false`** (→ `BT_IO_SEC_LOW`) is the only thing in this source that removes
  the link-level PIN prompt; `RequireAuthorization=false` (`src/profile.c:2326`) removes the
  `AuthorizeService` prompt. Both are properties of the *registered profile*, which this project does
  not register — it opens a raw socket instead (see below).
- **IO capability for a caller-less pairing** comes from the default agent globally
  (`src/agent.c:136` → `adapter_set_io_capability` → `MGMT_OP_SET_IO_CAPABILITY`,
  `src/adapter.c:9401`), not from a per-request bonding capability.
- **Naming correction to §3:** there is no `device_request_auth()` in current BlueZ. The link-level
  entry points are `device_request_pincode` / `device_request_passkey` / `device_confirm_passkey`
  (all via `new_auth`); the service-level one is `btd_request_authorization` / `adapter_authorize`.

### 6.4 Reachability against this project

Both paths are real in BlueZ, and neither is reached by the relay as it stands:

| Path | Reached here? |
|---|---|
| Device initiates pairing | No — the receiver never initiates (confirmed with the maintainer, #25). |
| Relay's own data path | No — `ensure_device_ready` deliberately skips `Connect()` for SPP, pairs with a caller present, then opens a raw `AF_BLUETOOTH` socket (`bluetooth_input.py:135-142`) that sets **no `BT_SECURITY` sockopt`**, so the kernel default of LOW applies and no authentication is demanded — and a bond exists by then regardless. |
| `connect_device()` | In principle yes; in practice no caller. Neither this repo nor `sp-rtk-base` invokes it (`sp-rtk-base`'s `api/device.py:70 connect_device` is its own REST endpoint, not this method). |

### 6.5 Not settleable from BlueZ source

Whether the *kernel* actually starts HCI authentication for a given `BT_SECURITY_MEDIUM` socket on an
already-encrypted-or-not ACL is Linux `net/bluetooth/` behaviour, not bluez userspace — BlueZ only
sets the sockopt. Everything downstream of `MGMT_EV_PIN_CODE_REQUEST` is fully settled above.
