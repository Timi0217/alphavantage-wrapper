import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import httpx


ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
BASE_URL = "https://www.alphavantage.co/query"

http_client: Optional[httpx.AsyncClient] = None

# ── Simple TTL cache ─────────────────────────────────────────────────────
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 3600  # 1 hour

# Dashboard data lives here — updated by background task
_dashboard_data: dict = {"rsi": None, "macd": None, "bbands": None, "forex": [], "status": "warming_up"}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: dict):
    _cache[key] = (time.time(), value)


async def _bg_fetch(params: dict):
    """Single upstream call, returns parsed JSON or None."""
    key = ALPHA_VANTAGE_API_KEY or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        return None
    params["apikey"] = key
    try:
        resp = await http_client.get(BASE_URL, params=params, timeout=25.0)
        if resp.status_code == 200:
            data = resp.json()
            if "Error Message" not in data and "Note" not in data:
                info = data.get("Information", "")
                if "rate" not in info.lower():
                    return data
    except Exception:
        pass
    return None


async def _refresh_dashboard():
    """Background task: fetches dashboard data on startup, then every 4 hours.
    Makes 4 sequential upstream calls with 15s gaps to respect 5 calls/min.
    Preserves previous data when rate-limited instead of overwriting with nulls."""
    global _dashboard_data
    await asyncio.sleep(5)  # Let server fully boot

    while True:
        # Start from previous data if available (preserve on rate-limit)
        prev = _dashboard_data
        result = {
            "rsi": prev.get("rsi"),
            "macd": prev.get("macd"),
            "bbands": prev.get("bbands"),
            "forex": prev.get("forex", []),
        }
        any_success = False

        # 1) RSI
        data = await _bg_fetch({"function": "RSI", "symbol": "AAPL", "interval": "daily",
                                "time_period": "14", "series_type": "close"})
        if data:
            for k in data:
                if "Technical Analysis" in k:
                    pts = list(data[k].items())
                    if pts:
                        val = float(pts[0][1].get("RSI", 0))
                        result["rsi"] = {"value": round(val, 1),
                                         "signal": "Oversold" if val < 30 else "Overbought" if val > 70 else "Neutral"}
                        any_success = True
                    break

        await asyncio.sleep(15)

        # 2) MACD
        data = await _bg_fetch({"function": "MACD", "symbol": "AAPL", "interval": "daily",
                                "series_type": "close"})
        if data:
            for k in data:
                if "Technical Analysis" in k:
                    pts = list(data[k].items())
                    if pts:
                        val = float(pts[0][1].get("MACD", 0))
                        result["macd"] = {"value": round(val, 2),
                                          "signal": "Bullish" if val > 0 else "Bearish"}
                        any_success = True
                    break

        await asyncio.sleep(15)

        # 3) BBANDS
        data = await _bg_fetch({"function": "BBANDS", "symbol": "AAPL", "interval": "daily",
                                "time_period": "20", "series_type": "close"})
        if data:
            for k in data:
                if "Technical Analysis" in k:
                    pts = list(data[k].items())
                    if pts:
                        p = pts[0][1]
                        result["bbands"] = {
                            "upper": round(float(p.get("Real Upper Band", 0)), 2),
                            "middle": round(float(p.get("Real Middle Band", 0)), 2),
                            "lower": round(float(p.get("Real Lower Band", 0)), 2),
                        }
                        any_success = True
                    break

        await asyncio.sleep(15)

        # 4) Forex pairs
        forex_pairs = [
            ("EUR", "USD"),
            ("GBP", "USD"),
            ("USD", "JPY"),
        ]
        forex_results = list(result.get("forex", []))  # preserve previous
        for frm, to in forex_pairs:
            data = await _bg_fetch({"function": "CURRENCY_EXCHANGE_RATE",
                                    "from_currency": frm, "to_currency": to})
            if data:
                rd = data.get("Realtime Currency Exchange Rate", {})
                if rd:
                    pair_name = f"{frm}/{to}"
                    rate = round(float(rd.get("5. Exchange Rate", 0)), 4)
                    # Update existing or append
                    found = False
                    for i, fx in enumerate(forex_results):
                        if fx.get("pair") == pair_name:
                            forex_results[i] = {"pair": pair_name, "rate": rate}
                            found = True
                            break
                    if not found:
                        forex_results.append({"pair": pair_name, "rate": rate})
                    any_success = True
            await asyncio.sleep(15)

        result["forex"] = forex_results
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        result["status"] = "ready"
        _dashboard_data = result
        _cache_set("dashboard", result)

        # Refresh every 6 hours (uses 6 calls per refresh = ~24 calls/day at 4 refreshes)
        await asyncio.sleep(21600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=30.0)
    task = asyncio.create_task(_refresh_dashboard())
    yield
    task.cancel()
    await http_client.aclose()


