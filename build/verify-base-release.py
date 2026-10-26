#!/usr/bin/env python3
"""Validate preserved upstream identity without executing os-release as shell code."""
import argparse
from pathlib import Path
import shlex


def read_identity(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.startswith('#'):
            tokens = shlex.split(value)
            values[key] = tokens[0] if len(tokens) == 1 else ''
    return values


def validate(root, version, codename):
    values = read_identity(Path(root) / 'usr/lib/os-release.ubuntu')
    expected = {'ID': 'ubuntu', 'VERSION_ID': version, 'VERSION_CODENAME': codename}
    for key, value in expected.items():
        if values.get(key) != value:
            raise ValueError(f'Upstream {key}: expected {value!r}, found {values.get(key)!r}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--codename', required=True)
    args = parser.parse_args()
    try:
        validate(args.root, args.version, args.codename)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Invalid Ubuntu base identity: {exc}\n')
