"""
DGJG Gold Rate API
------------------
Scrapes the Dubai Jewellery Group's "Today's Suggested Retail Gold Jewellery
Price" from dubaicityofgold.com (server-side, so no browser CORS issue) and
serves it as a small JSON API with CORS enabled, so the Gold Buying Assistant
web tool can fetch it directly.

Deploy this on Render (or Railway/Fly/PythonAnywhere) exactly like your other
Flask tools (PAC, Product Health Monitor). Free tier is enough.

Endpoints:
  GET /                -> health check
  GET /api/gold-rate    -> {"rates": {"24K": 488.5, "22K": 452.25, ...},
                            "currency": "AED", "unit": "gram",
                            "source": "...", "fetched_at": "...", "cached": bool}
"""

import re
import time
import logging

from flask import Flask, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)  # allow the static HTML tool (any origin, incl. file://) to fetch this

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dgjg-rate-api")

SOURCE_URL = "https://dubaicityofgold.com/"
CACHE_TTL_SECONDS = 10 * 60  # re-scrape at most every 10 minutes — be a polite scraper
REQUEST_TIMEOUT = 10

KARATS = ["24", "22", "21", "18", "14"]

_cache = {"data": None, "ts": 0}


def scrape_dgjg_rates():
    """Fetch dubaicityofgold.com and extract the 5 karat rates in AED/gram."""
    resp = requests.get(
        SOURCE_URL,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; GoldBuyingAssistant/1.0; "
                "personal-use rate fetcher)"
            )
        },
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(separator=" "))

    rates = {}
    for karat in KARATS:
        # Page text reads like: "24K Gold AED 488.50"
        match = re.search(rf"{karat}K\s*Gold\s*AED\s*([\d,]+\.\d{{2}})", text, re.IGNORECASE)
        if match:
            rates[f"{karat}K"] = float(match.group(1).replace(",", ""))

    if len(rates) < 5:
        raise ValueError(f"Only found {len(rates)}/5 rates on the page: {rates}")

    return rates


@app.route("/")
def health():
    return jsonify({"status": "ok", "endpoint": "/api/gold-rate"})


@app.route("/api/gold-rate")
def gold_rate():
    now = time.time()

    # Serve from cache if fresh
    if _cache["data"] and (now - _cache["ts"] < CACHE_TTL_SECONDS):
        return jsonify({**_cache["data"], "cached": True})

    try:
        rates = scrape_dgjg_rates()
        payload = {
            "rates": rates,
            "currency": "AED",
            "unit": "gram",
            "source": "Dubai Jewellery Group (dubaicityofgold.com)",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }
        _cache["data"] = payload
        _cache["ts"] = now
        return jsonify({**payload, "cached": False})

    except Exception as exc:  # noqa: BLE001 - want to always return JSON, never crash
        logger.warning("Scrape failed: %s", exc)
        # Serve stale cache if we have one, rather than failing outright
        if _cache["data"]:
            return jsonify({**_cache["data"], "cached": True, "warning": str(exc)})
        return jsonify({"error": "Could not fetch gold rate", "detail": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
