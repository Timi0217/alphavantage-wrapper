import os
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
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


@app.get("/")
async def root():
    return {
        "name": "Alpha Vantage Wrapper",
        "description": "Technical indicators (RSI, MACD, SMA, EMA, BBANDS), stock quotes, intraday data, and forex from Alpha Vantage",
        "endpoints": [
            {"path": "/quote?symbol=AAPL", "description": "Get current stock quote"},
            {"path": "/technical?symbol=AAPL&indicator=RSI", "description": "Get technical indicator"},
            {"path": "/intraday?symbol=AAPL&interval=5min", "description": "Get intraday prices"},
            {"path": "/daily?symbol=AAPL", "description": "Get daily price history"},
            {"path": "/forex?from_currency=USD&to_currency=EUR", "description": "Get forex exchange rate"},
            {"path": "/search?keywords=apple", "description": "Search for symbols"},
            {"path": "/health", "description": "Health check"},
        ],
    }


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
