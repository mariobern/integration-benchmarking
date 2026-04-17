# Config Linter Transport to pyth-lazer-staging-governance

**Date:** 2026-04-17
**Status:** Approved for implementation planning
**Source repo:** `integration-benchmarking`
**Target repo:** `pyth-lazer-staging-governance`

## Problem

The config linter (`config_linter.py` + `lib/config_lint.py`, rules E001–E016 and W001–W009) lives in `integration-benchmarking`, but the `after.json` files it lints live in `pyth-lazer-staging-governance`. Today the linter is run manually against proposal PRs; there is no automated check. We want the linter running on every governance PR, blocking on errors and reporting warnings non-blockingly.

## Goals

1. Make the config linter available in the governance repo so it can run in CI.
2. Wire it into the existing `.github/workflows/ci-pr.yml` so errors block PR merges.
3. Bring the test suite so rule edits are caught by CI.
4. Establish governance as the canonical home for future linter edits.

## Non-goals

- Rewriting any rule logic. Files are copied as-is.
- Backfill-linting the 40+ existing proposals.
- Adding pre-commit hooks in governance.
- Automating cross-repo sync.
- Deleting the copy in integration-benchmarking (kept as a frozen reference).

## Decisions (from brainstorming)

| Question | Decision |
| --- | --- |
| Scope | Copy files **and** add CI integration. |
| Warnings policy | Errors block, warnings reported but non-blocking. `--warnings-as-errors` not used. |
| File layout in governance | Contained under `tools/config-linter/`. |
| Workflow choice | Extend existing `ci-pr.yml`; no new workflow. |
| Tests | Copy and run in CI on every PR. |
| Ownership model | Governance is canonical for future edits (1b). The integration-benchmarking copy is kept as a frozen reference — it will drift, and that is acceptable. |
| Docs | Short `README.md` in `tools/config-linter/`; full rule reference at `docs/config_linter.md` in governance. |

## Architecture

### Files in governance after transport

```
tools/config-linter/
├── config_linter.py              (copied from source, unchanged)
├── README.md                     (new; short; links to docs/config_linter.md)
├── lib/
│   ├── __init__.py               (new; empty)
│   ├── config_lint.py            (copied from source, unchanged)
│   └── symbol_utils.py           (copied from source, unchanged)
└── tests/
    ├── __init__.py               (new; empty)
    ├── test_config_lint.py       (copied from source, unchanged)
    └── test_config_linter_cli.py (copied from source, unchanged)

docs/
└── config_linter.md              (copied from source; full rule reference)
```

### Why no code changes are needed

- `config_linter.py` → `from lib.config_lint import ...`: resolves because `sys.path[0]` is the script's directory (`tools/config-linter/`) when invoked as `python3 tools/config-linter/config_linter.py ...`.
- `lib/config_lint.py` → `from lib.symbol_utils import ...`: same `sys.path[0]` applies.
- `tests/test_config_lint.py` → `from lib.config_lint import ...`: pytest rootdir lands on `tools/config-linter/` (given `__init__.py` files), so `lib.*` resolves.
- `tests/test_config_linter_cli.py` spawns `subprocess.run([sys.executable, "config_linter.py", ...], cwd=PROJECT_DIR)` where `PROJECT_DIR = Path(__file__).resolve().parent.parent` — resolves to `tools/config-linter/`, which contains `config_linter.py`.

The empty `__init__.py` files are added as a safety belt for pytest discovery; strictly optional under implicit namespace packages, but cheap insurance.

### Dependencies

- Runtime: Python 3.12, standard library only. No `pip install` required for the linter itself.
- Test: `pytest`. Installed in CI only.

## CI integration

**File touched:** `.github/workflows/ci-pr.yml`.

### New steps (appended after the existing "Push changes" step)

```yaml
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install linter dependencies
        run: pip install pytest

      - name: Run linter tests
        working-directory: tools/config-linter
        run: pytest tests/ -v

      - name: Lint proposal config
        if: env.PROPOSAL_DIR != ''
        run: python3 tools/config-linter/config_linter.py --config "${PROPOSAL_DIR}/after.json"
```

### Behavior

