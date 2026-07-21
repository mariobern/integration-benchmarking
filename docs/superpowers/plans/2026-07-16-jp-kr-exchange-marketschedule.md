# JP/KR Exchange ID + MarketSchedule Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assign `exchangeId: 29` to all active `Equity.JP.*` feeds and `exchangeId: 24` to all active `Equity.KR.*` feeds in `lazer_kr_jp.json`, removing their per-session `marketSchedule` strings so they inherit the exchange's calendar instead.

**Architecture:** Two independent CLI invocations of the existing `tools/edit-config/edit_config.py --add-exchange-id` operation (one per market), each reviewed as a dry-run before `--apply`. A third, read-only verification task confirms the JP/KR result and confirms HK/CN were correctly left untouched. There is no new code — this plan operates an existing tool against a local config file.

**Tech Stack:** Python 3.12 via the repo's `venv` (`source venv/bin/activate` — the system `python3` is 3.9 and cannot even import `edit_config.py`, which uses `int | None` syntax requiring 3.10+). Existing tools: `tools/edit-config/edit_config.py`, `tools/config-linter/config_linter.py`.

## Global Constraints

- Target file: `lazer_kr_jp.json` (repo root). This file is gitignored (`lazer*.json` in `.gitignore`) and not tracked in git history — there is no git commit step for the JSON changes themselves; `edit_config.py`'s own `.bak` backup is the safety net.
- Spec: `docs/superpowers/specs/2026-07-16-jp-kr-exchange-marketschedule-design.md`.
- Only `Equity.JP.*` and `Equity.KR.*` feeds change. `Equity.HK.*` (exchange 21) is already fully done and must NOT change. `Equity.CN.*` (exchange 22) was explicitly excluded by the user and must NOT change.
- INACTIVE feeds are skipped automatically by `edit_config.py` (1 JP, 2 KR) — do not use `--set-state` to work around this; it's out of scope.
- Every command below must be run with the venv activated: `source venv/bin/activate` first, from the repo root.

---

### Task 1: Apply exchangeId 29 to Equity.JP.\* feeds

**Files:**

- Modify (via tool, not by hand): `lazer_kr_jp.json`

**Interfaces:**

- Consumes: `tools/edit-config/edit_config.py`'s existing `--add-exchange-id` op (no code changes).
- Produces: `lazer_kr_jp.json` with all 235 active `Equity.JP.*` feeds carrying `exchangeId: 29` and no `marketSchedule` string in any session. Task 3 depends on this being applied before it runs its verification.

- [ ] **Step 1: Run the dry-run and confirm the plan summary**

```bash
source venv/bin/activate
python3 tools/edit-config/edit_config.py --config lazer_kr_jp.json \
    --add-exchange-id 29 --symbol-pattern "Equity.JP.*" --dry-run
```

Expected (tail of output — the full diff lists 470 individual field changes, one `exchangeId` + one `marketSchedule` removal per active feed):

```
Plan:
  [1] AddExchangeId → 236 feed(s) matched

Validation: PASS (0 errors, 0 warnings)
...
Summary: 470 changes, 0 errors, 0 warnings. Skipped 1 INACTIVE feed(s) (reactivate via --set-state to edit).
[DRY RUN] No changes written. Re-run with --apply to write.
```

If the numbers differ from `236 feed(s) matched`, `470 changes`, `0 errors, 0 warnings`, or `Skipped 1 INACTIVE feed(s)`, STOP and investigate before proceeding — the config has changed since this plan was written.

- [ ] **Step 2: Apply the change**

```bash
python3 tools/edit-config/edit_config.py --config lazer_kr_jp.json \
    --add-exchange-id 29 --symbol-pattern "Equity.JP.*" --apply
```

Expected (tail of output):

```
Backup written: lazer_kr_jp.json.bak
Wrote 470 changes to lazer_kr_jp.json.
```

- [ ] **Step 3: Spot-check the result**

