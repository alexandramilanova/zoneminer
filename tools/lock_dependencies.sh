#!/bin/sh
# Existing output pins are retained by uv; pass --upgrade for an intentional update.
set -eu
cd "$(dirname "$0")/.."
uv pip compile pyproject.toml --python-version 3.12 --universal --generate-hashes --output-file requirements.txt "$@"
uv pip compile pyproject.toml --extra legacy --extra dev --python-version 3.12 --universal --generate-hashes --constraint requirements.txt --output-file requirements-test.txt "$@"
