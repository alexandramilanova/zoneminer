"""Collect license texts for frontend runtime dependencies and Vite's polyfill."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    frontend = root / "frontend"
    packages = json.loads((frontend / "package-lock.json").read_text())["packages"]
    sections = ["ZoneMiner — third-party frontend notices\n\n"
                "Application-authored code is covered by LICENSE. Dependencies retain\n"
                "their own licenses. The following texts cover frontend runtime\n"
                "dependencies and Vite's bundled module-preload polyfill. Python and\n"
                "system-package licenses are retained in the Docker image. PM4Py\n"
                "declares AGPL-3.0-or-later and remains in use with r4pm alignment.\n"
                "r4pm ships MIT and Apache license texts. See\n"
                "docs/dependency-review.md for the complete stack and source obligations.\n"]
    for name, metadata in sorted(packages.items()):
        if not name or (metadata.get("dev") and name != "node_modules/vite"):
            continue
        directory = frontend / name
        files = sorted(p for p in directory.iterdir() if p.is_file() and
                       p.name.lower().startswith(("license", "licence", "copying", "notice", "ofl")))
        if not files:
            raise RuntimeError(f"Missing license text: {name}. Run npm ci first.")
        sections.append(f"\n{'=' * 72}\n{name.removeprefix('node_modules/')} {metadata['version']}\n")
        for path in files:
            sections.append(f"\n{path.name}\n\n{path.read_text().strip()}\n")
    (root / "THIRD_PARTY_NOTICES.txt").write_text("".join(sections))


if __name__ == "__main__":
    main()