```bash
python3 -c "
import json
d = json.load(open('lazer_kr_jp.json'))
feeds = d['feeds']
fs = [f for f in feeds if str(f.get('symbol','')).startswith('Equity.JP.')]
active = [f for f in fs if f.get('state') != 'INACTIVE']
inactive = [f for f in fs if f.get('state') == 'INACTIVE']
correct = [f for f in active if f.get('exchangeId') == 29
           and not any('marketSchedule' in s for s in f.get('marketSchedules', []))]
print(f'total={len(fs)} active={len(active)} inactive={len(inactive)} correct={len(correct)}')
still_scheduled = [f['symbol'] for f in inactive if any('marketSchedule' in s for s in f.get('marketSchedules', []))]
print('inactive feeds still carrying marketSchedule (expected all 1):', len(still_scheduled))
"
```

Expected:

```
total=236 active=235 inactive=1 correct=235
inactive feeds still carrying marketSchedule (expected all 1): 1
```

- [ ] **Step 4: No commit** — `lazer_kr_jp.json` is gitignored. Do not `git add` it. Move directly to Task 2.

---

### Task 2: Apply exchangeId 24 to Equity.KR.\* feeds

**Files:**

- Modify (via tool, not by hand): `lazer_kr_jp.json`

**Interfaces:**

- Consumes: same `--add-exchange-id` op as Task 1, run against Task 1's output (`lazer_kr_jp.json` already has JP changes applied).
- Produces: `lazer_kr_jp.json` with all 105 active `Equity.KR.*` feeds carrying `exchangeId: 24` and no `marketSchedule` string in any session (2 of these already had `exchangeId: 24` before this plan started, so they show as no-ops in the diff). Task 3 depends on this being applied.

- [ ] **Step 1: Run the dry-run and confirm the plan summary**

```bash
python3 tools/edit-config/edit_config.py --config lazer_kr_jp.json \
    --add-exchange-id 24 --symbol-pattern "Equity.KR.*" --dry-run
```

Expected (tail of output — 206 changes because 2 of the 105 active feeds already have `exchangeId: 24` and no `marketSchedule`, so they contribute zero changes):

```
Plan:
  [1] AddExchangeId → 107 feed(s) matched

Validation: PASS (0 errors, 0 warnings)
...
Summary: 206 changes, 0 errors, 0 warnings. Skipped 2 INACTIVE feed(s) (reactivate via --set-state to edit).
[DRY RUN] No changes written. Re-run with --apply to write.
```

If the numbers differ from `107 feed(s) matched`, `206 changes`, `0 errors, 0 warnings`, or `Skipped 2 INACTIVE feed(s)`, STOP and investigate before proceeding.

- [ ] **Step 2: Apply the change**

```bash
python3 tools/edit-config/edit_config.py --config lazer_kr_jp.json \
    --add-exchange-id 24 --symbol-pattern "Equity.KR.*" --apply
```

Expected (tail of output):

```
Backup written: lazer_kr_jp.json.bak
Wrote 206 changes to lazer_kr_jp.json.
```

Note: this overwrites the `.bak` file Task 1 created, with a snapshot taken _after_ Task 1's changes. That's fine — `.bak` is a single-step undo, not a full history.

- [ ] **Step 3: Spot-check the result**

```bash
python3 -c "
import json
d = json.load(open('lazer_kr_jp.json'))
feeds = d['feeds']
fs = [f for f in feeds if str(f.get('symbol','')).startswith('Equity.KR.')]
active = [f for f in fs if f.get('state') != 'INACTIVE']
inactive = [f for f in fs if f.get('state') == 'INACTIVE']
correct = [f for f in active if f.get('exchangeId') == 24
           and not any('marketSchedule' in s for s in f.get('marketSchedules', []))]
print(f'total={len(fs)} active={len(active)} inactive={len(inactive)} correct={len(correct)}')
"
```

Expected:

```
total=107 active=105 inactive=2 correct=105
```

- [ ] **Step 4: No commit** — same as Task 1, `lazer_kr_jp.json` is gitignored.

