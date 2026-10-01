"""A release as GitHub serves it, signed like release.yml signs it, for the updater tests: a throwaway minisign key,
the release file, SHA256SUMS.txt and SHA256SUMS.txt.minisig, behind fake URLs."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
import zipfile
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from roundtable_souls import signing, updates


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


def zip_with(exe: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("RoundtableSouls.exe", exe)
        z.writestr("How to use.txt", "hi")
    return buf.getvalue()


def tar_with(program: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("RoundtableSouls")
        info.size = len(program)
        tar.addfile(info, io.BytesIO(program))
    return buf.getvalue()


@dataclass
class Release:
    """info (as check_launcher_update offers it), urls (url -> bytes), key, and fetch / fetch_file stand-ins that
    record the URLs asked for."""

    info: dict
    urls: dict[str, bytes]
    key: Key
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

    def download(self, **kw):
        kw.setdefault("key", self.key.public)
        return updates.download_update(self.info, fetch_file=self.fetch_file, fetch=self.fetch, **kw)


def make(
    name: str = updates.ASSET_NAME,
    payload: bytes | None = None,
    version: str = "99.0.0",
    signed_for: str | None = None,
    signed: bool = True,
    key: Key | None = None,
    corrupt: bool = False,
) -> Release:
    key = key or Key()
    if payload is None:
        payload = {
            updates.ASSET_NAME: lambda: zip_with(b"new exe"),
            updates.LINUX_ASSET_NAME: lambda: tar_with(b"\x7fELF new build"),
        }.get(name, lambda: b"MZ fake setup")()
    digest = "0" * 64 if corrupt else hashlib.sha256(payload).hexdigest()
    sums = f"{digest}  {name}\n{'1' * 64}  RoundtableSouls.exe\n".encode()
    urls = {f"https://x/{name}": payload, "https://x/sums": sums}
    assets = {name: f"https://x/{name}", updates.CHECKSUMS_NAME: "https://x/sums"}
    if signed:
        comment = updates.SIGNED_COMMENT.format(version=signed_for or version)
        urls["https://x/sig"] = key.sign(sums, comment).encode()
        assets[updates.SIGNATURE_NAME] = "https://x/sig"
    return Release(info={"version": version, "url": "", "assets": assets}, urls=urls, key=key)
