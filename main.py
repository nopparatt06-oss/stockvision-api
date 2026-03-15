from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import threading
import urllib.request
import time as _time

TWELVE_API_KEY = "c60bcea00e8a477783a8ac81cd5ba1cc"
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


# ── Twelve Data helper ───────────────────────
async def td_get(path: str, params: dict):
    params["apikey"] = TWELVE_API_KEY
    url = f"https://api.twelvedata.com{path}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        return r.json()


@app.get("/")
def root():
    return {"status": "ok", "message": "StockVision API is running 🚀"}


@app.get("/ping")
def ping():
    return {"pong": True}


@app.get("/price/{symbol}")
async def get_price(symbol: str):
    sym = symbol.upper()
    cached = get_cache(f"p_{sym}", ttl=600)
    if cached:
        return cached
    try:
        data = await td_get("/quote", {"symbol": sym})
        if data.get("status") == "error" or "code" in data:
            return {"error": data.get("message", "Symbol not found")}
        price = round(float(data["close"]), 2)
        prev = round(float(data["previous_close"]), 2)
        change = round(price - prev, 2)
        chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
        result = {
            "symbol": sym,
            "price": price,
            "prev": prev,
            "change": change,
            "changePct": chg_pct,
            "currency": data.get("currency", "USD"),
        }
        set_cache(f"p_{sym}", result)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/prices")
async def get_prices(symbols: str):
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
            data = await td_get("/quote", {"symbol": sym})
            if data.get("status") == "error" or "code" in data:
                results[sym] = {"error": data.get("message", "not found")}
                continue
            price = round(float(data["close"]), 2)
            prev = round(float(data["previous_close"]), 2)
            change = round(price - prev, 2)
            chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
            res = {"symbol": sym, "price": price, "changePct": chg_pct, "change": change}
            set_cache(f"p_{sym}", res)
            results[sym] = res
        except Exception as e:
            results[sym] = {"error": str(e)}
    return results


@app.get("/history/{symbol}")
async def get_history(symbol: str, period: str = "1M"):
    sym = symbol.upper()
    cache_key = f"h_{sym}_{period}"
    cached = get_cache(cache_key, ttl=3600)
    if cached:
        return cached
    try:
        period_map = {
            "1M": (365, "1month"),
            "6M": (180, "6month"),
            "YTD": (365, "ytd"),
            "1Y": (365, "1year"),
            "5Y": (260, "5year"),
        }
        outputsize, _ = period_map.get(period.upper(), (30, "1month"))
        interval = "1week" if period.upper() == "5Y" else "1day"
        data = await td_get("/time_series", {
            "symbol": sym,
            "interval": interval,
            "outputsize": outputsize,
            "order": "ASC",
        })
        if data.get("status") == "error" or "code" in data:
            return {"error": data.get("message", "No data")}
        values = data.get("values", [])
        chart_data = [{"date": v["datetime"], "close": round(float(v["close"]), 2)} for v in values]
        result = {"symbol": sym, "period": period, "data": chart_data}
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
