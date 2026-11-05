---
name: milburn-long-running-coder
version: 1.0.0
description: Implement one issue with durable progress, recovery, and handoff evidence.
resources: ["references/startup-checklist.md", "references/progress-template.txt", "references/completion-checklist.md"]
scripts: ["scripts/verify-handoff.py"]
---

# Milburn long-running Coder

Use this skill for one approved issue in one assigned worktree. Recover from durable evidence, implement small tested slices, keep progress current, and return a local candidate with exact evidence. Run the handoff validator before stopping.

Read the startup checklist before editing and the completion checklist before handoff. Run tests through `scripts/run-tests.sh` in the assigned worktree; record its bounded summary and log reference in `progress.txt`. Write negative tests before validators and adapters, and cover fake/live parity when adding a fake.

For every boundary you touch, answer these six questions and add a regression test for a weaker case that could pass:

1. What could pass each check while the real condition is false?
2. Is every field and variant of an accepted input validated or explicitly ignored?
3. Can any caller bypass a public entry point's guard?
4. Is every identifier unique across its full key scope?
5. Are preconditions checked before every state change or external effect, with consistent failure paths?
6. Does each test double enforce the live boundary's preconditions and terminal states?
