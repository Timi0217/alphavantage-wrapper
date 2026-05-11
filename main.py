import os
import time
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


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: dict):
    _cache[key] = (time.time(), value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=30.0)
    yield
    await http_client.aclose()


app = FastAPI(title="Alpha Vantage Wrapper", lifespan=lifespan)


HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alpha Vantage</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#fff;padding:40px 20px;line-height:1.5}
.container{max-width:640px;margin:0 auto;opacity:0;animation:fadeIn 0.6s forwards}
@keyframes fadeIn{to{opacity:1}}
.card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:16px;padding:24px;margin-bottom:20px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.title{font-family:'Courier New',monospace;font-size:28px;color:#9B59B6;font-weight:700}
.health{font-family:'Courier New',monospace;font-size:13px;color:#555;display:flex;align-items:center;gap:6px}
.health .d{width:8px;height:8px;border-radius:50%;background:#555;transition:background .3s}
.health .d.on{background:#4CAF50}
.subtitle{color:#888;font-size:14px;margin-bottom:24px}
.gauge-grid{display:grid;grid-template-columns:1fr;gap:12px;margin-bottom:20px}
.gauge-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:16px;text-align:center}
.gauge-card.blue-border{border-color:rgba(91,155,213,0.3)}
.gauge-card.green-border{border-color:rgba(76,175,80,0.3)}
.gauge-card.red-border{border-color:rgba(239,83,80,0.3)}
.gauge-label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:8px}
.gauge-value{font-size:32px;font-weight:700;margin-bottom:4px}
.gauge-value.blue{color:#5B9BD5}
.gauge-value.green{color:#4CAF50}
.gauge-value.red{color:#ef5350}
.gauge-signal{font-size:13px;margin-bottom:12px}
.gauge-signal.green{color:#4CAF50}
.gauge-signal.red{color:#ef5350}
.gauge-signal.neutral{color:#888}
.progress-bar{width:100%;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden}
.progress-fill{height:100%;border-radius:2px;transition:width 0.3s}
.progress-fill.blue{background:#5B9BD5}
.progress-fill.green{background:#4CAF50}
.progress-fill.red{background:#ef5350}
.section-title{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#888;margin-bottom:12px;font-weight:600}
.forex-row{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.05)}
.forex-row:last-child{border-bottom:none}
.forex-pair{color:#ccc;font-weight:500}
.forex-rate{font-family:'Courier New',monospace;font-size:16px;color:#fff}
.forex-change{font-size:13px;font-weight:600}
.forex-change.positive{color:#4CAF50}
.forex-change.negative{color:#ef5350}
.form-section{margin-top:24px}
.input-group{display:flex;gap:8px;margin-bottom:12px}
.input-field{flex:1;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 16px;color:#fff;font-size:14px}
.input-field:focus{outline:none;border-color:#9B59B6}
.btn{background:#9B59B6;color:#fff;border:none;border-radius:8px;padding:12px 24px;font-size:14px;font-weight:600;cursor:pointer;transition:background 0.2s}
.btn:hover{background:#8e44ad}
.try-suggestions{display:flex;gap:8px;flex-wrap:wrap}
.try-chip{background:rgba(255,255,255,0.05);color:#888;padding:6px 12px;border-radius:6px;font-size:12px;cursor:pointer;transition:all 0.2s}
.try-chip:hover{background:rgba(155,89,182,0.2);color:#9B59B6}
.error-msg{color:#ef5350;font-size:12px;margin-top:8px}
.loading{color:#888;font-size:13px;text-align:center;padding:12px}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="header">
<div class="title">Alpha Vantage</div>
<div class="health"><span class="d" id="dot"></span><span id="health-text">connecting...</span></div>
</div>
<div class="subtitle">50+ technical indicators, forex pairs, intraday data</div>

<div class="gauge-grid" id="gauges">
<div class="gauge-card blue-border">
<div class="gauge-label">RSI (14)</div>
<div class="loading">Loading...</div>
</div>
<div class="gauge-card green-border">
<div class="gauge-label">MACD</div>
<div class="loading">Loading...</div>
</div>
<div class="gauge-card red-border">
<div class="gauge-label">BOLLINGER</div>
<div class="loading">Loading...</div>
</div>
</div>

<div class="section-title">FOREX RATES</div>
<div id="forex">
<div class="loading">Loading forex rates...</div>
</div>

<div class="form-section">
<div class="input-group">
<input type="text" class="input-field" id="symbolInput" placeholder="AAPL" value="AAPL">
<button class="btn" onclick="fetchIndicator()">\\u2192 indicators</button>
</div>
<div class="try-suggestions">
<span style="color:#666;font-size:12px;margin-right:4px">Try:</span>
<div class="try-chip" onclick="setIndicator('RSI')">RSI</div>
<div class="try-chip" onclick="setIndicator('MACD')">MACD</div>
<div class="try-chip" onclick="setIndicator('BBANDS')">BBANDS</div>
<div class="try-chip" onclick="setIndicator('SMA')">SMA</div>
<div class="try-chip" onclick="setIndicator('EMA')">EMA</div>
</div>
<div id="result"></div>
</div>
</div>
</div>

<script>
let currentIndicator = 'RSI';

async function init() {
  const t0 = Date.now();
  try {
    await fetch('/health');
    const ms = Date.now() - t0;
    document.getElementById('dot').classList.add('on');
    document.getElementById('health-text').textContent = 'online \\u00B7 ' + ms + 'ms';
  } catch (e) {
    document.getElementById('health-text').textContent = 'offline';
  }

  // All homepage data in one server-side call
  try {
    const dash = await fetch('/dashboard').then(r => r.json());
    const container = document.getElementById('gauges');
    container.innerHTML = '';

    // RSI
    const rsi = dash.rsi;
    const rsiVal = rsi ? rsi.value : 'N/A';
    const rsiSig = rsi ? rsi.signal : 'Error';
    const rsiCls = rsi ? (rsi.value < 30 ? 'green' : rsi.value > 70 ? 'red' : 'neutral') : 'neutral';
    const rsiProg = rsi ? rsi.value : 0;
    container.innerHTML += '<div class="gauge-card blue-border"><div class="gauge-label">RSI (14)</div><div class="gauge-value blue">' + rsiVal + '</div><div class="gauge-signal ' + rsiCls + '">' + rsiSig + '</div><div class="progress-bar"><div class="progress-fill blue" style="width:' + rsiProg + '%"></div></div></div>';

    // MACD
    const macd = dash.macd;
    const macdVal = macd ? ((macd.value > 0 ? '+' : '') + macd.value) : 'N/A';
    const macdSig = macd ? macd.signal : 'Error';
    const macdColor = macd && macd.value > 0 ? 'green' : 'red';
    const macdCls = macd ? (macd.value > 0 ? 'green' : 'red') : 'neutral';
    container.innerHTML += '<div class="gauge-card ' + macdColor + '-border"><div class="gauge-label">MACD</div><div class="gauge-value ' + macdColor + '">' + macdVal + '</div><div class="gauge-signal ' + macdCls + '">' + macdSig + '</div><div class="progress-bar"><div class="progress-fill ' + macdColor + '" style="width:65%"></div></div></div>';

    // BBANDS
    const bb = dash.bbands;
    const bbVal = bb ? ('$' + bb.upper + ' / $' + bb.lower) : 'N/A';
    container.innerHTML += '<div class="gauge-card red-border"><div class="gauge-label">BOLLINGER</div><div class="gauge-value red" style="font-size:20px">' + bbVal + '</div><div class="gauge-signal neutral">Band range</div><div class="progress-bar"><div class="progress-fill red" style="width:85%"></div></div></div>';

    // Forex
    const forexContainer = document.getElementById('forex');
    forexContainer.innerHTML = '';
    (dash.forex || []).forEach(function(fx) {
      forexContainer.innerHTML += '<div class="forex-row"><div class="forex-pair">' + fx.pair + '</div><div class="forex-rate">' + fx.rate.toFixed(4) + '</div><div class="forex-change neutral">\\u2014</div></div>';
    });
    if (!dash.forex || !dash.forex.length) {
      forexContainer.innerHTML = '<div style="color:#666;font-size:13px;padding:8px 0">Forex data loading...</div>';
    }
  } catch (e) {
    // Fallback: show error state
    const container = document.getElementById('gauges');
    container.innerHTML = '<div class="gauge-card blue-border"><div class="gauge-label">RSI (14)</div><div class="loading">Rate limited</div></div><div class="gauge-card green-border"><div class="gauge-label">MACD</div><div class="loading">Rate limited</div></div><div class="gauge-card red-border"><div class="gauge-label">BOLLINGER</div><div class="loading">Rate limited</div></div>';
  }
}

function setIndicator(indicator) {
  currentIndicator = indicator;
  document.getElementById('result').innerHTML = '<div style="color:#9B59B6;font-size:12px;margin-top:8px">Selected: ' + indicator + '</div>';
}

async function fetchIndicator() {
  const symbol = document.getElementById('symbolInput').value.trim().toUpperCase() || 'AAPL';
  const resultDiv = document.getElementById('result');
  resultDiv.innerHTML = '<div class="loading">Fetching...</div>';
  try {
    const res = await fetch('/technical?symbol=' + symbol + '&indicator=' + currentIndicator);
    const data = await res.json();
    if (data.data && data.data.length > 0) {
      const point = data.data[0];
      const keys = Object.keys(point).filter(function(k) { return k !== 'date'; });
      const valueStr = keys.map(function(k) { return k + ': ' + (typeof point[k] === 'number' ? point[k].toFixed(2) : point[k]); }).join(', ');
      resultDiv.innerHTML = '<div style="margin-top:12px;padding:12px;background:rgba(155,89,182,0.1);border-radius:8px;font-size:12px"><div style="color:#9B59B6;font-weight:600;margin-bottom:4px">' + symbol + ' - ' + currentIndicator + '</div><div style="color:#ccc">' + valueStr + '</div><div style="color:#666;margin-top:4px;font-size:11px">Date: ' + point.date + '</div></div>';
    } else {
      resultDiv.innerHTML = '<div class="error-msg">No data available</div>';
    }
  } catch (e) {
    resultDiv.innerHTML = '<div class="error-msg">Error fetching data</div>';
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
    """
    Single endpoint for homepage data: RSI, MACD, BBANDS for AAPL + EUR/USD forex.
    Sequential upstream calls with delays to respect Alpha Vantage rate limits (5/min).
    Cached for 1 hour to avoid burning API quota.
    """
    import asyncio
    cached = _cache_get("dashboard")
    if cached:
        return cached
    result = {"rsi": None, "macd": None, "bbands": None, "forex": []}
    key = _get_key()

    async def _fetch(params):
        params["apikey"] = key
        try:
            resp = await http_client.get(BASE_URL, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if "Error Message" not in data and "Note" not in data:
                    return data
        except Exception:
            pass
        return None

    # 1) RSI
    data = await _fetch({"function": "RSI", "symbol": "AAPL", "interval": "daily", "time_period": "14", "series_type": "close"})
    if data:
        for key_name in data:
            if "Technical Analysis" in key_name:
                points = list(data[key_name].items())
                if points:
                    val = float(points[0][1].get("RSI", 0))
                    result["rsi"] = {"value": round(val, 1), "signal": "Oversold" if val < 30 else "Overbought" if val > 70 else "Neutral"}
                break

    await asyncio.sleep(15)  # Alpha Vantage: 5 calls/min = 12s between calls

    # 2) MACD
    data = await _fetch({"function": "MACD", "symbol": "AAPL", "interval": "daily", "series_type": "close"})
    if data:
        for key_name in data:
            if "Technical Analysis" in key_name:
                points = list(data[key_name].items())
                if points:
                    val = float(points[0][1].get("MACD", 0))
                    result["macd"] = {"value": round(val, 2), "signal": "Bullish" if val > 0 else "Bearish"}
                break

    await asyncio.sleep(15)

    # 3) BBANDS
    data = await _fetch({"function": "BBANDS", "symbol": "AAPL", "interval": "daily", "time_period": "20", "series_type": "close"})
    if data:
        for key_name in data:
            if "Technical Analysis" in key_name:
                points = list(data[key_name].items())
                if points:
                    p = points[0][1]
                    result["bbands"] = {
                        "upper": round(float(p.get("Real Upper Band", 0)), 2),
                        "middle": round(float(p.get("Real Middle Band", 0)), 2),
                        "lower": round(float(p.get("Real Lower Band", 0)), 2),
                    }
                break

    await asyncio.sleep(15)

    # 4) EUR/USD forex only (save API calls)
    data = await _fetch({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": "EUR", "to_currency": "USD"})
    if data:
        rate_data = data.get("Realtime Currency Exchange Rate", {})
        if rate_data:
            result["forex"].append({
                "pair": "EUR/USD",
                "rate": round(float(rate_data.get("5. Exchange Rate", 0)), 4),
            })

    result["timestamp"] = _ts()
    _cache_set("dashboard", result)
    return result


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