---

### Task 3: Verify JP/KR result and confirm HK/CN untouched

**Files:**

- Read-only: `lazer_kr_jp.json`

**Interfaces:**

- Consumes: `lazer_kr_jp.json` as left by Task 1 and Task 2.
- Produces: pass/fail confirmation for the plan's Definition of Done. No file changes.

- [ ] **Step 1: Full spot-check across all four markets**

```bash
python3 -c "
import json
d = json.load(open('lazer_kr_jp.json'))
feeds = d['feeds']
def check(prefix, exchange_id):
    fs = [f for f in feeds if str(f.get('symbol','')).startswith(prefix)]
    active = [f for f in fs if f.get('state') != 'INACTIVE']
    inactive = [f for f in fs if f.get('state') == 'INACTIVE']
    correct = [f for f in active if f.get('exchangeId') == exchange_id
               and not any('marketSchedule' in s for s in f.get('marketSchedules', []))]
    print(f'{prefix}: total={len(fs)} active={len(active)} inactive={len(inactive)} correct={len(correct)}')
check('Equity.JP.', 29)
check('Equity.KR.', 24)
check('Equity.HK.', 21)
check('Equity.CN.', 22)
"
```

Expected — JP and KR are now fully corrected; HK and CN are unchanged from before this plan started (HK: 100/100 active already correct, unchanged; CN: 13/15 active correct, unchanged — the 2 CN ETFs are still deliberately left alone):

```
Equity.JP.: total=236 active=235 inactive=1 correct=235
Equity.KR.: total=107 active=105 inactive=2 correct=105
Equity.HK.: total=105 active=100 inactive=5 correct=100
Equity.CN.: total=15 active=15 correct=13
```

If HK's `correct` count changed from `100`, or CN's `correct` count changed from `13`, STOP — that means Task 1 or Task 2's `--symbol-pattern` accidentally matched feeds outside their intended market, and the change needs to be investigated before going further.

- [ ] **Step 2: Run the config linter and compare JP/KR/HK line counts against the pre-change baseline**

The linter's overall error/warning totals are dominated by thousands of pre-existing, unrelated issues (`CLAUDE.md` notes the linter still assumes the old feed-level-publisher config format, which this config doesn't use — so most of its output isn't meaningful here). Don't compare the grand total; compare only the lines mentioning our target feeds, which the baseline run below showed are driven entirely by publisher-list issues, not `exchangeId`/`marketSchedule` — so their count should be identical before and after this plan.

```bash
python3 tools/config-linter/config_linter.py --config lazer_kr_jp.json > /tmp/lint_after.txt 2>&1
grep -c "Equity\.JP\." /tmp/lint_after.txt
grep -c "Equity\.KR\." /tmp/lint_after.txt
grep -c "Equity\.HK\." /tmp/lint_after.txt
grep "W011.*Equity\.\(JP\|KR\)\." /tmp/lint_after.txt
```

Expected: the three counts are exactly `468`, `207`, and `200` (the same as the pre-change baseline captured when this plan was written), and the `W011` grep (which flags a feed that has an `exchangeId` but still carries an inline `marketSchedule` — i.e. exactly the bug this plan must avoid) returns **no lines**.

If any of the three counts differ from `468` / `207` / `200`, or the `W011` grep returns any line, STOP — either an unrelated pre-existing issue was fixed/introduced as a side effect, or a feed was left in the broken half-migrated state (`exchangeId` set but `marketSchedule` not stripped, or vice versa).

- [ ] **Step 3: Update the spec's Definition of Done**

Open `docs/superpowers/specs/2026-07-16-jp-kr-exchange-marketschedule-design.md` and check off all four boxes under "Definition of done" (all should now be true per Steps 1–2 above).

- [ ] **Step 4: Commit the spec update**

```bash
git add docs/superpowers/specs/2026-07-16-jp-kr-exchange-marketschedule-design.md
git commit -m "docs: mark JP/KR exchangeId spec definition-of-done complete"
```
