# Dependencies and redistribution

`pyproject.toml` is the authoritative Python dependency list. `requirements.txt`
is the generated, exact runtime dependency closure with artifact hashes.
`requirements-test.txt` additionally includes the dev and legacy Streamlit
extras. Docker and CI enforce hashes. Runtime images no longer need Streamlit
or the HTTP test client. PyArrow is explicit because the DuckDB conversion path
uses Arrow to preserve pandas compatibility without its deprecated inplace path.

Run `sh tools/lock_dependencies.sh` with uv installed to regenerate locks while
retaining existing pins. Pass `--upgrade` only for an intentional dependency
update, then rerun backend tests, numerical parity and browser regressions.
The universal lock contains platform markers; it does not establish that every
Python version and operating system works. Evaluation runs used Python 3.12 on
Linux ARM64; the published image also includes a Linux AMD64 build, tested by
opening the application and loading the demo on a Windows AMD laptop. Frontend installations use `npm ci` and
the committed package-lock. Docker base images still use mutable major/minor
tags: preserve a verified image digest for a release, and review base-image
updates deliberately rather than treating a future rebuild as identical.

Generate `docs/dependency-licenses.json` with
`python tools/dependency_licenses.py --output docs/dependency-licenses.json`
**inside the release image**. It inventories installed Python and Debian package
versions and the locked frontend packages (including development tools). It
records metadata and locations of upstream license files, not a legal clearance.

## Redistribution requirements

- Application-authored code currently has the existing MIT license. This change
  does not relicense it, and does not assert that the full combined stack is MIT.
- PM4Py 2.7.23.11 declares AGPL-3.0-or-later. The project uses PM4Py for log/model
  operations even when r4pm performs alignment. Switching the alignment backend
  therefore does not remove PM4Py from the application.
- r4pm 0.6.0.post1 has no license expression in wheel metadata, but ships
  `LICENSE-MIT` and `LICENSE-APACHE`. Those files must be considered rather than
  guessing a license from the missing metadata field.
- Several packages have missing or non-SPDX metadata. Review their included
  licenses/upstream terms. Inventory tooling cannot infer compatibility from a
  package name or the presence of a license file.
- Retain required notices and license texts for code, bundled JavaScript/fonts,
  Python dependencies, and container system packages in the eventual release.
  Installed Python/system notices remain in the image. Frontend license texts
  are collected in `THIRD_PARTY_NOTICES.txt`; regenerate them after `npm ci` with
  `python tools/frontend_notices.py` whenever frontend dependencies change.
- Before either a download release or public service, obtain a determination of
  the relevant AGPL/other obligations for this integration, then choose a
  compliant licensing/source-distribution route or a suitable alternate license.
  Merely adding attribution notices or making the repository public is not
  itself a determination of compliance.

Primary upstream sources:
[PM4Py licensing](https://processintelligence.solutions/pm4py/),
[PM4Py license](https://github.com/process-intelligence-solutions/pm4py/blob/release/LICENSE),
[uv locking](https://docs.astral.sh/uv/pip/compile/).
