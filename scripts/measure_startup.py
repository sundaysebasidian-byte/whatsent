"""Measure fresh-process CLI startup; no page-cache flush or running services.

Use the same Python/environment before and after a change. Subcommand --help
isolates entry-point startup from capture, corpus execution and output generation.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--out', type=Path, default=Path('whatsent-report/backend-validation'))
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    commands = {'version': ['--version'], **{name: [name, '--help'] for name in ('board', 'check', 'demo', 'ui', 'selftest')}}
    results = {}
    for name, command in commands.items():
        samples = []
        for _ in range(args.samples):
            start = time.perf_counter()
            proc = subprocess.run([sys.executable, '-m', 'whatsent', *command], capture_output=True)
            samples.append((time.perf_counter() - start) * 1000)
        profile = subprocess.run([sys.executable, '-X', 'importtime', '-m', 'whatsent', *command],
                                 capture_output=True, text=True)
        (args.out / f'{args.label}-{name}-importtime.txt').write_text(profile.stderr)
        results[name] = {'median_ms': round(statistics.median(samples), 2), 'samples_ms': samples,
                         'mitmproxy_imported': any(line.rsplit('|', 1)[-1].strip().startswith('mitmproxy')
                                                  for line in profile.stderr.splitlines() if line.startswith('import time:')),
                         'exit_code': proc.returncode}
    (args.out / f'cold-start-{args.label}.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
