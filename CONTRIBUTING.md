# Contributing to localRAGcoder

## PR flow (mandatory)

- All changes go through draft PRs. No direct pushes to `main` — ever.
- CI must be green before owner review.
- Each PR adds a CHANGELOG.md entry under `## [Unreleased]`.
- Each PR bumps the version: patch for fixes/chores, minor for features.
- Merge commits reference the PR number; releases are tagged `vX.Y.Z` after merge.
- Note: GitHub required status checks need Pro/Team on private repos — until
  then, green-merge is manual discipline.

## Build / test

```bash
pip install -r requirements.txt
python run_tests.py --unit        # unit tests
python run_tests.py               # full suite
```

Builds: `.\deploy.ps1 -Install|-Test|-PWA|-Windows|-All` (Windows) or
`make android|ios|pwa|windows|linux` (see Makefile).

## Packaging

- **Android**: Chaquopy + PWA WebView (`packaging/android/`)
- **PWA**: installable web app (`packaging/pwa/`)
- **Windows**: PyInstaller EXE (`packaging/windows/`)
- **Linux**: AppImage (`packaging/linux/`)