| PR scenario | `run linter tests` | `lint proposal config` | PR status |
| --- | --- | --- | --- |
| Proposal with clean `after.json` | green | green (no issues) | pass |
| Proposal with warnings only | green | green (prints warnings, exits 0) | pass |
| Proposal with errors | green | red (exit 1) | **blocked** |
| PR that edits only `tools/config-linter/` | green | skipped (`if: env.PROPOSAL_DIR != ''`) | pass |
| PR that breaks a lint rule's tests | **red** | n/a | **blocked** |

### Ordering rationale

1. Checkout, Docker login / pull (existing).
2. Detect proposal dir, diff jsons, push changes (existing — governance-tool invariants: schema, signing).
3. Set up Python, install pytest (new).
4. **Run linter tests** before lint step: if rule edits broke tests, we want that surfaced as the test failure rather than a downstream lint false positive.
5. **Lint proposal config** last, conditional on a proposal being present.

### Invocation detail

Lint step runs from repo root (no `working-directory`), using `python3 tools/config-linter/config_linter.py ...`. This keeps `$PROPOSAL_DIR` (which is already relative to repo root) usable directly without `../../` prefixes. Python sets `sys.path[0]` to the script's directory, so `from lib.config_lint import ...` resolves inside `tools/config-linter/`.

Test step uses `working-directory: tools/config-linter` because `test_config_linter_cli.py` invokes the CLI as `"config_linter.py"` (not a path), expecting cwd to be the tool directory.

## Docs

- `tools/config-linter/README.md` — one paragraph of purpose; `python3 config_linter.py --config <proposal>/after.json` usage example; link to `../../docs/config_linter.md`.
- `docs/config_linter.md` — full rule reference, copied verbatim from source.

## Integration-benchmarking follow-up (optional, same day or deferred)

Add a note at the top of `config_linter.py` and `lib/config_lint.py` in integration-benchmarking:

```python
# NOTE: Canonical copy lives in pyth-lazer-staging-governance/tools/config-linter/.
# This copy is kept as a frozen reference and will drift. Edit in the governance repo.
```

Optionally update the `config_linter.py` row in `CLAUDE.md` to point at the governance repo. Nothing in integration-benchmarking is deleted: `lib/symbol_utils.py` is still used by `lib/sql_filters.py` and `tests/test_symbol_utils.py`, and the linter copy stays as a reference.

## Risks and verification

- **First real proposal PR after merge**: confirm the lint step runs and `${PROPOSAL_DIR}` substitution works. Use a proposal with a known warning (e.g., a deprecated `kind`) to confirm warnings surface but do not block.
- **Rule false positives on real data**: if a rule fires on a valid proposal, fix or downgrade the rule in a follow-up PR. Transport does not need to be rolled back.
- **Python version drift**: pinned to 3.12 to match what source tests were run against. When bumping Python, re-run tests locally first.

## Out of scope

- No changes to `ci-main.yml` or `ci-create-proposal.yml`.
- No pre-commit hook in governance.
- No backfill-lint of existing 40+ proposals.
- No `--warnings-as-errors` mode (easy to flip later).
- No automated sync between the two repo copies of the linter.

## Execution order

PR in `pyth-lazer-staging-governance` on branch `feat/config-linter`:

1. Create `tools/config-linter/` directory tree; copy the 5 Python files unchanged.
2. Add empty `tools/config-linter/lib/__init__.py` and `tools/config-linter/tests/__init__.py`.
3. Copy `docs/config_linter.md` into `pyth-lazer-staging-governance/docs/config_linter.md` (creating the `docs/` dir).
4. Write `tools/config-linter/README.md`.
5. Edit `.github/workflows/ci-pr.yml` with the four new steps above.
6. Local sanity check:
   - `cd tools/config-linter && pytest tests/ -v` → all green.
   - From repo root: `python3 tools/config-linter/config_linter.py --config <existing-proposal>/after.json` → exits 0 or reports real findings; no import errors.
7. Open PR. CI runs tests (green) and skips lint step (no proposal in the PR). Review + merge.

Follow-up in `integration-benchmarking` (separate PR, optional):

8. Add the reference-copy note to `config_linter.py` and `lib/config_lint.py`.
