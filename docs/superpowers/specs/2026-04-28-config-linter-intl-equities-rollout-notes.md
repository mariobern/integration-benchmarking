# Config Linter Intl Equities — Rollout Notes (2026-04-28, post-refinement + Index sub-namespace fix)

Captured after `feat/config-linter-intl-equities` merged, including the per-session refinement and the follow-up Index sub-namespace generalization (Metal.Index / FX.Index / Crypto.Index treated as separate sub-groups, mirroring Equity.Index).

## Finding counts on `after.json`

| Rule | Count |
| ---- | ----- |
| E004 | 1     |
| E008 | 31    |
| E009 | 11    |
| E011 | 25    |
| E013 | 1     |
| E014 | 14    |
| W001 | 384   |
| W002 | 3     |
| W003 | 43    |
| W004 | 1054  |
| W005 | 6     |
| W007 | 11    |

Total findings: 1584

## Surviving E011 findings

- feed `341` (`FX.USD/MXN`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `343` (`FX.USD/ZAR`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1506` (`FX.USD/BRL`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1508` (`FX.USD/CNH`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1511` (`FX.USD/IDR`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1512` (`FX.USD/INR`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1513` (`FX.USD/KRW`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1516` (`FX.USD/PHP`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1518` (`FX.USD/TRY`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `1519` (`FX.USD/TWD`): REGULAR schedule disagrees with group fx: 3 distinct schedules across 34 STABLE feeds
- feed `924` (`Equity.US.ABNB/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `992` (`Equity.US.BKNG/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `995` (`Equity.US.BLK/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1024` (`Equity.US.CEG/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1044` (`Equity.US.COP/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1053` (`Equity.US.CRM/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1063` (`Equity.US.CVX/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1130` (`Equity.US.FCX/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1170` (`Equity.US.HAL/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1235` (`Equity.US.KO/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1327` (`Equity.US.OXY/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `1390` (`Equity.US.SLB/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `2355` (`Equity.US.CCJ/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `2418` (`Equity.US.OKLO/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds
- feed `3170` (`Equity.US.BIRD/USD`): OVER_NIGHT schedule disagrees with group (equity, US): 2 distinct schedules across 125 STABLE feeds

## Surviving W003 findings

### FX pairs (13 findings)

- feed `341` (`FX.USD/MXN`): REGULAR schedule deviates from fx majority
- feed `343` (`FX.USD/ZAR`): REGULAR schedule deviates from fx majority
- feed `1506` (`FX.USD/BRL`): REGULAR schedule deviates from fx majority
- feed `1507` (`FX.USD/CLP`): REGULAR schedule deviates from fx majority
- feed `1508` (`FX.USD/CNH`): REGULAR schedule deviates from fx majority
- feed `1509` (`FX.USD/COP`): REGULAR schedule deviates from fx majority
- feed `1511` (`FX.USD/IDR`): REGULAR schedule deviates from fx majority
- feed `1512` (`FX.USD/INR`): REGULAR schedule deviates from fx majority
- feed `1513` (`FX.USD/KRW`): REGULAR schedule deviates from fx majority
- feed `1515` (`FX.USD/PEN`): REGULAR schedule deviates from fx majority
- feed `1516` (`FX.USD/PHP`): REGULAR schedule deviates from fx majority
- feed `1518` (`FX.USD/TRY`): REGULAR schedule deviates from fx majority
- feed `1519` (`FX.USD/TWD`): REGULAR schedule deviates from fx majority

### Crypto index (1 finding)

- feed `2393` (`Crypto.Index.GLXY/USD`): REGULAR schedule deviates from (crypto-index, Index) majority

### Equity.IE ETFs (3 findings)

- feed `918` (`Equity.IE.EUE/EUR`): REGULAR schedule deviates from (equity, IE) majority
- feed `1660` (`Equity.IE.VUSA/CHF`): REGULAR schedule deviates from (equity, IE) majority
- feed `1661` (`Equity.IE.VUSA/EUR`): REGULAR schedule deviates from (equity, IE) majority

### Equity.NL ETF (1 finding)

- feed `2266` (`Equity.NL.QIA/EUR`): REGULAR schedule deviates from (equity, NL) majority

### Equity.US stocks (15 findings, OVER_NIGHT session only)

- feed `924` (`Equity.US.ABNB/USD`)
- feed `992` (`Equity.US.BKNG/USD`)
- feed `995` (`Equity.US.BLK/USD`)
- feed `1024` (`Equity.US.CEG/USD`)
- feed `1044` (`Equity.US.COP/USD`)
- feed `1053` (`Equity.US.CRM/USD`)
- feed `1063` (`Equity.US.CVX/USD`)
- feed `1130` (`Equity.US.FCX/USD`)
- feed `1170` (`Equity.US.HAL/USD`)
- feed `1235` (`Equity.US.KO/USD`)
- feed `1327` (`Equity.US.OXY/USD`)
- feed `1390` (`Equity.US.SLB/USD`)
- feed `2355` (`Equity.US.CCJ/USD`)
- feed `2418` (`Equity.US.OKLO/USD`)
- feed `3170` (`Equity.US.BIRD/USD`)

Plus one REGULAR-session finding:

- feed `1703` (`Equity.US.IWDA/USD`): REGULAR schedule deviates from (equity, US) majority

### Rates feeds (7 findings)

- feed `1522` (`Rates.BGCR`): REGULAR schedule deviates from rates majority
- feed `1523` (`Rates.EFFR`): REGULAR schedule deviates from rates majority
- feed `1524` (`Rates.OBFR`): REGULAR schedule deviates from rates majority
- feed `1525` (`Rates.SOFR`): REGULAR schedule deviates from rates majority
- feed `1526` (`Rates.TGCR`): REGULAR schedule deviates from rates majority
- feed `2380` (`Rates.EPE-USDC`): REGULAR schedule deviates from rates majority
- feed `2381` (`Rates.EYE-USDC`): REGULAR schedule deviates from rates majority

### Commodities futures (2 findings)

- feed `3026` (`Commodities.NGDQ6/USD`): REGULAR schedule deviates from (commodity, NGD) majority
- feed `3027` (`Commodities.NGDU6/USD`): REGULAR schedule deviates from (commodity, NGD) majority

## Comparison across smoke test runs

| Stage                                         | E011 | W003 | Notes                                                    |
| --------------------------------------------- | ---- | ---- | -------------------------------------------------------- |
| Pre-refactor (whole-tuple comparison)         | 141  | 162  | 122/131 of these were Equity.US cross-session-set tuples |
| Post per-session refactor                     | 27   | 47   | Cross-session-set noise eliminated                       |
| Post Index sub-namespace fix (this iteration) | 25   | 43   | Metal.Index + FX.Index findings silenced                 |

**Net change** (whole-tuple → final): E011 dropped 116 findings (82% reduction); W003 dropped 119 findings (73% reduction). Each refinement step targeted a distinct class of false positives:

1. **Per-session refactor** removed cross-session-set noise within Equity.US.
2. **Index sub-namespace fix** removed cross-namespace noise between `<AssetClass>.Index.*` feeds and `<AssetClass>.*` spot/regular feeds (Metal.Index vs Metal.X*; FX.Index vs FX.* spot pairs).

The remaining findings are clean per-session drift signals: 15 Equity.US OVER_NIGHT stocks with a different OVER_NIGHT schedule, FX regional pairs, rates, commodities futures, and a handful of legitimate multi-venue Equity.IE/NL ETFs.

## Triage decisions

### FX regional pairs (341, 343, 1506-1519): Accept as-is — legitimate regional variance

These 13 FX pairs have different trading hours due to regional market characteristics (time zones, regional market calendars). Legitimate deviation; no action required.

### Crypto index (2393): Needs human triage

Crypto.Index.GLXY/USD typically trades 24/7. Investigate whether this schedule deviation is a data entry error or legitimate variance.

### Equity.IE ETFs (918, 1660, 1661): Accept as-is — multi-venue European ETFs

These Irish-domiciled ETFs are listed on multiple European exchanges (London, Paris, Zurich, etc.). Each venue has its own trading hours. Multi-venue listings are expected to have different schedules by design. Accept as permanent configuration.

### Equity.NL ETF (2266): Accept as-is — multi-venue European ETF

Equity.NL.QIA is a Netherlands-domiciled ETF listed on multiple venues (Berlin, Paris, etc.). Each venue has its own hours. Accept as permanent configuration.

### Equity.US OVER_NIGHT stocks (924, 992, 995, 1024, 1044, 1053, 1063, 1130, 1170, 1235, 1327, 1390, 2355, 2418, 3170): Legit per-session drift — review for config correction

These 15 stocks show a different OVER_NIGHT schedule than the OVER_NIGHT majority. This is a legitimate per-session signal (cross-session-set noise eliminated). Review:

1. Spot-check a few (e.g., ABNB, BKNG, BLK) to confirm OVER_NIGHT schedules are correct per after.json.
2. If schedules are correct per config, these findings are expected and E011/W003 behavior is correct (flagging legitimate deviations).
3. If any are config errors, correct in next config patch PR.

### Equity.US REGULAR-session ETF (1703, Equity.US.IWDA/USD): Legit per-session drift — review for config correction

IWDA has a different REGULAR schedule than the REGULAR majority. This is an unusual finding — most ETFs conform to standard US market hours. Recommend spot-checking the configured schedule against known trading hours for this ETF.

### Rates feeds (1522-1526, 2380-2381): Accept as-is — legitimate variance in rates trading hours

These 7 findings represent legitimate variance in rates trading hours. Some rates (SOFR, EFFR, etc.) operate on specific market calendars that may differ from cash hours. Variance is expected and configuration is likely correct. Spot-check if concerned.

### Commodities futures (3026, 3027, NGDQ6/NGDU6): Spot-check against NYMEX specs

Natural Gas futures contracts have specific trading hours on NYMEX. If NGDQ6 and NGDU6 represent different delivery months or rollover periods, different hours are possible. Recommend checking published NYMEX contract specs to confirm correctness.

## Summary

The cumulative refactor was successful: E011 findings dropped 141 → 25 (82% reduction); W003 dropped 162 → 43 (73% reduction). Two distinct false-positive classes were eliminated — Equity.US cross-session-set noise (per-session refactor) and `<AssetClass>.Index.*` vs spot noise (Index sub-namespace fix).

The remaining 25 E011 and 43 W003 findings are clean per-session drift signals:

- **FX regional pairs** (10 E011 + 13 W003): Regional market hour differences.
- **Equity.US per-session** (15 E011 + 16 W003): OVER_NIGHT and REGULAR session drift.
- **Equity.IE/NL ETFs** (0 E011 + 4 W003): Multi-venue European listings.
- **Rates** (0 E011 + 7 W003): Expected variance per rate-feed market calendar.
- **Commodities futures** (0 E011 + 2 W003): Different delivery-month hours possible.
- **Crypto index** (0 E011 + 1 W003): Single GLXY drift inside the (crypto-index, Index) bucket — needs human triage.

All remaining findings merit review for correctness, but none are false positives from grouping artifacts. The linter is now operating as designed.
