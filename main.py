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

def get_cache(key, ttl=300):
    if key in _cache:
        val, ts = _cache[key]
        if _time.time() - ts < ttl:
            return val
    return None

def set_cache(key, val):
    # cleanup เก่าถ้า cache ใหญ่เกิน 500 keys
    if len(_cache) > 500:
        now = _time.time()
        old = [k for k,(v,t) in _cache.items() if now - t > 3600]
        for k in old:
            _cache.pop(k, None)
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
    # cache 5 นาที — ประหยัด quota
    cached = get_cache(f"p_{sym}", ttl=300)
    if cached:
        return cached
    try:
        data = await td_get("/quote", {"symbol": sym})
        if data.get("status") == "error":
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
            "is_market_open": data.get("is_market_open", False),
        }
        set_cache(f"p_{sym}", result)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/prices")
async def get_prices(symbols: str):
    """ดึงราคาหลายตัวพร้อมกัน — ใช้ batch API = 1 call แทน N calls"""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:20]  # จำกัด 20 ตัว
    results = {}
    uncached = []

    for s in sym_list:
        c = get_cache(f"p_{s}", ttl=300)
        if c:
            results[s] = c
        else:
            uncached.append(s)

    if uncached:
        try:
            # Twelve Data batch quote — 1 API call สำหรับทุกตัว
            data = await td_get("/quote", {"symbol": ",".join(uncached)})

            # ถ้าตัวเดียวจะได้ dict, หลายตัวจะได้ dict of dicts
            if len(uncached) == 1:
                items = {uncached[0]: data}
            else:
                items = data if isinstance(data, dict) else {}

            for sym, d in items.items():
                sym = sym.upper()
                if not isinstance(d, dict) or d.get("status") == "error":
                    results[sym] = {"error": d.get("message", "not found") if isinstance(d, dict) else "error"}
                    continue
                try:
                    price = round(float(d["close"]), 2)
                    prev = round(float(d["previous_close"]), 2)
                    change = round(price - prev, 2)
                    chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
                    res = {
                        "symbol": sym,
                        "price": price,
                        "changePct": chg_pct,
                        "change": change,
                        "is_market_open": d.get("is_market_open", False),
                    }
                    set_cache(f"p_{sym}", res)
                    results[sym] = res
                except Exception:
                    results[sym] = {"error": "parse error"}
        except Exception as e:
            for sym in uncached:
                results[sym] = {"error": str(e)}

    return results


@app.get("/history/{symbol}")
async def get_history(symbol: str, period: str = "1M"):
    sym = symbol.upper()
    cache_key = f"h_{sym}_{period}"
    # history cache 1 ชั่วโมง
    cached = get_cache(cache_key, ttl=3600)
    if cached:
        return cached
    try:
        period_map = {
            "1M":  ("1day",  30),
            "6M":  ("1day",  180),
            "YTD": ("1day",  365),
            "1Y":  ("1day",  365),
            "5Y":  ("1week", 260),
        }
        interval, outputsize = period_map.get(period.upper(), ("1day", 30))
        data = await td_get("/time_series", {
            "symbol": sym,
            "interval": interval,
            "outputsize": outputsize,
            "order": "ASC",
        })
        if data.get("status") == "error":
            return {"error": data.get("message", "No data")}
        values = data.get("values", [])
        chart_data = [
            {
                "date":  v["datetime"],
                "close": round(float(v["close"]), 2),
                "high":  round(float(v["high"]), 2),
                "low":   round(float(v["low"]), 2),
                "open":  round(float(v["open"]), 2),
            }
            for v in values
        ]
        result = {"symbol": sym, "period": period, "data": chart_data}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/news/{symbol}")
async def get_news(symbol: str, name: str = ""):
    cache_key = f"news_{symbol.upper()}"
    # news cache 30 นาที
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
