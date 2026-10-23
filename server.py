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
        "screener": safe("screener.in", lambda: screener(symbol)) or {},
        "errors": errors,
    }


# ---------- Screener.in (Indian stocks): 5Y growth + promoter holding ----------
import re
import urllib.request
from html.parser import HTMLParser


class _Tables(HTMLParser):
    """Collects every <table> as rows of cell text, tagged with its <section id>."""

    def __init__(self):
        super().__init__()
        self.section, self.tables = None, []
        self._t = self._r = self._c = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and a.get("id"):
            self.section = a["id"]
        elif tag == "table":
            self._t = {"section": self.section, "rows": []}
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None:
            self._r.append(re.sub(r"\s+", " ", "".join(self._c)).strip())
            self._c = None
        elif tag == "tr" and self._r is not None:
            if self._r:
                self._t["rows"].append(self._r)
            self._r = None
        elif tag == "table" and self._t is not None:
            self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._c is not None:
            self._c.append(data)


def _num(s):
    s = (s or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _find(tables, section, label):
    """(header_row, data_row) for the first row whose label starts with `label`."""
    for t in tables:
        if t["section"] != section or not t["rows"]:
            continue
        for r in t["rows"][1:]:
            if r and r[0].lower().startswith(label.lower()):
                return t["rows"][0], r
    return None, None


def _cagr5(header, row):
    """5-year CAGR from the last full fiscal-year column (TTM excluded)."""
    cols = [(h, _num(v)) for h, v in zip(header[1:], row[1:]) if h and h.upper() != "TTM"]
    cols = [c for c in cols if c[1] is not None]
    if len(cols) < 6:
        return None
    (end_lbl, end), (start_lbl, start) = cols[-1], cols[-6]
    if end <= 0 or start <= 0:
        return {"v": None, "why": f"Loss or zero in {start_lbl}/{end_lbl}: CAGR not meaningful"}
    return {"v": ((end / start) ** 0.2 - 1) * 100, "period": f"{start_lbl} → {end_lbl}"}


def screener(symbol):
    if not symbol.upper().endswith((".NS", ".BO")):
        return {}
    code = symbol.rsplit(".", 1)[0].upper()
    for view in ("consolidated/", ""):
        url = f"https://www.screener.in/company/{code}/{view}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (checklist helper)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        p = _Tables()
        p.feed(html)
        hdr, sales = _find(p.tables, "profit-loss", "Sales")
        if not sales:
            hdr, sales = _find(p.tables, "profit-loss", "Revenue")  # banks
        _, profit = _find(p.tables, "profit-loss", "Net Profit")
        if not sales and not profit:
            continue  # e.g. consolidated view empty -> try standalone
        out = {"url": url, "view": "consolidated" if view else "standalone"}
        if sales:
            out["revenueCagr5"] = _cagr5(hdr, sales)
        if profit:
            out["profitCagr5"] = _cagr5(hdr, profit)
        sh_hdr, prom = _find(p.tables, "shareholding", "Promoters")
        if prom:
            vals = [(h, _num(v)) for h, v in zip(sh_hdr[1:], prom[1:]) if _num(v) is not None]
            if vals:
                out["promoterHolding"] = {"v": vals[-1][1], "period": vals[-1][0]}
        return out
    return {"error": f"Screener.in page not found for {code}"}


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
