# SearXNG Runtime Input

This directory records the SearXNG inputs used by the AIO image. The source is
the published `docker.io/searxng/searxng:latest` artifact locked in
`aio/provenance/components.lock.json`, not the repository default branch.

Current locked identity:

- OCI version: `2026.7.15-7b2199ecd`
- source commit: `7b2199ecdf75a00981583fa2f392a785dfc4fcee`
- linux/amd64 manifest: `sha256:1a196e52ef0aec52a462667e5c54030840f94865c13e1260004caa10cca6be49`

`requirements.txt` and `requirements-server.txt` mirror that exact source
commit. The AIO build installs them into `/home/appuser/.venv`; it must not copy
the upstream image's Void Linux virtual environment into the Debian runtime.
