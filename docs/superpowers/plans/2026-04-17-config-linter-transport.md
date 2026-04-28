# Config Linter Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transport the config linter from `integration-benchmarking` to `pyth-lazer-staging-governance` and wire it into the PR CI so every governance proposal is automatically linted.

**Architecture:** Copy the linter source (CLI + lib + tests + rule reference) verbatim into `tools/config-linter/` in the governance repo. Extend the existing `.github/workflows/ci-pr.yml` with four new steps: set up Python, install pytest, run the linter tests (always), and run the linter against the changed proposal's `after.json` (only when a proposal is detected). Errors exit 1 and block the PR; warnings print but do not block. Governance becomes the canonical home for future linter edits.

**Tech Stack:** Python 3.12 standard library (linter, no runtime deps), pytest (tests only), GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`), bash.

**Reference spec:** `docs/superpowers/specs/2026-04-17-config-linter-transport-design.md`

**Source file paths (integration-benchmarking):**

- `/home/mariobern/integration-benchmarking/config_linter.py`
- `/home/mariobern/integration-benchmarking/lib/config_lint.py`
- `/home/mariobern/integration-benchmarking/lib/symbol_utils.py`
- `/home/mariobern/integration-benchmarking/tests/test_config_lint.py`
- `/home/mariobern/integration-benchmarking/tests/test_config_linter_cli.py`
- `/home/mariobern/integration-benchmarking/docs/config_linter.md`

**Target repo:** `/home/mariobern/pyth-lazer-staging-governance`

---

## Task 1: Create branch and directory structure in governance

**Files:**

- Create: `/home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/`
- Create: `/home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests/`
- Create: `/home/mariobern/pyth-lazer-staging-governance/docs/`

- [ ] **Step 1: Confirm governance repo is clean and on main**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && git status
```

Expected: `On branch main`, `nothing to commit, working tree clean`. If not clean, stop and ask the user before continuing.

- [ ] **Step 2: Create branch `feat/config-linter`**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && git checkout -b feat/config-linter
```

Expected: `Switched to a new branch 'feat/config-linter'`.

- [ ] **Step 3: Create the directory tree**

Run:

```bash
mkdir -p /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib
mkdir -p /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests
mkdir -p /home/mariobern/pyth-lazer-staging-governance/docs
```

Expected: no output. Verify with `ls -d /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/{lib,tests} /home/mariobern/pyth-lazer-staging-governance/docs`.

- [ ] **Step 4: No commit yet** — empty directories are not tracked by git; Task 2 creates files that will make them real.

---

## Task 2: Copy linter source files

**Files:**

- Create: `tools/config-linter/config_linter.py` (copy from source)
- Create: `tools/config-linter/lib/config_lint.py` (copy from source)
- Create: `tools/config-linter/lib/symbol_utils.py` (copy from source)
- Create: `tools/config-linter/lib/__init__.py` (new, empty)

- [ ] **Step 1: Copy the three Python source files**

Run:

```bash
cp /home/mariobern/integration-benchmarking/config_linter.py /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/config_linter.py
cp /home/mariobern/integration-benchmarking/lib/config_lint.py /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/config_lint.py
cp /home/mariobern/integration-benchmarking/lib/symbol_utils.py /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/symbol_utils.py
```

Expected: no output. Verify with:

```bash
wc -l /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/config_linter.py \
      /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/config_lint.py \
      /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/symbol_utils.py
```

Expected line counts (approximate, match the source):

- `config_linter.py`: 175 lines
- `lib/config_lint.py`: ~959 lines
- `lib/symbol_utils.py`: ~60 lines

- [ ] **Step 2: Create empty `lib/__init__.py`**

Run:

```bash
touch /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/__init__.py
```

Expected: no output. Verify: `test -f /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/lib/__init__.py && echo ok`.

- [ ] **Step 3: Sanity-check imports before committing**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && python3 -c "import sys; sys.path.insert(0, 'tools/config-linter'); from lib.config_lint import lint_config; print('imports ok')"
```

