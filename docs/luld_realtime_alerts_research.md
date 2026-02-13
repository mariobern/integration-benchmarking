# Real-Time LULD Alert Sources for US Equities

Research date: February 2026

## Background

Limit Up/Limit Down (LULD) is an SEC-mandated market safeguard (approved permanently April 2019) designed to curb excess volatility in individual stocks and ETFs. It uses dynamic price bands that trigger limit states, halts, and auctions. If a security's price doesn't revert within 15 seconds after breaching a band, a 5-minute trading halt is triggered and trading resumes with an auction.

The authoritative source for LULD price bands is the SIP (Securities Information Processor). The CTA SIP handles Tape A/B securities via the CQS (quotes + LULD bands) and CTS (trades) feeds. The UTP SIP handles NASDAQ-listed securities (Tape C).

## Use Case

**Primary need:** Real-time halt event notifications for US equities (not continuous price band streaming).

**Budget:** $30-100/mo for a paid API.

---

## Provider Comparison

### Tier 1: Full Market Data APIs (Best for Programmatic Use)

#### 1. Polygon.io / Massive (Recommended)

- **URL:** https://polygon.io/docs/websocket/stocks/luld
- **Delivery:** WebSocket LULD stream
- **Coverage:** NYSE, NASDAQ, Cboe BZX, NYSE Arca, NYSE American
- **Fields:** event type, ticker, high/low price bands, indicator array, tape, timestamp, sequence number
- **Subscription:** Individual tickers or `*` for all US equities
- **Python client:** `polygon-api-client`
- **Pricing:** Starts ~$29/mo (Stocks Starter plan)
- **Connection limits:** 1 concurrent WebSocket per asset class by default (more available via support)

**Example payload:**
```json
{
  "ev": "LULD",
  "T": "MSFT",
  "h": 492.99,
  "l": 446.04,
  "i": [16],
  "z": 3,
  "t": 1764086430905642800,
  "q": 5925769
}
```

**Fields breakdown:**
| Field | Description |
|-------|-------------|
| `ev` | Event type (LULD) |
| `T` | Ticker symbol |
| `h` / `l` | Upper / lower price band |
| `i` | Indicators array (volatility event signals) |
| `z` | Tape identifier: 1=NYSE, 2=AMEX, 3=NASDAQ |
| `t` | Unix millisecond timestamp |
| `q` | Sequence number per ticker |

#### 2. Alpaca Markets (Runner-Up)

- **URL:** https://docs.alpaca.markets/docs/real-time-stock-pricing-data
- **Delivery:** WebSocket with dedicated LULD channel
- **Fields:** symbol (`S`), upper limit (`u`), lower limit (`d`), message type (`T`: `l`)
- **Python SDK:** `alpaca-py`
- **Pricing:** Free tier available with paper trading account; paid tiers for production
- **Auth:** API key + secret, must authenticate within 10 seconds of connecting
- **Extras:** Also streams trades, quotes, and minute bars in the same connection

**Good option if:**
- You want to prototype at zero cost first
- You also need trade/quote data alongside LULD

#### 3. Databento

- **URL:** https://databento.com/microstructure/luld
- **Delivery:** SIP-level LULD bands via CTS/CQS/UTP feeds
- **Latency:** Ultra-low — 42us cross-connect, 590us internet (p90)
- **Pricing:** Pay-as-you-go model; $125 free credits for new users
- **Client libraries:** Python, Rust, C++
- **Schema:** Historical and live message schemas are identical (same code for backtest and live)

**Best for:** Institutional-grade latency requirements. Overkill for halt-event-only use case.

---

### Tier 2: Free / Low-Cost Alert Services

#### 4. NASDAQ Trader RSS Feed (Already In Use)

- **URL:** https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts
- **Delivery:** RSS (requires polling every few seconds)
- **Coverage:** All NASDAQ-listed + exchange-listed securities
- **Cost:** Free, no authentication
- **Data:** Halt reason codes (LUDP, M, T1, T2, T12, etc.), halt/resume times
- **Limitation:** Not truly real-time — RSS polling has inherent latency (seconds to minutes)
- **Note:** Already used in `trading_halt_history.py` for historical halt data

**Related NASDAQ resources:**
- Current halts page: https://www.nasdaqtrader.com/trader.aspx?id=tradehalts
- Halt history search: https://www.nasdaqtrader.com/trader.aspx?id=TradingHaltHistory
- Halt reason codes: https://www.nasdaqtrader.com/trader.aspx?id=tradehaltcodes

#### 5. HaltAlerts.org

