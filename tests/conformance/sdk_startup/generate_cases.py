"""Generate the startup matrix from declared modes and the ticket's source class.

No timings or expected decisions are taken from either SDK. A new deployment
mode in either configuration table fails generation until its source is read.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
# sync_engine.md Startup Behavior/Policy Precedence; HTL-45 Measure first.
# Hosted policies belong to the service, so there is no SDK disk/file source.
SOURCES = {'local': ['none', 'json', 'yaml'],
           'hybrid': ['none', 'json', 'yaml', 'disk', 'pull'], 'hosted': ['service']}


def cases():
    for language in ('python', 'typescript'):
        text = (ROOT / f'docs-site/sdk/{language}-configuration.mdx').read_text()
        section = text.split('### Auto-detection rules\n', 1)[1]
        table = re.search(r'(?m)(?:^\|[^\n]*\n)+', section).group(0)
        modes = set(re.findall(r'\*\*(\w+)\*\*', table))
        assert modes == set(SOURCES), (language, modes, set(SOURCES))
    for mode, sources in SOURCES.items():
        for source in sources:
            # The configuration pages' two evaluation modes. A local client
            # without a policy refuses RESPECT_POLICY at construction.
            for evaluation in ('OBSERVE_ALL', 'RESPECT_POLICY'):
                if mode == 'local' and source == 'none' and evaluation == 'RESPECT_POLICY':
                    continue
                yield dict(mode=mode, source=source, evaluation=evaluation,
                           startup='immediate', cold_start='warn-and-observe')
                if mode == 'hybrid' and source in ('disk', 'pull'):
                    # sync_engine.md Startup Behavior: TS starts asynchronously;
                    # fail-closed awaits that start inside its first evaluate.
                    yield dict(mode=mode, source=source, evaluation=evaluation,
                               startup='settled', cold_start='warn-and-observe')
                    yield dict(mode=mode, source=source, evaluation=evaluation,
                               startup='immediate', cold_start='fail-closed')


if __name__ == '__main__':
    (HERE / 'cases.json').write_text(json.dumps(list(cases()), indent=2) + '\n')
