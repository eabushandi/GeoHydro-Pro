# Release procedure

Every release must ship with all five of the following. A version missing any of them is
not released.

| Item | Where |
|---|---|
| Version number | `geohydro/__init__.py` and `pyproject.toml` (identical); `packaging/version_info.txt` regenerated with `python packaging/make_version_info.py` |
| Changelog | `CHANGELOG.md` entry and `docs/release-notes/vX.Y.Z.md` (the GitHub release text) |
| Test results | `docs/TEST_RESULTS.md`: local run with counts per file, and the CI run IDs |
| Installation package | installer, portable zip and self-test report, built and attached by the *windows-package* workflow |
| Technical documentation | user and scientific docs updated for every new feature (equations, assumptions, limitations, validation); `docs/FEATURE_CHECKLIST.md` marks implemented versus planned |

## Steps

1. Update the version, changelog, release notes, checklist and documentation on `main`.
2. Run the full test suite locally and record the result.
3. Push to `main` and wait until both workflows pass: *tests* (9 jobs) and
   *windows-package*. Record the run IDs in `docs/TEST_RESULTS.md` and push.
4. Publish the release on GitHub: Releases ▸ Draft a new release ▸ new tag `vX.Y.Z` on
   `main` ▸ tick **Set as a pre-release** (until production) ▸ Publish. Alternatively push
   the tag from a clone: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. The tag starts *windows-package*, which builds from the tagged commit, runs the
   self-test, a silent install and uninstall, and attaches the installer, zip and self-test
   report to the release, with `docs/release-notes/vX.Y.Z.md` as its text.
6. Check that the release has the three files and that the self-test report ends with
   `RESULT: all checks passed`.

## Reproducibility

* The release is built from the tagged commit only.
* The Windows build installs exact library versions from
  `packaging/windows-constraints.txt` and uses Python 3.12.10, so rebuilding a tag gives
  the same libraries. Change those versions only in a commit of their own, followed by a
  full test and package run.
* The tests workflow deliberately uses version ranges (`requirements.txt`) on several
  Python versions, to catch breakage from new library releases early.
* Builds are not byte-for-byte identical (PyInstaller and the installer embed time
  stamps), and they are not code-signed yet.
