"""Pairing primitives: device tokens and short-lived pairing codes.

A device token is long-lived and authenticates a phone on every request.
A pairing code is single-use and short-lived; the phone exchanges it once
for the token (see the hub's /api/pair endpoint).
"""

import io
import secrets
import socket

PAIRING_TTL = 90  # seconds a pairing code stays valid


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_code() -> str:
    return secrets.token_urlsafe(9)


def new_device_id() -> str:
    return secrets.token_hex(4)


def lan_ip() -> str:
    """Best-effort primary LAN IP for the QR URL (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # selects the default route's interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def render_qr(data: str) -> str:
    import segno
    buf = io.StringIO()
    segno.make(data).terminal(buf, compact=True)
    return buf.getvalue()
