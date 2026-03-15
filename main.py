from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import threading
import urllib.request
import time as _time
from datetime import datetime, timedelta

AV_KEY = "TR15H1ZZCCT2AVVO"
NEWS_API_KEY = "3d7fe42a10054f6ea8e05d93dc4348c7"

app = FastAPI(title="StockVision API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory cache ──────────────────────────
_cache = {}
CACHE_TTL = 60  # seconds

def get_cache(key):
    if key in _cache:
        val, ts = _cache[key]
        if _time.time() - ts < CACHE_TTL:
            return val
    return None

def set_cache(key, val):
    _cache[key] = (val, _time.time())


@app.get("/")
def root():
    return {"status": "ok", "message": "StockVision API is running 🚀"}


@app.get("/ping")
def ping():
    return {"pong": True}


@app.get("/price/{symbol}")
async def get_price(symbol: str):
    sym = symbol.upper()
    cached = get_cache(f"price_{sym}")
    if cached:
        return cached

    try:
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=GLOBAL_QUOTE"
            f"&symbol={sym}"
            f"&apikey={AV_KEY}"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            data = r.json()

        q = data.get("Global Quote", {})
        if not q or not q.get("05. price"):
            return {"error": f"Symbol {sym} not found"}

        price = round(float(q["05. price"]), 2)
        prev = round(float(q["08. previous close"]), 2)
        chg_amt = round(float(q["09. change"]), 2)
        chg_pct = round(float(q["10. change percent"].replace("%", "")), 2)

        result = {
            "symbol": sym,
            "price": price,
            "prev": prev,
            "change": chg_amt,
            "changePct": chg_pct,
            "currency": "USD",
        }
        set_cache(f"price_{sym}", result)
        return result

    except Exception as e:
        return {"error": str(e)}


@app.get("/prices")
async def get_prices(symbols: str):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = {}

    async with httpx.AsyncClient(timeout=15) as client:
        for sym in sym_list:
            cached = get_cache(f"price_{sym}")
            if cached:
                results[sym] = cached
                continue
            try:
                url = (
                    f"https://www.alphavantage.co/query"
                    f"?function=GLOBAL_QUOTE"
                    f"&symbol={sym}"
                    f"&apikey={AV_KEY}"
                )
                r = await client.get(url)
                data = r.json()
                q = data.get("Global Quote", {})
                if not q or not q.get("05. price"):
                    results[sym] = {"error": "not found"}
                    continue
                price = round(float(q["05. price"]), 2)
                prev = round(float(q["08. previous close"]), 2)
                chg_pct = round(float(q["10. change percent"].replace("%", "")), 2)
                res = {
                    "symbol": sym,
                    "price": price,
                    "changePct": chg_pct,
                    "change": round(price - prev, 2),
                }
                set_cache(f"price_{sym}", res)
                results[sym] = res
                _time.sleep(0.5)  # หลีกเลี่ยง rate limit
            except Exception as e:
                results[sym] = {"error": str(e)}

    return results


@app.get("/history/{symbol}")
async def get_history(symbol: str, period: str = "1M"):
    sym = symbol.upper()
    cache_key = f"hist_{sym}_{period}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    try:
        # Alpha Vantage: daily adjusted
        outputsize = "compact" if period in ["1M", "6M"] else "full"
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=TIME_SERIES_DAILY"
            f"&symbol={sym}"
            f"&outputsize={outputsize}"
            f"&apikey={AV_KEY}"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            data = r.json()

        ts = data.get("Time Series (Daily)", {})
        if not ts:
            return {"error": "No data"}

        # Filter by period
        now = datetime.now()
        period_days = {
            "1M": 30, "6M": 180, "YTD": (now - datetime(now.year, 1, 1)).days,
            "1Y": 365, "5Y": 365 * 5
        }
        days = period_days.get(period.upper(), 30)
        cutoff = now - timedelta(days=days)

        data_list = []
        for date_str, vals in sorted(ts.items()):
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if date >= cutoff:
                data_list.append({
                    "date": date_str,
                    "close": round(float(vals["4. close"]), 2)
                })

        result = {"symbol": sym, "period": period, "data": data_list}
        set_cache(cache_key, result)
        return result

    except Exception as e:
        return {"error": str(e)}


@app.get("/news/{symbol}")
async def get_news(symbol: str, name: str = ""):
    try:
        query = f"{symbol} {name} stock".strip()
        url = (
            f"https://newsapi.org/v2/everything"
            f"?q={query}"
            f"&language=en"
            f"&sortBy=publishedAt"
            f"&pageSize=10"
            f"&apiKey={NEWS_API_KEY}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            data = r.json()

        if data.get("status") == "ok":
            articles = []
            for a in data.get("articles", []):
                articles.append({
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "url": a.get("url", ""),
                    "urlToImage": a.get("urlToImage", ""),
                    "publishedAt": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", ""),
                })
            return {"symbol": symbol.upper(), "articles": articles}
        else:
            return {"error": data.get("message", "NewsAPI error"), "articles": []}
    except Exception as e:
        return {"error": str(e), "articles": []}


# Keep-alive
def _self_ping():
    _time.sleep(60)
    while True:
        try:
            urllib.request.urlopen(
                "https://stockvision-api-ol23.onrender.com/ping", timeout=10
            )
            print("ping OK", flush=True)
        except Exception as e:
            print(f"ping failed: {e}", flush=True)
        _time.sleep(4 * 60)


threading.Thread(target=_self_ping, daemon=True).start()
