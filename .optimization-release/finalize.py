"""Publish an existing, tested draft without changing source or tags."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

REPO = os.environ['GITHUB_REPOSITORY']
TAG = os.environ['TARGET_TAG']
DOMAIN = os.environ['DOMAIN']
TEMP = Path(os.environ['RUNNER_TEMP'])

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def api(path, *args):
    return json.loads(run('gh', 'api', f'repos/{REPO}/{path}', *args))

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(re.fullmatch(r'v?\d+\.\d+\.\d+', TAG), 'Invalid tag')
require(re.fullmatch(r'[a-z_]+', DOMAIN), 'Invalid domain')
commit = run('git', 'rev-parse', 'HEAD')
require(api('git/ref/tags/' + TAG)['object']['sha'] == commit, 'Tag differs from checkout')
require(api('git/ref/heads/main')['object']['sha'] == commit, 'Main moved; manual review required')
component = Path('custom_components') / DOMAIN
require(json.loads((component/'manifest.json').read_text())['version'] == TAG.lstrip('v'), 'Version mismatch')
doc = Path('docs/OPTIMIZATION_2026-09-06.md').read_text()
match = re.search(r'https://github.com/' + re.escape(REPO) + r'/actions/runs/(\d+)', doc)
require(match is not None, 'Missing original validation provenance')
run_id = match.group(1)
if os.environ.get('EXPECTED_RUN'):
    require(run_id == os.environ['EXPECTED_RUN'], 'Unexpected original validation run')
original = api('actions/runs/' + run_id)
require(original['head_branch'] == 'release/optimization-20260906' and original['path'] == '.github/workflows/deploy-optimization-20260906.yml', 'Unexpected validation workflow')
require(original['event'] == 'push' and original['status'] == 'completed', 'Validation run is not complete')
jobs = api('actions/runs/' + run_id + '/jobs')['jobs']
job = next(j for j in jobs if j['name'] == 'validate-and-publish')
steps = job['steps']
publisher = next(s for s in steps if s['name'] == 'Publish verified commit, tag and release assets')
require(all(s['conclusion'] == 'success' for s in steps if s['number'] < publisher['number']), 'A prepublication check did not pass')
for required in ('HACS validation', 'Hassfest validation'):
    require(any(s['name'] == required and s['conclusion'] == 'success' for s in steps), required + ' did not pass')
parent = run('git', 'rev-parse', 'HEAD^')
require(f'기준 커밋: `{parent}`' in doc, 'Validated baseline does not match release parent')
releases = api('releases?per_page=100')
matches = [r for r in releases if r['tag_name'] == TAG]
require(len(matches) == 1, 'Expected one existing release')
release = matches[0]
require(release['draft'] and not release['prerelease'], 'Expected an unpublished stable draft')
require(f'배포 커밋: `{commit}`' in release['body'], 'Release notes do not match tested commit')
for other in releases:
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', other['tag_name'])
    if m and not other['draft'] and not other['prerelease']:
        require(tuple(map(int, m.groups())) < tuple(map(int, TAG.lstrip('v').split('.'))), 'Newer release already published')
assets_dir = TEMP / 'verified-assets'
assets_dir.mkdir(exist_ok=False)
for asset in release['assets']:
    name = asset['name']
    require(Path(name).name == name, 'Unexpected asset path')
    p = assets_dir / name
    with p.open('wb') as output:
        subprocess.run(['gh', 'api', f"repos/{REPO}/releases/assets/{asset['id']}", '-H', 'Accept: application/octet-stream'], stdout=output, check=True)
    require(p.stat().st_size == asset['size'], 'Asset size mismatch: ' + name)
    require(asset.get('digest') == 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest(), 'Asset digest mismatch: ' + name)
sums = {}
for line in (assets_dir/'SHA256SUMS.txt').read_text().splitlines():
    digest, name = line.split('  ', 1)
    require(re.fullmatch(r'[0-9a-f]{64}', digest) and Path(name).name == name, 'Invalid checksum entry')
    require(name not in sums, 'Duplicate checksum entry')
    sums[name] = digest
require(set(sums) == {p.name for p in assets_dir.iterdir()} - {'SHA256SUMS.txt'}, 'Incomplete checksum list')
for name, digest in sums.items():
    require(hashlib.sha256((assets_dir/name).read_bytes()).hexdigest() == digest, 'Checksum mismatch')
zips = list(assets_dir.glob('*.zip'))
require(len(zips) == 1, 'Expected one integration archive')
tracked = run('git', 'ls-files', '--', str(component)).splitlines()
expected = {Path(p).relative_to(component).as_posix(): Path(p) for p in tracked if Path(p).is_file() and not Path(p).is_symlink() and '__pycache__' not in Path(p).parts and Path(p).suffix not in {'.pyc', '.pyo'}}
with zipfile.ZipFile(zips[0]) as archive:
    require(archive.testzip() is None and len(archive.namelist()) == len(set(archive.namelist())), 'Archive integrity failure')
    require(set(archive.namelist()) == set(expected), 'Archive file list differs from tested integration')
    for name, p in expected.items():
        require(archive.read(name) == p.read_bytes(), 'Archive content differs from tested integration: ' + name)
if DOMAIN == 'ha_ios_ancs':
    old = api('releases/tags/v0.6.9')
    previous = {a['name']: a for a in old['assets'] if a['name'].endswith('.factory.bin')}
    require(len(previous) == 7 and set(previous) == {p.name for p in assets_dir.glob('*.factory.bin')}, 'Firmware inventory changed')
    for name, asset in previous.items():
        require('sha256:' + sums[name] == asset['digest'], 'Firmware changed')
evidence = TEMP / 'original-validation'
run('gh', 'run', 'download', run_id, '--repo', REPO, '--name', 'optimization-validation', '--dir', str(evidence))
counts = {}
for phase in ('baseline', 'patched'):
    root = ET.parse(evidence/f'optimization-{phase}.xml').getroot()
    suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
    values = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    require(values['tests'] > 0 and values['failures'] == 0 and values['errors'] == 0, 'Native tests did not pass')
    counts[phase] = values
require(api('git/ref/heads/main')['object']['sha'] == commit, 'Main moved during verification')
api('releases/' + str(release['id']), '--method', 'PATCH', '-F', 'draft=false', '-f', 'make_latest=true')
published = api('releases/tags/' + TAG)
require(not published['draft'] and bool(published['published_at']) and not published['prerelease'], 'Release is not public')
require(api('releases/latest')['id'] == published['id'], 'Release is not latest')
require(api('git/ref/tags/' + TAG)['object']['sha'] == commit, 'Tag changed during publication')
result = {'repository': REPO, 'tag': TAG, 'version': TAG.lstrip('v'), 'commit': commit, 'release': published['html_url'], 'published_at': published['published_at'], 'tests': counts, 'validation_run': int(run_id), 'publication_run': int(os.environ['GITHUB_RUN_ID']), 'asset_sha256': sums, 'ha_installed': False}
text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
(TEMP/'published-result.json').write_text(text)
print(text)
with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as output:
    output.write('# Published and verified\n\n```json\n' + text + '```\n')
