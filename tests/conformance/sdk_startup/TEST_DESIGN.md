# HTL-45 — a fresh process's first evaluation

Read 2026-11-16: decision_response.md Timing Metadata and Error Handling;
sync_engine.md Numeric domain and Startup Behavior; both SDK configuration
pages. Box: SDK/ingest and decision planes (proposed).
The plan is HTL-45 `2ca20a45`. This measures before changing production code.

The deployment modes come from the configuration pages' auto-detection table;
the local and hybrid policy sources come from sync_engine.md Startup Behavior
and the held-policy sentence: none, file, disk cache and received policy. Hosted
evaluation has a service-owned policy, not a local SDK policy source. Both
evaluation modes are exercised where valid. JSON and YAML file paths are paired.

Every sample starts a separate interpreter. Imports and client construction are
measured separately from the first and next evaluate calls. Disk data is written
as a stored wire artifact before the child starts; constructing another SDK to
prime that cache in the measured process would invalidate the test. A pull goes
through the actual sync client, admission, engine and cache. Only HTTP transport
is a fixture; it never contacts a real service. The hosted record measures SDK
overhead with a fixed wire decision, not a production service/region guarantee.
Both the HTTP transport fixture and the absence of network time are reported.
Background sync is real. No resolver, loader, evaluator or admission is mocked.

The original record used twelve fresh processes, matching CC's diagnostic
on HTL-17 `4b818c3d`. The hand-back (70254bbc) reads p95 and derives twenty
samples: the smallest n where ceil(.95*n) < n. The existing shared percentile
interpolation is unchanged; first and repeated calls are separate populations.
Both calls are retained, even if they fail. The original record
at 5485345d and the feature head uses the same runner and fixture bytes. Bounds
are read from the owning sentences, with no tolerance or local fallback.

HTL-45 6d410ffd resolves the measured stops. Hybrid evaluation_ms reads the
typical-core declaration; the whole local/hybrid call reads the pure-local
declaration. No new number is introduced. Cold-start network startup is timed
separately: the TypeScript cell waits for the real initial-sync promise before
the timed call when no disk/file source is present. A separate first-call
fail-closed observation records its real in-call wait and decision. Neither
path warms an evaluation. The old immediate observations remain in before.json.
Disk/file first calls are immediate: they must read that policy, never the empty
set. The policy's guard decides BLOCK in RESPECT_POLICY and OBSERVE in
OBSERVE_ALL; its version is v1.0.0. Empty sets retain their declared behavior.

Each fresh-process file cell also counts real content reads by phase: the
constructor must read the supplied file. An unchanged file must not be reread
once platform timestamps distinguish a later rewrite; within that window its
content is confirmed. This gives the restored first-call-load
mutation a behavioral assertion independent of the host's speed. TypeScript
children run a private build of both packages' current source, so an old dist
or a dependency linked into another tree cannot hide a mutation.

After the measurement, spec text precedes the generated cells and fix. Error
cells pair missing, unreadable and unparsable files at construction and after it,
including an unchanged-mtime permission change, an invalid rewrite, a same-size
valid rewrite and an atomic replacement that retain mtime. Construction refuses
invalid files with PolicyLoadError; a later failure returns and records
POLICY_ERROR. A valid replacement immediately decides by the new policy.
Metadata is tested on CI's Linux/macOS matrix; no Windows timestamp guarantee
is inferred from Unix ctime. Retained decisions and records must remain the ones
Error Handling declares; a change stops in the ruling form.
The original cached-policy test runs alone and in suite order. Each SDK receives
a first-call-load mutation that the fresh-process cell must catch by assertion.
Full reached SDK/core and conformance suites and mutation controls complete the
evidence. A timing measurement never substitutes for an enforcement assertion.

## Single hand-back, 70254bbc (read 2026-11-17)

The plan is 2d10f434; CC's record is merged at 61d4fe4f. A separate producer
observation uses the same generated mode/source taxonomy and fresh processes:
Python schema/declaration builders and TypeScript schema conversion/parser
compilation are counted at their actual producers, including the first real
background sync cycle. They must build none after construction. The observation
does not pre-import a dependency or run an evaluation to warm it. Producer-only observations
read no elapsed clock. Uninstrumented samples are recorded; release mode asserts their latency.

The same construction rule reaches a directly constructed core evaluator. Its
fresh-process cell observes parser producers without constructing an SDK first;
otherwise the SDK constructor would conceal that core entry's lazy setup. The
first complete run at 764a8d3e exposed it in the typical-core p95 cell (1.100786 ms
against 1 ms). The direct producer cell is red before its construction fix, and a
mutation removing that preparation is caught. Actual per-call admission remains
inside the core's clock; no warm-up evaluation or wider target replaces it.

File cells exercise a same-size rewrite before the timestamp clock advances,
including restored mtime, then an unchanged reading after it advances. They
check the policy answer and retained model identity, content-read counts and
actual stat values. A controlled coarse clock makes this deterministic on
fine-grained filesystems; the Linux record also uses real filesystem operations.
No sleep or grace-period constant defines cache validity. Read-only source
directories and inability to obtain a clock observation must not create a new
permission requirement on policy files. Permission probes record their own
open/read attempt; mode 000 alone cannot determine an expectation.

The p95 helper is checked using deliberately mixed samples so reading one sample
or demanding every sample fails independently of host timing. Every existing
assertion against a declared latency target uses p95; unsupported measurements
remain measurements. The original cached-policy cell runs alone and in suite
order. Mutations remove construction-time setup, restore metadata-only reuse,
read a single sample and hard-code the non-root permission answer. The permission
mutation is exercised as root as well as the non-root controls.

