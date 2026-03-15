from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import httpx
import requests
import threading
import urllib.request
import time as _time
import random

NEWS_API_KEY = "3d7fe42a10054f6ea8e05d93dc4348c7"

app = FastAPI(title="StockVision API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Cache ────────────────────────────────────
_cache = {}

def get_cache(key, ttl=600):
    if key in _cache:
        val, ts = _cache[key]
        if _time.time() - ts < ttl:
            return val
    return None

def set_cache(key, val):
    _cache[key] = (val, _time.time())


def fetch_yf(sym, period="2d", retries=3):
    for i in range(retries):
        try:
            _time.sleep(random.uniform(1.0, 2.5))
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            })
            ticker = yf.Ticker(sym, session=session)
            hist = ticker.history(period=period)
            if not hist.empty:
                return hist
        except Exception as e:
            if i < retries - 1:
                _time.sleep(2 ** i)
            else:
                raise e
    return None


@app.get("/")
def root():
    return {"status": "ok", "message": "StockVision API is running 🚀"}


@app.get("/ping")
def ping():
    return {"pong": True}


@app.get("/price/{symbol}")
def get_price(symbol: str):
    sym = symbol.upper()
    cached = get_cache(f"p_{sym}", ttl=600)
    if cached:
        return cached
    try:
        hist = fetch_yf(sym, "2d")
        if hist is None or hist.empty:
            return {"error": f"Symbol {sym} not found"}
        price = round(float(hist["Close"].iloc[-1]), 2)
        prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
        chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
        result = {
            "symbol": sym,
            "price": price,
            "prev": prev,
            "change": round(price - prev, 2),
            "changePct": chg_pct,
            "currency": "USD",
        }
        set_cache(f"p_{sym}", result)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/prices")
def get_prices(symbols: str):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = {}
    uncached = []
    for s in sym_list:
        c = get_cache(f"p_{s}", ttl=600)
        if c:
            results[s] = c
        else:
            uncached.append(s)
    for sym in uncached:
        try:
            hist = fetch_yf(sym, "2d")
            if hist is None or hist.empty:
                results[sym] = {"error": "not found"}
                continue
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
            res = {"symbol": sym, "price": price, "changePct": chg_pct, "change": round(price - prev, 2)}
            set_cache(f"p_{sym}", res)
            results[sym] = res
        except Exception as e:
            results[sym] = {"error": str(e)}
    return results


@app.get("/history/{symbol}")
def get_history(symbol: str, period: str = "1M"):
    sym = symbol.upper()
    cache_key = f"h_{sym}_{period}"
    cached = get_cache(cache_key, ttl=3600)
    if cached:
        return cached
    try:
        period_map = {"1M": "1mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y", "5Y": "5y"}
        yf_period = period_map.get(period.upper(), "1mo")
        hist = fetch_yf(sym, yf_period)
        if hist is None or hist.empty:
            return {"error": "No data"}
        data = [{"date": str(d.date()), "close": round(float(c), 2)} for d, c in zip(hist.index, hist["Close"])]
        result = {"symbol": sym, "period": period, "data": data}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/news/{symbol}")
async def get_news(symbol: str, name: str = ""):
    cache_key = f"news_{symbol.upper()}"
    cached = get_cache(cache_key, ttl=1800)
    if cached:
        return cached
    try:
        query = f"{symbol} {name} stock".strip()
        url = f"https://newsapi.org/v2/everything?q={query}&language=en&sortBy=publishedAt&pageSize=8&apiKey={NEWS_API_KEY}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            data = r.json()
        if data.get("status") == "ok":
            articles = [
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "url": a.get("url", ""),
                    "urlToImage": a.get("urlToImage", ""),
                    "publishedAt": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", "")
                }
                for a in data.get("articles", [])
            ]
            result = {"symbol": symbol.upper(), "articles": articles}
            set_cache(cache_key, result)
            return result
        return {"error": data.get("message", "NewsAPI error"), "articles": []}
    except Exception as e:
        return {"error": str(e), "articles": []}


# Keep-alive
def _self_ping():
    _time.sleep(60)
    while True:
        try:
            urllib.request.urlopen("https://stockvision-api-ol23.onrender.com/ping", timeout=10)
            print("ping OK", flush=True)
        except Exception as e:
            print(f"ping failed: {e}", flush=True)
        _time.sleep(4 * 60)

threading.Thread(target=_self_ping, daemon=True).start()
