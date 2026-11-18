# HTL-45 — first-call latency and startup evidence

The original scope ruling is HTL-45 `6d410ffd`, following measured stops
`c745f379` and `3939fe0b`. Its plans were `2ca20a45` and `3e84aa02`. The
single hand-back follows CC HOLD `b3f627fc`, ruling `70254bbc`, and plan
`2d10f434`; CC's record was merged without squashing at `61d4fe4f`.

The generated matrix covers all three deployment modes, JSON/YAML files, no
policy, disk cache and policy pull, both evaluation modes where valid, and the
immediate/settled/fail-closed startup paths. Each sample starts its own process;
no earlier evaluation pays for it. The real client, loader, cache, sync receipt,
evaluator and audit store run. HTTP alone is an in-process wire fixture: hosted
service and network latency are **not** measured or certified by these records.

`before.json` retains 1,200 fresh processes (2,400 evaluations), twelve per case
at both 5485345d and e949cc1a in both SDKs. Python's first RESPECT_POLICY JSON
call rose from median 4.363 to 17.146 ms; YAML rose from 4.450 to 17.613 ms.
All twelve head samples in each local file case failed the existing target.
The original diagnostic and failed pilot receipts remain named in
`measurement-record.json`.

The scope is now stated by the latency targets: hybrid `evaluation_ms` reads
the typical-core declaration; the whole local/hybrid call reads the pure-local
declaration. A declared cold-start sync wait is separate. No new limit or
allowed-failure count was added. A warm disk/file first call is immediate and
must read the supplied version. The TypeScript fail-closed cold case calls
`evaluate()` immediately: its wall time and the actual startup wait within it
are both retained; only that wait is excluded from the latency assertion.

| Run | Python | TypeScript |
| --- | --- | --- |
| Original measurement cells, before scope ruling | 3 passed, 4 latency failures, 18 unread declarations | 7 passed, 18 unread declarations |
| Ruled cells, before production changes | 16 passed, 10 failed | 23 passed, 3 failed |
| Original submission, before CC's HOLD | 26 passed | 26 passed |

The ruled Python red includes a disk-case latency sample as well as deferred
loads and constructor-error differences. TypeScript's red catches the empty
immediate disk view and stale file readings. These failures are not relabelled
as all being latency failures.

`after.json` is the original submission's historical record: 600 fresh processes and
1,200 evaluations. `after-summary.json` gives per-case min/median/max, as
measurements rather than new limits. That submission's local JSON/YAML first-call
medians are 3.229/3.270 ms. The setup still costs time: construction medians are
15.090/15.510 ms on those cases. The declarations and file reading are prepared
at construction; each call's own admission remains inside its clock.

`file-observations-after.json` holds 80 paired observations: missing,
unreadable and unparsable files at construction and afterwards; permission
changes and rewrites keeping mtime; valid same-size rewrites and atomic
replacements keeping mtime. Construction refuses with PolicyLoadError. Later
failures return and record POLICY_ERROR. A valid replacement decides by its
new version. That submission's unchanged-file cells did not reach Linux's same-timestamp rewrite; CC's HOLD records that missing case. The older
`file-observations-python.json` and `file-observations-typescript.json` remain
historical measurements, not expected answers derived from either SDK.

Reproduce with `generate_cases.py`, then each SDK's `test_fresh_process` /
`fresh-process.test.ts` suite. The TypeScript suite builds both current packages
in a private directory; old dist files or another tree's core cannot hide a
mutation. `measure.py ROOT LANGUAGE OUTPUT` is the standalone measurement;
for TypeScript supply `--node NODE` and build that root's core and SDK first.
`file_probe.py` / `file_probe.mjs ROOT` exercise the expanded ruled file class.

The original private review record carries its full-suite counts, the 182
reached mutation results, source-binding controls and retained failed attempts. The Python
external MCP stdio integration remains qualified: its optional git-server
package is absent. No public repository or registry was changed. Cost: $0.


## Single hand-back after CC's HOLD

The spec now names p95 for a declared latency target. First and repeated calls
are separate populations. Twenty fresh processes are derived from the first
sample count at which nearest-rank p95 is below the maximum; the value still
uses canon's existing linear interpolation at `(n−1)×p`. No rounding or extra
tolerance is used for comparison. Producer instrumentation runs separately from
those timing populations, so observing schema construction cannot inflate the
latency gate.

Both SDKs build the reached declaration and parser setup during construction,
before the first sync cycle. Python prepares the decision/remediation, policy,
rule and route readers; TypeScript prepares every declared schema child, including
Zod's first-object parser compilation. Actual admission, evaluation and audit work
stay on the call path. The interpreter's switch interval is unchanged.

A file reading is confirmed by content while the file's change timestamp and the
read timestamp cannot distinguish a later rewrite. The read timestamp is observed
from an inode on the same filesystem, before reading the source; wall-clock
precision is not assumed to equal filesystem timestamp precision. A tied or
unavailable clock keeps content confirmation. Identical content retains the admitted
model. Once timestamps distinguish later rewrites, unchanged metadata reuses it
without content I/O. No policy-directory write permission or fixed duration is
introduced. Controlled-clock cells cover ties and later unchanged reads; an actual
filesystem probe retains the metadata and decision for every rewrite.

The permission cell reads the damaged file using the current process's own
permissions before deciding its expected answer. The private Linux workflow
also runs the hard-coded non-root-expectation mutation as root.

The runner workflow reads its seven runtimes from the public matrix and runs
only in the private repository. It preserves the actual runner image, kernel,
source tree, raw observations, first and repeated p95 margins, and separately
instrumented profiles. No runner result is inferred from a Colima projection.
The hand-back's final receipt belongs in the private evidence record; the old
`after.json` remains unchanged so the original HOLD is reproducible.