Private GitHub-hosted Linux runs read the public workflow's runtime matrix.
The runner record names its source tree, kernel, runtime, identity, all samples
and p95 margins. Costs are checked before triggering; no public push is part of
this block. A first-sync-cycle or runner p95 failure stops under 70254bbc with
its time attributed; it is not rerun, skipped or given a wider bound.


## Release gate, d001d308 (2026-11-17)

The same fresh-process populations, cached-policy cell and declared-target core
cells record raw samples in ordinary builds. `HIITL_RELEASE_LATENCY=1` alone
asserts their p95. Structural observations do not read elapsed time: producer
children use a constant observation clock, while the real product retains its
own timing; file metadata remains an input to the source-replacement contract.
Red cells exercise an over-target synthetic population with the switch off/on,
the equality boundary, invalid samples and a missing output path in release mode.

The private release suite's validator reads the expected matrix and case catalogue
from the export source, recalculates p95 and target values rather than trusting
reported summaries, and binds every row to the named source commit and machine.
It rejects absent/stale evidence, an empty machine, omitted/duplicated populations,
an unasserted row, too few samples, non-finite/negative times and p95 at/over target.
Its actual-record cell is invoked unconditionally by the release-check command,
independently of the timing switch. Mutations remove each refusal and the ordinary
record-only branch. Workflow cells prove every public runtime preserves sample
artifacts even on failure. No product behavior, audit mode or target is changed.


## In-process runs, HTL-17 19d576ee (2026-11-18)

Read whole: HTL-17 `19d576ee` and `4133fb42`; decision_response.md:897 as amended. Boxes: SDK/ingest and
audit/ops (proposed).

HTL-45 cut every in-process timing cell to 20 calls, first call included. decision_response.md:897 gives that
count to fresh-process checks only. Each in-process benchmark now runs the warmup and the iteration count it had
before HTL-45. The timing catalogue names both for each cell, and the helpers in both languages read them there.

- **Purpose.** An in-process p95 describes the steady call its cell measured before HTL-45. The first call in a
  process stays the subject of the fresh-process cells, at 20 processes.
- **Critical behaviours.**
  1. A catalogued case records exactly its declared warmup and run. A dropped warmup or a wrong run length is
     refused in every build, before any time is read.
  2. Each warmup call is timed and kept in the row (`warmup_ms`) as evidence that it ran. The p95 reads the run
     alone, so a slow warmup cannot fail the release and a fast one cannot rescue it.
  3. A catalogued case that declares no run is refused. Unread is red, never a default count.
  4. A case outside the catalogue (a fresh-process population) takes no warmup and exactly 20 samples.
  5. The release check reads each population's own warmup and count from the export commit's catalogue.
- **Mutations.** For each changed cell, two: its warmup dropped (caught in an ordinary build), and its clock
  dilated by 1000 ms a call (passes an ordinary build, caught under `HIITL_RELEASE_LATENCY=1`). These run in both
  modes, outside the single-mode list, as F2's did. The helper and release-check refusals carry registry rows.
- **Not tested here.** Whether a run meets its target on a given machine. That is the release record's question.
- **Python's in-process cells** had no warmup, or one measured call, before HTL-45 (`test_evaluator.py`
  `test_simple_allow_rule` and `test_timing_metadata_present`; `test_client.py` `test_evaluate_uses_cached_policy`
  and `test_evaluate_latency_under_10ms`). Each takes the run ruled for it (HTL-17 `680f8ccf`, R-1393):
  - `core/allow` and `core/timing`: warmup 200, count 1500, the run of Python's own in-process evaluator benchmark
    before HTL-45 (`test_hot_path_benchmark.py`). The first, asserted call is the first warmup call.
  - `sdk/local-call`: warmup 1, count 100. The warmup is the cell's own; the count is its Node twin's, so one case
    has one run in both languages.
  - `cached-policy/first` and `/repeated`: warmup 0, count 20, as the cell stands. Each sample is a new client
    with one first and one repeated call. A first call has no warmup to drop, so this cell's run mutation is a
    catalogue that declares a warmup the cell does not run.

## Corrections PR, ac769270 (CC, 2026-11-17)

Read whole: HTL-45 `ac769270`, `8613a7bc`, `7bb83c22`; `d001d308`; decision_response.md
Timing Metadata as restated (R-1381). Boxes: SDK/ingest and audit/ops (proposed).

**F2, the Node local call.** The cell asserted a mean and a hand-computed tail in every
build. It now records its call population as `sdk/local-call` and asserts nothing
itself. The timing catalogue names that population, so the release gate refuses a
record without it. Its mutation, a dilated clock, passes in an ordinary build and fails
only under `HIITL_RELEASE_LATENCY=1`, so it is run in both modes, outside the
single-mode mutation list.

**The timing child takes no preload (`ac769270` item 3).** decision_response.md:897
names the builders hiitl prepays and makes no claim about the runtime's own first use,
so a child must meet the SDK's first call as a customer's process does. The TypeScript
child read `performance.now()` before it imported the SDK. That first read loads Node's
`perf_hooks` and the internal modules behind it (11 on Node 22.22.3, read from
`process.moduleLoadList`), which the SDK's own first call otherwise loads: the child
prepaid it. Each child now reads a clock the runtime holds without loading anything
(`process.hrtime.bigint()`; Python's `time.perf_counter`, a builtin) and records
`clock_loads`, the modules first loaded across its first clock read (Node's
`process.moduleLoadList` difference; Python's `sys.modules` difference). The
fresh-process cell requires `clock_loads` empty in every row of both observations. Its
mutations restore the `performance` clock in the TypeScript child and read Python's
clock through a module the child has not loaded (`timeit.default_timer`); each must be
caught.
