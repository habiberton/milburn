"""Stub ``gh`` for delivery tests: pull requests over a local bare remote.

State lives in the JSON file named by FAKE_GH_STATE; the bare repository named
by FAKE_GH_REMOTE stands in for GitHub. ``pr merge`` performs a real merge
commit into the remote's base branch, so the CLI's post-merge checks run
against real Git. Mirrors real gh and GitHub where Milburn depends on them:
``pr list --head`` matches the branch name only (forks included), a second
open PR for the same head and base is refused, only an OPEN PR merges, and
``pr checks`` exits 1 when a check fails and 8 while one is pending.

Knobs:
- FAKE_GH_REQUIRED: comma-separated required contexts from branch protection
  ("" = branch not protected; "forbidden" = 403 on the protection read)
- FAKE_GH_RULES: comma-separated required contexts from rulesets
- FAKE_GH_CHECKS: none (no checks reported) | pass | pending | fail, for "ci"
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


def fail_with(message: str, code: int = 1) -> None:
    save(state)
    print(message, file=sys.stderr)
    sys.exit(code)


def remote_head(branch: str) -> str | None:
    done = subprocess.run(("git", "--git-dir", remote, "rev-parse", "--verify", "--quiet",
                           f"refs/heads/{branch}"), capture_output=True, text=True)
    return done.stdout.strip() or None


def option(name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def view(pr: dict) -> dict:
    if pr["state"] == "OPEN" and not pr["isCrossRepository"]:
        pr["headRefOid"] = remote_head(pr["headRefName"]) or pr["headRefOid"]
    return pr


def contexts(variable: str) -> list[str]:
    return [c for c in os.environ.get(variable, "").split(",") if c]


state = load()
state["calls"].append(args)
fail = os.environ.get("FAKE_GH_FAIL", "")
if args[:1] == ["api"]:
    path = args[-1]
    if path.endswith("/protection/required_status_checks"):
        required = os.environ.get("FAKE_GH_REQUIRED", "")
        if required == "forbidden":
            fail_with("gh: Resource not accessible by integration (HTTP 403)")
        if not required:
            fail_with("gh: Branch not protected (HTTP 404)")
        print(json.dumps({"strict": True, "contexts": required.split(","),
                          "checks": [{"context": c, "app_id": None} for c in required.split(",")]}))
    elif "/rules/branches/" in path:
        rules = contexts("FAKE_GH_RULES")
        print(json.dumps([{"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": c} for c in rules]}}] if rules else []))
    else:
        fail_with(f"fake gh: unsupported api {path}", 2)
elif args[:2] == ["pr", "list"]:
    head, wanted = option("--head"), option("--state") or "open"
    prs = [view(p) for p in state["prs"] if p["headRefName"] == head]
    if wanted != "all":
        prs = [p for p in prs if p["state"] == wanted.upper()]
    print(json.dumps(prs))
elif args[:2] == ["pr", "create"]:
    if fail == "create":
        fail_with("GraphQL: something went wrong")
    head, base = option("--head"), option("--base")
    if remote_head(head) is None:
        fail_with(f"pull request create failed: head branch {head} not found")
    for pr in state["prs"]:
        if (pr["headRefName"], pr["baseRefName"], pr["state"], pr["isCrossRepository"]) == (head, base, "OPEN", False):
            fail_with(f"a pull request for branch \"{head}\" into branch \"{base}\" already exists")
    number = len(state["prs"]) + 1
    state["prs"].append({
        "number": number, "url": f"https://github.example/acme/toy/pull/{number}",
        "state": "OPEN", "headRefName": head, "headRefOid": remote_head(head),
        "baseRefName": base, "body": option("--body"), "title": option("--title"),
        "mergeCommit": None, "isCrossRepository": False,
    })
    print(state["prs"][-1]["url"])
elif args[:2] == ["pr", "view"]:
    print(json.dumps(view(state["prs"][int(args[2]) - 1])))
elif args[:2] == ["pr", "checks"]:
    mode = os.environ.get("FAKE_GH_CHECKS", "none")
    if mode == "none":
        fail_with("no checks reported on the 'x' branch")
    print(json.dumps([{"name": "ci", "bucket": mode}, {"name": "lint", "bucket": "pass"}]))
    save(state)
    sys.exit({"pass": 0, "pending": 8, "fail": 1}[mode])
elif args[:2] == ["pr", "merge"]:
    pr = view(state["prs"][int(args[2]) - 1])
    if pr["state"] != "OPEN":
        fail_with(f"Pull request #{pr['number']} is not mergeable: the pull request is {pr['state'].lower()}")
    if pr["headRefOid"] != option("--match-head-commit"):
        fail_with("Head branch was modified. Review and try the merge again.")
    with tempfile.TemporaryDirectory() as work:
        run = lambda *a: subprocess.run(a, cwd=work, check=True, capture_output=True, text=True)
        run("git", "clone", "-q", "-b", pr["baseRefName"], remote, ".")
        run("git", "-c", "user.name=GitHub", "-c", "user.email=noreply@github.example", "merge",
            "--no-ff", "-q", "-m", option("--subject"), pr["headRefOid"])
        run("git", "push", "-q", "origin", pr["baseRefName"])
        merge = run("git", "rev-parse", "HEAD").stdout.strip()
    pr.update(state="MERGED", mergeCommit={"oid": merge})
    if fail == "merge-after":
        fail_with("merge request timed out")
else:
    fail_with(f"fake gh: unsupported {args}", 2)
save(state)
