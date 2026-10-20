"""Self-signed HTTPS certificate for the app on the local network (spec §12).

    python scripts/make_cert.py              # new certs/key.pem and certs/cert.pem
    python scripts/make_cert.py --if-needed  # only if missing, expiring or not covering the LAN IP
    python scripts/make_cert.py --print-ip   # print the laptop's current LAN IP and exit

The Subject Alternative Names cover localhost, 127.0.0.1 and the laptop's current LAN IP
(the address of the interface that holds the default route), plus any --ip given. The LAN IP
changes with the network (for example on a phone hotspot), so serve.ps1 runs this with
--if-needed before every start. A new certificate has to be accepted again on the phone.
certs/ is git-ignored.
"""

import argparse
import datetime as dt
import ipaddress
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from emotion_analyzer import config

CERTS_DIR = config.ROOT / "certs"
KEY_PATH, CERT_PATH = CERTS_DIR / "key.pem", CERTS_DIR / "cert.pem"
VALID_DAYS = 365
RENEW_DAYS = 30


def lan_ip():
    """The local address the laptop would use to reach the internet. Connecting a UDP socket
    sends nothing; it only asks the OS to pick the route. None when there is no network."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed, never contacted
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith(("0.", "127.")) else ip


def wanted_ips(extra=()):
    ips = ["127.0.0.1", *extra]
    if (ip := lan_ip()) and ip not in ips:
        ips.append(ip)
    return [ipaddress.ip_address(i) for i in ips]


def needs_new(ips):
    """Why the current certificate won't do, or None if it will."""
    if not (KEY_PATH.exists() and CERT_PATH.exists()):
        return "no certificate yet"
    cert = x509.load_pem_x509_certificate(CERT_PATH.read_bytes())
    if cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc) < dt.timedelta(days=RENEW_DAYS):
        return f"it expires on {cert.not_valid_after_utc:%Y-%m-%d}"
    covered = set(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                  .get_values_for_type(x509.IPAddress))
    if missing := [str(i) for i in ips if i not in covered]:
        return f"it doesn't cover {', '.join(missing)}"
    return None


def make(ips):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Emotion Analyzer (local)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), *map(x509.IPAddress, ips)]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    CERTS_DIR.mkdir(exist_ok=True)
    KEY_PATH.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--if-needed", action="store_true", help="keep the current certificate if it still fits")
    ap.add_argument("--print-ip", action="store_true", help="print the current LAN IP and exit")
    ap.add_argument("--ip", action="append", default=[], help="another IP address to cover (repeatable)")
    args = ap.parse_args(argv)
    if args.print_ip:
        ip = lan_ip()
        print(ip or "")
        return 0 if ip else 1
    ips = wanted_ips(args.ip)
    if lan_ip() is None:
        print("No network: the certificate covers localhost and 127.0.0.1 only.", file=sys.stderr)
    reason = needs_new(ips)
    if args.if_needed and reason is None:
        print(f"Certificate OK: {CERT_PATH.relative_to(config.ROOT)} covers localhost, {', '.join(map(str, ips))}")
        return 0
    cert = make(ips)
    print(f"New certificate ({reason or 'requested'}): {CERT_PATH.relative_to(config.ROOT)} for localhost, "
          f"{', '.join(map(str, ips))}, valid until {cert.not_valid_after_utc:%Y-%m-%d}. "
          + ("Accept it once on each phone." if reason == "no certificate yet" else "Phones have to accept it again."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
