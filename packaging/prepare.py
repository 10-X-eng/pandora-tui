"""Build a deterministic, explicitly allowlisted source archive."""
import gzip
import hashlib
from pathlib import Path
import re
import tarfile
import tomllib


def prepare(root):
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    name = f'pandora-tui-{version}'
    archive = root / 'packaging' / f'{name}.tar.gz'
    paths = [root / name for name in ('pyproject.toml', 'README.md', 'AGENTS.md',
             'SECURITY.md', 'LICENSE', 'packaging/pandora-tui.desktop')]
    paths += [p for p in (root / 'src/pandora_tui').rglob('*')
              if p.is_file() and p.suffix in ('.py', '.json', '.tcss')]
    paths += list((root / 'tests').glob('*.py'))
    paths += list((root / 'scripts').glob('*.py'))
    with archive.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as tar:
                for path in sorted(paths):
                    if path.is_symlink():
                        raise ValueError('Release files must not be symlinks')
                    info = tar.gettarinfo(str(path), arcname=name + '/' + str(path.relative_to(root)))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = 0
                    info.mode = 0o644
                    info.pax_headers = {}
                    with path.open('rb') as data:
                        tar.addfile(info, data)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    pkg = root / 'packaging/PKGBUILD'
    pkg.write_text(re.sub(r"sha256sums=\('[^']*'\)", f"sha256sums=('{checksum}')", pkg.read_text()))
    print(archive.name, checksum)


if __name__ == '__main__':
    prepare(Path(__file__).resolve().parents[1])
