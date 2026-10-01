# 0003 Release checksums are signed with minisign

**Status:** in use from the release after 3.13.2.

## Decision

Every release carries `SHA256SUMS.txt.minisig`: a minisign signature of `SHA256SUMS.txt`, made in the release
workflow with the key in the `MINISIGN_KEY` repository secret, with the trusted comment `roundtable-souls <version>`.
The launcher ships the public key (`src/roundtable_souls/data/release-signing.pub`, key ID `7E6CB2F456375629`) and
Update now refuses a release unless:

- the signature verifies with that key (both minisign signature kinds are accepted; `src/roundtable_souls/signing.py`),
- the trusted comment, which the signature also covers, names the version being installed, and
- that version is newer than the running copy.

Only then is the downloaded file's SHA-256 compared with the signed list. A release without a signature is offered as
a download from the releases page, never installed by Update now.

## Why

The checksums alone prove that a download arrived intact, not who published it: the release file and its checksum
file come from the same place, so whoever can replace one can replace both. The signature ties the checksums to a key
that never leaves the repository's secrets. Naming the version in the signed comment means an older release's
validly signed checksums cannot be served as a newer release's, and refusing versions that are not newer stops a
downgrade to a release with a known problem.

minisign was chosen over Sigstore/cosign because verifying it needs only Ed25519 (the `cryptography` package the
launcher already uses) and one 56-character public key, with no network access or transparency-log lookup at update
time. The verifier is tested against signatures made by minisign 0.12 itself (`tests/unit/data/minisign`), and the
release workflow verifies every signature with the minisign program before and after uploading.

Code signing of the exe and the setup (Authenticode) is a separate matter and is not done: it would reduce Windows
SmartScreen prompts on a first download, but does not change what Update now trusts.

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
