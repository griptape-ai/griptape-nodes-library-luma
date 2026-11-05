- Luma nodes report failures as structured errors. The editor shows Luma's own message, and the status
  code, request ID, generation ID and Luma's response appear under "More info". A missing or refused
  `LUMA_AGENTS_API_KEY` links to Settings and to the Luma API key page. A missing key is reported on its
  own, before any input problem, when the node runs. Input problems are no longer checked when the flow
  starts, so a flow with an empty input now starts and fails at that node. Requires engine 0.104.0.
  [#18](https://github.com/griptape-ai/griptape-nodes-library-luma/issues/18)
