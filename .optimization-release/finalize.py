"""Finalize an existing, validated integration draft without changing source or tags.

The caller must run the repository's native tests, HACS and Hassfest first.
Only the current repository's explicit release ID may be published.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    repo = os.environ['RELEASE_REPOSITORY']
    sha = os.environ['RELEASE_COMMIT']
    version = os.environ['RELEASE_VERSION']
    domain = os.environ['RELEASE_DOMAIN']
    tag = os.environ['RELEASE_TAG']
    release_id = int(os.environ['RELEASE_ID'])
    require(repo == os.environ['GITHUB_REPOSITORY'], 'Repository mismatch')
    require(re.fullmatch(r'[0-9a-f]{40}', sha) is not None, 'Invalid source SHA')
    require(re.fullmatch(r'[a-z0-9_]+', domain) is not None, 'Invalid domain')
    require(re.fullmatch(r'\d+\.\d+\.\d+', version) is not None, 'Invalid version')
    require(tag in {version, 'v' + version}, 'Tag/version mismatch')

    def api(path: str):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/{path}']))

    release = api(f'releases/{release_id}')
    require(release['tag_name'] == tag and not release['prerelease'], 'Unexpected release')
    ref = api(f'git/ref/tags/{tag}')['object']
    for _ in range(5):
        if ref['type'] != 'tag':
            break
        ref = api('git/tags/' + ref['sha'])['object']
    require(ref['type'] == 'commit' and ref['sha'] == sha, 'Tag changed')
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == sha, 'Checkout mismatch')
    metadata = api('')
    branch = api('branches/' + metadata['default_branch'])
    require(branch['commit']['sha'] == sha, 'Default branch moved; review required')
    proposed = tuple(map(int, version.split('.')))
    for other in api('releases?per_page=100'):
        match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', other['tag_name'])
        if match and not other['prerelease']:
            require(tuple(map(int, match.groups())) <= proposed, 'Newer release exists')

    component = Path('custom_components') / domain
    require(json.loads((component / 'manifest.json').read_text())['version'] == version, 'Manifest version mismatch')
    require(Path('docs/OPTIMIZATION_2026-09-06.md').is_file(), 'Release documentation missing')
    hacs = json.loads(Path('hacs.json').read_text()) if Path('hacs.json').exists() else {}
    filename = hacs.get('filename', domain + '.zip') if hacs.get('zip_release') else domain + '.zip'
    require(Path(filename).name == filename and filename.endswith('.zip'), 'Unsafe asset name')
    assets = {a['name']: a for a in release['assets']}
    require(len(assets) == len(release['assets']) and set(assets) == {filename, 'SHA256SUMS.txt'}, 'Unexpected or incomplete assets')
    downloaded = {}
    for name, asset in assets.items():
        require(asset['state'] == 'uploaded' and 0 < asset['size'] < 50000000, 'Invalid asset state/size')
        data = subprocess.check_output(['gh', 'api', f"repos/{repo}/releases/assets/{asset['id']}", '-H', 'Accept: application/octet-stream'])
        require(len(data) == asset['size'], 'Asset size mismatch: ' + name)
        require('sha256:' + hashlib.sha256(data).hexdigest() == asset['digest'], 'Asset digest mismatch: ' + name)
        downloaded[name] = data
    checksums = downloaded['SHA256SUMS.txt'].decode().splitlines()
    require(checksums == [hashlib.sha256(downloaded[filename]).hexdigest() + '  ' + filename], 'Checksum manifest mismatch')
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', str(component)]).decode().split('\0')
    expected = {Path(p).relative_to(component).as_posix(): Path(p).read_bytes() for p in tracked if p and Path(p).is_file() and not Path(p).is_symlink() and '__pycache__' not in Path(p).parts and Path(p).suffix not in {'.pyc', '.pyo'}}
    with zipfile.ZipFile(io.BytesIO(downloaded[filename])) as archive:
        require(archive.testzip() is None, 'Corrupt ZIP')
        require(len(archive.namelist()) == len(expected) and set(archive.namelist()) == set(expected), 'ZIP file list mismatch')
        require(json.loads(archive.read('manifest.json'))['version'] == version, 'ZIP version mismatch')
        for name, data in expected.items():
            require(archive.read(name) == data, 'ZIP/source mismatch: ' + name)
    require(api('branches/' + metadata['default_branch'])['commit']['sha'] == sha, 'Default branch changed during verification')
    if release['draft']:
        workflow = 'https://github.com/' + repo + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
        body = (release.get('body') or '') + '\n\n공개 복구 검증: ' + workflow + '\n기존 릴리스 초안을 ID로 확인하고 저장소 테스트·HACS·Hassfest와 배포 ZIP의 모든 파일 및 SHA-256을 재검증했습니다. 운영 HA 설치는 수행하지 않았습니다.\n'
        payload = json.dumps({'draft': False, 'prerelease': False, 'make_latest': 'true', 'body': body})
        subprocess.run(['gh', 'api', '--method', 'PATCH', f'repos/{repo}/releases/{release_id}', '--input', '-'], input=payload, text=True, check=True, stdout=subprocess.DEVNULL)
    final = api('releases/tags/' + tag)
    require(final['id'] == release_id and not final['draft'] and final['published_at'] and not final['prerelease'], 'Not published')
    require(api('releases/latest')['id'] == release_id, 'Not the latest release')
    require({a['name']: (a['size'], a['digest']) for a in final['assets']} == {n: (a['size'], a['digest']) for n, a in assets.items()}, 'Published assets changed')
    result = {'repository': repo, 'version': version, 'commit': sha, 'release': final['html_url'], 'release_id': release_id, 'assets_verified': len(assets), 'source_files_verified': len(expected), 'published_at': final['published_at']}
    print(json.dumps(result, ensure_ascii=False))
    Path(os.environ['RUNNER_TEMP'], 'release-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
