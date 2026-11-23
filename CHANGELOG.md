# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Lower `requires-python` floor to `>=3.10`; no 3.11-only syntax in `src/` (the floor had blocked editable installs in the 3.10 MCP environment).
- Acceptance tests skip cleanly when `radicale` is not installed (Windows dev hosts); EOL pin handling fixed.
- CI triggers now match suite policy: `pull_request` to `main` + `workflow_dispatch` only.
- Added `publish.yml` (PyPI trusted publishing) and `notify-feature.yml` workflows, `.mailmap`, and this changelog.
- Packaging aligned with the suite for the first PyPI release: `__version__` from distribution metadata, project URLs, classifiers, README install section.
- `acceptance` extra pins `agents-calendar>=0.2.0` from PyPI instead of a git commit URL (PyPI rejects direct URL dependencies).
