"""Lock the dependency closure using installed metadata and verified local wheels.

Run with the verified Windows CPython 3.13 environment. Downloads/builds are
separate explicit steps; this script neither installs nor upgrades anything.
"""
import argparse
import hashlib
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename


def generate(wheelhouse, output):
    root = Path(__file__).resolve().parents[1]
    pending = [Requirement(line) for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines()
               if line.strip() and not line.startswith('#')]
    pending += [Requirement('pytest==9.0.3'), Requirement('websockets==17.4')]
    versions, visited = {}, set()
    while pending:
        req = pending.pop()
        if req.marker and not req.marker.evaluate():
            continue
        name = canonicalize_name(req.name)
        key = (name, tuple(sorted(req.extras)))
        if key in visited:
            continue
        visited.add(key)
        installed = distribution(req.name)
        if req.specifier and installed.version not in req.specifier:
            raise ValueError(f'installed_version_mismatch:{req}')
        versions[name] = installed.version
        for raw in installed.requires or []:
            dependency = Requirement(raw)
            if dependency.marker is None or any(dependency.marker.evaluate({'extra': extra}) for extra in ['', *req.extras]):
                dependency.marker = None
                pending.append(dependency)
    supported, hashes = set(sys_tags()), {}
    for path in Path(wheelhouse).glob('*.whl'):
        name, version, _, tags = parse_wheel_filename(path.name)
        if tags & supported and versions.get(name) == str(version):
            hashes.setdefault(name, set()).add(hashlib.sha256(path.read_bytes()).hexdigest())
    missing = set(versions) - hashes.keys()
    if missing:
        raise ValueError('missing_compatible_wheels:' + ','.join(sorted(missing)))
    lines = ['# Windows x64 CPython 3.13 verified dependency closure (runtime + tests + browser harness).',
             '# Direct runtime pins remain owned by requirements.txt; regenerate with scripts/lock_environment.py.',
             '# jieba wheel is built from 0.42.1 sdist; preserve the verified wheelhouse for offline replay.',
             '--only-binary=:all:', '--require-hashes']
    for name, version in sorted(versions.items()):
        lines.append(f'{name}=={version} ' + ' '.join('--hash=sha256:' + digest for digest in sorted(hashes[name])))
    Path(output).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Locked {len(versions)} packages: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--wheelhouse', required=True)
    parser.add_argument('--output', default='requirements.lock')
    args = parser.parse_args()
    generate(args.wheelhouse, args.output)
