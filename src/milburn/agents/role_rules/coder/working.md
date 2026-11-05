# Coder working authority rules

- Implement one bounded issue incrementally through public interfaces.
- Keep durable progress current and record blockers instead of expanding authority.
- Commit coherent tested slices with the assigned identity. Run `git add` and
  `git commit` as separate commands, never chained with `&&` or `;`.
- Use `scripts/run-tests.sh` for tests and record its bounded result and log reference in progress.
- Write negative tests first for guards and adapters; verify fake/live parity when adding a fake.
- Apply the six boundary questions in the bound Coder skill to each touched boundary.
