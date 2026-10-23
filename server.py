"""
Fundamental analysis checklist - local Yahoo Finance helper.

Run:   pip install yfinance pandas
       python server.py
Open:  http://localhost:8000

Serves index.html and two JSON endpoints the page calls:
  /api/search?q=infosys          -> matching tickers
  /api/fundamentals?symbol=INFY.NS -> profile + annual statements
Data comes from Yahoo Finance through the unofficial yfinance library
(intended for personal/research use under Yahoo's terms).
"""
import json
import math
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8000"))
# 127.0.0.1 = only this computer. On a server/cloud host set HOST=0.0.0.0.
HOST = os.environ.get("HOST", "127.0.0.1")


def clean(v):
    """Turn pandas/numpy values into plain JSON numbers; NaN/inf -> None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def row(df, col, names):
    """First available line item (by Yahoo row name) for one statement column."""
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            val = clean(df.at[n, col])
            if val is not None:
                return val
    return None


# Yahoo line-item names, with fallbacks. Output keys match what the page expects.
INCOME = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "costOfRevenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "operatingIncome": ["Operating Income", "Total Operating Income As Reported"],
    "ebit": ["EBIT"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "netIncome": ["Net Income", "Net Income Common Stockholders",
                  "Net Income From Continuing Operation Net Minority Interest"],
    "epsDiluted": ["Diluted EPS", "Basic EPS"],
    "interestExpense": ["Interest Expense", "Interest Expense Non Operating"],
    "incomeBeforeTax": ["Pretax Income"],
    "incomeTaxExpense": ["Tax Provision"],
}
BALANCE = {
    "totalAssets": ["Total Assets"],
    "totalCurrentAssets": ["Current Assets"],
    "totalCurrentLiabilities": ["Current Liabilities"],
    "inventory": ["Inventory"],
    "netReceivables": ["Accounts Receivable", "Receivables", "Gross Accounts Receivable"],
    "totalDebt": ["Total Debt"],
    "cashAndCashEquivalents": ["Cash And Cash Equivalents",
                               "Cash Cash Equivalents And Short Term Investments"],
    "totalStockholdersEquity": ["Stockholders Equity", "Common Stock Equity",
                                "Total Equity Gross Minority Interest"],
}
CASHFLOW = {
    "operatingCashFlow": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capitalExpenditure": ["Capital Expenditure", "Purchase Of PPE"],
    "commonDividendsPaid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
}


def statement(df, mapping, currency):
    """DataFrame (rows = line items, columns = period end dates) -> newest-first list."""
    out = []
    if df is None or df.empty:
        return out
    for col in sorted(df.columns, reverse=True):
        rec = {k: row(df, col, names) for k, names in mapping.items()}
        if all(v is None for v in rec.values()):
            continue
        if rec.get("interestExpense") is not None:
            rec["interestExpense"] = abs(rec["interestExpense"])
        d = str(col)[:10]
        rec.update({"date": d, "fiscalYear": d[:4], "reportedCurrency": currency})
        out.append(rec)
    return out


def fundamentals(symbol):
    t = yf.Ticker(symbol)
    errors = []
    info = {}
    try:
        info = t.info or {}
    except Exception as e:  # noqa: BLE001
        errors.append(f"profile: {e}")

    fin_cur = info.get("financialCurrency") or info.get("currency")
    profile = {
        "symbol": symbol,
        "companyName": info.get("longName") or info.get("shortName"),
        "price": clean(info.get("currentPrice") or info.get("regularMarketPrice")),
        "marketCap": clean(info.get("marketCap")),
        "currency": info.get("currency"),
        "exchange": info.get("fullExchangeName") or info.get("exchange"),
    }

    def safe(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            return None

    inc = safe("income statement", lambda: t.income_stmt)
    bal = safe("balance sheet", lambda: t.balance_sheet)
    cf = safe("cash flow", lambda: t.cashflow)

    return {
        "source": "Yahoo Finance (via yfinance)",
        "profile": [profile] if profile["companyName"] or profile["price"] else [],
        "income": statement(inc, INCOME, fin_cur),
        "balance": statement(bal, BALANCE, fin_cur),
        "cashflow": statement(cf, CASHFLOW, fin_cur),
        "errors": errors,
    }


def search(q):
    hits = []
    try:
        res = yf.Search(q, max_results=10, news_count=0)
        for h in res.quotes or []:
            if h.get("quoteType") in (None, "EQUITY") and h.get("symbol"):
                hits.append({
                    "symbol": h["symbol"],
                    "name": h.get("longname") or h.get("shortname") or "",
                    "exchange": h.get("exchDisp") or h.get("exchange") or "",
                })
    except Exception:  # noqa: BLE001 - older yfinance without Search, or lookup failure
        pass
    if not hits:  # fall back to treating the query as a ticker
        hits.append({"symbol": q.upper(), "name": "", "exchange": ""})
    return hits


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path == "/api/search":
                q = (qs.get("q") or [""])[0].strip()
                return self.send_json(search(q) if q else [])
            if u.path == "/api/fundamentals":
                s = (qs.get("symbol") or [""])[0].strip()
                if not s:
                    return self.send_json({"error": "symbol is required"}, 400)
                return self.send_json(fundamentals(s))
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 502)
        if u.path == "/":
            self.path = "/index.html"
        return super().do_GET()


if __name__ == "__main__":
    print(f"Checklist running on {HOST}:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
