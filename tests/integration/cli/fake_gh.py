"""Stub ``gh`` for delivery tests: pull requests over a local bare remote.

State lives in the JSON file named by FAKE_GH_STATE; the bare repository named
by FAKE_GH_REMOTE stands in for GitHub. ``pr merge`` performs a real merge
commit into the remote's base branch, so the CLI's post-merge checks run
against real Git. Knobs:

- FAKE_GH_CHECKS: none (default) | pass | pending | fail
- FAKE_GH_FAIL: create | merge-after (merge happens, then the call fails)
"""

import json
import os
import subprocess
import sys
import tempfile

state_path = os.environ["FAKE_GH_STATE"]
remote = os.environ["FAKE_GH_REMOTE"]
args = sys.argv[1:]


def load() -> dict:
    try:
        with open(state_path) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"prs": [], "calls": []}


def save(state: dict) -> None:
    with open(state_path, "w") as handle:
        json.dump(state, handle)


def remote_head(branch: str) -> str | None:
    done = subprocess.run(("git", "--git-dir", remote, "rev-parse", "--verify", "--quiet",
                           f"refs/heads/{branch}"), capture_output=True, text=True)
    return done.stdout.strip() or None


def option(name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def view(pr: dict) -> dict:
    if pr["state"] == "OPEN":
        pr["headRefOid"] = remote_head(pr["headRefName"]) or pr["headRefOid"]
    return pr


state = load()
state["calls"].append(args)
fail = os.environ.get("FAKE_GH_FAIL", "")
if args[:2] == ["pr", "list"]:
    head = option("--head")
    print(json.dumps([view(p) for p in state["prs"] if p["headRefName"] == head]))
elif args[:2] == ["pr", "create"]:
    if fail == "create":
        save(state)
        print("GraphQL: something went wrong", file=sys.stderr)
        sys.exit(1)
    head, base = option("--head"), option("--base")
    if remote_head(head) is None:
        save(state)
        print(f"pull request create failed: head branch {head} not found", file=sys.stderr)
        sys.exit(1)
    number = len(state["prs"]) + 1
    state["prs"].append({
        "number": number, "url": f"https://github.example/acme/toy/pull/{number}",
        "state": "OPEN", "headRefName": head, "headRefOid": remote_head(head),
        "baseRefName": base, "body": option("--body"), "title": option("--title"),
        "mergeCommit": None,
    })
    print(state["prs"][-1]["url"])
elif args[:2] == ["pr", "view"]:
    print(json.dumps(view(state["prs"][int(args[2]) - 1])))
elif args[:2] == ["pr", "checks"]:
    mode = os.environ.get("FAKE_GH_CHECKS", "none")
    if mode == "none":
        save(state)
        print("no required checks reported on the 'x' branch", file=sys.stderr)
        sys.exit(1)
    bucket = {"pass": "pass", "pending": "pending", "fail": "fail"}[mode]
    print(json.dumps([{"name": "ci", "bucket": bucket}, {"name": "lint", "bucket": "pass"}]))
    save(state)
    sys.exit(0 if mode == "pass" else 8)
elif args[:2] == ["pr", "merge"]:
    pr = view(state["prs"][int(args[2]) - 1])
    if pr["headRefOid"] != option("--match-head-commit"):
        save(state)
        print("Head branch was modified. Review and try the merge again.", file=sys.stderr)
        sys.exit(1)
    with tempfile.TemporaryDirectory() as work:
        run = lambda *a: subprocess.run(a, cwd=work, check=True, capture_output=True, text=True)
        run("git", "clone", "-q", "-b", pr["baseRefName"], remote, ".")
        run("git", "-c", "user.name=GitHub", "-c", "user.email=noreply@github.example", "merge",
            "--no-ff", "-q", "-m", option("--subject"), f"origin/{pr['headRefName']}")
        run("git", "push", "-q", "origin", pr["baseRefName"])
        merge = run("git", "rev-parse", "HEAD").stdout.strip()
    pr.update(state="MERGED", mergeCommit={"oid": merge})
    if fail == "merge-after":
        save(state)
        print("merge request timed out", file=sys.stderr)
        sys.exit(1)
else:
    save(state)
    print(f"fake gh: unsupported {args}", file=sys.stderr)
    sys.exit(2)
save(state)
