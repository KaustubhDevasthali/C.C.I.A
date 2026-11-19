# Code Change Impact Analyzer (CCIA)

CCIA compares two committed Git snapshots and traces which unchanged Python files
may depend on the changed files. It runs locally with Python 3.12+ and Git 2.30+.
The CLI reads Git objects without writing to the index, refs, or working tree.

## Run

From the project directory:

```sh
PYTHONPATH=src python3.12 -m ccia.cli HEAD^ HEAD --repo /path/to/repo
```

Use `--source-root src` for a repository whose importable packages live under
`src/`. The default import root is the Git tree root. With setuptools 68+ already
installed, `python3.12 -m pip install --no-build-isolation --no-deps .` installs the
`ccia` command. The module command requires no installation.

## Try the sample

Run these commands from the CCIA project directory. They create two commits in
a new temporary repository.

```sh
demo_repo=$(mktemp -d)
git -C "$demo_repo" init --quiet --template=
git -C "$demo_repo" config user.name "CCIA Example"
git -C "$demo_repo" config user.email "ccia@example.invalid"
cp -R examples/base/. "$demo_repo/"
git -C "$demo_repo" add .
git -C "$demo_repo" -c core.hooksPath=/dev/null commit --quiet --no-gpg-sign -m "Base snapshot"
cp -R examples/head/. "$demo_repo/"
git -C "$demo_repo" add .
git -C "$demo_repo" -c core.hooksPath=/dev/null commit --quiet --no-gpg-sign -m "Update prices"
PYTHONPATH=src python3.12 -m ccia.cli HEAD^ HEAD --repo "$demo_repo"
```

The report lists `shop/prices.py` as modified and `main.py` and
`shop/checkout.py` as impacted. Reports include resolved commit IDs, sorted
Git paths with status codes, sorted impacted paths, and parse warnings by
snapshot. Exit status is 0 for a report and 2 for an input or Git error.

## Scope and limitations

- Compares committed trees. Dirty, staged, and untracked files are outside the
  comparison. Renames appear as deletions and additions.
- Builds a graph in each snapshot from regular `.py` blobs under one import
  root. It recognizes absolute and relative imports and package initializers.
  Looking at both snapshots preserves dependencies on added or removed modules.
- Estimates file-level impact from imports. It treats conditional imports as
  possible and may mistake a `from` import of an attribute for a submodule.
  Dynamic imports, runtime path changes, external packages, symlinks, and
  submodule contents are outside its model. Unparseable files produce warnings
  and contribute no outgoing import edges.
- Parses both source trees, sharing parsed blobs within a run. It is intended
  for small repositories and needs the relevant commit objects available locally.

Roadmap: support multiple import roots, optional staged comparisons, and
explanations showing which import chains led to each impacted file.

## Tests

```sh
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
```

Tests use the standard library and temporary local Git repositories. MIT licensed.
