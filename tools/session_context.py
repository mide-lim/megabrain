#!/usr/bin/env python3
"""Capture and verify committed context; never grant authority or change Git."""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse


class ContextError(Exception):
    pass


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, timeout=15
    )
    if result.returncode:
        raise ContextError("Git verification failed: " + args[0])
    return result.stdout.decode("utf-8").strip()


def reference(value):
    url = urllib.parse.urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ContextError("Use a canonical HTTPS task/PR reference without credentials or query")
    return value


def context_path(value):
    path = pathlib.PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or str(path) != value
            or "\\" in value or not value.endswith(".md")):
        raise ContextError("Context must be a relative Markdown path")
    allowed = value == "AGENTS.md" or value.startswith("docs/") or value.startswith("evidence/context-handoffs/")
    if not allowed:
        raise ContextError("Only instructions, docs and context handoffs may be referenced")
    return value


def revision(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ContextError("Commit must be an exact 40-character SHA")
    return value


def current(repo, base):
    root = pathlib.Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != pathlib.Path(repo).resolve():
        raise ContextError("Use the task's exact worktree root")
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    if not branch.startswith("agent/"):
        raise ContextError("Execution context requires an agent/* branch")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContextError("Uncommitted changes exist; preserve them in an agent/* commit before capture/resume")
    head = git(root, "rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", revision(base), head],
        capture_output=True, timeout=15,
    )
    if ancestor.returncode:
        raise ContextError("Base commit is not an ancestor of the current HEAD")
    remote = git(root, "remote", "get-url", "origin")
    if remote != "https://github.com/mide-lim/megabrain.git":
        raise ContextError("Repository origin does not match mide-lim/megabrain")
    return {"repository": "mide-lim/megabrain", "worktree": str(root),
            "branch": branch, "head": head, "base": base,
            "tree": git(root, "rev-parse", "HEAD^{tree}")}


def document(repo, head, path):
    path = context_path(path)
    entry = git(repo, "ls-tree", head, "--", path)
    fields = entry.split("\t", 1)
    if len(fields) != 2 or fields[1] != path:
        raise ContextError("Required context document is not committed")
    mode, kind, blob = fields[0].split()
    if kind != "blob" or mode != "100644":
        raise ContextError("Context must be a regular non-executable Markdown file")
    if int(git(repo, "cat-file", "-s", blob)) > 262144:
        raise ContextError("Context document exceeds 256 KiB; use smaller references")
    return {"path": path, "blob": blob}


def capture(args):
    identity = current(args.repo, revision(args.base))
    paths = list(dict.fromkeys(["AGENTS.md", "docs/CONTEXT.md", "docs/DECISIONS.md",
                              args.packet, args.checkpoint]))
    refs = [document(args.repo, identity["head"], path) for path in paths]
    if not args.next_step.strip():
        raise ContextError("Next permitted step must be explicit")
    result = {"format": "megabrain-session-context-v1", "canonical_ref": reference(args.task_ref),
              "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "git": identity, "packet": args.packet, "checkpoint": args.checkpoint,
              "next_step": args.next_step, "refs": refs,
              "authority": "Reference projection only; consult canonical task, policies and resource APIs"}
    # Recheck Git after reading references; never produce a checkpoint across a changed HEAD.
    if current(args.repo, args.base) != identity:
        raise ContextError("Git changed during capture")
    output = pathlib.Path(args.output).resolve()
    root = pathlib.Path(identity["worktree"])
    if output == root or root in output.parents:
        raise ContextError("Save the projection outside the tracked checkout")
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {"status": "captured", "head": identity["head"], "snapshot": str(output)}


def verify(args):
    path = pathlib.Path(args.snapshot)
    if path.stat().st_size > 65536:
        raise ContextError("Snapshot exceeds 64 KiB")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved["format"] != "megabrain-session-context-v1":
        raise ContextError("Unsupported context projection")
    if reference(args.task_ref) != saved["canonical_ref"]:
        raise ContextError("Canonical task/PR reference differs")
    observed = current(args.repo, revision(saved["git"]["base"]))
    if observed != saved["git"]:
        raise ContextError("Worktree, branch, HEAD or tree differs; reconcile without reset")
    required = {"AGENTS.md", "docs/CONTEXT.md", "docs/DECISIONS.md",
                context_path(saved["packet"]), context_path(saved["checkpoint"])}
    refs = saved["refs"]
    if not isinstance(refs, list) or {item["path"] for item in refs} != required or len(refs) != len(required):
        raise ContextError("Essential context references are missing or duplicated")
    for item in refs:
        if document(args.repo, observed["head"], item["path"]) != item:
            raise ContextError("A pinned context document differs")
    if not isinstance(saved["next_step"], str) or not saved["next_step"].strip():
        raise ContextError("Next permitted step is missing")
    if current(args.repo, observed["base"]) != observed:
        raise ContextError("Git changed during verification")
    return {"status": "verified", "canonical_ref": saved["canonical_ref"], "git": observed,
            "read_before_execution": refs, "next_step": saved["next_step"],
            "authority": "Reference projection only; consult canonical task, policies and resource APIs"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ["capture", "verify"]:
        sub = subs.add_parser(name)
        sub.add_argument("--repo", default=".")
        sub.add_argument("--task-ref", required=True)
        if name == "capture":
            for flag in ["base", "packet", "checkpoint", "next-step", "output"]:
                sub.add_argument("--" + flag, required=True)
        else:
            sub.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    try:
        result = capture(args) if args.command == "capture" else verify(args)
    except (ContextError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        # Avoid dumping paths, credentials, provider logs or malformed snapshot contents.
        exc = sys.exc_info()[1]
        reason = str(exc) if isinstance(exc, ContextError) else "Invalid snapshot or unavailable Git/filesystem"
        print(json.dumps({"status": "blocked", "reason": reason}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
