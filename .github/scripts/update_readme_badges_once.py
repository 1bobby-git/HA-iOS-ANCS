from pathlib import Path
import re

REPOSITORY = "HA-iOS-ANCS"
ARCHITECTURE_TEXT = "ESP32, ESP32-C2, ESP32-C3, ESP32-C5, ESP32-C6, ESP32-C61, ESP32-S3"
ARCHITECTURE_BADGE = "ESP32%20family"
ARCHITECTURE_LINK = "https://github.com/1bobby-git/HA-iOS-ANCS/blob/main/docs/manifests/ios-ancs.json"

readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
branding = re.compile(r"<!-- project-branding:start -->.*?<!-- project-branding:end -->", re.S)
match = branding.search(text)
if not match:
    raise SystemExit("project branding block not found")

logo_match = re.search(r'<p\s+align="center">\s*<img\b.*?</p>', match.group(0), re.S)
if not logo_match:
    raise SystemExit("project logo block not found")

logo_block = logo_match.group(0)
badge_block = f'''<p align="center">
  <a href="https://github.com/1bobby-git/{REPOSITORY}/stargazers"><img src="https://img.shields.io/github/stars/1bobby-git/{REPOSITORY}?style=flat-square&logo=github&label=Stars" alt="GitHub Stars"></a>
  <a href="https://github.com/1bobby-git/{REPOSITORY}/releases"><img src="https://img.shields.io/github/v/release/1bobby-git/{REPOSITORY}?style=flat-square&label=Release" alt="Latest Release"></a>
  <a href="{ARCHITECTURE_LINK}"><img src="https://img.shields.io/badge/Architecture-{ARCHITECTURE_BADGE}-0ea5e9?style=flat-square" alt="{ARCHITECTURE_TEXT}"></a>
  <a href="https://github.com/1bobby-git/{REPOSITORY}/blob/main/LICENSE"><img src="https://img.shields.io/github/license/1bobby-git/{REPOSITORY}?style=flat-square&label=License" alt="License"></a>
  <a href="https://github.com/1bobby-git/{REPOSITORY}/commits/main"><img src="https://img.shields.io/github/last-commit/1bobby-git/{REPOSITORY}?style=flat-square&label=Updated" alt="Last Commit"></a>
</p>'''

new_branding = f"<!-- project-branding:start -->\n{logo_block}\n{badge_block}\n<!-- project-branding:end -->"
text = text[:match.start()] + new_branding + text[match.end():]
readme.write_text(text, encoding="utf-8")
