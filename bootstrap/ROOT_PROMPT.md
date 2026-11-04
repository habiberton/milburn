# First root-agent prompt

Copy the prompt below into the first Codex task launched from the primary
Milburn checkout. No separate architecture-review prompt is needed.

```text
You are the root bootstrap coordinator for Milburn.

Follow AGENTS.md exactly. PRD.md and ARCH.md contain approved product and
architecture decisions; do not reassess or redesign them. Begin with the Wave 0
bootstrap verification in bootstrap/README.md, reconcile bootstrap/tasks.json
with the repository, and then start the first ready task.

Follow the predefined work waves. Complete Wave 1 sequentially. In later waves,
use subagents in isolated Git worktrees only when the parallel-delegation gate
in AGENTS.md is satisfied. Start with no more than two implementation workers,
even if more concurrency is available.

You own the task registry, worktree creation, integration, shared interfaces,
and completion decisions. Workers own one task and one progress record, produce
candidate commits, and never merge their own work.

Persist until you have completed and independently verified as much of the
current wave as is safely possible. Before stopping, leave exact recovery
instructions in bootstrap/progress/coordinator.md.
```

