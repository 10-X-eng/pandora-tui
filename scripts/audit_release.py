"""Scan exact Git index/archive contents. Report locations, never secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

EMAIL = re.compile(rb'[A-Za-z0-9_.+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})')
HOME_PATH = re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.\-]+')
SAFE_DOMAINS = {b'example.com', b'example.org', b'example.net', b'example.invalid'}
FORBIDDEN_PARTS = {'.venv', '__pycache__', '.test-state', 'research', '.env'}


def inspect(name, data, private_values):
    issues = []
    if any(part in FORBIDDEN_PARTS for part in Path(name).parts):
        issues.append('private/generated path')
    if HOME_PATH.search(data):
        issues.append('personal home path')
    if any(match.group(1).lower() not in SAFE_DOMAINS for match in EMAIL.finditer(data)):
        issues.append('non-example email')
    lowered = data.lower()
    if any(value.lower() in lowered or value.lower() in name.encode().lower() for value in private_values):
        issues.append('private value')
    if re.search(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----', data):
        issues.append('private key')
    return issues


def archive_entries(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    yield item.filename, archive.read(item)
    else:
        with tarfile.open(path, 'r:*') as archive:
            for item in archive.getmembers():
                if item.uid or item.gid or item.uname or item.gname:
                    raise ValueError('Archive contains non-normalized owner metadata')
                if item.isfile():
                    yield item.name, archive.extractfile(item).read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--sensitive-file', type=Path,
                        help='External JSON list of private strings; never put this file in the repository')
    args = parser.parse_args()
    private = []
    if args.sensitive_file:
        values = json.loads(args.sensitive_file.read_text())
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise SystemExit('Sensitive-file must contain a list of nonempty strings')
        private = [v.encode() for v in values]
    if args.archive:
        entries = archive_entries(args.archive)
    else:
        names = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
        entries = ((name, subprocess.check_output(['git', 'show', ':' + name])) for name in names if name)
    failed, count = False, 0
    for name, data in entries:
        count += 1
        issues = inspect(name, data, private)
        if issues:
            failed = True
            print(f'{name}: {", ".join(issues)}')
    if not count:
        raise SystemExit('Nothing to audit; stage files first')
    if failed:
        raise SystemExit('Privacy audit failed; no matched values were printed')
    print(f'Privacy audit passed: {count} files')


if __name__ == '__main__':
    main()
