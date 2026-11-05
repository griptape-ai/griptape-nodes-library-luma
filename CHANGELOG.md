# Changelog

All notable changes to the Griptape Nodes Luma Labs Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/), and each version is
the `library_version` in `luma/griptape_nodes_library.json`.
**Breaking** marks a change that can stop a saved workflow from working without edits.

## [Unreleased]

<!-- Entries go in changelog.d/, one file each. See changelog.d/README.md. -->

## [0.4.0] - 2026-11-06

### Changed

- Luma nodes report failures as structured errors. The editor shows Luma's own message, and the status
  code, request ID, generation ID and Luma's response appear under "More info". A missing or refused
  `LUMA_AGENTS_API_KEY` links to Settings and to the Luma API key page. A missing key is reported on its
  own, before any input problem, when the node runs. Input problems are no longer checked when the flow
  starts, so a flow with an empty input now starts and fails at that node. Requires engine 0.105.0.
  [#18](https://github.com/griptape-ai/griptape-nodes-library-luma/issues/18)

[Unreleased]: https://github.com/griptape-ai/griptape-nodes-library-luma/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/griptape-ai/griptape-nodes-library-luma/compare/d93254ddcbbe70bce1cb384039a9d582d660a2dc...v0.4.0
