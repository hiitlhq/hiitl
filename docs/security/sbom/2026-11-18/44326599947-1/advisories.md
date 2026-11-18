# Dependency advisory record

Read 2026-11-18T14:40:02Z under HTL-17 4d086f19: "the gate still fails on any vulnerability in what a published package installs, and on any vulnerability anywhere that has a fixed release. An unfixed advisory outside what ships is written into the release's public advisory record with its reach, and fails the gate the day a fix exists."

## Subjects

| Subject | Package | Ecosystem | Read | Closure | Installed |
|---|---|---|---|---|---|
| python | hiitl | PyPI | package closure | 31 | 50 |
| typescript/packages/core | @hiitl/core | npm | package closure | 1 | 71 |
| typescript/packages/sdk | @hiitl/sdk | npm | package closure | 7 | 79 |

## Unfixed advisories outside what ships

| Subject | Advisory | Aliases | Package | Installed | Severity | Reach |
|---|---|---|---|---|---|---|
| typescript/packages/core | [GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) | CVE-2026-112366 | picomatch | 4.0.7 | high | @hiitl/core@0.2.0 → vitest@5.1.0 → picomatch@4.0.7 |
| typescript/packages/sdk | [GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf) | CVE-2026-112366 | picomatch | 4.0.7 | high | @hiitl/sdk@0.2.0 → vitest@5.1.0 → picomatch@4.0.7 |

## Failing

None.

## Unread

None.

**Result:** passed.
