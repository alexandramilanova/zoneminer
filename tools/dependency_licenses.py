"""Record exact installed Python/system versions and locked frontend licenses.

Run inside the release image. This is an inventory, not a compatibility opinion.
Package license files remain in site-packages and /usr/share/doc in the image.
"""
import argparse
from importlib.metadata import distributions
import json
from pathlib import Path
import subprocess


def inventory():
    root = Path(__file__).resolve().parents[1]
    python = []
    for package in distributions():
        metadata = package.metadata
        python.append({"name": metadata["Name"], "version": package.version,
                       "license": metadata.get("License-Expression") or metadata.get("License") or "UNKNOWN",
                       "project_urls": metadata.get_all("Project-URL") or [],
                       "license_files": [str(p) for p in package.files or [] if "license" in str(p).lower() or "copying" in str(p).lower()]})
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    frontend = [{"package": path, "version": item.get("version"), "license": item.get("license", "UNKNOWN"),
                 "development_only": bool(item.get("dev")), "source": item.get("resolved")}
                for path, item in lock["packages"].items() if path]
    system = []
    result = subprocess.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Run in the Debian-based release image to inventory system dependencies")
    for line in result.stdout.splitlines():
        name, version = line.split("\t", 1)
        system.append({"name": name, "version": version, "copyright_file": f"/usr/share/doc/{name}/copyright"})
    return {"scope": "Installed release-image Python and OS packages; frontend package-lock including development tools",
            "legal_review": "Pending. License metadata is not a determination of compatibility or redistribution obligations.",
            "python": sorted(python, key=lambda p: p["name"].lower()), "frontend": frontend, "system": system}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inventory(), indent=2) + "\n")