- **URL:** https://www.haltalerts.org/
- **Delivery:** Push notifications + API webhooks
- **Free tier:** 20 daily live halt alerts (no credit card required)
- **Paid plan:** Unlimited halts (pricing not publicly listed)
- **Data enrichment:** Alerts include price, volume, time, halt reason
- **Integration:** Webhook API for automated systems
- **Sources:** Monitors multiple data sources continuously

**Good for:** Alert-only use cases where you don't need raw price band data.

#### 6. NYSE Trading Halts

- **URL:** https://www.nyse.com/trade-halt
- **Delivery:** Web page (current day only)
- **Cost:** Free
- **Limitation:** Limited programmatic access, current day only

---

### Tier 3: SIP Direct Feeds (Institutional)

#### 7. CTA/UTP SIP Feeds

- **URL:** https://www.ctaplan.com/index
- **Description:** The authoritative, regulatory source for LULD price bands
- **Feeds:** CQS (quotes + NBBO + LULD bands) and CTS (trades) for Tape A/B; UTP for Tape C
- **Cost:** Expensive ($$$$) — requires direct exchange connectivity agreement
- **Target users:** HFT firms, market makers, institutional trading desks
- **Not practical** for this use case

---

### Tier 4: Visualization / Manual

#### 8. TradingView LULD Indicator

- **URL:** https://www.tradingview.com/script/Xz1IlKHS-LULD-Bands-Trading-Halt-Detector-Volume-Vigilante/
- **Description:** Pine Script indicator that visualizes LULD price bands and detects halts on charts
- **Alerts:** Real-time chart alerts for trading resumptions, LULD zone entries, band breaches
- **Limitation:** Manual/visual only, no programmatic API

#### 9. TheDesperateTrader

- **URL:** https://thedesperatetrader.com/
- **Description:** Free real-time stock scanner with live halt feed from NASDAQ official data
- **Features:** Sub-second latency, reason codes, direction analysis
- **Status:** Was free until Feb 10, 2026 — transitioning to subscription model

---

## Comparison Matrix

| Provider | Delivery | Latency | Cost | Python SDK | Free Tier | Halt Events | Price Bands |
|----------|----------|---------|------|------------|-----------|-------------|-------------|
| **Polygon/Massive** | WebSocket | Sub-second | ~$29/mo | Yes | No | Yes | Yes |
| **Alpaca** | WebSocket | Sub-second | Free-$99/mo | Yes | Yes | Yes | Yes |
| **Databento** | Live API | 42-590us | Pay-per-use | Yes | $125 credit | Yes | Yes |
| **NASDAQ RSS** | RSS polling | Seconds-minutes | Free | DIY | Yes | Yes | No |
| **HaltAlerts.org** | Webhook | Near real-time | Free/Paid | Webhook | 20/day | Yes | No |
| **NYSE** | Web page | N/A | Free | No | Yes | Yes | No |
| **CTA/UTP SIP** | Direct feed | Microseconds | $$$$$ | No | No | Yes | Yes |
| **TradingView** | Chart alerts | Real-time | Free | No | Yes | Yes | Yes |

---

## Recommendation

### Top Pick: Polygon.io (now Massive)

For halt event notifications within $30-100/mo budget:

1. **Polygon.io** ($29/mo) — Best overall value. WebSocket LULD stream delivers halt/resume events in real-time (sub-second). Python client library available. Subscribe to `*` for all US equities or specific tickers. The `i` (indicator) field signals the halt state.

2. **Alpaca** (free/$99/mo) — Best for prototyping. Free tier with paper trading account lets you test LULD WebSocket before committing to paid. Good if you also need trade/quote data.

### Not Recommended for This Use Case

- **Databento** — Excellent data but overkill/expensive for just halt events (better suited for continuous price band streaming + HFT)
- **NASDAQ RSS polling** — Already available in `trading_halt_history.py` but not truly real-time
- **CTA/UTP SIP** — Institutional-grade, prohibitively expensive

### Suggested Approach

1. Start with **Alpaca free tier** to prototype and validate the halt alerting workflow
2. If latency or data richness is insufficient, upgrade to **Polygon.io** ($29/mo)
3. Keep NASDAQ RSS polling (`trading_halt_history.py`) as a historical data backup

---

## Existing Infrastructure

The project already has `trading_halt_history.py` which:
- Downloads LULD halts from NASDAQ Trader RSS feed (historical, batch)
- Parses HTML tables from RSS entries
- Filters for `LUDP` reason code
- Outputs CSV with date, ticker, halt_time, resume_time, market

This could be enhanced with a real-time polling mode (every 5-10 seconds) as a zero-cost alternative, though it would have higher latency than WebSocket-based solutions.
