---
status: accepted
---

# Frame subscribers are not destinations, and the Relay never decodes Frames

`sp-rtk-base` needs to see the RTCM the receiver is producing while the
Relay owns the serial port: its Signal Quality indicator decodes C/N0 from
MSM messages. Until now the only way anything left the Relay was through a
destination, and the Relay had no in-process hook at all.

So `RelayEngine` gains a **Frame subscriber** API
(`subscribe_frames(message_ids=None)`), synchronous in the same style as
`subscribe_events()`. A subscriber receives a copy of every Frame the Relay
reads from its **input**, before any destination filtering, optionally
narrowed to a set of message IDs. Its queue is bounded and drops when full,
counted in `RelayStatus`; it never blocks the hub, which is the same
fault-isolation guarantee destinations have. While any subscriber exists the
hub delimits Frames even when every destination is pass-all; pass-all
destinations still receive raw chunks, so relaying itself is unchanged. A
subscription belongs to one engine instance and ends with it.

Two lines are drawn deliberately:

- **A Frame subscriber is not a destination.** A destination is somewhere
  the Relay delivers corrections on the operator's behalf: configured,
  listed, reconnected, reported on the dashboard. A subscriber is none of
  those. Modelling it as a destination type would put a phantom row in the
  operator's destination list and in the config file.
- **The Relay never decodes a Frame's payload.** It knows a Frame's
  message number and length, and stops there, as `RTCMMessageDecoder`
  always has. Decoding (`pyrtcm`, MSM C/N0, anything vendor- or
  purpose-specific) is the subscriber's job. This keeps the Relay a thing
  that moves RTCM, not one that interprets it.

## Considered Options

- **A loopback `tcp_server` destination** that `sp-rtk-base` connects to.
  Needs no Relay change, but spends a socket re-framing bytes that are
  already in the same process, and is visible to the operator as a
  destination they didn't configure. Rejected.
- **Decoding MSM inside the Relay** and exposing C/N0 in `RelayStatus`.
  Rejected: it pulls a decoder dependency and Signal Quality policy into a
  library whose scope is relaying.
- **A raw-chunk subscription** with the consumer re-framing. Rejected:
  every consumer would reimplement framing and CRC the Relay already does.