app = FastAPI(title="Alpha Vantage Wrapper", lifespan=lifespan)


HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alpha Vantage \u2014 Technical Indicators & Forex</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e8e8e8;padding:40px 20px;line-height:1.5}
.container{max-width:680px;margin:0 auto;opacity:0;animation:fadeIn .5s ease forwards}
@keyframes fadeIn{to{opacity:1}}
@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes pulse{0%,100%{opacity:.6}50%{opacity:.25}}

/* Header */
.header-card{background:linear-gradient(135deg,rgba(120,60,170,.15),rgba(80,40,130,.08));border:1px solid rgba(155,89,182,.15);border-radius:20px;padding:28px;margin-bottom:14px;overflow:hidden}
.header-row{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.brand{display:flex;align-items:center;gap:12px}
.brand-icon{width:42px;height:42px;background:linear-gradient(135deg,#9B59B6,#7D3C98);border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:'Courier New',monospace;font-weight:900;font-size:18px;color:#fff}
.brand-text .title{font-size:22px;font-weight:700;color:#fff;letter-spacing:-.5px}
.brand-text .org{font-size:12px;color:rgba(155,89,182,.8);font-weight:500;letter-spacing:.5px}
.health-badge{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:6px 14px;font-size:12px;color:#888}
.health-dot{width:7px;height:7px;background:#555;border-radius:50%;transition:background .3s}
.health-dot.on{background:#4CAF50;box-shadow:0 0 8px rgba(76,175,80,.4)}
.tagline{color:#888;font-size:14px;margin-bottom:20px;margin-left:54px}
.symbol-tag{display:inline-block;background:rgba(155,89,182,.12);color:#9B59B6;font-family:'Courier New',monospace;font-size:12px;font-weight:700;padding:3px 10px;border-radius:6px;margin-left:54px;margin-bottom:20px}

/* Indicator grid */
.ind-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px}
.ind-card{background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:18px;text-align:center;transition:all .2s}
.ind-card:hover{background:rgba(155,89,182,.04);border-color:rgba(155,89,182,.15)}
.ind-label{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:1.2px;font-weight:600;margin-bottom:12px}
.ind-val{font-family:'Courier New',monospace;font-size:30px;font-weight:700;color:#fff;line-height:1;margin-bottom:6px}
.ind-signal{font-size:11px;font-weight:600;margin-bottom:10px}
.ind-signal.bullish{color:#4CAF50}
.ind-signal.bearish{color:#ef5350}
.ind-signal.neutral{color:#888}
.ind-signal.overbought{color:#ef5350}
.ind-signal.oversold{color:#4CAF50}

/* RSI gauge bar */
.gauge{width:100%;height:6px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;position:relative}
.gauge-fill{height:100%;border-radius:3px;transition:width .6s ease}
.gauge-zones{position:absolute;top:0;left:0;right:0;bottom:0;display:flex}
.gauge-zone{flex:1}
.gauge-zone.low{background:rgba(76,175,80,.15)}
.gauge-zone.mid{background:rgba(255,255,255,.03)}
.gauge-zone.high{background:rgba(239,83,80,.15)}
.gauge-marker{position:absolute;top:-2px;width:3px;height:10px;background:#fff;border-radius:2px;transition:left .6s ease;box-shadow:0 0 4px rgba(255,255,255,.5)}

/* Band visualization */
.band-viz{display:flex;align-items:center;gap:4px;justify-content:center;margin-top:4px}
.band-bar{height:4px;border-radius:2px;transition:width .3s}
.band-label{font-size:9px;color:#555;font-family:'Courier New',monospace}

/* Forex section */
.forex-section{margin-top:4px}
.forex-grid{display:grid;grid-template-columns:1fr;gap:1px;background:rgba(255,255,255,.03);border-radius:12px;overflow:hidden}
.forex-row{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;background:#0a0a0a;transition:background .2s}
.forex-row:hover{background:rgba(155,89,182,.03)}
.forex-pair{font-size:13px;color:#aaa;font-weight:500;display:flex;align-items:center;gap:8px}
.forex-flag{font-size:16px}
.forex-rate{font-family:'Courier New',monospace;font-size:18px;color:#fff;font-weight:600}

/* Cards */
.card{background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:20px 24px;margin-bottom:12px;animation:slideUp .5s ease backwards}
.section-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;margin-bottom:14px}

/* Indicator selector */
.ind-select{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.ind-chip{background:rgba(255,255,255,.04);color:#777;padding:7px 14px;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;transition:all .15s;border:1px solid transparent}
.ind-chip:hover{background:rgba(155,89,182,.1);color:#9B59B6;border-color:rgba(155,89,182,.2)}
.ind-chip.active{background:rgba(155,89,182,.15);color:#9B59B6;border-color:rgba(155,89,182,.3)}

/* Search */
.search-row{display:flex;gap:8px;margin-bottom:10px}
.search-input{flex:1;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:11px 16px;color:#fff;font-size:14px;outline:none;transition:all .2s;font-family:inherit}
.search-input:focus{border-color:rgba(155,89,182,.5);background:rgba(255,255,255,.06);box-shadow:0 0 0 3px rgba(155,89,182,.1)}
.search-input::placeholder{color:#444}
.search-btn{background:linear-gradient(135deg,#9B59B6,#7D3C98);color:#fff;border:none;border-radius:10px;padding:11px 20px;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;white-space:nowrap}
.search-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(155,89,182,.3)}
#result{margin-top:14px;padding:14px;background:rgba(155,89,182,.06);border:1px solid rgba(155,89,182,.15);border-radius:10px;font-family:'Courier New',monospace;font-size:12px;color:#999;white-space:pre-wrap;word-wrap:break-word;display:none;max-height:280px;overflow-y:auto}
.warm{animation:pulse 2s infinite}
</style>
</head>
<body>
<div class="container">

<div class="header-card">
<div class="header-row">
<div class="brand">
<div class="brand-icon">AV</div>
<div class="brand-text">
<div class="title">Alpha Vantage</div>
<div class="org">Technical Analysis & Forex</div>
</div>
</div>
<div class="health-badge"><span class="health-dot" id="dot"></span><span id="ht">checking...</span></div>
</div>
<div class="tagline">50+ technical indicators, forex pairs &amp; intraday data</div>
<div class="symbol-tag">AAPL &middot; Daily</div>

<div class="ind-grid" id="indicators">
<div class="ind-card"><div class="ind-label">RSI (14)</div><div class="ind-val warm">&mdash;</div><div class="ind-signal neutral">Loading...</div><div class="gauge"><div class="gauge-fill" style="width:0"></div></div></div>
<div class="ind-card"><div class="ind-label">MACD</div><div class="ind-val warm">&mdash;</div><div class="ind-signal neutral">Loading...</div></div>
<div class="ind-card"><div class="ind-label">Bollinger</div><div class="ind-val warm" style="font-size:16px">&mdash;</div><div class="ind-signal neutral">Loading...</div></div>
</div>

<div class="forex-section">
<div class="section-label">Forex Rates</div>
<div class="forex-grid" id="forex">
<div class="forex-row"><div class="forex-pair">Loading...</div><div class="forex-rate">&mdash;</div></div>
</div>
</div>
</div>

<div class="card" style="animation-delay:.15s">
<div class="section-label">Fetch Indicator</div>
<div class="search-row">
<input type="text" class="search-input" id="symbolInput" placeholder="Symbol (e.g. AAPL, MSFT, TSLA)" value="AAPL">
<button class="search-btn" id="fetchBtn">Fetch &rarr;</button>
</div>
<div class="ind-select" id="indSelect">
<span class="ind-chip active" data-ind="RSI">RSI</span>
<span class="ind-chip" data-ind="MACD">MACD</span>
<span class="ind-chip" data-ind="BBANDS">BBANDS</span>
<span class="ind-chip" data-ind="SMA">SMA</span>
<span class="ind-chip" data-ind="EMA">EMA</span>
<span class="ind-chip" data-ind="STOCH">STOCH</span>
<span class="ind-chip" data-ind="ADX">ADX</span>
<span class="ind-chip" data-ind="ATR">ATR</span>
</div>
<div id="result"></div>
</div>

</div>

<script>
var currentInd = 'RSI';

function renderDash(d) {
  var w = d.status === 'warming_up';
  var g = document.getElementById('indicators');

  // RSI
  var rsi = d.rsi;
  var rV = rsi ? rsi.value.toFixed(1) : (w ? '...' : '\u2014');
  var rSig = rsi ? rsi.signal : (w ? 'Loading...' : 'No data');
  var rCls = rsi ? (rsi.value > 70 ? 'overbought' : rsi.value < 30 ? 'oversold' : 'neutral') : 'neutral';
  var rPct = rsi ? rsi.value : 50;

  // MACD
  var macd = d.macd;
  var mV = macd ? ((macd.value > 0 ? '+' : '') + macd.value.toFixed(2)) : (w ? '...' : '\u2014');
  var mSig = macd ? macd.signal : (w ? 'Loading...' : 'No data');
  var mCls = macd ? (macd.value > 0 ? 'bullish' : 'bearish') : 'neutral';

  // Bollinger Bands
  var bb = d.bbands;
  var bV = bb ? '$' + bb.middle.toFixed(0) : (w ? '...' : '\u2014');
  var bSig = bb ? '$' + bb.lower.toFixed(0) + ' \u2014 $' + bb.upper.toFixed(0) : (w ? 'Loading...' : 'No data');
  var bRange = bb ? bb.upper - bb.lower : 0;
  var bWidth = bb ? ((bb.upper - bb.lower) / bb.middle * 100).toFixed(1) : 0;

  g.innerHTML =
    '<div class="ind-card"><div class="ind-label">RSI (14)</div>' +
    '<div class="ind-val' + (w && !rsi ? ' warm' : '') + '">' + rV + '</div>' +
    '<div class="ind-signal ' + rCls + '">' + rSig + '</div>' +
    '<div class="gauge" style="position:relative"><div class="gauge-zones"><div class="gauge-zone low"></div><div class="gauge-zone mid"></div><div class="gauge-zone high"></div></div>' +
    (rsi ? '<div class="gauge-marker" style="left:' + Math.min(97, rPct) + '%"></div>' : '') +
    '</div></div>' +

    '<div class="ind-card"><div class="ind-label">MACD</div>' +
    '<div class="ind-val' + (w && !macd ? ' warm' : '') + '">' + mV + '</div>' +
    '<div class="ind-signal ' + mCls + '">' + mSig + '</div></div>' +

    '<div class="ind-card"><div class="ind-label">Bollinger</div>' +
    '<div class="ind-val' + (w && !bb ? ' warm' : '') + '" style="font-size:22px">' + bV + '</div>' +
    '<div class="ind-signal neutral">' + bSig + '</div>' +
    (bb ? '<div style="text-align:center;margin-top:6px"><span style="font-size:10px;color:#555;font-family:monospace">Width: ' + bWidth + '%</span></div>' : '') +
    '</div>';

  // Forex
  var fx = document.getElementById('forex');
  if (d.forex && d.forex.length) {
    var flags = {'EUR/USD':'\\ud83c\\uddea\\ud83c\\uddfa','GBP/USD':'\\ud83c\\uddec\\ud83c\\udde7','USD/JPY':'\\ud83c\\uddef\\ud83c\\uddf5'};
    fx.innerHTML = d.forex.map(function(f) {
      return '<div class="forex-row"><div class="forex-pair">' + (flags[f.pair]||'') + ' ' + f.pair + '</div><div class="forex-rate">' + f.rate.toFixed(4) + '</div></div>';
    }).join('');
  } else {
    fx.innerHTML = '<div class="forex-row"><div class="forex-pair" style="color:#555">' + (w ? 'Loading...' : 'No data') + '</div><div class="forex-rate">&mdash;</div></div>';
  }
}

async function init() {
  var t0 = Date.now();
  try {
    await fetch('/health');
    document.getElementById('dot').classList.add('on');
    document.getElementById('ht').textContent = 'online \u00b7 ' + (Date.now()-t0) + 'ms';
  } catch(e) {
    document.getElementById('ht').textContent = 'offline';
  }

  try {
    var d = await fetch('/dashboard').then(function(r){return r.json()});
    renderDash(d);
    if (d.status === 'warming_up') {
      var poll = setInterval(async function() {
        try { var d2 = await fetch('/dashboard').then(function(r){return r.json()}); renderDash(d2); if (d2.status==='ready') clearInterval(poll); } catch(e) { clearInterval(poll); }
      }, 8000);
    }
  } catch(e) { /* leave loading state */ }
}

// Indicator chips
document.getElementById('indSelect').addEventListener('click', function(e) {
  var chip = e.target.closest('.ind-chip');
  if (!chip) return;
  document.querySelectorAll('.ind-chip').forEach(function(c){c.classList.remove('active')});
  chip.classList.add('active');
  currentInd = chip.getAttribute('data-ind');
});

// Fetch button
document.getElementById('fetchBtn').addEventListener('click', doFetch);
document.getElementById('symbolInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); doFetch(); }
});

async function doFetch() {
  var symbol = document.getElementById('symbolInput').value.trim().toUpperCase() || 'AAPL';
  var r = document.getElementById('result');
  r.style.display = 'block';
  r.style.color = '#9B59B6';
  r.textContent = 'Fetching ' + currentInd + ' for ' + symbol + '...';
  try {
    var res = await fetch('/technical?symbol=' + symbol + '&indicator=' + currentInd);
    var data = await res.json();
    if (data.detail) { r.style.color = '#ef5350'; r.textContent = 'Error: ' + data.detail; return; }
    if (data.data && data.data.length > 0) {
      r.style.color = '#999';
      r.textContent = JSON.stringify(data, null, 2);
    } else {
      r.style.color = '#ef5350';
      r.textContent = 'No data available';
    }
  } catch(e) {
    r.style.color = '#ef5350';
    r.textContent = 'Error: ' + e.message;
  }
}

init();
</script>
</body>
</html>
"""


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_key() -> str:
    key = ALPHA_VANTAGE_API_KEY or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="ALPHA_VANTAGE_API_KEY not configured")
    return key


async def _av_request(params: dict) -> dict:
    """Make a request to Alpha Vantage with error handling."""
    params["apikey"] = _get_key()
    try:
        response = await http_client.get(BASE_URL, params=params)
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="Alpha Vantage rate limit exceeded (25 requests/day on free tier)")
        response.raise_for_status()
        data = response.json()

        # Alpha Vantage returns error messages inside JSON
        if "Error Message" in data:
            raise HTTPException(status_code=404, detail=data["Error Message"])
        if "Note" in data:
            raise HTTPException(status_code=429, detail=data["Note"])
        if "Information" in data and "rate" in data["Information"].lower():
            raise HTTPException(status_code=429, detail=data["Information"])

        return data
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Network error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unexpected error: {str(e)}")


# ── Endpoints ────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def root():
    return HOME_HTML


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": _ts()}


@app.get("/dashboard")
async def dashboard():
    """Returns pre-fetched dashboard data instantly. Data is refreshed hourly
    by a background task — no blocking upstream calls on this endpoint."""
    return _dashboard_data


@app.get("/quote")
async def get_quote(symbol: str = Query(..., description="Stock symbol (e.g., AAPL)")):
    """Get current stock quote via GLOBAL_QUOTE."""
    data = await _av_request({"function": "GLOBAL_QUOTE", "symbol": symbol})
    gq = data.get("Global Quote", {})
    if not gq:
        raise HTTPException(status_code=404, detail=f"No quote data for {symbol}")

    return {
        "symbol": gq.get("01. symbol", symbol),
        "current_price": float(gq["05. price"]) if gq.get("05. price") else None,
        "open": float(gq["02. open"]) if gq.get("02. open") else None,
        "high": float(gq["03. high"]) if gq.get("03. high") else None,
        "low": float(gq["04. low"]) if gq.get("04. low") else None,
        "volume": int(gq["06. volume"]) if gq.get("06. volume") else None,
        "previous_close": float(gq["08. previous close"]) if gq.get("08. previous close") else None,
        "change": float(gq["09. change"]) if gq.get("09. change") else None,
        "change_pct": gq.get("10. change percent", "").replace("%", ""),
        "latest_trading_day": gq.get("07. latest trading day"),
        "timestamp": _ts(),
    }


@app.get("/technical")
async def get_technical(
    symbol: str = Query(..., description="Stock symbol (e.g., AAPL)"),
    indicator: str = Query(..., description="Indicator: RSI, MACD, SMA, EMA, BBANDS, STOCH, ADX, CCI, AROON, OBV, VWAP"),
    interval: str = Query("daily", description="Interval: 1min, 5min, 15min, 30min, 60min, daily, weekly, monthly"),
    time_period: int = Query(14, description="Number of data points for calculation (e.g., 14 for RSI-14)"),
    series_type: str = Query("close", description="Price type: close, open, high, low"),
):
    """Get a technical indicator for a symbol."""
    indicator_upper = indicator.upper()
    supported = {"RSI", "MACD", "SMA", "EMA", "BBANDS", "STOCH", "ADX", "CCI", "AROON", "OBV", "VWAP", "WMA", "DEMA", "TEMA", "WILLR", "MFI", "ATR"}
    if indicator_upper not in supported:
        raise HTTPException(status_code=400, detail=f"Unsupported indicator: {indicator}. Supported: {sorted(supported)}")

    cache_key = f"technical:{symbol}:{indicator_upper}:{interval}:{time_period}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {
        "function": indicator_upper,
        "symbol": symbol,
        "interval": interval,
        "time_period": str(time_period),
        "series_type": series_type,
    }

    data = await _av_request(params)

    # Alpha Vantage returns data under "Technical Analysis: {INDICATOR}" key
    ta_key = None
    for key in data:
        if "Technical Analysis" in key:
            ta_key = key
            break

    if not ta_key:
        raise HTTPException(status_code=404, detail=f"No {indicator_upper} data for {symbol}")

    # Get most recent data points (up to 30)
    raw_points = data[ta_key]
    points = []
    for date_str, values in list(raw_points.items())[:30]:
        point = {"date": date_str}
        for k, v in values.items():
            try:
                point[k] = float(v)
            except (ValueError, TypeError):
                point[k] = v
        points.append(point)

    meta = data.get("Meta Data", {})

    resp = {
        "symbol": symbol,
        "indicator": indicator_upper,
        "interval": interval,
        "time_period": time_period,
        "series_type": series_type,
        "data": points,
        "meta": {
            "last_refreshed": meta.get("3: Last Refreshed"),
            "time_zone": meta.get("4: Time Zone"),
        },
        "timestamp": _ts(),
    }
    _cache_set(cache_key, resp)
    return resp


@app.get("/intraday")
async def get_intraday(
    symbol: str = Query(..., description="Stock symbol (e.g., AAPL)"),
    interval: str = Query("5min", description="Interval: 1min, 5min, 15min, 30min, 60min"),
    outputsize: str = Query("compact", description="compact (100 points) or full"),
):
    """Get intraday time series."""
    data = await _av_request({
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
    })

    ts_key = f"Time Series ({interval})"
    raw = data.get(ts_key, {})
    if not raw:
        raise HTTPException(status_code=404, detail=f"No intraday data for {symbol}")

    points = []
    for dt, values in list(raw.items())[:100]:
        points.append({
            "datetime": dt,
            "open": float(values.get("1. open", 0)),
            "high": float(values.get("2. high", 0)),
            "low": float(values.get("3. low", 0)),
            "close": float(values.get("4. close", 0)),
            "volume": int(values.get("5. volume", 0)),
        })

    return {
        "symbol": symbol,
        "interval": interval,
        "data": points,
        "timestamp": _ts(),
    }


@app.get("/daily")
async def get_daily(
    symbol: str = Query(..., description="Stock symbol (e.g., AAPL)"),
    outputsize: str = Query("compact", description="compact (100 days) or full (20+ years)"),
):
    """Get daily adjusted time series."""
    data = await _av_request({
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": outputsize,
    })

    raw = data.get("Time Series (Daily)", {})
    if not raw:
        raise HTTPException(status_code=404, detail=f"No daily data for {symbol}")

    points = []
    for date_str, values in list(raw.items())[:100]:
        points.append({
            "date": date_str,
            "open": float(values.get("1. open", 0)),
            "high": float(values.get("2. high", 0)),
            "low": float(values.get("3. low", 0)),
            "close": float(values.get("4. close", 0)),
            "volume": int(values.get("5. volume", 0)),
        })

    return {
        "symbol": symbol,
        "data": points,
        "timestamp": _ts(),
    }


@app.get("/forex")
async def get_forex(
    from_currency: str = Query(..., description="From currency (e.g., USD)"),
    to_currency: str = Query(..., description="To currency (e.g., EUR)"),
):
    """Get real-time forex exchange rate."""
    cache_key = f"forex:{from_currency.upper()}:{to_currency.upper()}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    data = await _av_request({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
    })

    rate_data = data.get("Realtime Currency Exchange Rate", {})
    if not rate_data:
        raise HTTPException(status_code=404, detail=f"No forex data for {from_currency}/{to_currency}")

    resp = {
        "from_currency": rate_data.get("1. From_Currency Code"),
        "from_name": rate_data.get("2. From_Currency Name"),
        "to_currency": rate_data.get("3. To_Currency Code"),
        "to_name": rate_data.get("4. To_Currency Name"),
        "exchange_rate": float(rate_data.get("5. Exchange Rate", 0)),
        "last_refreshed": rate_data.get("6. Last Refreshed"),
        "time_zone": rate_data.get("7. Time Zone"),
        "bid_price": float(rate_data.get("8. Bid Price", 0)),
        "ask_price": float(rate_data.get("9. Ask Price", 0)),
        "timestamp": _ts(),
    }
    _cache_set(cache_key, resp)
    return resp


@app.get("/search")
async def search_symbols(
    keywords: str = Query(..., description="Search keywords (e.g., 'apple', 'microsoft')"),
):
    """Search for stock symbols."""
    data = await _av_request({"function": "SYMBOL_SEARCH", "keywords": keywords})
    matches = data.get("bestMatches", [])

    results = []
    for m in matches[:10]:
        results.append({
            "symbol": m.get("1. symbol"),
            "name": m.get("2. name"),
            "type": m.get("3. type"),
            "region": m.get("4. region"),
            "currency": m.get("8. currency"),
            "match_score": m.get("9. matchScore"),
        })

    return {
        "keywords": keywords,
        "results": results,
        "timestamp": _ts(),
    }
