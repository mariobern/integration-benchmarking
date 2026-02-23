# Extend Futures Mappings in generate_ric_mapping.py

## Problem

`test_tickers.txt` contains 19 new futures tickers (16 commodity, 3 equity index) that need RIC mappings. Of these, 5 commodity root symbols (NL, LE, TI, RS, GO) and 3 equity index aliases (US30, US100, US500) are not currently mapped. The equity index futures regex also won't match codes longer than 2 characters.

## New Commodity Futures Mappings

Add to `FUTURES_PYTH_TO_RIC`:

| Pyth Root | RIC Root | Commodity          | Exchange   | Source                       |
| --------- | -------- | ------------------ | ---------- | ---------------------------- |
| NL        | MNI      | Nickel             | LME        | Refinitiv RIC symbology card |
| LE        | MPB      | Lead (Refined)     | LME        | Refinitiv RIC symbology card |
| TI        | MSN      | Tin                | LME        | Refinitiv RIC symbology card |
| RS        | SB       | Raw Sugar No. 11   | ICE US     | SIRCA listing                |
| GO        | LGO      | Low Sulphur Gasoil | ICE Europe | ICE on Reuters docs          |

Examples: `Commodities.NLH6/USD` -> `MNIH26`, `Commodities.RSK6/USD` -> `SBK26`

## New Equity Index Futures Mappings

Add to `INDEX_FUTURES_PYTH_TO_RIC`:

| Pyth Root | RIC Root | Index             | Notes                                         |
| --------- | -------- | ----------------- | --------------------------------------------- |
| US500     | ES       | S&P 500 E-mini    | Alias for EM (same pyth_mappings description) |
| US100     | NQ       | Nasdaq 100 E-mini | Alias for NM                                  |
| US30      | YM       | Dow Jones E-mini  | Alias for DM                                  |

FCD (Financial CDX) skipped -- no standard Datascope RIC found.

## Regex Fix

Current `_INDEX_FUTURES_PATTERN`:

```
^Equity\.US\.([A-Z]{2})([FGHJKMNQUVXZ])(\d)/USD$
```

Change to:

```
^Equity\.US\.([A-Z][A-Z0-9]*)([FGHJKMNQUVXZ])(\d)/USD$
```

Allows codes like US30, US100, US500 (contain digits, >2 chars). False positives are harmless since unrecognized codes won't be in the dictionary.

## Coverage Analysis

After these changes, all 14 commodity roots and all 8 equity index roots in lazer_symbols.json will have deterministic RIC mappings (100% coverage).

`commodities_futures.txt` lists 25 additional commodities (RBOB, Heating Oil, Wheat, Soybeans, Cattle, Cocoa, Coffee, Cotton, etc.) not yet in lazer_symbols.json. These are deferred because:

- Pyth root codes are unpredictable (e.g., CC=Copper in Pyth but Cocoa in standard futures)
- Naming conflicts exist (LE=Lead in Pyth vs Live Cattle in standard futures)
- Some Datascope RICs in the file differ from actual Datascope usage (ZW vs W, ZS vs S)

When new commodities are added to lazer_symbols.json, their Pyth root will be known and the mapping can be added at that time.

## Scope

- 3 changes in `generate_ric_mapping.py`: dictionary entries + regex
- Test additions in `tests/test_generate_ric_mapping.py`
- No changes to other scripts
