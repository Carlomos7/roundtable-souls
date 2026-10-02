"""Minisign signatures: proof that a release's checksum file was made with this project's key.

The checksums prove a download arrived intact; the signature proves who published the checksums. Both minisign
signature kinds are read: "ED" (the file is hashed with BLAKE2b-512 first, minisign's default since 0.11) and the
older "Ed" (the file itself is signed). The trusted comment is covered by a second signature, so the version it
names cannot be changed either.

File format (https://jedisct1.github.io/minisign/):
  public key:  "untrusted comment: ..." then base64("Ed" + 8-byte key id + 32-byte Ed25519 key)
  signature:   "untrusted comment: ...", base64(algorithm + key id + 64-byte signature),
               "trusted comment: <text>", base64(64-byte signature over signature + text)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from roundtable_souls.resources import DATA_DIR

KEY_FILE = DATA_DIR / "release-signing.pub"
TRUSTED_PREFIX = "trusted comment: "


class SignatureError(ValueError):
    """The signature is missing, malformed, made with another key, or does not match the file."""


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes
    key: bytes

    @property
    def id_hex(self) -> str:
        return self.key_id[::-1].hex().upper()  # the way minisign prints it


def _b64(text: str, size: int, what: str) -> bytes:
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except binascii.Error, ValueError:
        raise SignatureError(f"The {what} is not valid base64.") from None
    if len(raw) != size:
        raise SignatureError(f"The {what} has {len(raw)} bytes instead of {size}.")
    return raw


def parse_public_key(text: str) -> PublicKey:
    """A key from a .pub file's text, or from the bare base64 line minisign prints."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lower().startswith("untrusted comment:")]
    if len(lines) != 1:
        raise SignatureError("A public key is one base64 line.")
    raw = _b64(lines[0], 42, "public key")
    if raw[:2] != b"Ed":
        raise SignatureError("Not a minisign Ed25519 public key.")
    return PublicKey(key_id=raw[2:10], key=raw[10:])


def release_key() -> PublicKey:
    """The key every release's checksum file is signed with (shipped inside the launcher)."""
    return parse_public_key(KEY_FILE.read_text(encoding="utf-8"))


def verify(data: bytes, signature: str, key: PublicKey) -> str:
    """Check a minisign signature of data. Returns the trusted comment; raises SignatureError otherwise."""
    lines = [ln.rstrip("\r") for ln in signature.splitlines() if ln.strip()]
    if len(lines) != 4 or not lines[0].lower().startswith("untrusted comment:"):
        raise SignatureError("The signature file does not have minisign's four lines.")
    if not lines[2].startswith(TRUSTED_PREFIX):
        raise SignatureError("The signature has no trusted comment.")
    sig = _b64(lines[1], 74, "signature")
    algorithm, key_id, body = sig[:2], sig[2:10], sig[10:]
    if key_id != key.key_id:
        raise SignatureError(f"Signed with key {key_id[::-1].hex().upper()}, not this project's key {key.id_hex}.")
    if algorithm == b"ED":
        message = hashlib.blake2b(data, digest_size=64).digest()
    elif algorithm == b"Ed":
        message = data
    else:
        raise SignatureError("Unknown signature algorithm.")
    comment = lines[2][len(TRUSTED_PREFIX) :]
    global_sig = _b64(lines[3], 64, "comment signature")
    public = Ed25519PublicKey.from_public_bytes(key.key)
    try:
        public.verify(body, message)
    except InvalidSignature:
        raise SignatureError("The signature does not match the file.") from None
    try:
        public.verify(global_sig, body + comment.encode("utf-8"))
    except InvalidSignature:
        raise SignatureError("The trusted comment was changed after signing.") from None
    return comment
