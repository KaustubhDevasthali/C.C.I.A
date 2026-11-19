"""Compare committed Git trees and trace local Python imports."""

import ast
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
import os
import subprocess


class GitError(Exception):
    """A Git command could not read the requested data."""


def _git(repo: Path, *args: str) -> bytes:
    env = {
        **os.environ,
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LC_ALL": "C",
    }
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        env=env,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise GitError(result.stderr.decode("utf-8", errors="replace").strip()
                       or f"Git exited with status {result.returncode}")
    return result.stdout


def _changes(repo: Path, base: str, head: str) -> list[dict[str, str]]:
    records = _git(
        repo, "diff", "--name-status", "-z", "--no-relative", "--no-renames",
        "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", base, head, "--",
    ).split(b"\0")[:-1]
    changes = [
        {"path": os.fsdecode(path), "status": status.decode("ascii")}
        for status, path in zip(records[::2], records[1::2], strict=True)
    ]
    return sorted(changes, key=lambda change: change["path"])


def _python_files(repo: Path, commit: str, root: PurePosixPath):
    records = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0")
    for record in records[:-1]:
        metadata, raw_path = record.split(b"\t", 1)
        mode, _, object_id = metadata.split()
        path = PurePosixPath(os.fsdecode(raw_path))
        if mode not in {b"100644", b"100755"} or path.suffix != ".py":
            continue
        if not path.is_relative_to(root):
            continue
        relative = path.relative_to(root)
        if relative.stem == "__init__":
            module = relative.parts[:-1]
            package = module
        else:
            module = (*relative.parts[:-1], relative.stem)
            package = module[:-1]
        if module and all(part.isidentifier() for part in module):
            yield str(path), object_id.decode("ascii"), module, package


def _import_targets(tree: ast.AST, package: tuple[str, ...]):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [tuple(alias.name.split(".")) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > len(package):
                continue
            prefix = package[:len(package) - node.level + 1] if node.level else ()
            if node.module:
                prefix += tuple(node.module.split("."))
            names = [prefix]
            names.extend((*prefix, alias.name) for alias in node.names if alias.name != "*")
        else:
            continue
        for name in names:
            for depth in range(1, len(name) + 1):
                yield name[:depth]


def _impact(repo: Path, commit: str, root: PurePosixPath, changed: set[str],
            parsed: dict[str, ast.AST | str]) -> tuple[set[str], list[dict[str, str]]]:
    files = list(_python_files(repo, commit, root))
    modules = defaultdict(set)
    for path, _, module, _ in files:
        modules[module].add(path)

    importers = defaultdict(set)
    warnings = []
    for path, object_id, _, package in sorted(files):
        if object_id not in parsed:
            try:
                parsed[object_id] = ast.parse(
                    _git(repo, "cat-file", "blob", object_id), feature_version=(3, 12),
                )
            except SyntaxError as error:
                parsed[object_id] = f"line {error.lineno}: {error.msg}"
            except ValueError as error:
                parsed[object_id] = str(error)
        tree = parsed[object_id]
        if isinstance(tree, str):
            warnings.append({"path": path, "message": tree})
            continue
        for target in _import_targets(tree, package):
            for dependency in modules.get(target, ()):
                if dependency != path:
                    importers[dependency].add(path)

    reached = set(changed)
    pending = deque(changed)
    while pending:
        for importer in importers.get(pending.popleft(), ()):
            if importer not in reached:
                reached.add(importer)
                pending.append(importer)
    return reached - changed, warnings


def analyze(repo: Path, base_ref: str, head_ref: str, source_root: str = ".") -> dict:
    """Report tree changes and unchanged transitive importers in either snapshot."""
    root = PurePosixPath(source_root)
    if root.is_absolute() or ".." in root.parts:
        raise ValueError("source root must be a repo-relative directory without '..'")
    commits = {
        label: _git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        .decode("ascii").strip()
        for label, ref in (("base", base_ref), ("head", head_ref))
    }
    changes = _changes(repo, commits["base"], commits["head"])
    changed = {change["path"] for change in changes}
    parsed = {}
    impacted = set()
    warnings = []
    for label, commit in commits.items():
        snapshot_impact, snapshot_warnings = _impact(repo, commit, root, changed, parsed)
        impacted.update(snapshot_impact)
        warnings.extend({"snapshot": label, **warning} for warning in snapshot_warnings)

    return {
        **commits,
        "source_root": str(root),
        "changes": changes,
        "impacted_python_files": sorted(impacted),
        "warnings": warnings,
    }
