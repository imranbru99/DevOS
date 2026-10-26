#!/usr/bin/env python3
"""Check packaged ELF files against dpkg metadata before shipping a cached rootfs."""
import argparse
import hashlib
import json
from pathlib import Path


def mismatches(root):
    root = Path(root)
    problems = []
    for manifest in sorted((root / 'var/lib/dpkg/info').glob('*.md5sums')):
        package = manifest.name.removesuffix('.md5sums')
        for line in manifest.read_text(errors='strict').splitlines():
            fields = line.split(None, 1)
            if len(fields) != 2:
                continue
            expected, relative = fields
            relative = relative.lstrip()
            if not relative.startswith(('usr/bin/', 'usr/sbin/', 'usr/lib/', 'bin/', 'sbin/', 'lib/')):
                continue
            path = root / relative
            if path.is_symlink() or not path.is_file():
                continue
            with path.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    continue  # branding intentionally modifies some text scripts
                stream.seek(0)
                actual = hashlib.file_digest(stream, 'md5').hexdigest()
            if actual != expected:
                problems.append({'package': package, 'path': relative,
                                 'expected': expected, 'actual': actual})
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--packages', action='store_true', help='print affected package names for trusted APT repair')
    args = parser.parse_args()
    problems = mismatches(args.root)
    if args.packages:
        print('\n'.join(sorted({p['package'] for p in problems})))
        return 0
    print(json.dumps({'valid': not problems, 'mismatches': problems}, indent=2))
    return int(bool(problems))


if __name__ == '__main__':
    raise SystemExit(main())
