# BlueZ `Device1.Pair()`: when does it reply, and what does it reply?

Research findings for [issue #44](https://github.com/rodenj1/sp-rtk-base-relay/issues/44)
(part of map [#41](https://github.com/rodenj1/sp-rtk-base-relay/issues/41), originating bug
[#39](https://github.com/rodenj1/sp-rtk-base-relay/issues/39)).

**Date:** 2026-09-03
**Method:** read BlueZ's own C source, plus Linux kernel `net/bluetooth/` for the one hop that
leaves userspace (the mgmt status that comes back after a negative PIN reply). No secondary
sources, no hardware.

Companion to [`bluez-agent-dispatch.md`](bluez-agent-dispatch.md), which settled *which* agent
gets `RequestPinCode`. This one settles *when* `Pair()` answers and *what* it says.

## Sources

BlueZ: upstream git tree (<https://github.com/bluez/bluez>, mirror of
`git.kernel.org/pub/scm/bluetooth/bluez.git`), checked out at commit
`ed3d4c3f91b2a1a73ff8b8ffc6a1e83d34488dfd` (`git describe` = `5.87-117-ged3d4c3f9`,
2026-08-27) — the same tree `bluez-agent-dispatch.md` used.

Linux: `torvalds/linux` `master`, files `net/bluetooth/mgmt.c`, `net/bluetooth/hci_event.c`,
`net/bluetooth/hci_conn.c`, `net/bluetooth/hci_sync.c` (fetched 2026-09-03).

| File | What it settles |
|---|---|
| `gdbus/object.c` — `process_message()` | what returning `NULL` from an `ASYNC` handler means |
| `src/device.c` — `pair_device()`, `device_bonding_complete()`, `device_bonding_failed()`, `device_cancel_bonding()`, `new_authentication_return()`, `browse_request_complete()`, `device_set_paired()`, `pincode_cb()` | the whole reply path for `Pair` |
| `src/adapter.c` — `pin_code_request_callback()`, `btd_adapter_pincode_reply()`, `bonding_attempt_complete()`, `bonding_complete()`, `pair_device_complete()`, `auth_failed_callback()` | mgmt plumbing and the retry rung |
| `net/bluetooth/mgmt.c` — `mgmt_status_table[]`, `mgmt_auth_failed()`, `pairing_complete_cb()` | HCI error → mgmt status mapping |
| `net/bluetooth/hci_event.c` — `hci_auth_complete_evt()` | what the controller reports after a negative PIN reply |

---

## Summary — the four answers

| # | Question | Answer |
|---|---|---|
| 1 | Does `pair_device()` return without replying, with the reply emitted later? | **Yes.** `pair_device()` ends `return NULL;` (`src/device.c:3439`) under `GDBUS_ASYNC_METHOD` (`:3606`); every success reply is emitted later from `device_bonding_complete()` or `browse_request_complete()`. |
| 2 | What error does `Pair()` return when the agent rejects `RequestPinCode`? | **`org.bluez.Error.AuthenticationFailed`, message `"Authentication Failed"`** — *not* `AuthenticationRejected`. The agent's `org.bluez.Error.Rejected` is discarded; the caller sees whatever the controller reports, which for a negative PIN reply is HCI `0x05`/`0x06` → `MGMT_STATUS_AUTH_FAILED` → the `default:` arm of `new_authentication_return()`. |
| 3 | Any path where `Pair()` replies **success** while `Paired` is false? | **No.** Every one of the four sites that can emit a method-return for a `Pair` message is downstream of `device_set_paired()` or explicitly guarded by `device_is_paired()`. |
| 4 | Do these hold 5.51 → HEAD? | **Yes**, byte-identical. `new_authentication_return()` last changed 2015-03-11 (`755d9d311`, first in 5.30). One cosmetic addition at 5.87 (`622a46ebc`) adds a fourth reply site — still paired-guarded. |

**Candidate 1 of map #41 is REFUTED.** `call_pair()` cannot resolve before the PIN round-trip
finishes: BlueZ does not write a reply to the `Pair` message until the bonding attempt has
terminated one way or the other, and a *successful* reply is unreachable unless `Paired` is
already true at the moment it is written.

---

## 1. `pair_device()` returns without replying

### 1.1 The registration

`src/device.c:3606`, in `device_methods[]`:

```c
	{ GDBUS_ASYNC_METHOD("Pair", NULL, NULL, pair_device) },
```

`GDBUS_ASYNC_METHOD` (`gdbus/gdbus.h:159-164`) is nothing but a struct initialiser that sets
`.flags = G_DBUS_METHOD_FLAG_ASYNC`. It is a *permission*, not a mechanism — it does not by
itself defer anything. What it permits is spelled out in `gdbus/object.c`,
`process_message()` (`:287-313`):

```c
	reply = method->function(connection, message, iface_user_data);

	if (method->flags & G_DBUS_METHOD_FLAG_NOREPLY ||
					dbus_message_get_no_reply(message)) {
		if (reply != NULL)
			dbus_message_unref(reply);
		return DBUS_HANDLER_RESULT_HANDLED;
	}

	if (method->flags & G_DBUS_METHOD_FLAG_ASYNC) {
		if (reply == NULL)
			return DBUS_HANDLER_RESULT_HANDLED;
	}

	if (reply == NULL)
		return DBUS_HANDLER_RESULT_NEED_MEMORY;

	g_dbus_send_message(connection, reply);
```

So: for an ASYNC method, a `NULL` return means "handled, nothing sent" — the message sits on the
bus with no reply until some later code writes one. For a *non*-ASYNC method the same `NULL`
would be an out-of-memory error. This is the mechanism the registration macro enables, and it is
the same in every release checked (§5).

### 1.2 The handler takes that branch on every non-error path

`src/device.c:3343-3440`, `pair_device()`. Its terminal statement is:

```c
	if (err < 0) {
		bonding_request_free(device->bonding);
		return btd_error_failed(msg, strerror(-err));
	}

	return NULL;                                          /* :3439 */
```

Every other `return` in the function is an *error* reply, delivered synchronously:

| Line | Condition | Reply |
|---|---|---|
| `:3359` | non-empty argument list | `org.bluez.Error.InvalidArguments` |
| `:3362` | `device->bonding \|\| device->connect` | `org.bluez.Error.InProgress` |
| `:3386-3387` | `state->bonded` | `org.bluez.Error.AlreadyExists` |
| `:3435-3436` | `adapter_create_bonding()` failed | `org.bluez.Error.Failed` |

There is **no `dbus_message_new_method_return()` anywhere in `pair_device()`**. It is not
possible for the function to answer success synchronously.

Before returning `NULL`, it stores the message for later
(`bonding_request_new()`, `src/device.c:3229`):

```c
	bonding->msg = dbus_message_ref(msg);
```

and hands the bonding attempt to the kernel via `adapter_create_bonding()` →
`adapter_bonding_attempt()` → `MGMT_OP_PAIR_DEVICE`.

### 1.3 Where the reply actually comes from

Every use of the stored `bonding->msg` in the tree — the four that write a BR/EDR reply are
`:3493`, `:7355`, `:7379` and `:7551`, plus `:7369` which hands it to the browse request:

```
$ grep -n "bonding->msg" src/device.c
3242:	bonding->msg = dbus_message_ref(msg);                          # store
3322:	if (bonding->msg)
3323:		dbus_message_unref(bonding->msg);                      # free, no reply
3493:	reply = new_authentication_return(bonding->msg, status);       # device_cancel_bonding
6593:		reply = btd_error_failed(device->bonding->msg, ...);   # LE-only connect failure
6662:				dev->bonding->msg, gerr->message);     # LE-only ATT failure
7355:		g_dbus_send_reply(dbus_conn, bonding->msg, DBUS_TYPE_INVALID);
7369:						bonding->msg);                 # handed to browse
7379:			g_dbus_send_reply(dbus_conn, bonding->msg,
7477:	return g_str_equal(sender, dbus_message_get_sender(bonding->msg));  # read-only
7551:	reply = new_authentication_return(bonding->msg, status);       # device_bonding_failed
```

plus `browse_request_complete()` (`src/device.c:3069`), which receives the same `DBusMessage *`
via `:7369`, after `device_bonding_complete()` hands it to `device_discover_services()`.

The path from the kernel back to those sites:

```
MGMT_OP_PAIR_DEVICE cmd complete  →  pair_device_complete()        src/adapter.c:8695
MGMT_EV_AUTH_FAILED              →  auth_failed_callback()         src/adapter.c:8901
MGMT_EV_NEW_LINK_KEY             →  new_link_key_callback()        src/adapter.c:8963
MGMT_EV_DEVICE_DISCONNECTED      →  ...                            src/adapter.c:8832
        ↓
bonding_attempt_complete()   src/adapter.c:8649   (retry rung — see §2.3)
        ↓
bonding_complete()           src/adapter.c:8627
        ↓
device_bonding_complete(device, addr_type, status)   src/device.c:7303
```

`device_bonding_complete()` is the fork:

```c
	if (status) {
		device_cancel_authentication(device, TRUE);
		...
		device_bonding_failed(device, status);        /* :7331  → error reply */
		return;
	}
	...
	/* If we're already paired nothing more is needed */
	if (state->paired)                                    /* :7342 */
		return;                                       /*         → NO reply, see §3.2 */

	device_set_paired(device, bdaddr_type);               /* :7345 */

	if (state->svc_resolved && bonding) {
		store_gatt_db(device);
		g_dbus_send_reply(dbus_conn, bonding->msg, DBUS_TYPE_INVALID);   /* :7355 */
		bonding_request_free(bonding);
		return;
	}

	if (bonding) {
		err = device_discover_services(device, bdaddr_type, bonding->msg);
		if (err) {
			...
			/* Disregard browse errors in case of Pair */
			g_dbus_send_reply(dbus_conn, bonding->msg,
						DBUS_TYPE_INVALID);       /* :7379 */
		}
		bonding_request_free(bonding);
	}
```

**Conclusion for question 1: confirmed from the code that emits the reply, not from the macro.**
The `Pair` method return travels back to the caller only after `MGMT_OP_PAIR_DEVICE` has
completed — and, in the ordinary BR/EDR case, only after SDP service discovery on top of that.
The PIN round-trip happens strictly inside that window: `MGMT_EV_PIN_CODE_REQUEST` →
`pin_code_request_callback()` (`src/adapter.c:8522`) → `device_request_pincode()` →
`Agent1.RequestPinCode` → agent's answer → `btd_adapter_pincode_reply()` →
`MGMT_OP_PIN_CODE_REPLY` / `MGMT_OP_PIN_CODE_NEG_REPLY`. None of that can outlive the reply,
because the reply is written by the event that terminates the bonding.

---

## 2. What the caller gets when the agent rejects the PIN

### 2.1 The agent's error name is thrown away

BlueZ never translates the agent's D-Bus error into the `Pair()` error. `src/agent.c:455-511`,
`pincode_reply()` — the handler for the `RequestPinCode` reply:

```c
	dbus_error_init(&err);
	if (dbus_set_error_from_message(&err, message)) {
		error("Agent %s replied with an error: %s, %s",
				agent->path, err.name, err.message);

		cb(agent, &err, NULL, req->user_data);      /* :477 */
		dbus_error_free(&err);
		goto done;
	}
```

(That `error()` line is the journal message the field report shows.) The callback `cb` is
`pincode_cb()` (`src/device.c:7565`), and it **ignores the `DBusError` entirely**:

```c
static void pincode_cb(struct agent *agent, DBusError *err, const char *pin,
								void *data)
{
	struct authentication_req *auth = data;
	struct btd_device *device = auth->device;

	/* No need to reply anything if the authentication already failed */
	if (auth->agent == NULL)
		return;

	btd_adapter_pincode_reply(device->adapter, &device->bdaddr,
						pin, pin ? strlen(pin) : 0);
	...
}
```

`err` is never read. `pin` is `NULL`, so `btd_adapter_pincode_reply()` (`src/adapter.c:8255`)
takes its `pin == NULL` branch and sends `MGMT_OP_PIN_CODE_NEG_REPLY`:

```c
	if (pin == NULL) {
		struct mgmt_cp_pin_code_neg_reply cp;
		...
		id = mgmt_reply(adapter->mgmt, MGMT_OP_PIN_CODE_NEG_REPLY, ...);
```

So `org.bluez.Error.Rejected` and `org.bluez.Error.Canceled` are indistinguishable to the
caller of `Pair()`: both become "no PIN", and the eventual error name is decided entirely by
what the controller reports next.

### 2.2 What the controller reports next

Kernel side. `MGMT_OP_PIN_CODE_NEG_REPLY` sends HCI `PIN Code Request Negative Reply`; the
controller then completes authentication with a failure. `net/bluetooth/hci_event.c`,
`hci_auth_complete_evt()`:

```c
	if (!ev->status) {
		...
	} else {
		if (ev->status == HCI_ERROR_PIN_OR_KEY_MISSING)
			set_bit(HCI_CONN_AUTH_FAILURE, &conn->flags);

		mgmt_auth_failed(conn, ev->status);
	}
```

`mgmt_auth_failed()` (`net/bluetooth/mgmt.c:10316`) runs the HCI status through
`mgmt_status()`, emits `MGMT_EV_AUTH_FAILED`, **and** completes the pending `pair_device`
command with the same status. The mapping table (`net/bluetooth/mgmt.c:216`) is decisive:

```c
static const u8 mgmt_status_table[] = {
	MGMT_STATUS_SUCCESS,
	...
	MGMT_STATUS_CONNECT_FAILED,	/* Page Timeout */
	MGMT_STATUS_AUTH_FAILED,	/* Authentication Failed */      /* HCI 0x05 */
	MGMT_STATUS_AUTH_FAILED,	/* PIN or Key Missing */         /* HCI 0x06 */
	...
```

Both HCI statuses a rejected legacy PIN can produce map to **`MGMT_STATUS_AUTH_FAILED` (0x05)**.

### 2.3 The retry rung, and why it does not fire here

`bonding_attempt_complete()` (`src/adapter.c:8649`) intercepts exactly this status:

```c
	if (status == MGMT_STATUS_AUTH_FAILED && adapter->pincode_requested) {
		/* On failure, issue a bonding_retry if possible. */
		if (device != NULL) {
			if (device_bonding_attempt_retry(device) == 0)
				return;
		}
	}
	...
	bonding_complete(adapter, bdaddr, addr_type, status);
```

`adapter->pincode_requested` was set to `true` by `pin_code_request_callback()`
(`src/adapter.c:8553`), so the branch is entered. But `device_bonding_attempt_retry()`
(`src/device.c:7514`) bails at `:7529`:

```c
	if (btd_adapter_pin_cb_iter_end(bonding->cb_iter))
		return -EINVAL;
```

and `btd_adapter_pin_cb_iter_end()` (`src/adapter.c:8494`) is true once the *in-process PIN-callback chain* is
exhausted (`iter->it == NULL && iter->attempt == 0`). That chain is
`adapter->pin_callbacks`, whose only upstream registrant is the `autopair` plugin
(`plugins/autopair.c:248`). When the PIN came from a D-Bus agent rather than a plugin, the
iterator was already walked to exhaustion by `btd_adapter_pin_cb_iter_next()` before
`device_request_pincode()` was reached (`src/adapter.c:8560-8586`), so `..._iter_end()` is
true, no retry is scheduled, and the failure proceeds immediately to `bonding_complete()`.

### 2.4 The error name

`bonding_complete()` → `device_bonding_complete(status = MGMT_STATUS_AUTH_FAILED)` →
`device_bonding_failed()` (`src/device.c:7538`):

```c
	reply = new_authentication_return(bonding->msg, status);
	g_dbus_send_message(dbus_conn, reply);
	bonding_request_free(bonding);
```

and `new_authentication_return()` (`src/device.c:3442-3476`):

```c
	switch (status) {
	case MGMT_STATUS_SUCCESS:
		return dbus_message_new_method_return(msg);
	case MGMT_STATUS_CONNECT_FAILED:
		... ".ConnectionAttemptFailed", "Page Timeout"
	case MGMT_STATUS_TIMEOUT:
		... ".AuthenticationTimeout", "Authentication Timeout"
	case MGMT_STATUS_BUSY:
	case MGMT_STATUS_REJECTED:
		... ".AuthenticationRejected", "Authentication Rejected"
	case MGMT_STATUS_CANCELLED:
	case MGMT_STATUS_NO_RESOURCES:
	case MGMT_STATUS_DISCONNECTED:
		... ".AuthenticationCanceled", "Authentication Canceled"
	case MGMT_STATUS_ALREADY_PAIRED:
		... ".AlreadyExists", "Already Paired"
	default:
		return dbus_message_new_error(msg,
				ERROR_INTERFACE ".AuthenticationFailed",
				"Authentication Failed");
	}
```

`MGMT_STATUS_AUTH_FAILED` has **no case of its own** and falls to `default:`.

> **Answer to question 2: `org.bluez.Error.AuthenticationFailed`, message `"Authentication Failed"`.**

The near-miss names, for the record — none of them is the agent-rejection case:

| D-Bus error | Produced by | Meaning here |
|---|---|---|
| `.AuthenticationFailed` | `MGMT_STATUS_AUTH_FAILED` and anything unmapped | **the agent rejected / gave no PIN, or the PIN was wrong** |
| `.AuthenticationRejected` | `MGMT_STATUS_BUSY`, `MGMT_STATUS_REJECTED` | the *remote* refused pairing (HCI "Rejected Security"/"Pairing Not Allowed"), or the controller was busy |
| `.AuthenticationCanceled` | `MGMT_STATUS_CANCELLED`, `NO_RESOURCES`, `DISCONNECTED` | `Device1.CancelPairing()`, or the link dropped mid-bond |
| `.AuthenticationTimeout` | `MGMT_STATUS_TIMEOUT` | HCI/LMP timeout |
| `.AlreadyExists` | `MGMT_STATUS_ALREADY_PAIRED`, or `pair_device()`'s own `state->bonded` guard | already bonded |

This matches #39's own history exactly: pre-3.0.0, the same receiver with the same wrong/absent
PIN produced a loud `AuthenticationFailed`. That is the correct, expected, *unavoidable*
outcome of a rejected `RequestPinCode` on an outgoing `Pair()`.

**A note on error timing.** dbus-fast raises `DBusError` from `await ...call_pair()` when the
error reply arrives, and `_async_pair_device()` converts it
(`src/sp_rtk_base_relay/core/bluetooth_manager.py:632-633`:
`except DBusError as e: raise BluetoothError(f"D-Bus error during pairing: {e}")`). There is no
path on which that error is swallowed. Silence from `call_pair()` therefore is not a
"rejection that failed to surface" — it is the absence of a rejection.

---

## 3. Can `Pair()` reply success while `Paired` is false?

**No.** Enumerating every site that can produce a `METHOD_RETURN` for a `Pair` message:

### 3.1 The four success sites, each guarded

| # | Site | Guard |
|---|---|---|
| A | `device_bonding_complete()` `src/device.c:7355` | reached only after `device_set_paired(device, bdaddr_type)` at `:7345`, which sets `state->paired = true` (`:7221`) |
| B | `device_bonding_complete()` `src/device.c:7379` | same — `:7345` runs first; this arm added at 5.87, see §5 |
| C | `browse_request_complete()` `src/device.c:3100` | explicit re-check at `:3082-3085`: `if (!device_is_paired(dev, bdaddr_type)) { reply = btd_error_failed(req->msg, "Not paired"); goto done; }` |
| D | `new_authentication_return(msg, MGMT_STATUS_SUCCESS)` `src/device.c:3446` | unreachable with status 0 — see below |

Site D is the only formal way to send a method-return without touching `device_set_paired()`,
and it cannot be reached with `MGMT_STATUS_SUCCESS`. `new_authentication_return()` has exactly
two callers:

- `device_bonding_failed()` (`src/device.c:7551`), whose only in-tree callers are
  `device_bonding_complete()` at `:7331` — inside `if (status) { ... }`, so `status != 0` by
  construction — `reply_pending_requests()` (`src/adapter.c:6027`, its call at `:6039` passes
  `HCI_OE_USER_ENDED_CONNECTION` = 0x13) and `connect_failed_callback()`
  (`src/adapter.c:9932`, its call at `:9971` passes `ev->status`).
- `device_cancel_bonding()` (`src/device.c:3493`), whose callers pass literal constants:
  `MGMT_STATUS_CANCELLED` (`src/device.c:3514`, `cancel_pairing()`),
  `MGMT_STATUS_DISCONNECTED` (`src/bearer.c:179`), and
  `MGMT_STATUS_DISCONNECTED`/`MGMT_STATUS_CONNECT_FAILED` (`src/device.c:5501-5509`).

The only non-constant of those is `connect_failed_callback()`'s `ev->status`. On the kernel
side `MGMT_EV_CONNECT_FAILED` is emitted only from `mgmt_connect_failed()`
(`net/bluetooth/mgmt.c:10168`), whose callers are `hci_le_conn_failed()`/`hci_conn_failed()`
(`net/bluetooth/hci_conn.c:1399`); every ACL call site reaches it under a non-zero status —
`net/bluetooth/hci_conn.c:106` (`if (status && status != HCI_ERROR_UNKNOWN_CONN_ID)`),
`hci_conn.c:734` (`HCI_ERROR_ADVERTISING_TIMEOUT`), `hci_event.c:3287` (`if (status)`),
`hci_sync.c:5806`/`:5994`/`:7303` (abort reasons). And `mgmt_status()` maps a non-zero HCI
error to a non-zero mgmt status for every table entry (`mgmt_status_table[]` index 0 is the
only `MGMT_STATUS_SUCCESS`). So `MGMT_STATUS_SUCCESS` never reaches site D.

### 3.2 The one genuinely silent path — and it is a hang, not a success

`device_bonding_complete()` `src/device.c:7341-7343`:

```c
	/* If we're already paired nothing more is needed */
	if (state->paired)
		return;
```

Reached with `status == 0` and `state->paired` already true, this returns **without replying at
all** and without calling `bonding_request_free()`. The `Pair` message is simply never
answered.

Reachability: `pair_device()`'s early-out at `:3386` tests `state->bonded`, not
`state->paired`, and the two are separate fields of `struct bearer_state`
(`device_is_paired()` `:966` reads `state->paired`; `device_is_bonded()` `:973` reads
`state->bonded`; the D-Bus `Paired` property getter `dev_property_get_paired()` (`:1192`) reads
`dev->bredr_state.paired || dev->le_state.paired`). They diverge in exactly one place:
`new_link_key_callback()` (`src/adapter.c:8963`) calls `device_set_bonded()` at `:9003` **only** if
`ev->store_hint` is set, then unconditionally `bonding_complete(..., 0)` at `:9006` — which reaches
`device_set_paired()`. A non-persistent link key therefore leaves `paired = true,
bonded = false`, and a subsequent `Pair()` on that device gets past the `bonded` guard and
then falls into the silent return above.

That is a real BlueZ wart, but it is **not** the map's candidate 1 and not a false success:

- it needs `Paired: true` beforehand, whereas #39 reports `Paired: no`;
- `dbus_fast.aio.MessageBus.call()` imposes **no timeout** (only `introspect()` does, 30 s
  default — `dbus_fast/aio/message_bus.py:344`), so `await call_pair()` would block for the
  life of the process, not return promptly with `True`.

### 3.3 What §3 means for #39

`call_pair()` returning normally is, from BlueZ's side, a *positive assertion* that
`device_set_paired()` ran and `state->paired` is true. It is not compatible with a subsequent
`bluetoothctl info` showing `Paired: no` unless something un-paired the device in between
(`device_set_unpaired()` — `RemoveDevice`, `MGMT_EV_UNPAIRED`, a key removal).

Therefore, in #39's observed state — `Trusted: yes`, `Paired: no`, no exception raised, no
hang — the only reading consistent with this source is that **`Device1.Pair()` was never
invoked at all**. That is map #41's candidate 4 (`bluetooth_manager.py:612-616`, the "already
paired" fast path returning `True` without recording a PIN or calling `Pair()`), and this
research removes candidate 1 as an alternative explanation.

One caveat on `Paired` as read by the relay: `device_set_paired()` (`src/device.c:7234-7237`)
defers the `PropertiesChanged` signal via `dev->pending_paired` when services are not yet
resolved. The *state* is true immediately, so a direct
`org.freedesktop.DBus.Properties.Get("Paired")` — which is what
`_async_pair_device()` does — returns the true value; only a signal-cached view could lag.

---

## 4. The full outgoing-pairing timeline

For a BR/EDR legacy-PIN device, one `Device1.Pair()` from a caller with a registered agent:

```
caller           bluetoothd                        kernel / controller
  |
  |-- Pair() ------->|
  |                  | pair_device()  device.c:3343
  |                  |   bonding->msg = ref(msg)          (no reply written)
  |                  |   adapter_create_bonding()
  |                  |------------------------------> MGMT_OP_PAIR_DEVICE
  |                  |                                    HCI Create Connection,
  |                  |                                    Authentication Requested
  |                  |<----------------------------- MGMT_EV_PIN_CODE_REQUEST
  |                  | pin_code_request_callback()  adapter.c:8522
  |                  |   adapter->pincode_requested = true
  |                  |   pin_cb_iter (autopair) -> 0
  |                  |   device_request_pincode() -> new_auth() -> agent
  |<-- RequestPinCode|
  |                  |
  |     [ agent answers: PIN string, or an error ]
  |                  |
  |-- reply -------->| pincode_reply()  agent.c:455
  |                  |   error?  -> pincode_cb(err, pin=NULL)   (err DISCARDED)
  |                  | btd_adapter_pincode_reply()  adapter.c:8255
  |                  |------------------------------> MGMT_OP_PIN_CODE_(NEG_)REPLY
  |                  |
  |                  |                                    HCI Authentication Complete
  |                  |                                      status 0x05 / 0x06 on failure
  |                  |<----------------------------- MGMT_EV_AUTH_FAILED (0x05)
  |                  |                                 or MGMT_EV_NEW_LINK_KEY + cmd complete
  |                  | bonding_attempt_complete()  adapter.c:8649
  |                  |   (retry rung: only if a PIN *plugin* has another guess)
  |                  | bonding_complete() -> device_bonding_complete()  device.c:7303
  |                  |   status != 0 -> device_bonding_failed()
  |                  |                    -> new_authentication_return()
  |<-- ERROR --------|                       org.bluez.Error.AuthenticationFailed
  |                  |
  |                  |   status == 0 -> device_set_paired()  :7345
  |                  |                  -> SDP browse (device_discover_services)
  |                  |                  -> browse_request_complete()  :3068
  |                  |                       re-checks device_is_paired()
  |<-- METHOD_RETURN-|
```

The PIN round-trip is strictly *inside* the `Pair()` call window. There is no arrangement of
these events that lets the reply precede the agent's answer.

---

## 5. Version applicability, 5.51 → HEAD

Every deciding function is byte-identical across the supported range. Checked by extracting the
function bodies from each release tag and hashing them:

```
tag     new_auth_return  process_message  async_reg  pair_ret_NULL  bonding_failed  notpaired_guard
5.51    fb62613a         51e55f70         1          1              558b13aa        1
5.55    fb62613a         51e55f70         1          1              558b13aa        1
5.60    fb62613a         51e55f70         1          1              558b13aa        1
5.64    fb62613a         51e55f70         1          1              558b13aa        1
5.66    fb62613a         51e55f70         1          1              558b13aa        1
5.70    fb62613a         51e55f70         1          1              558b13aa        1
5.75    fb62613a         51e55f70         1          1              558b13aa        1
5.79    fb62613a         51e55f70         1          1              558b13aa        1
5.82    fb62613a         51e55f70         1          1              558b13aa        1
5.85    fb62613a         51e55f70         1          1              558b13aa        1
5.87    fb62613a         51e55f70         1          1              558b13aa        1
master  fb62613a         51e55f70         1          1              558b13aa        1
```

(`new_auth_return` = md5 of `new_authentication_return()`; `process_message` = md5 of
`gdbus/object.c`'s `process_message()`; `async_reg` = count of
`GDBUS_ASYNC_METHOD("Pair", NULL, NULL, pair_device)`; `pair_ret_NULL` = `return NULL;` present
in the last three lines of `pair_device()`; `bonding_failed` = md5 of `device_bonding_failed()`;
`notpaired_guard` = count of `btd_error_failed(req->msg, "Not paired")`.)

Reaching further back, `new_authentication_return()` last changed on **2015-03-11**, commit
`755d9d311677a400253f6921002784ed8729489f` — "core: Add mapping from 'Already Paired' status to
D-Bus error", first released in **5.30**. That commit only *added* the
`MGMT_STATUS_ALREADY_PAIRED` case; the `AuthenticationRejected` / `AuthenticationCanceled` /
`default: AuthenticationFailed` arms are older still. So the error-name answer holds from
5.30 onward, comfortably below the project's 5.51 floor.

### The one change in range

Commit `622a46ebcd72a511219d51366352d4cf6a46dbba`, "device: Fix returning discovery error for
Device.Pair", **first released in 5.87**, restructures the tail of `device_bonding_complete()`:

```diff
-		if (device->discov_timer) {
-			timeout_remove(device->discov_timer);
-			device->discov_timer = 0;
-		}
-
-		if (bdaddr_type == BDADDR_BREDR)
-			device_browse_sdp(device, bonding->msg);
-		else
-			device_browse_gatt(device, bonding->msg);
-
+		err = device_discover_services(device, bdaddr_type,
+						bonding->msg);
+		if (err) {
+			if (device->pending_paired) {
+				g_dbus_emit_property_changed(dbus_conn,
+							device->path,
+							DEVICE_INTERFACE,
+							"Paired");
+				device->pending_paired = false;
+			}
+			/* Disregard browse errors in case of Pair */
+			g_dbus_send_reply(dbus_conn, bonding->msg,
+						DBUS_TYPE_INVALID);
+		}
 		bonding_request_free(bonding);
```

This adds success site B in §3.1 — a direct method-return when service discovery cannot even be
*started*. It does not weaken any answer here: it is reached only after
`device_set_paired()` at `:7345`, and it makes `Pair()` *more* likely to answer promptly, never
more likely to answer success spuriously. Before 5.87 the same case would have left the message
with the browse request, which replies through the `device_is_paired()`-guarded
`browse_request_complete()`.

**Distro relevance** (same targets as `bluez-agent-dispatch.md` §5): Raspberry Pi OS Bullseye
5.55, Bookworm 5.66, Trixie 5.79+. All are ≥ 5.51 and all predate 5.87, so all take the
pre-`622a46ebc` shape — which is the *more* conservative of the two.

---

## 6. What this does and does not settle

**Settled from primary source:**

- `Pair()` never replies synchronously with success; the reply is written by the bonding-completion
  path (§1).
- An agent-rejected `RequestPinCode` yields `org.bluez.Error.AuthenticationFailed` (§2), because
  the agent's own error name is discarded and only the controller's status reaches the caller.
- No BlueZ path replies success to `Pair` while `Paired` is false (§3.1).
- All of the above hold unchanged 5.51 → HEAD (§5), and the error mapping holds from 5.30.

**Explicitly not settled here:**

- **What a controller actually returns after a negative PIN reply on this specific receiver.**
  The mapping HCI `0x05`/`0x06` → `MGMT_STATUS_AUTH_FAILED` is verified in the kernel table, and
  `hci_auth_complete_evt()` is verified to call `mgmt_auth_failed()` for any non-zero status. But
  which HCI status a given controller/peer pair emits is a firmware-and-peer question. It does
  not change the answer: **every** status other than the small mapped set lands on
  `default: AuthenticationFailed`, and the mapped alternatives
  (`REJECTED`/`CANCELLED`/`TIMEOUT`) are all still errors, never success.
- **Whether the peer might complete bonding despite a negative PIN reply.** Not reachable from
  source; would need a `btmon` capture. It would produce a success reply *with* `Paired: true`,
  so it still does not create the false-success shape.
- **Whether some non-BlueZ actor changed `Paired` between the `Pair()` reply and the
  `bluetoothctl info` read** in #39. Out of scope for source reading; §3.3 names it as the only
  remaining way a success reply could coexist with a later `Paired: no`.

---

## 7. Consequences for map #41

1. **Candidate 1 is refuted.** `call_pair()` cannot resolve before the PIN round-trip completes.
   The `GDBUS_ASYNC_METHOD` inference recorded in `bluez-agent-dispatch.md:41` was correct, and is
   now confirmed against the four sites that actually emit the reply.
2. **A successful `call_pair()` is a positive assertion that `Paired` became true.** The guard
   ticket (map note 5) should treat a post-`call_pair()` re-read as a *cross-check on the
   relay's own bookkeeping*, not as a hedge against BlueZ lying — BlueZ does not lie on this path.
3. **Silence is now positive evidence for candidate 4.** No exception + prompt return + `Paired:
   no` has exactly one explanation left in this repo's code: `Pair()` was never called, i.e. the
   `bluetooth_manager.py:612-616` fast path.
4. **The expected symptom of a genuinely rejected PIN is `AuthenticationFailed`, and #39 reports
   its absence.** That absence is the anomaly to explain, and it is explained by candidate 4 —
   which never reaches `Pair()` and so never reaches the agent, leaving `_pending_pins`
   permanently empty for the *caller-less* pairings that do reach it.
5. **A `Pair()` that hangs forever is possible** (§3.2, `paired && !bonded`), and
   `dbus_fast.aio.MessageBus.call()` has no timeout. That is not #39, but it is a real hazard for
   any future guard that calls `Pair()` unconditionally — worth a bounded `asyncio.wait_for` in
   whatever the spec lands.
