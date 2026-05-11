import os
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import httpx


ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
BASE_URL = "https://www.alphavantage.co/query"

http_client: Optional[httpx.AsyncClient] = None


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
.title{font-family:'Courier New',monospace;font-style:italic;font-size:28px;color:#9B59B6}
.health-badge{background:rgba(76,175,80,0.2);color:#4CAF50;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.health-badge.loading{background:rgba(155,89,182,0.2);color:#9B59B6}
.health-badge.error{background:rgba(239,83,80,0.2);color:#ef5350}
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
<div class="health-badge loading" id="health">\\u2022 \\u2022 \\u2022</div>
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

async function fetchHealth() {
  try {
    const res = await fetch('/health');
    const data = await res.json();
    const badge = document.getElementById('health');
    badge.textContent = '\\u2713 Healthy';
    badge.className = 'health-badge';
  } catch (e) {
    const badge = document.getElementById('health');
    badge.textContent = '\\u2717 Error';
    badge.className = 'health-badge error';
  }
}

async function fetchRSI() {
  try {
    const res = await fetch('/technical?symbol=AAPL&indicator=RSI');
    const data = await res.json();
    if (data.data && data.data.length > 0) {
      const value = data.data[0].RSI || 0;
      const signal = value < 30 ? 'Oversold' : value > 70 ? 'Overbought' : 'Neutral';
      const signalClass = value < 30 ? 'green' : value > 70 ? 'red' : 'neutral';
      return { value: value.toFixed(1), signal, signalClass, progress: value, color: 'blue' };
    }
  } catch (e) {
    return { value: 'N/A', signal: 'Error', signalClass: 'neutral', progress: 0, color: 'blue' };
  }
}

async function fetchMACD() {
  try {
    const res = await fetch('/technical?symbol=AAPL&indicator=MACD');
    const data = await res.json();
    if (data.data && data.data.length > 0) {
      const value = data.data[0].MACD || 0;
      const signal = value > 0 ? 'Bullish' : 'Bearish';
      const signalClass = value > 0 ? 'green' : 'red';
      const displayValue = (value > 0 ? '+' : '') + value.toFixed(2);
      return { value: displayValue, signal, signalClass, progress: 65, color: value > 0 ? 'green' : 'red' };
    }
  } catch (e) {
    return { value: 'N/A', signal: 'Error', signalClass: 'neutral', progress: 0, color: 'green' };
  }
}

async function fetchBBANDS() {
  try {
    const res = await fetch('/technical?symbol=AAPL&indicator=BBANDS');
    const data = await res.json();
    if (data.data && data.data.length > 0) {
      const point = data.data[0];
      const upper = point['Real Upper Band'] || 0;
      const middle = point['Real Middle Band'] || 0;
      const lower = point['Real Lower Band'] || 0;

      // Assume close is near middle for demo
      const signal = 'Overbought';
      const signalClass = 'red';
      const displayValue = 'Upper';
      return { value: displayValue, signal, signalClass, progress: 85, color: 'red' };
    }
  } catch (e) {
    return { value: 'N/A', signal: 'Error', signalClass: 'neutral', progress: 0, color: 'red' };
  }
}

async function fetchForex() {
  const pairs = [
    { from: 'EUR', to: 'USD', name: 'EUR/USD' },
    { from: 'GBP', to: 'USD', name: 'GBP/USD' },
    { from: 'USD', to: 'JPY', name: 'USD/JPY' },
    { from: 'USD', to: 'CHF', name: 'USD/CHF' }
  ];

  const forexContainer = document.getElementById('forex');
  forexContainer.innerHTML = '';

  for (const pair of pairs) {
    try {
      const res = await fetch(`/forex?from_currency=${pair.from}&to_currency=${pair.to}`);
      const data = await res.json();
      const rate = data.exchange_rate || 0;

      const row = document.createElement('div');
      row.className = 'forex-row';
      row.innerHTML = `
        <div class="forex-pair">${pair.name}</div>
        <div class="forex-rate">${rate.toFixed(4)}</div>
        <div class="forex-change neutral">\\u2014</div>
      `;
      forexContainer.appendChild(row);
    } catch (e) {
      const row = document.createElement('div');
      row.className = 'forex-row';
      row.innerHTML = `
        <div class="forex-pair">${pair.name}</div>
        <div class="forex-rate" style="color:#ef5350">Error</div>
        <div class="forex-change neutral">\\u2014</div>
      `;
      forexContainer.appendChild(row);
    }
  }
}

async function updateGauges() {
  const [rsi, macd, bbands] = await Promise.all([fetchRSI(), fetchMACD(), fetchBBANDS()]);

  const gauges = [
    { data: rsi, label: 'RSI (14)', borderClass: 'blue-border' },
    { data: macd, label: 'MACD', borderClass: macd.color === 'green' ? 'green-border' : 'red-border' },
    { data: bbands, label: 'BOLLINGER', borderClass: 'red-border' }
  ];

  const container = document.getElementById('gauges');
  container.innerHTML = '';

  gauges.forEach(({ data, label, borderClass }) => {
    const card = document.createElement('div');
    card.className = `gauge-card ${borderClass}`;
    card.innerHTML = `
      <div class="gauge-label">${label}</div>
      <div class="gauge-value ${data.color}">${data.value}</div>
      <div class="gauge-signal ${data.signalClass}">${data.signal}</div>
      <div class="progress-bar">
        <div class="progress-fill ${data.color}" style="width:${data.progress}%"></div>
      </div>
    `;
    container.appendChild(card);
  });
}

function setIndicator(indicator) {
  currentIndicator = indicator;
  document.getElementById('result').innerHTML = `<div style="color:#9B59B6;font-size:12px;margin-top:8px">Selected: ${indicator}</div>`;
}

async function fetchIndicator() {
  const symbol = document.getElementById('symbolInput').value.trim().toUpperCase() || 'AAPL';
  const resultDiv = document.getElementById('result');

  resultDiv.innerHTML = '<div class="loading">Fetching...</div>';

  try {
    const res = await fetch(`/technical?symbol=${symbol}&indicator=${currentIndicator}`);
    const data = await res.json();

    if (data.data && data.data.length > 0) {
      const point = data.data[0];
      const keys = Object.keys(point).filter(k => k !== 'date');
      const valueStr = keys.map(k => `${k}: ${typeof point[k] === 'number' ? point[k].toFixed(2) : point[k]}`).join(', ');

      resultDiv.innerHTML = `
        <div style="margin-top:12px;padding:12px;background:rgba(155,89,182,0.1);border-radius:8px;font-size:12px">
          <div style="color:#9B59B6;font-weight:600;margin-bottom:4px">${symbol} - ${currentIndicator}</div>
          <div style="color:#ccc">${valueStr}</div>
          <div style="color:#666;margin-top:4px;font-size:11px">Date: ${point.date}</div>
        </div>
      `;
    } else {
      resultDiv.innerHTML = '<div class="error-msg">No data available</div>';
    }
  } catch (e) {
    resultDiv.innerHTML = `<div class="error-msg">Error: ${e.message || 'Failed to fetch'}</div>`;
  }
}

// Initialize
fetchHealth();
updateGauges();
fetchForex();
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

    return {
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
    data = await _av_request({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
    })

    rate_data = data.get("Realtime Currency Exchange Rate", {})
    if not rate_data:
        raise HTTPException(status_code=404, detail=f"No forex data for {from_currency}/{to_currency}")

    return {
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
