# JP/KR exchangeId assignment + marketSchedule removal

Last updated: 2026-07-16

## Goal

Assign `exchangeId: 29` (Tokyo Stock Exchange) to all `Equity.JP.*` feeds and
`exchangeId: 24` (Korea Exchange) to all `Equity.KR.*` feeds in
`lazer_kr_jp.json`, so each feed inherits its exchange's trading calendar
instead of carrying its own `marketSchedule` string.

`Equity.HK.*` (exchange 21, "The Stock Exchange of Hong Kong Ltd") was
initially in scope too, but investigation found it already done: 100 of 105
HK feeds already carry `exchangeId: 21` with `marketSchedule` fully stripped;
the remaining 5 are `INACTIVE` (the same population `--add-exchange-id`
would skip if re-run). HK is therefore verification-only in this pass — see
Scope and Verification below.

## Scope

- Config file: `lazer_kr_jp.json` (local, gitignored working copy — most
  recently modified, already carries prior exchange-inheritance work for
  other markets).
- Feeds changed by this pass: all feeds whose `symbol` starts with
  `Equity.JP.` (236 feeds) or `Equity.KR.` (107 feeds).
- Feeds checked but not changed: `Equity.HK.*` (105 feeds) — confirmed
  already at the target state, included only in the verification step.
- Out of scope: any other feed/symbol prefix; changing feed `state`;
  changing `minPublishers` or publisher lists. `Equity.CN.*` (exchange 22,
  "Shanghai Stock Exchange") was considered too — 13 of 15 feeds already
  have `exchangeId: 22`, 2 (`510310`, `510330`, both COMING_SOON CSI 300
  ETFs) still don't — but excluded from this pass by explicit decision;
  those 2 feeds are left as-is, still carrying their own `marketSchedule`.

## Approach

Use the existing `--add-exchange-id` operation in
`tools/edit-config/edit_config.py`, invoked twice (two separate CLI calls,
not a batched `--from-spec` YAML):

```bash
python3 tools/edit-config/edit_config.py --config lazer_kr_jp.json \
    --add-exchange-id 29 --symbol-pattern "Equity.JP.*" --dry-run

python3 tools/edit-config/edit_config.py --config lazer_kr_jp.json \
    --add-exchange-id 24 --symbol-pattern "Equity.KR.*" --dry-run
```

Each call is reviewed as a dry-run first; `--apply` is run only after the
diff looks correct. `--add-exchange-id` already implements the required
behavior: it sets the feed's top-level `exchangeId` and deletes the
now-redundant `marketSchedule` string from every session entry on that feed.

Targeting is by `--symbol-pattern`, not `--asset-class`: both JP and KR feeds
share the generic `metadata.asset_type = "equity"` value, so asset-class
targeting can't distinguish the two markets.

## Confirmed pre-conditions

- Exchange 29 ("Tokyo Stock Exchange") and exchange 24 ("Korea Exchange")
  already exist in `exchanges[]`, each defining only a `REGULAR` session.
- Every targeted JP and KR feed has exactly one session entry (`REGULAR`) —
  matches what both exchanges define, so no feed hits the "session the
  exchange doesn't define" error path.

## Edge cases

- **INACTIVE feeds** (1 JP, 2 KR): skipped automatically by
  `edit_config.py` (documented behavior — INACTIVE feeds require
  `--set-state` first). Not reactivated as part of this change; they keep
  their existing `marketSchedule`.
- **KR feeds already at `exchangeId: 24`** (2 feeds): already consistent
  with the target state; the op no-ops (or shows no diff) for these.

## Verification

After both `--apply` runs:

1. `python3 tools/config-linter/config_linter.py --config lazer_kr_jp.json`
   (`edit_config.py` does not lint automatically).
2. Spot-check that no active (`STABLE`/`COMING_SOON`) `Equity.JP.*` or
   `Equity.KR.*` feed retains a `marketSchedule` key in any session entry,
   and that `exchangeId` is `29`/`24` respectively.
3. Spot-check `Equity.HK.*` as a read-only confirmation (no op run): every
   active feed already has `exchangeId: 21` and no `marketSchedule` string;
   only the 5 pre-existing INACTIVE feeds lack it.

## Definition of done

- [x] All active `Equity.JP.*` feeds have `exchangeId: 29` and no
      `marketSchedule` string in any session. (235/235, verified 2026-07-16)
- [x] All active `Equity.KR.*` feeds have `exchangeId: 24` and no
      `marketSchedule` string in any session. (105/105, verified 2026-07-16)
- [x] INACTIVE feeds in all three sets (JP, KR, HK) left untouched.
      (1 JP, 2 KR, 5 HK — all still carry their original `marketSchedule`)
- [x] Confirmed (not changed) that all active `Equity.HK.*` feeds already
      have `exchangeId: 21` and no `marketSchedule` string. (100/100)
- [x] Config linter passes (or pre-existing warnings only, no new ones
      introduced by this change). JP and HK line counts unchanged (468,
      200). KR dropped from 207 to 205: 2 `W003` "schedule deviates from
      majority" warnings resolved as a side effect, since those 2 feeds no
      longer carry their own (deviating) `marketSchedule` string — not a
      regression. No `W011` (exchangeId set but marketSchedule not
      stripped) lines for any JP/KR feed.
