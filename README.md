# Milburn

Milburn is a local-first control plane for coordinating specialized Codex
agents. The repository is currently in its bootstrap phase: a root Codex agent
temporarily coordinates isolated worker agents until Milburn can coordinate its
own development.

The approved product and architecture specifications are:

- [`PRD.md`](PRD.md)
- [`ARCH.md`](ARCH.md)

To start the first build session:

1. Run `scripts/bootstrap-repo.sh` once from the repository root.
2. Launch a Codex task in the primary checkout with multi-agent support enabled.
3. Use the prompt in [`bootstrap/ROOT_PROMPT.md`](bootstrap/ROOT_PROMPT.md).

The operating process is documented in [`AGENTS.md`](AGENTS.md) and
[`bootstrap/README.md`](bootstrap/README.md).

