from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import httpx
import threading
import urllib.request
import time as _time

NEWS_API_KEY = "3d7fe42a10054f6ea8e05d93dc4348c7"

app = FastAPI(title="StockVision API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "StockVision API is running 🚀"}

@app.get("/ping")
def ping():
    return {"pong": True}

@app.get("/price/{symbol}")
def get_price(symbol: str):
    try:
        hist = yf.Ticker(symbol.upper()).history(period="2d")
        if hist.empty:
            return {"error": f"Symbol {symbol} not found"}
        price = round(float(hist["Close"].iloc[-1]), 2)
        prev  = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
        chg_amt = round(price - prev, 2)
        chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
        return {
            "symbol": symbol.upper(),
            "price": price,
            "prev": prev,
            "change": chg_amt,
            "changePct": chg_pct,
            "currency": "USD",
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/prices")
def get_prices(symbols: str):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = {}
    tickers = yf.Tickers(" ".join(sym_list))
    for sym in sym_list:
        try:
            hist = tickers.tickers[sym].history(period="2d")
            if hist.empty:
                results[sym] = {"error": "not found"}
                continue
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev  = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
            chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
            results[sym] = {
                "symbol": sym,
                "price": price,
                "changePct": chg_pct,
                "change": round(price - prev, 2),
            }
        except Exception as e:
            results[sym] = {"error": str(e)}
    return results


@app.get("/history/{symbol}")
def get_history(symbol: str, period: str = "1mo"):
    try:
        period_map = {
            "1M": "1mo", "6M": "6mo", "YTD": "ytd",
            "1Y": "1y",  "5Y": "5y"
        }
        yf_period = period_map.get(period.upper(), period)
        hist = yf.Ticker(symbol.upper()).history(period=yf_period)
        if hist.empty:
            return {"error": "No data"}
        data = [
            {"date": str(d.date()), "close": round(float(c), 2)}
            for d, c in zip(hist.index, hist["Close"])
        ]
        return {"symbol": symbol.upper(), "period": period, "data": data}
    except Exception as e:
        return {"error": str(e)}


@app.get("/news/{symbol}")
async def get_news(symbol: str, name: str = ""):
    """ดึงข่าวหุ้นจาก NewsAPI (เรียกจาก server เพื่อหลีกเลี่ยง CORS)"""
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


# Keep-alive: ping ตัวเองทุก 4 นาที
def _self_ping():
    _time.sleep(60)
    while True:
        try:
            urllib.request.urlopen(
                "https://stockvision-api-ol23.onrender.com/ping",
                timeout=10
            )
            print("ping OK", flush=True)
        except Exception as e:
            print(f"ping failed: {e}", flush=True)
        _time.sleep(4 * 60)


threading.Thread(target=_self_ping, daemon=True).start()