Expected: `imports ok`. If this fails, stop and debug — something is wrong with the copy.

- [ ] **Step 4: Commit**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  git add tools/config-linter/config_linter.py \
          tools/config-linter/lib/config_lint.py \
          tools/config-linter/lib/symbol_utils.py \
          tools/config-linter/lib/__init__.py && \
  git commit -m "feat: copy config linter source from integration-benchmarking"
```

Expected: `4 files changed, ~1194 insertions(+)`.

---

## Task 3: Copy linter tests

**Files:**

- Create: `tools/config-linter/tests/test_config_lint.py` (copy from source)
- Create: `tools/config-linter/tests/test_config_linter_cli.py` (copy from source)
- Create: `tools/config-linter/tests/__init__.py` (new, empty)

- [ ] **Step 1: Copy the two test files**

Run:

```bash
cp /home/mariobern/integration-benchmarking/tests/test_config_lint.py /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests/test_config_lint.py
cp /home/mariobern/integration-benchmarking/tests/test_config_linter_cli.py /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests/test_config_linter_cli.py
```

Expected: no output. Verify with:

```bash
wc -l /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests/test_config_lint.py \
      /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests/test_config_linter_cli.py
```

Expected: ~1547 and ~123 lines.

- [ ] **Step 2: Create empty `tests/__init__.py`**

Run:

```bash
touch /home/mariobern/pyth-lazer-staging-governance/tools/config-linter/tests/__init__.py
```

- [ ] **Step 3: Ensure pytest is installed locally**

Run:

```bash
python3 -c "import pytest; print(pytest.__version__)"
```

Expected: prints a version number (e.g., `7.4.4` or similar). If it errors with `ModuleNotFoundError`, run `pip install pytest` before continuing.

- [ ] **Step 4: Run the test suite locally**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance/tools/config-linter && python3 -m pytest tests/ -v
```

Expected: all tests pass. There are several hundred tests across `test_config_lint.py` and 7 in `test_config_linter_cli.py`. If any fail, stop and debug — most likely cause is an `__init__.py` / `sys.path` issue (fix by ensuring the `__init__.py` files from Task 2 step 2 and Task 3 step 2 exist).

- [ ] **Step 5: Commit**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  git add tools/config-linter/tests/ && \
  git commit -m "test: copy config linter test suite"
```

Expected: `3 files changed, ~1670 insertions(+)`.

---

## Task 4: Add rule reference docs and tool README

**Files:**

- Create: `docs/config_linter.md` (copy from source)
- Create: `tools/config-linter/README.md` (new, short)

- [ ] **Step 1: Copy the full rule reference**

Run:

```bash
cp /home/mariobern/integration-benchmarking/docs/config_linter.md /home/mariobern/pyth-lazer-staging-governance/docs/config_linter.md
```

Expected: no output. Verify:

```bash
wc -l /home/mariobern/pyth-lazer-staging-governance/docs/config_linter.md
```

Expected: ~158 lines.

- [ ] **Step 2: Write `tools/config-linter/README.md`**

Create file `/home/mariobern/pyth-lazer-staging-governance/tools/config-linter/README.md` with exactly this content:

````markdown
# Config Linter

Validates `after.json` proposal configs for common errors (duplicate feed IDs, unknown publishers, schedule inconsistencies, benchmark mapping mismatches, etc.). Runs automatically on every pull request via `.github/workflows/ci-pr.yml`. Errors block merge; warnings are reported but non-blocking.

Rules are implemented in `lib/config_lint.py`. Full reference for every rule (E001–E016, W001–W009) is in [`../../docs/config_linter.md`](../../docs/config_linter.md).

## Local usage

```bash
# Lint a single proposal
python3 tools/config-linter/config_linter.py --config <proposal-dir>/after.json

