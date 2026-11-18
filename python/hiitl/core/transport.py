"""Where hiitl sends: the one check of every URL the SDK, the gateway or the hosted worker sends a credential or a
record to, a route's `endpoint` and a `server_url` alike (routes.md Validation Rules; sync_engine.md section 8;
HTL-29, rows 140 and 236). Mirrors typescript/packages/core/src/transport.ts: both read the value by its written form,
and one table of written values holds them to one answer (tests/conformance/transport/)."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Optional, Tuple

SCHEME = "https"
_WRITTEN = f"{SCHEME}://"
_DEFAULT_PORT = 443                 # https's port (RFC 9110 section 4.2.2)
_PORT_MAX = 2 ** 16 - 1             # a port is sixteen bits
_C0_SPACE, _DEL = 0x20, 0x7F        # the C0 controls and space, and DEL: no URL holds them as written
# RFC 3986 section 3.2: the authority runs to the first "/", "?" or "#", and is a userinfo of unreserved, sub-delims,
# ":" and percent-encoded characters, a host, and a port of digits. A name is read as written: unreserved and
# sub-delims characters, no percent-encoding
_NAME = r"[A-Za-z0-9\-._~!$&'()*+,;=]"
_AUTHORITY_END = re.compile(r"[/?#]")
_AUTHORITY = re.compile(rf"(?:(?:{_NAME}|%[0-9A-Fa-f]{{2}}|:)*@)?"
                        rf"(?P<host>\[[0-9A-Fa-f:.]+\]|{_NAME}+)(?::(?P<port>[0-9]*))?")
_A_LABEL = "xn--"                   # an IDNA label: the URL Standard decodes it, RFC 3986 keeps it as written
# The URL Standard reads a name whose last label is a number (decimal, or hex after 0x) as an IPv4 address, in forms
# RFC 3986 keeps as written; the one form both read alike is four decimal octets
_NUMBER = re.compile(r"[0-9]+|0[xX][0-9A-Fa-f]*")
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_DOTTED = re.compile(rf"{_OCTET}(?:\.{_OCTET}){{3}}")


def _name_as_written(name: str) -> bool:
    """Both URL parsers read this name as it is written: no IDNA label, and a name ending in a number is four decimal
    octets (the URL Standard's "ends in a number", a trailing empty label set aside)."""
    labels = name.split(".")
    if any(label[:len(_A_LABEL)].lower() == _A_LABEL for label in labels):
        return False
    last = labels[-2] if len(labels) > 1 and not labels[-1] else labels[-1]
    return not _NUMBER.fullmatch(last) or bool(_DOTTED.fullmatch(name))


def written_authority(url: Any) -> Optional[Tuple[str, int]]:
    """The host and port an `https` URL writes, or None when it writes none hiitl sends to (routes.md Validation Rules,
    "`endpoint` is an `https` URL"): the host lowercased, an IPv6 address without its brackets, the port 443 when none
    is written."""
    if not isinstance(url, str) or any(ord(c) <= _C0_SPACE or ord(c) == _DEL for c in url):
        return None
    if url[:len(_WRITTEN)].lower() != _WRITTEN:
        return None
    written = _AUTHORITY.fullmatch(_AUTHORITY_END.split(url[len(_WRITTEN):], 1)[0])
    if not written:
        return None
    host, port = written["host"], written["port"] or ""
    try:
        # A port is read once, by its value: the zeros that lead it are not digits of the number (HTL-29 review, 7)
        number = int(port.lstrip("0") or 0) if port else _DEFAULT_PORT
        if number > _PORT_MAX:
            return None
        if host.startswith("["):
            host = str(ipaddress.IPv6Address(host[1:-1]))   # an IPv6 address that is not one raises here
        elif not _name_as_written(host):
            return None
    except ValueError:      # such an address, or a port of more digits than a number is read from
        return None
    return host.lower(), number


def https_refusal(url: Any, field: str) -> Optional[str]:
    """Why `url` is not one hiitl sends to, or None: an `https` URL naming a host ("TLS everywhere. No exceptions.",
    the security requirements; sync_engine.md section 8, loopback included)."""
    if written_authority(url) is not None:
        return None
    return (f"{field} is {url!r}. hiitl sends only to an https URL naming a host as it is written, "
            f"'https://<host>': a name with no percent-encoding, non-ASCII character or 'xn--' label, four decimal "
            f"octets, or a bracketed IPv6 address (TLS everywhere, no exceptions). On your own machine, serve https on "
            f"localhost with a self-signed certificate and trust it with SSL_CERT_FILE. "
            f"Example: 'https://api.hiitl.com'")
