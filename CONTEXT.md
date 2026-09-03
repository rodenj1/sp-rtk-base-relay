# SP-Base-Relay

Relays RTCM correction data from a single GPS input (TCP / serial / Bluetooth) to multiple output destinations.

## Language

**Bond**:
The long-lived pairing relationship BlueZ retains for a device (reflected by `Device1.Paired`), letting it reconnect without repeating the PIN/passkey exchange. Distinct from the one-time pairing process that creates it.
_Avoid_: "Paired" as a noun for the relationship itself — reserve "pair"/"pairing" for the exchange process.

**Caller-less pairing**:
A pairing BlueZ routes to the *default* agent because no local `Pair()` call created a bonding request for it. Arises when a device initiates pairing itself, or when `Connect()` or a profile's security requirement elevates security on an unbonded device. Distinct from ordinary pairing, where the initiating caller's own agent receives the PIN request.
_Avoid_: "incoming pairing" — the distinction is the absence of a local caller, not the direction the connection was opened from.

**Force-repair**:
Discarding a device's existing bond and re-establishing it with a newly supplied PIN, for the case where the configured PIN changed after the device was already bonded. Distinct from ordinary pairing, which only applies to a device with no existing bond.
_Avoid_: "Re-pair" alone — ambiguous with a device simply reconnecting after being briefly out of range.
