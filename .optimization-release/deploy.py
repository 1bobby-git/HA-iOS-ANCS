"""One-time, fail-closed publisher for the user-approved optimization patches.

Only the current repository is writable. No force pushes, rule changes, credential
logging, HA installation, or firmware rebuilding are performed.
"""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path.cwd()
TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
STATE = TEMP / "optimization-state.json"
SPEC = json.loads(os.environ["PATCH_SPEC"])
REPO = SPEC["repository"]
BASE_VERSION = SPEC["base_version"]
VERSION = SPEC["candidate_version"]
DOMAIN = next(c["path"].split("/")[1] for c in SPEC["changes"])
DOC = "docs/OPTIMIZATION_2026-09-06.md"


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def api(path: str):
    return json.loads(run("gh", "api", f"repos/{REPO}/{path}".rstrip("/")))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def source_updates() -> dict[str, str]:
    staged = {}
    originals = {}
    for change in SPEC["changes"]:
        path = change["path"]
        require(path.startswith(f"custom_components/{DOMAIN}/") and ".." not in Path(path).parts, "Unexpected patch path")
        if path not in originals:
            raw = Path(path).read_bytes()
            require(not Path(path).is_symlink(), f"Symlink not allowed: {path}")
            sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            originals[path] = sha
            staged[path] = raw.decode("utf-8")
        require(originals[path] == change["git_blob_sha1"], f"Source changed; review required: {path}")
        old = change["old"]
        require(staged[path].count(old) == change.get("count", 1), f"Replacement count mismatch: {path}")
        staged[path] = staged[path].replace(old, change["new"])
    for path, text in staged.items():
        if path.endswith(".py"):
            ast.parse(text, filename=path)
        elif path.endswith(".json"):
            json.loads(text)
    return staged


def check() -> None:
    require(os.environ["GITHUB_REPOSITORY"].lower() == REPO.lower(), "Repository mismatch")
    require(api("")["default_branch"] == SPEC["branch"], "Default branch changed")
    branch = api("branches/" + SPEC["branch"])
    require(not branch["protected"], "Protected branch: use the repository review process instead")
    head = run("git", "rev-parse", "HEAD")
    require(head == branch["commit"]["sha"], "Default branch moved before validation")
    require(not run("git", "status", "--porcelain"), "Validation checkout is not clean")
    manifest = json.loads(Path(f"custom_components/{DOMAIN}/manifest.json").read_text())
    require(manifest["version"] == BASE_VERSION, "Base version changed")
    source_updates()
    releases = api("releases?per_page=100")
    proposed = tuple(map(int, VERSION.split(".")))
    for release in releases:
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", release["tag_name"])
        if match and not release["prerelease"]:
            require(tuple(map(int, match.groups())) < proposed, "Candidate version already used or superseded")
    latest = next((r for r in releases if not r["draft"] and not r["prerelease"]), None)
    prefix = "" if latest and not latest["tag_name"].startswith("v") else "v"
    tag = prefix + VERSION
    require(not run("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"), "Candidate tag already exists")
    state = {"repository": REPO, "base_sha": head, "base_version": BASE_VERSION, "version": VERSION,
             "tag": tag, "old_release": latest, "paths": [], "workflow": os.environ["GITHUB_SERVER_URL"] + "/" + REPO + "/actions/runs/" + os.environ["GITHUB_RUN_ID"]}
    save(state)
    print(f"Validated source hashes and release preconditions: {REPO} {BASE_VERSION} -> {VERSION}; base {head}")


