# Decision records

Why some of the launcher's behaviour (file formats, releases) is the way it is: what was decided, what it rests on, and what
would reopen it. One file per decision, numbered in order. A later record supersedes an earlier one by saying so;
records are not rewritten afterwards.

| No. | Decision | Status |
|---|---|---|
| 0001 | [regulation.bin is compressed with a 64 KB zstd window](0001-regulation-zstd-window.md) | in use since 3.13.2 |
| 0002 | [Merged Oodle files stay at level 6 (6/6)](0002-kraken-layout-speed.md) | in use since 3.13.1 |
| 0003 | [Release feeds are signed with minisign](0003-signed-releases.md) | in use from the release after 3.13.2 |
| 0004 | [Velopack installs and applies updates; the launcher decides what to trust and undoes failed starts](0004-velopack.md) | in use from the release after 3.13.2 |
