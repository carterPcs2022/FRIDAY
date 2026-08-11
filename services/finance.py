"""services/finance.py — market data (stocks via yfinance/Yahoo fallback,
crypto via CoinGecko) and a finance brief. Ported from JARVIS_V5's
services/finance.py, scoped down: JARVIS's version also does Plaid-based
bank-account linking, transaction categorization, subscription detection,
and bill-due prediction — all of that needs a real Plaid OAuth bank-link
flow FRIDAY has no equivalent of, and would be a much bigger, separate
undertaking. FRIDAY already has manual bill tracking via
core/friday_bills.py (add_bill/get_bills), which finance_brief() folds in
instead of trying to auto-detect subscriptions from bank transactions
she doesn't have access to.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    _requests = None


class FinanceIntelligence:

    def get_stock_price(self, symbol: str) -> dict:
        """Current stock price via yfinance, falling back to Yahoo
        Finance's JSON chart endpoint if yfinance isn't installed/fails."""
        symbol = symbol.upper().strip()

        if YFINANCE_AVAILABLE:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)
                if price is not None:
                    change = (price - prev_close) if prev_close else 0.0
                    change_pct = (change / prev_close * 100) if prev_close else 0.0
                    return {
                        "symbol": symbol, "price": round(float(price), 2),
                        "change": round(float(change), 2), "change_pct": round(float(change_pct), 2),
                        "previous_close": round(float(prev_close), 2) if prev_close else None,
                        "source": "yfinance",
                    }
            except Exception as e:
                logger.warning(f"yfinance failed for {symbol}: {e}")

        if REQUESTS_AVAILABLE:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
                resp = _requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice", 0.0)
                prev_close = meta.get("previousClose", price)
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                return {
                    "symbol": symbol, "price": round(float(price), 2),
                    "change": round(float(change), 2), "change_pct": round(float(change_pct), 2),
                    "previous_close": round(float(prev_close), 2), "source": "yahoo_finance_api",
                }
            except Exception as e:
                logger.error(f"Yahoo Finance fallback failed for {symbol}: {e}")
                return {"symbol": symbol, "price": None, "change": None, "change_pct": None, "error": str(e)}

        return {"symbol": symbol, "price": None, "change": None, "change_pct": None,
                "error": "No market data source available (install yfinance or requests)."}

    def portfolio_check(self, symbols: list) -> dict:
        """Quick multi-symbol check, capped at 10 to bound how many
        network calls one request can trigger."""
        portfolio = {symbol: self.get_stock_price(symbol) for symbol in symbols[:10]}
        return {"portfolio": portfolio, "ts": datetime.now().isoformat()}

    def crypto_prices(self, coins: list) -> dict:
        """coins: CoinGecko IDs, e.g. ["bitcoin", "ethereum", "solana"]."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests library not installed", "coins": {}}

        ids_str = ",".join(coins)
        url = (f"https://api.coingecko.com/api/v3/simple/price"
               f"?ids={ids_str}&vs_currencies=usd,btc&include_24hr_change=true")
        try:
            resp = _requests.get(url, timeout=10, headers={"Accept": "application/json"})
            resp.raise_for_status()
            raw = resp.json()
            result = {
                coin_id: {
                    "usd": data.get("usd"), "btc": data.get("btc"),
                    "usd_24h_change": round(data.get("usd_24h_change", 0.0), 2),
                    "btc_24h_change": round(data.get("btc_24h_change", 0.0), 2),
                }
                for coin_id, data in raw.items()
            }
            return {"status": "ok", "coins": result, "as_of": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"CoinGecko API error: {e}")
            return {"status": "error", "message": str(e), "coins": {}}

    def finance_brief(self, symbols: list | None = None) -> str:
        """LLM finance summary combining a quick portfolio check with
        FRIDAY's existing manually-tracked bills (core/friday_bills.py) —
        no bank-linked spending data available without Plaid."""
        from core.friday_brain import friday_brain, MODELS

        parts = []
        if symbols:
            portfolio = self.portfolio_check(symbols)
            parts.append(f"Portfolio: {portfolio['portfolio']}")

        try:
            from core.friday_bills import get_bills
            bills = get_bills()
            if bills:
                parts.append(f"Tracked bills: {bills}")
        except Exception:
            pass

        if not parts:
            return "No financial data to brief yet, boss — track a bill or ask about a stock first."

        prompt = ("Generate a concise financial briefing in FRIDAY's warm, direct style. "
                  "Highlight anything notable. Keep it under 150 words.\n\n" + "\n".join(parts))
        result = friday_brain._call_anthropic(
            [{"role": "user", "content": prompt}],
            "You are FRIDAY, a helpful personal assistant.", MODELS["nuanced"], max_tokens=400,
        )
        return result["content"] if result else "Couldn't generate the brief right now, boss."


finance = FinanceIntelligence()
