from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from typing import List
import asyncio

app = FastAPI(title="StockVision API")

# Allow all origins (เพื่อให้ HTML เรียกได้)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "StockVision API is running 🚀"}

@app.get("/price/{symbol}")
def get_price(symbol: str):
    """ดึงราคาหุ้นตัวเดียว"""
    try:
        ticker = yf.Ticker(symbol.upper())
        info = ticker.fast_info
        hist = ticker.history(period="2d")

        if hist.empty:
            return {"error": f"Symbol {symbol} not found"}

        price = round(float(hist["Close"].iloc[-1]), 2)
        prev  = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else price
        chg_amt = round(price - prev, 2)
        chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0

        return {
            "symbol":   symbol.upper(),
            "price":    price,
            "prev":     prev,
            "change":   chg_amt,
            "changePct": chg_pct,
            "currency": "USD",
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/prices")
def get_prices(symbols: str):
    """ดึงราคาหลายตัวพร้อมกัน  ?symbols=AAPL,NVDA,VOO"""
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
                "symbol":    sym,
                "price":     price,
                "changePct": chg_pct,
                "change":    round(price - prev, 2),
            }
        except Exception as e:
            results[sym] = {"error": str(e)}

    return results


@app.get("/history/{symbol}")
def get_history(symbol: str, period: str = "1mo"):
    """
    ดึงประวัติราคา
    period: 1mo | 6mo | ytd | 1y | 5y
    """
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