# Machine-readable output
python3 tools/config-linter/config_linter.py --config <proposal-dir>/after.json --format json

# Treat warnings as errors
python3 tools/config-linter/config_linter.py --config <proposal-dir>/after.json --warnings-as-errors
```

Exit codes: `0` clean (or warnings only), `1` at least one error (or warning with `--warnings-as-errors`).

## Running the test suite

```bash
cd tools/config-linter && python3 -m pytest tests/ -v
```

Tests have no runtime dependencies beyond `pytest` and the Python standard library.
````

- [ ] **Step 3: Commit**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  git add docs/config_linter.md tools/config-linter/README.md && \
  git commit -m "docs: add config linter rule reference and tool README"
```

Expected: `2 files changed, ~185 insertions(+)`.

---

## Task 5: Extend ci-pr.yml with Python setup, tests, and lint steps

**Files:**

- Modify: `.github/workflows/ci-pr.yml` (append 4 steps after the existing `Push changes` step, ending at line 78)

- [ ] **Step 1: Open `.github/workflows/ci-pr.yml`**

Read `/home/mariobern/pyth-lazer-staging-governance/.github/workflows/ci-pr.yml`. The last existing step is `Push changes`, which ends with the `env:` block at lines 77–78:

```yaml
env:
  GH_TOKEN: ${{ secrets.GH_OPS_TOKEN }}
```

- [ ] **Step 2: Append 4 new steps after the `env:` block**

Add exactly these lines to the end of the file, preserving YAML indentation (6 spaces for step keys under `steps:`):

```yaml
- name: Set up Python
  uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- name: Install linter dependencies
  run: pip install pytest
- name: Run linter tests
  working-directory: tools/config-linter
  run: python3 -m pytest tests/ -v
- name: Lint proposal config
  if: env.PROPOSAL_DIR != ''
  run: python3 tools/config-linter/config_linter.py --config "${PROPOSAL_DIR}/after.json"
```

- [ ] **Step 3: Validate YAML parses**

Run:

```bash
python3 -c "import yaml; yaml.safe_load(open('/home/mariobern/pyth-lazer-staging-governance/.github/workflows/ci-pr.yml'))" && echo "yaml ok"
```

Expected: `yaml ok`. If `yaml` import fails, try `python3 -c "import json; import sys; sys.exit(0)"` as a process check and install pyyaml: `pip install pyyaml`.

- [ ] **Step 4: Verify structure with grep**

Run:

```bash
grep -nE "^      - name:" /home/mariobern/pyth-lazer-staging-governance/.github/workflows/ci-pr.yml
```

Expected: 9 step names total, in this order:

