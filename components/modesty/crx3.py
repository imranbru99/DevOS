#!/usr/bin/env python3
"""
Minimal CRX3 packer for the DevOS Modesty filter (stdlib + `cryptography` if it
is installed, otherwise the `openssl` command line tool).

CRX3 layout (see chromium components/crx_file/crx3.proto and crx_creator.cc):

    "Cr24"                      magic
    uint32 LE  3                format version
    uint32 LE  N                length of the header that follows
    N bytes    CrxFileHeader    protobuf
    ...        the extension ZIP archive

    message CrxFileHeader {
      repeated AsymmetricKeyProof sha256_with_rsa = 2;
      repeated AsymmetricKeyProof sha256_with_ecdsa = 3;
      bytes signed_header_data = 10000;          // serialized SignedData
    }
    message AsymmetricKeyProof { bytes public_key = 1; bytes signature = 2; }
    message SignedData { bytes crx_id = 1; }     // first 16 bytes of SHA-256(public key DER)

The RSA PKCS#1 v1.5 / SHA-256 signature covers:
    b"CRX3 SignedData\\x00" + uint32 LE len(signed_header_data) + signed_header_data + zip

The extension ID is the same 16 bytes written as 32 letters a-p (one per nibble).
"""

import hashlib
import io
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile

CRX_MAGIC = b"Cr24"
CRX_VERSION = 3
SIGNATURE_CONTEXT = b"CRX3 SignedData\x00"
# Fixed timestamp so the same sources always give the same ZIP (and CRX) bytes.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)

try:  # optional fast path
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - depends on the environment
    HAVE_CRYPTOGRAPHY = False


# --------------------------------------------------------------------------- protobuf
def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field_bytes(field_number, payload):
    """Length-delimited field (wire type 2)."""
    return _varint((field_number << 3) | 2) + _varint(len(payload)) + payload


def _read_varint(buf, pos):
    shift = result = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def parse_protobuf(buf):
    """Return [(field_number, bytes)] for length-delimited fields (all CRX3 uses)."""
    fields, pos = [], 0
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire != 2:
            raise ValueError("unexpected protobuf wire type %d" % wire)
        length, pos = _read_varint(buf, pos)
        fields.append((field, bytes(buf[pos:pos + length])))
        pos += length
    return fields


# --------------------------------------------------------------------------- keys
def _pem_block(path):
    """The key file may start with comment lines; return just the PEM block."""
    with open(path, "rb") as fh:
        data = fh.read()
    match = re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", data, re.S)
    if not match:
        raise ValueError("no PEM private key in %s" % path)
    return match.group(0) + b"\n"


def _openssl():
    exe = shutil.which("openssl")
    if not exe:
        raise RuntimeError("Neither the Python 'cryptography' package nor the 'openssl' tool is available")
    return exe


