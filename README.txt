Fundamental analysis checklist - Yahoo Finance edition

1. Install Python 3.9+ and run once:   pip install yfinance pandas
2. In this folder run:                 python server.py
3. Open in your browser:               http://localhost:8000
4. Type a company name or ticker (Indian stocks: RELIANCE.NS / .BO) and click Load.

Keep the terminal window open while you use the page; Ctrl+C stops it.
Data: Yahoo Finance via the unofficial yfinance library, plus Screener.in's public
company page for Indian tickers (.NS/.BO): 5-year sales/profit CAGR and promoter
holding. Personal/research use - check each site's terms before sharing widely.
Still manual: promoter pledging (from the NSE/BSE shareholding pattern), and 5-year
CAGRs for non-Indian stocks. Companies with no inventory line get Quick ratio =
Current ratio and Inventory days = 0, flagged "verify" in the Source column.

INSTALL ON ANDROID
The page is an installable web app (PWA). Chrome on Android only installs it
fully when it is served over HTTPS or from localhost on the phone itself:
 A) Host server.py on an HTTPS web host (see the deployment notes; set HOST=0.0.0.0),
    open the URL in Chrome on the phone, tap "Install app" (or menu > Install app).
    Optional: paste that URL into pwabuilder.com to generate an Android package (.apk/.aab).
 B) Run it on the phone with Termux: install Python + yfinance + pandas in Termux,
    run "python server.py", open http://localhost:8000 in Chrome, tap "Install app".
    Termux must stay running while you use the app.
Opening it from another computer's address (http://192.168.x.x:8000) only gives a
browser shortcut, not a full install.
