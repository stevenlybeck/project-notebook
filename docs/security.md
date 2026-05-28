# Project Notebook — Hub Security Model

The hub serves three classes of caller with different reachability and
trust. Each is served on its own listener, so a route is simply *absent*
on listeners where it shouldn't be reachable — defense in depth by
construction rather than present-but-guarded.

Baseline being hardened: today the hub does `web.run_app(app, port=9999)`,
which binds **all interfaces with no auth** — every route, including
`register`, is currently open to the whole LAN.

## The three planes

| Plane | Listener | Reachable by | Authorization | Routes |
| ----- | -------- | ------------ | ------------- | ------ |
| **Local commands** | Unix domain socket `~/.project-notebook/hub.sock` (mode `0600`) | Owner process on this machine | Filesystem permissions | `register`, `unregister`, `status`, `devices`, `pair` (initiate) |
| **Phone API** | TCP `0.0.0.0:9999` | Any LAN device | Bearer device token | `ingest`, `pair` (complete) |
| **Web UI** | TCP `127.0.0.1:<port>` | Browser on this machine | Loopback bind + Host-header check | UI page + read-only `projects`, `uploads` |

One process, three aiohttp listeners (`AppRunner` + `UnixSite` + two
`TCPSite`s) sharing in-memory state.

## Plane 1 — local commands (Unix domain socket)

Reachability *and* authorization both come from filesystem permissions:
"can you open this file?" is gated by the OS, owner-only. No tokens to
manage. A UDS is unreachable over the network and unreachable from a
browser (browsers can't open a UDS), so it is immune to the
DNS-rebinding / CSRF class entirely.

The alternative — loopback TCP + a token file (Jupyter-style) — is
strictly weaker: any local process/user can reach `127.0.0.1`, and a
malicious webpage can attempt requests to it. The only cost of UDS is
minor client plumbing, already solved by `aiohttp.UnixConnector(path=…)`
or `httpx` with a `uds=` transport.

## Plane 2 — phone API (LAN-reachable, bearer token)

The only plane exposed off-box, so it carries the real auth.

- The phone never needs `register`/`status`, so those are **not** served
  here — only `ingest` and `pair` completion.
- **Auth:** a bearer device token minted at pairing. The phone stores it
  in the Keychain and sends `Authorization: Bearer <token>`; the hub
  validates against its persisted device registry.
- **Pairing code:** short-lived (~60–120s) and single-use, so a LAN
  attacker can't brute-force it during the QR window. The code is
  exchanged once at `pair` completion for the long-lived device token.
- **Per-device tokens + revocation:** one token per device so a lost
  phone can be revoked (`devices`) without affecting the others.

### Threats and v1 stance

- **Plaintext on LAN** — the token is sniffable on the wire. This is the
  documented "trusted home network" v1 tradeoff. TLS or a Tailscale-style
  overlay is the eventual fix (see [PLAN.md](../PLAN.md) deferred items).
- **Path traversal in `ingest`** — the destination is currently built as
  `artifacts_dir / filename` straight from client input, so a filename
  like `../../…` or an absolute path escapes the artifacts dir. Must use
  `Path(filename).name` to strip directory components. This is a live bug
  in the current code, independent of auth.

## Plane 3 — web UI (loopback, read-only)

Loopback binding stops LAN devices, but **not** a browser on this machine
being tricked via DNS rebinding (the request originates from localhost).
So:

- **Host-header check** — reject anything whose `Host` isn't
  `localhost` / `127.0.0.1:<port>`.
- **Read-only** — no mutating endpoints on this plane.

## Why the split is more than cosmetic

Every *mutating local* operation lives on the UDS, and browsers cannot
open a UDS. So CSRF / DNS-rebinding against the dangerous operations is
**impossible by construction**, not merely guarded. The web UI can only
read; the LAN API requires a token; the dangerous operations are on a
channel that neither the network nor the browser can reach.

## Discovery vs. authentication

The hub advertises itself on the LAN via Bonjour / mDNS-SD as
`_notebook._tcp.local`, so the phone can find it without a hardcoded IP
(resilient to DHCP reassignment and network changes; falls back to a
manually entered URL when multicast is blocked — guest wifi, client
isolation, or across subnets).

**Discovery is not authentication, and the two must stay orthogonal.**
mDNS is unauthenticated — *any* device on the link can advertise
`_notebook._tcp.local`, including a malicious one impersonating the hub.
So "found via Bonjour" must never imply "trusted":

- **Bonjour answers** *where is the hub* — a convenience for locating an
  endpoint.
- **Pairing answers** *can these two trust each other* — the actual trust
  decision.

The trust anchor is the pairing code the user physically initiates
(`notebook pair` → QR), exchanged once for a long-lived device token — not
the discovered endpoint. The phone must not auto-trust a discovered hub;
it completes pairing against whatever endpoint it connects to, and from
then on both sides authenticate by token. Treating "discovered" as
"trusted" would let an impersonator collect a pairing or receive uploads.

## Relationship to persisted state

Device tokens persist alongside the project registry (see the durable
state work — `state.json` / a `devices.json` in `~/.project-notebook/`),
so pairings survive a hub restart the same way registrations do.
