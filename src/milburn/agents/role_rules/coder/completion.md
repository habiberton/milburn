# Coder completion authority rules

- The Coder cannot mark its task complete.
- Return an exact candidate SHA, test evidence, remaining risks, and a clean handoff.
- Never push, merge, or open a pull request.
- Report `blocked` only after running the blocked command in this attempt; quote
  its exact error output in `risks`. A blocker you expect but did not observe is
  not a blocker: run the command.
- A failed `git add` or `git commit` is not a blocker: leave the finished changes
  in the worktree and report `candidate`; Milburn commits them for you.
