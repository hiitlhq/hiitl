/**
 * Where hiitl sends: the one check of every URL the SDK sends a credential or a record to, a route's `endpoint` and a
 * `server_url` alike (routes.md Validation Rules; sync_engine.md section 8; HTL-29, rows 140 and 236). Mirrors
 * python/hiitl/core/transport.py: both read the value by its written form, and one table of written values holds them
 * to one answer (tests/conformance/transport/).
 */

export const SCHEME = 'https';
const WRITTEN = `${SCHEME}://`;
const C0_SPACE = 0x20;         // the C0 controls and space, and DEL: no URL holds them as written
const DEL = 0x7f;
// RFC 3986 section 3.2: the authority runs to the first "/", "?" or "#", and is a userinfo of unreserved, sub-delims,
// ":" and percent-encoded characters, a host, and a port of digits. A name is read as written: unreserved and
// sub-delims characters, no percent-encoding
const NAME = "[A-Za-z0-9\\-._~!$&'()*+,;=]";
const AUTHORITY_END = /[/?#]/;
const AUTHORITY = new RegExp(`^(?:(?:${NAME}|%[0-9A-Fa-f]{2}|:)*@)?(\\[[0-9A-Fa-f:.]+\\]|${NAME}+)(?::[0-9]*)?$`);
const A_LABEL = 'xn--';        // an IDNA label: the URL Standard decodes it, RFC 3986 keeps it as written
// The URL Standard reads a name whose last label is a number (decimal, or hex after 0x) as an IPv4 address, in forms
// RFC 3986 keeps as written; the one form both read alike is four decimal octets
const NUMBER = /^(?:[0-9]+|0[xX][0-9A-Fa-f]*)$/;
const OCTET = '(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])';
const DOTTED = new RegExp(`^${OCTET}(?:\\.${OCTET}){3}$`);

/**
 * Both URL parsers read this name as it is written: no IDNA label, and a name ending in a number is four decimal
 * octets (the URL Standard's "ends in a number", a trailing empty label set aside).
 */
function nameAsWritten(name: string): boolean {
  const labels = name.split('.');
  if (labels.some((label) => label.slice(0, A_LABEL.length).toLowerCase() === A_LABEL)) return false;
  const last = labels.length > 1 && !labels[labels.length - 1] ? labels[labels.length - 2] : labels[labels.length - 1];
  return !NUMBER.test(last) || DOTTED.test(name);
}

/**
 * The value writes `https://` and then its authority as RFC 3986 writes one, holds no control character, space or DEL,
 * and its host is read as written and any written port is read (routes.md Validation Rules, "`endpoint` is an `https`
 * URL").
 */
function hostNamed(url: string): boolean {
  for (let i = 0; i < url.length; i++) {
    const code = url.charCodeAt(i);
    if (code <= C0_SPACE || code === DEL) return false;
  }
  if (url.slice(0, WRITTEN.length).toLowerCase() !== WRITTEN) return false;
  const written = AUTHORITY.exec(url.slice(WRITTEN.length).split(AUTHORITY_END, 1)[0]);
  if (!written) return false;
  if (!written[1].startsWith('[') && !nameAsWritten(written[1])) return false;
  try {
    new URL(url);   // an IPv6 address or a port that is not one throws here
    return true;
  } catch {
    return false;   // not a URL
  }
}

/**
 * Why `url` is not one hiitl sends to, or null: an `https` URL naming a host ("TLS everywhere. No exceptions.",
 * the security requirements; sync_engine.md section 8, loopback included).
 */
export function httpsRefusal(url: unknown, field: string): string | null {
  if (typeof url === 'string' && hostNamed(url)) return null;
  return `${field} is ${JSON.stringify(url)}. hiitl sends only to an https URL naming a host as it is written, ` +
    "'https://<host>': a name with no percent-encoding, non-ASCII character or 'xn--' label, four decimal octets, " +
    'or a bracketed IPv6 address (TLS everywhere, no exceptions). On your own machine, serve https on localhost ' +
    "with a self-signed certificate and trust it with NODE_EXTRA_CA_CERTS. Example: 'https://api.hiitl.com'";
}
