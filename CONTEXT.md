# SP-Base-Relay

Relays RTCM correction data from a single GPS input (TCP / serial / Bluetooth / an NTRIP caster) to multiple output destinations.

## Language

**Bond**:
The long-lived pairing relationship BlueZ retains for a device, letting it reconnect without repeating the PIN/passkey exchange. Distinct from the one-time pairing process that creates it. BlueZ tracks two separate fields, which this project's own glossary previously conflated: `Device1.Paired` (the pairing exchange completed) and `Device1.Bonded` (the resulting link key was persisted). They diverge when a link key arrives with `store_hint == 0`, leaving `Paired: true, Bonded: false`. This project reads **`Paired`**, deliberately: `Bonded` was only added to the Device API in BlueZ 5.66 and the supported floor is 5.51.
_Avoid_: "Paired" as a noun for the relationship itself — reserve "pair"/"pairing" for the exchange process.

**Caller-less pairing**:
A pairing BlueZ routes to the *default* agent because no local `Pair()` call created a bonding request for it. Arises when a device initiates pairing itself, or when `Connect()` or a profile's security requirement elevates security on an unbonded device. Distinct from ordinary pairing, where the initiating caller's own agent receives the PIN request.
_Avoid_: "incoming pairing" — the distinction is the absence of a local caller, not the direction the connection was opened from.

**Force-repair**:
Discarding a device's existing bond and re-establishing it with a newly supplied PIN, for the case where the configured PIN changed after the device was already bonded. Distinct from ordinary pairing, which only applies to a device with no existing bond.
_Avoid_: "Re-pair" alone — ambiguous with a device simply reconnecting after being briefly out of range.

**Frame**:
One complete, CRC-valid RTCM 3 message as delimited by the Relay. The Relay knows a Frame's message number and length, and never what is inside it: decoding payloads is always the consumer's job.
_Avoid_: packet, message chunk, chunk (a chunk is whatever the input read returned, and may split a Frame)

**Frame subscriber**:
An in-process consumer that receives a copy of every Frame the Relay reads from its input, before any destination filtering. It never affects relaying, and it is not a destination: nothing is delivered to it on the operator's behalf, it is not configured, and it does not appear in the destination list.
_Avoid_: tap, listener, destination, sink
