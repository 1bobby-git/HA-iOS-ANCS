"""Correct the pinned one-time publisher without weakening release gates."""
from pathlib import Path
import ast
import hashlib
import sys

path = Path(sys.argv[1])
raw = path.read_bytes()
blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
if blob != '13b5835fbdccf949f0aa92b9989759d677cbb6b1':
    raise RuntimeError('Unexpected publisher source; review required')
text = raw.decode()
lookup = '    release = api("releases/tags/" + state["tag"])\n'
if text.count(lookup) != 2:
    raise RuntimeError('Unexpected release lookup count')
text = text.replace(lookup,
    '    matches = [r for r in api("releases?per_page=100") if r["tag_name"] == state["tag"]]\n'
    '    require(len(matches) == 1 and matches[0]["draft"], "Expected one uploaded draft")\n'
    '    release = api("releases/" + str(matches[0]["id"]))\n', 1)
old = '    run("gh", "release", "edit", state["tag"], "--repo", REPO, "--draft=false", "--latest")\n'
new = '    run("gh", "api", "--method", "PATCH", f"repos/{REPO}/releases/{release[\'id\']}", "-F", "draft=false", "-F", "prerelease=false", "-f", "make_latest=true")\n'
if text.count(old) != 1:
    raise RuntimeError('Unexpected publication command')
text = text.replace(old, new)
old = '        require(asset["size"] == (output / asset["name"]).stat().st_size, "Uploaded asset size mismatch")\n'
new = old + '        require(asset.get("digest") == "sha256:" + hashlib.sha256((output / asset["name"]).read_bytes()).hexdigest(), "Uploaded asset digest mismatch")\n'
if text.count(old) != 1:
    raise RuntimeError('Unexpected asset verification block')
text = text.replace(old, new)
old = '    require(not release["draft"] and not release["prerelease"] and bool(release["published_at"]), "Release not published")\n'
if text.count(old) != 1:
    raise RuntimeError('Unexpected publication verification block')
text = text.replace(old, old + '    require(api("releases/latest")["id"] == release["id"], "Published release is not latest")\n')
old = '    for path, text in staged.items():\n'
new = '    staged["CHANGELOG.md"] = staged["CHANGELOG.md"].rstrip("\\n") + "\\n"\n' + old
if text.count(old) != 1:
    raise RuntimeError('Unexpected document write block')
text = text.replace(old, new)
ast.parse(text)
path.write_text(text)
print('Verified publisher: draft-by-ID, SHA-256, latest-release checks and normalized changelog EOF')
