"""Pairing primitives: device tokens and short-lived pairing codes.

A device token is long-lived and authenticates a phone on every request.
A pairing code is single-use and short-lived; the phone exchanges it once
for the token (see the hub's /api/pair endpoint).
"""

import io
import re
import secrets
import socket
import subprocess

PAIRING_TTL = 90  # seconds a pairing code stays valid


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_code() -> str:
    return secrets.token_urlsafe(9)


def new_device_id() -> str:
    return secrets.token_hex(4)


def lan_ip() -> str:
    """Single best-effort IP — the default-route source. No packets are sent
    (a connected UDP socket just populates the local endpoint)."""
    return _route_source("8.8.8.8") or "127.0.0.1"


_INET_RE = re.compile(r"^\s*inet\s+(\d+\.\d+\.\d+\.\d+)\b")


def lan_addresses() -> list[str]:
    """All non-loopback IPv4 addresses on this machine, default-route first.

    Used by `pair` so the QR can encode every address the phone might be able
    to reach (LAN, Tailscale, other VPNs, …); the phone tries each. The
    default route comes first so the common case succeeds without delay.
    """
    addrs: list[str] = []
    try:
        result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=2)
        for line in result.stdout.splitlines():
            m = _INET_RE.match(line)
            if m and _is_routable(m.group(1)):
                addrs.append(m.group(1))
    except (OSError, subprocess.SubprocessError):
        pass

    primary = lan_ip()
    if primary != "127.0.0.1":
        if primary in addrs:
            addrs.remove(primary)
        addrs.insert(0, primary)

    seen: set[str] = set()
    return [a for a in addrs if not (a in seen or seen.add(a))]


def _route_source(target: str) -> str | None:
    """The local source IP the kernel would use to reach ``target``."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _is_routable(ip: str) -> bool:
    """Exclude loopback (127/8) and link-local (169.254/16)."""
    try:
        a, b, *_ = (int(p) for p in ip.split("."))
    except ValueError:
        return False
    if a == 127:
        return False
    if a == 169 and b == 254:
        return False
    return True


def render_qr(data: str) -> str:
    import segno
    buf = io.StringIO()
    segno.make(data).terminal(buf, compact=True)
    return buf.getvalue()
