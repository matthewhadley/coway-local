"""Build an installable archive without caches, captures or credentials."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "coway_local"
version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
destination = ROOT / "dist"
destination.mkdir(exist_ok=True)
archive = destination / f"coway-local-{version}.zip"
with ZipFile(archive, "w", ZIP_DEFLATED) as output:
    for path in sorted(COMPONENT.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            if path.suffix in (".key", ".pem"):
                raise ValueError("Credential file found in release source")
            output.write(path, path.relative_to(ROOT))
    for name in ("README.md", "LICENSE", "LICENSE.amqtt"):
        output.write(ROOT / name, name)
print(archive)
