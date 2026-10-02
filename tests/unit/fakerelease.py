"""A release as GitHub serves it, signed like release.yml signs it, for the updater tests: a throwaway minisign key,
Velopack packages (bytes standing in for .nupkg files), releases.<os>.json and its signature, behind fake URLs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from roundtable_souls import signing, updates
from roundtable_souls.config import identity

PACK = identity.get().pack_id


@dataclass
class Key:
    private: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    key_id: bytes = field(default_factory=lambda: os.urandom(8))

    @property
    def public(self) -> signing.PublicKey:
        raw = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return signing.PublicKey(key_id=self.key_id, key=raw)

    def sign(self, data: bytes, comment: str) -> str:
        """A minisign signature in the default (prehashed) form."""
        body = self.private.sign(hashlib.blake2b(data, digest_size=64).digest())
        line = base64.b64encode(b"ED" + self.key_id + body).decode()
        glob = base64.b64encode(self.private.sign(body + comment.encode())).decode()
        return f"untrusted comment: test\n{line}\ntrusted comment: {comment}\n{glob}\n"


def entry(version: str, kind: str, data: bytes) -> dict:
    suffix = "" if updates.OS_CHANNEL == "win" else "-linux"
    return {
        "PackageId": PACK,
        "Version": version,
        "Type": kind,
        "FileName": f"{PACK}-{version}{suffix}-{kind.lower()}.nupkg",
        "SHA1": hashlib.sha1(data).hexdigest().upper(),
        "SHA256": hashlib.sha256(data).hexdigest().upper(),
        "Size": len(data),
    }


@dataclass
class Release:
    """info (as check_launcher_update offers it), urls (url -> bytes), key, the feed's entries, and fetch /
    fetch_file stand-ins that record the URLs asked for."""

    info: dict
    urls: dict[str, bytes]
    key: Key
    full: dict
    delta: dict | None
    calls: list[str] = field(default_factory=list)

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.urls:
            raise updates.UpdateError(f"404 {url}")
        return self.urls[url]

    def fetch_file(self, url, part, progress=None):
        self.calls.append(url)
        data = self.urls[url]
        part.write_bytes(data)
        if progress:
            progress(len(data), len(data))
        return hashlib.sha256(data).hexdigest()

    def download(self, base_available=lambda feed, current: False, **kw):
        kw.setdefault("key", self.key.public)
        kw.setdefault("current", "1.0.0")
        return updates.download_update(
            self.info, fetch_file=self.fetch_file, fetch=self.fetch, base_available=base_available, **kw
        )


def make(
    version: str = "99.0.0",
    base: str | None = "98.0.0",
    signed_for: str | None = None,
    channel: str | None = None,
    key: Key | None = None,
    with_delta: bool = True,
    feed_edit=None,
    package_edit=None,
    signed: bool = True,
) -> Release:
    """A release of version whose delta was made against base. feed_edit(doc) changes the feed after signing (an
    attacker without the key); package_edit(bytes) changes the full package on the server."""
    key = key or Key()
    full_bytes = f"full package {version}".encode() * 50
    delta_bytes = f"delta {base}->{version}".encode() * 5
    full = entry(version, "Full", full_bytes)
    assets_feed = [full]
    delta = None
    urls = {}
    if with_delta and base:
        delta = entry(version, "Delta", delta_bytes)
        assets_feed += [delta, entry(base, "Full", f"full package {base}".encode() * 50)]
        urls[f"https://x/{delta['FileName']}"] = delta_bytes
    raw = json.dumps({"Assets": assets_feed}).encode()
    comment = updates.SIGNED_COMMENT.format(version=signed_for or version, channel=channel or updates.OS_CHANNEL)
    sig = key.sign(raw, comment).encode()
    if feed_edit:
        doc = json.loads(raw)
        feed_edit(doc)
        raw = json.dumps(doc).encode()
    urls[f"https://x/{full['FileName']}"] = package_edit(full_bytes) if package_edit else full_bytes
    urls["https://x/feed"] = raw
    assets = {name.rsplit("/", 1)[-1]: url for url, name in ((u, u) for u in urls if u.endswith(".nupkg"))}
    assets[updates.FEED_NAME] = "https://x/feed"
    if signed:
        urls["https://x/sig"] = sig
        assets[updates.SIGNATURE_NAME] = "https://x/sig"
    info = {"version": version, "url": "", "assets": assets}
    return Release(info=info, urls=urls, key=key, full=full, delta=delta)