1. (no name — `uses: actions/checkout@v4`, won't match this grep)
2. `Login to Docker repository`
3. `Pull Docker image`
4. `Detect proposal directory`
5. `Diff jsons`
6. `Push changes`
7. `Set up Python`
8. `Install linter dependencies`
9. `Run linter tests`
10. `Lint proposal config`

Exactly 9 matches from `grep`; the checkout step has no `name:` so it is excluded.

- [ ] **Step 5: Commit**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  git add .github/workflows/ci-pr.yml && \
  git commit -m "ci: run config linter and tests on PRs"
```

Expected: `1 file changed, 12 insertions(+)`.

---

## Task 6: Local end-to-end sanity check

**Files:** none modified. This task verifies what Tasks 2–5 produced.

- [ ] **Step 1: Re-run the full test suite**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance/tools/config-linter && python3 -m pytest tests/ -v
```

Expected: all tests pass, same as Task 3 Step 4. If they no longer pass, something was corrupted between tasks — bisect with `git diff`.

- [ ] **Step 2: Lint a real existing proposal**

Pick an existing proposal directory — use the most recent one:

```bash
ls -td /home/mariobern/pyth-lazer-staging-governance/2026-* | head -1
```

Then run the linter from repo root against its `after.json`:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  PROPOSAL_DIR=$(ls -d 2026-* | tail -1) && \
  python3 tools/config-linter/config_linter.py --config "${PROPOSAL_DIR}/after.json"
```

Expected: one of:

- `No issues found.` (exit 0), or
- Structured ERRORS/WARNINGS output (exit 0 if warnings only, exit 1 if errors).

**No import errors or tracebacks.** If you see `ModuleNotFoundError` or similar, the `lib/__init__.py` or copy in Task 2 is wrong.

- [ ] **Step 3: Check exit code is as expected**

Run the previous command again and capture `$?`:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  PROPOSAL_DIR=$(ls -d 2026-* | tail -1) && \
  python3 tools/config-linter/config_linter.py --config "${PROPOSAL_DIR}/after.json"; \
  echo "exit=$?"
```

Expected: `exit=0` (clean or warnings-only) or `exit=1` (real errors). Either is a valid outcome — we're confirming the CLI doesn't crash, not that every existing proposal is clean.

- [ ] **Step 4: Test JSON output format**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && \
  PROPOSAL_DIR=$(ls -d 2026-* | tail -1) && \
  python3 tools/config-linter/config_linter.py --config "${PROPOSAL_DIR}/after.json" --format json | python3 -m json.tool > /dev/null && echo "json valid"
```

Expected: `json valid`. Confirms `--format json` produces parseable JSON.

---

## Task 7: Push branch and open PR

**Files:** none modified.

- [ ] **Step 1: Inspect commit history**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && git log main..HEAD --oneline
```

Expected 4 commits in this order:

1. `feat: copy config linter source from integration-benchmarking`
2. `test: copy config linter test suite`
3. `docs: add config linter rule reference and tool README`
4. `ci: run config linter and tests on PRs`

- [ ] **Step 2: Push the branch**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && git push -u origin feat/config-linter
```

Expected: push succeeds, branch is created on origin.

- [ ] **Step 3: Open a pull request**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && gh pr create \
  --title "Add config linter + CI integration" \
  --body "$(cat <<'EOF'
## Summary
- Copies the config linter (CLI + rules + tests) from `integration-benchmarking` into `tools/config-linter/`.
- Adds the full rule reference at `docs/config_linter.md` and a short tool README.
- Extends `.github/workflows/ci-pr.yml` to run the linter test suite on every PR and lint the changed proposal's `after.json` when a proposal is detected. Errors block merge; warnings are reported but non-blocking.

Governance becomes the canonical home for future linter edits. The copy in `integration-benchmarking` remains as a frozen reference.

## Test plan
- [ ] CI passes on this PR (tests green; lint step skipped because no proposal is modified)
- [ ] Open a follow-up test PR that modifies one `after.json` with a known error (e.g., duplicate `feedId`) and confirm the lint step exits 1 and blocks merge
- [ ] Open a follow-up test PR with a known warning and confirm the lint step reports the warning but still exits 0
EOF
)"
```

Expected: PR URL printed to stdout.

- [ ] **Step 4: Wait for CI and report status**

Run:

```bash
cd /home/mariobern/pyth-lazer-staging-governance && gh pr checks --watch
```

Expected: `Check proposal` passes. The `Lint proposal config` step should show as skipped (not red) because the PR does not modify any `after.json` file. The `Run linter tests` step should be green.

If CI fails on `Run linter tests`, read the logs (`gh run view --log-failed`), fix the root cause, and push a follow-up commit.

---

## Task 8 (optional, separate PR in integration-benchmarking): Add reference note

Skip this task if the user does not want the note added yet. This is a low-priority cleanup in the source repo.

**Files:**

- Modify: `/home/mariobern/integration-benchmarking/config_linter.py:1`
- Modify: `/home/mariobern/integration-benchmarking/lib/config_lint.py:1`
- Modify: `/home/mariobern/integration-benchmarking/CLAUDE.md:104`

- [ ] **Step 1: Create branch in integration-benchmarking**

Run:

```bash
cd /home/mariobern/integration-benchmarking && git checkout -b chore/config-linter-reference-note
```

- [ ] **Step 2: Add reference note to `config_linter.py`**

Insert this block at the very top of `/home/mariobern/integration-benchmarking/config_linter.py`, before the existing docstring (which starts at line 1 with `"""Config linter CLI for after.json validation.`):

```python
# NOTE: Canonical copy lives in pyth-lazer-staging-governance/tools/config-linter/.
# This copy is kept as a frozen reference and will drift. Edit in the governance repo.
```

The file should now start with those two comment lines, a blank line, then the existing `"""Config linter CLI for after.json validation.` docstring.

- [ ] **Step 3: Add the same note to `lib/config_lint.py`**

Insert the same two-line block at the top of `/home/mariobern/integration-benchmarking/lib/config_lint.py`, before the existing docstring (which starts at line 1 with `"""Config linter rules for after.json validation.`).

- [ ] **Step 4: Update `CLAUDE.md` row for `config_linter.py`**

Find the row at line 104 of `/home/mariobern/integration-benchmarking/CLAUDE.md`, which currently reads:

```
| `config_linter.py`              | Lint after.json for config errors (duplicates, publishers, schedules) | `python3 config_linter.py --config after.json`                              | [docs/config_linter.md](docs/config_linter.md)                           |
```

Replace with:

```
| `config_linter.py`              | Lint after.json for config errors (duplicates, publishers, schedules) — **canonical copy in [pyth-lazer-staging-governance](https://github.com/pyth-network/pyth-lazer-staging-governance/tree/main/tools/config-linter)** | `python3 config_linter.py --config after.json`                              | [docs/config_linter.md](docs/config_linter.md)                           |
```

- [ ] **Step 5: Confirm the files still parse**

Run:

```bash
python3 -c "import sys; sys.path.insert(0, '/home/mariobern/integration-benchmarking'); from lib.config_lint import lint_config; print('ok')"
```

Expected: `ok`.

- [ ] **Step 6: Run pre-commit on the modified files**

Run:

```bash
cd /home/mariobern/integration-benchmarking && pre-commit run --files config_linter.py lib/config_lint.py CLAUDE.md
```

Expected: pass (or auto-fix and show the diff). If pre-commit modifies files, re-stage them.

- [ ] **Step 7: Commit and push**

Run:

```bash
cd /home/mariobern/integration-benchmarking && \
  git add config_linter.py lib/config_lint.py CLAUDE.md && \
  git commit -m "docs: mark config_linter as frozen; canonical copy in governance repo" && \
  git push -u origin chore/config-linter-reference-note
```

- [ ] **Step 8: Open PR**

Run:

```bash
cd /home/mariobern/integration-benchmarking && gh pr create \
  --title "Mark config_linter as frozen reference" \
  --body "$(cat <<'EOF'
## Summary
Adds a note to the top of `config_linter.py` and `lib/config_lint.py` and updates the \`CLAUDE.md\` scripts table to indicate that the canonical copy now lives in \`pyth-lazer-staging-governance/tools/config-linter/\`. This copy is kept as a frozen reference and will drift.

## Test plan
- [ ] Existing \`pytest tests/test_config_lint.py tests/test_config_linter_cli.py\` still passes unchanged
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** Every section of the spec (architecture, CI integration, docs, execution order, follow-up) maps to at least one task. The spec's "Risks and verification" section is addressed by Task 6 (local sanity) + Task 7 test plan.
- **Types consistency:** No new code is written. All types/signatures come verbatim from the source repo; no invented references.
- **No placeholders:** Every step contains exact commands, exact file paths, exact expected output, and verbatim file contents (README.md, YAML block, reference-note comment).
- **Known gap to accept:** Task 7 step 4 assumes the PR can be watched; if `gh pr checks --watch` is unavailable, fall back to `gh pr checks` (one-shot). Non-blocking.