def generate_key(path, comment=None):
    """Create a 2048-bit RSA key (PKCS#8 PEM) at `path`."""
    if HAVE_CRYPTOGRAPHY:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    else:
        pem = subprocess.run([_openssl(), "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
                             check=True, capture_output=True).stdout
    with open(path, "wb") as fh:
        if comment:
            for line in comment.splitlines():
                fh.write(("# " + line + "\n").encode())
        fh.write(pem)
    os.chmod(path, 0o600)


def public_key_der(key_path):
    """SubjectPublicKeyInfo DER of the key's public half."""
    pem = _pem_block(key_path)
    if HAVE_CRYPTOGRAPHY:
        key = serialization.load_pem_private_key(pem, password=None)
        return key.public_key().public_bytes(serialization.Encoding.DER,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)
    return subprocess.run([_openssl(), "pkey", "-pubout", "-outform", "DER"], input=pem,
                          check=True, capture_output=True).stdout


def sign_sha256_rsa(key_path, data):
    pem = _pem_block(key_path)
    if HAVE_CRYPTOGRAPHY:
        key = serialization.load_pem_private_key(pem, password=None)
        return key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    with tempfile.TemporaryDirectory() as tmp:
        kp = os.path.join(tmp, "k.pem")
        with open(kp, "wb") as fh:
            fh.write(pem)
        return subprocess.run([_openssl(), "dgst", "-sha256", "-sign", kp], input=data,
                              check=True, capture_output=True).stdout


def verify_sha256_rsa(pub_der, data, signature):
    """True if `signature` is valid for `data` under `pub_der` (used by the tests)."""
    if HAVE_CRYPTOGRAPHY:
        key = serialization.load_der_public_key(pub_der)
        try:
            key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:
            return False
    with tempfile.TemporaryDirectory() as tmp:
        pub, sig = os.path.join(tmp, "p.der"), os.path.join(tmp, "s.bin")
        with open(pub, "wb") as fh:
            fh.write(pub_der)
        with open(sig, "wb") as fh:
            fh.write(signature)
        res = subprocess.run([_openssl(), "dgst", "-sha256", "-verify", pub, "-keyform", "DER",
                              "-signature", sig], input=data, capture_output=True)
        return res.returncode == 0


# --------------------------------------------------------------------------- ids
def crx_id_bytes(pub_der):
    return hashlib.sha256(pub_der).digest()[:16]


def extension_id(pub_der):
    """Chrome extension ID: SHA-256 of the public key, first 128 bits, hex digits 0-f -> a-p."""
    return "".join(chr(ord("a") + int(c, 16)) for c in crx_id_bytes(pub_der).hex())


# --------------------------------------------------------------------------- packing
def zip_directory(src_dir):
    """Deterministic ZIP of `src_dir` (sorted names, fixed dates, no __pycache__/dotfiles)."""
    buf = io.BytesIO()
    entries = []
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for name in files:
            if name.startswith("."):
                continue
            full = os.path.join(root, name)
            entries.append((os.path.relpath(full, src_dir).replace(os.sep, "/"), full))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arc, full in sorted(entries):
            info = zipfile.ZipInfo(arc, ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as fh:
                zf.writestr(info, fh.read())
    return buf.getvalue()


def build_crx3(zip_bytes, key_path):
    pub = public_key_der(key_path)
    signed_header_data = _field_bytes(1, crx_id_bytes(pub))
    to_sign = SIGNATURE_CONTEXT + struct.pack("<I", len(signed_header_data)) + signed_header_data + zip_bytes
    signature = sign_sha256_rsa(key_path, to_sign)
    proof = _field_bytes(1, pub) + _field_bytes(2, signature)
    header = _field_bytes(2, proof) + _field_bytes(10000, signed_header_data)
    return CRX_MAGIC + struct.pack("<II", CRX_VERSION, len(header)) + header + zip_bytes


def parse_crx3(data):
    """Split a CRX3 file into its parts; raises ValueError if it is malformed."""
    if data[:4] != CRX_MAGIC:
        raise ValueError("not a CRX file")
    version, header_len = struct.unpack("<II", data[4:12])
    if version != CRX_VERSION:
        raise ValueError("CRX version %d, expected 3" % version)
    header = data[12:12 + header_len]
    proofs, signed = [], None
    for field, value in parse_protobuf(header):
        if field == 2:
            parts = dict(parse_protobuf(value))
            proofs.append({"public_key": parts.get(1, b""), "signature": parts.get(2, b"")})
        elif field == 10000:
            signed = value
    crx_id = dict(parse_protobuf(signed)).get(1) if signed is not None else None
    return {"version": version, "header_len": header_len, "rsa_proofs": proofs,
            "signed_header_data": signed, "crx_id": crx_id, "zip": data[12 + header_len:]}


def signed_payload(parsed):
    sh = parsed["signed_header_data"]
    return SIGNATURE_CONTEXT + struct.pack("<I", len(sh)) + sh + parsed["zip"]


def update_manifest_xml(ext_id, version, codebase):
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
            "  <app appid='%s'>\n"
            "    <updatecheck codebase='%s' version='%s' />\n"
            "  </app>\n"
            "</gupdate>\n") % (ext_id, codebase, version)
