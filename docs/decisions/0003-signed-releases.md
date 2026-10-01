# 0003 Release feeds are signed with minisign

**Status:** in use from the release after 3.13.2.

## Decision

Every release carries, for each system, Velopack's feed (`releases.win.json`, `releases.linux.json`) and a minisign
signature of it (`.minisig`), made in the release workflow with the key in the `MINISIGN_KEY` repository secret, with
the trusted comment `roundtable-souls <version> <os>`. `SHA256SUMS.txt` (every file) is signed too, with
`roundtable-souls <version>`, for people checking downloads by hand.

The launcher ships the public key (`src/roundtable_souls/data/release-signing.pub`, key ID `7E6CB2F456375629`) and
Update now (`updates.download_update`) installs nothing unless:

- the feed's signature verifies with that key (both minisign signature kinds are accepted;
  `src/roundtable_souls/signing.py`);
- the trusted comment, which the signature also covers, names the version being installed and this system;
- that version is newer than the running copy and has not failed to start here before;
- every entry is for this launcher's app ID, with a plain file name, a size and a SHA-256;
- every package downloaded (the full package, or the delta when this copy is exactly one version behind and holds
  its base) matches the size and SHA-256 of its entry.

Velopack is then pointed at a local folder holding only those packages and a feed made of entries copied verbatim
from the signed one; that folder is checked again just before it is applied (`updates.verify_prepared`). Velopack
compares each package with the same hashes once more before applying it.

## Why

A feed's hashes alone prove a download arrived intact, not who published it: the packages and the feed come from the
same place, so whoever can replace one can replace both. Velopack trusts its feed as it finds it; signing the feed
ties every hash in it to a key that never leaves the repository's secrets. Naming the version and system in the signed
comment means an older release's (or the other system's) validly signed feed cannot be served as this one's, and
refusing versions that are not newer stops a downgrade to a release with a known problem.

minisign was chosen over Sigstore/cosign because verifying it needs only Ed25519 (the `cryptography` package the
launcher already uses) and one 56-character public key, with no network access or transparency-log lookup at update
time. The verifier is tested against signatures made by minisign 0.12 itself (`tests/unit/data/minisign`), and the
release workflow verifies every signature with the minisign program before and after uploading.

Code signing of the programs (Authenticode) is a separate matter and is not done: it would reduce Windows SmartScreen
prompts on a first download, but does not change what Update now trusts.

## Replacing the key

If the secret key is lost or exposed:

1. Make a new pair without a password: `minisign -G -W -p roundtable-souls.pub -s roundtable-souls.key`, outside the
   repository. Keep an offline copy of the `.key` file.
2. Put the `.pub` file's contents in `src/roundtable_souls/data/release-signing.pub` and update the key ID above.
3. Set the secret: `gh secret set MINISIGN_KEY < roundtable-souls.key`.
4. Release. Copies older than this release only trust the old key: an exposed key can sign for them until they update,
   so say so in the release notes and ask for a manual update from the releases page. A lost (not exposed) key only
   means those copies are sent to the releases page for this one update.

## Reopen if

minisign's format changes, or the project moves to a signing service that also covers the program files themselves.
