# Changelog

All notable changes to the Griptape Nodes Luma Labs Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/), and each version is
the `library_version` in `luma/griptape_nodes_library.json`.
**Breaking** marks a change that can stop a saved workflow from working without edits.

## [Unreleased]

<!-- Entries go in changelog.d/, one file each. See changelog.d/README.md. -->

## [0.4.0] - 2026-11-06

### Changed

- **Breaking:** All six Luma nodes now check the API key and their inputs when the node runs, not when
  the flow starts. A flow with a missing key or an empty input now starts and fails at that node, after
  upstream nodes have run, and a wired `Failed` output is not followed for a missing key. Most workflows
  need no change. If one relied on the flow refusing to start, check for the error on the node.
  [#18](https://github.com/griptape-ai/griptape-nodes-library-luma/issues/18)
- Luma nodes report failures as structured errors. The editor shows Luma's own message, and the status
  code, request ID, generation ID and Luma's response appear under "More info". A missing key links to
  Settings and to the Luma API key page, and a refused key links to Settings. A missing key is reported
  on its own, before any input problem. Requires engine 0.105.0.
  [#18](https://github.com/griptape-ai/griptape-nodes-library-luma/issues/18)

[Unreleased]: https://github.com/griptape-ai/griptape-nodes-library-luma/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/griptape-ai/griptape-nodes-library-luma/compare/d93254ddcbbe70bce1cb384039a9d582d660a2dc...v0.4.0