def apply() -> None:
    state = json.loads(STATE.read_text())
    require(run("git", "rev-parse", "HEAD") == state["base_sha"], "Unexpected checkout change")
    staged = source_updates()
    require(not Path(DOC).exists(), "Optimization document already exists; review required")
    bullets = "\n".join("- " + item for item in SPEC["summary"])
    note = (f"# {REPO.split('/')[-1]} {VERSION} — 최적화\n\n2026-09-06 / Home Assistant 통합 패치\n\n"
            f"## 변경 내용\n\n{bullets}\n\n"
            "## 호환성과 범위\n\n도메인, 기존 설정, 엔티티·장치 식별자와 공개 서비스 이름은 유지합니다. "
            "의존성 일괄 업그레이드와 서버 측 세션 만료 우회는 포함하지 않습니다. "
            "SmartThings 브리지 앱과 ANCS 펌웨어는 변경하지 않습니다.\n\n"
            "## 검증 범위\n\n원본 전체 파일 해시를 확인한 뒤 기존 저장소 테스트를 변경 전후 실행합니다. "
            "HACS/Hassfest와 저장소별 CI 검증을 통과한 경우에만 릴리스를 게시합니다. "
            "앞선 후보 묶음의 오프라인 테스트 103개와 실제 저장소 테스트 결과는 별개입니다. "
            "운영 HA의 실제 로그인·쿠키 수명·재생·실기기 제어·장시간 운용은 검증하지 않았습니다. "
            "테스트 통과만으로 모든 환경에서 무영향이나 성능 향상을 보장하지 않습니다.\n\n"
            f"## 업데이트와 되돌리기\n\nHA 백업을 확보한 후 HACS에서 {VERSION}을 내려받고 Home Assistant를 재시작합니다. "
            f"문제가 생기면 HACS 재다운로드에서 이전 버전 {BASE_VERSION}을 선택하거나 백업을 복원합니다. "
            "이 GitHub 배포 작업은 사용자 HA에 직접 설치하거나 재시작하지 않습니다.\n\n"
            f"기준 커밋: `{state['base_sha']}`\n\n배포 검증 실행: {state['workflow']}\n")
    staged[DOC] = note
    entry = f"## {VERSION} — 2026-09-06\n\n{bullets}\n\n상세 변경·검증 범위·롤백: [{DOC}]({DOC})\n\n"
    changelog = Path("CHANGELOG.md")
    existing = changelog.read_text() if changelog.exists() else "# Changelog\n\n"
    require(not re.search(r"^## .*\b" + re.escape(VERSION) + r"\b", existing, re.M), "Version already documented")
    first, sep, rest = existing.partition("\n")
    staged["CHANGELOG.md"] = first + "\n\n" + entry + rest.lstrip("\n") if first.startswith("# ") else entry + existing
    for name in ("README.md", "README.en.md"):
        p = Path(name)
        if not p.exists():
            continue
        if name.endswith(".en.md"):
            section = f"\n\n## Integration update {VERSION}\n\nSee [optimization notes]({DOC}) for changes, validation scope and rollback. "
            section += "Existing identifiers and public services are preserved. Firmware/bridge applications are unchanged. "
            section += "Live Home Assistant, account sessions and physical devices were not validated by this release job.\n"
        else:
            section = f"\n\n## 통합 업데이트 {VERSION}\n\n{bullets}\n\n변경 내용, 검증 범위 및 롤백 방법: [최적화 문서]({DOC}). "
            section += "펌웨어·브리지 앱은 변경하지 않으며, 운영 HA 설치·실기기 검증은 별도입니다.\n"
        staged[name] = p.read_text().rstrip() + section
    for path, text in staged.items():
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    state["paths"] = sorted(staged)
    save(state)
    run("git", "diff", "--check")
    print(run("git", "diff", "--stat"))


def counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    result = {key: sum(int(s.attrib.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    require(result["tests"] > 0 and result["failures"] == 0 and result["errors"] == 0, "Native test gate failed")
    return result


def publish() -> None:
    state = json.loads(STATE.read_text())
    baseline = counts(TEMP / "optimization-baseline.xml")
    patched = counts(TEMP / "optimization-patched.xml")
    with Path(DOC).open("a") as stream:
        stream.write(f"\n## 실제 CI 결과\n\n기존 코드: {baseline}\n\n패치 코드: {patched}\n\nHACS와 Hassfest 검증을 통과한 뒤 게시합니다.\n")
    output = TEMP / "optimization-release-assets"
    output.mkdir(exist_ok=False)
    hacs = json.loads(Path("hacs.json").read_text()) if Path("hacs.json").exists() else {}
    filename = hacs.get("filename", f"{DOMAIN}.zip") if hacs.get("zip_release") else f"{DOMAIN}.zip"
    require(Path(filename).name == filename and filename.endswith(".zip"), "Invalid release filename")
    component = Path("custom_components") / DOMAIN
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", str(component)]).decode().split("\0")
    with zipfile.ZipFile(output / filename, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(filter(None, tracked)):
            p = Path(name)
            if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}:
                archive.write(p, p.relative_to(component).as_posix())
    with zipfile.ZipFile(output / filename) as archive:
        require(archive.testzip() is None, "Release ZIP integrity failed")
        require(json.loads(archive.read("manifest.json"))["version"] == VERSION, "Release ZIP version mismatch")
    if DOMAIN == "ha_ios_ancs":
        old = state["old_release"]
        assets = [a for a in old["assets"] if a["name"].endswith(".factory.bin")]
        require(bool(assets), "Previous firmware assets missing")
        run("gh", "release", "download", old["tag_name"], "--repo", REPO, "--pattern", "*.factory.bin", "--dir", str(output))
        for asset in assets:
            p = output / asset["name"]
            require(p.stat().st_size == asset["size"], "Firmware asset size mismatch")
            digest = asset.get("digest")
            require(bool(digest) and digest == "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(), "Firmware asset checksum mismatch")
    assets = sorted(output.iterdir())
    sums = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in assets)
    (output / "SHA256SUMS.txt").write_text(sums)
    expected = {p.name for p in output.iterdir()}
    manifest = json.loads((component / "manifest.json").read_text())
    require(manifest["version"] == VERSION, "Manifest version changed during tests")
    changed = set(run("git", "diff", "--name-only").splitlines())
    require(changed <= set(state["paths"]), "Tests modified unexpected tracked files")
    run("git", "add", "--", *state["paths"])
    require(set(run("git", "diff", "--cached", "--name-only").splitlines()) == set(state["paths"]), "Unexpected staged paths")
    run("git", "diff", "--cached", "--check")
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "commit", "-m", f"fix: apply validated optimization patches and release {VERSION}")
    commit = run("git", "rev-parse", "HEAD")
    branch = api("branches/" + SPEC["branch"])
    require(not branch["protected"] and branch["commit"]["sha"] == state["base_sha"], "Main changed or became protected; do not publish")
    require(not run("git", "ls-remote", "--tags", "origin", f"refs/tags/{state['tag']}"), "Release tag appeared during validation")
    run("git", "push", "origin", f"HEAD:refs/heads/{SPEC['branch']}")
    run("git", "tag", state["tag"], commit)
    run("git", "push", "origin", f"refs/tags/{state['tag']}")
    notes = TEMP / "optimization-release-notes.md"
    notes.write_text(Path(DOC).read_text() + f"\n배포 커밋: `{commit}`\n")
    run("gh", "release", "create", state["tag"], "--repo", REPO, "--verify-tag", "--draft", "--title", f"{REPO.split('/')[-1]} {VERSION}", "--notes-file", str(notes), *map(str, sorted(output.iterdir())))
    release = api("releases/tags/" + state["tag"])
    require({a["name"] for a in release["assets"]} == expected, "Uploaded release assets incomplete")
    for asset in release["assets"]:
        require(asset["size"] == (output / asset["name"]).stat().st_size, "Uploaded asset size mismatch")
    run("gh", "release", "edit", state["tag"], "--repo", REPO, "--draft=false", "--latest")
    release = api("releases/tags/" + state["tag"])
    require(not release["draft"] and not release["prerelease"] and bool(release["published_at"]), "Release not published")
    require(api("git/ref/tags/" + state["tag"])["object"]["sha"] == commit, "Published tag does not match tested commit")
    result = {"repository": REPO, "version": VERSION, "commit": commit, "tag": state["tag"], "release": release["html_url"], "baseline": baseline, "patched": patched, "assets": sorted(expected), "workflow": state["workflow"], "ha_installed": False}
    (TEMP / "optimization-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write("# Published optimization release\n\n```json\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n")


if __name__ == "__main__":
    require(len(sys.argv) == 2 and sys.argv[1] in {"check", "apply", "publish"}, "Expected check, apply, or publish")
    {"check": check, "apply": apply, "publish": publish}[sys.argv[1]]()
