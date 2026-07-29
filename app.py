"""
Gold Rate API
-------------
Scrapes UAE (Dubai Jewellery Group, dubaicityofgold.com) and India (Malabar
Gold & Diamonds GraphQL) gold rates server-side, so no browser CORS issue,
and serves them as small JSON APIs with CORS enabled for the Gold Buying
Assistant web tool to fetch directly.

Deploy this on Render (or Railway/Fly/PythonAnywhere) exactly like your other
Flask tools (PAC, Product Health Monitor). Free tier is enough.

Endpoints:
  GET /                      -> health check
  GET /api/gold-rate          -> UAE (DGJG) rates
                                 {"rates": {"24K": 488.5, "22K": 452.25, ...},
                                  "currency": "AED", "unit": "gram",
                                  "source": "...", "fetched_at": "...", "cached": bool}
  GET /api/gold-rate-india    -> India (Malabar) rates, 22K & 24K only
                                 {"rates": {"22K": 13155.0, "24K": 14351.0},
                                  "currency": "INR", "unit": "gram",
                                  "source": "...", "entry_date": "...",
                                  "fetched_at": "...", "cached": bool}
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
logger = logging.getLogger("gold-rate-api")

REQUEST_TIMEOUT = 10
CACHE_TTL_SECONDS = 10 * 60  # re-scrape at most every 10 minutes — be a polite scraper

USER_AGENT = (
    "Mozilla/5.0 (compatible; GoldBuyingAssistant/1.0; "
    "personal-use rate fetcher)"
)


# ============================================================
# UAE — Dubai Jewellery Group (dubaicityofgold.com)
# ============================================================

DGJG_SOURCE_URL = "https://dubaicityofgold.com/"
DGJG_KARATS = ["24", "22", "21", "18", "14"]

_dgjg_cache = {"data": None, "ts": 0}


def scrape_dgjg_rates():
    """Fetch dubaicityofgold.com and extract the 5 karat rates in AED/gram."""
    resp = requests.get(
        DGJG_SOURCE_URL,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(separator=" "))

    rates = {}
    for karat in DGJG_KARATS:
        # Page text reads like: "24K Gold AED 488.50"
        match = re.search(rf"{karat}K\s*Gold\s*AED\s*([\d,]+\.\d{{2}})", text, re.IGNORECASE)
        if match:
            rates[f"{karat}K"] = float(match.group(1).replace(",", ""))

    if len(rates) < 5:
        raise ValueError(f"Only found {len(rates)}/5 rates on the page: {rates}")

    return rates


@app.route("/api/gold-rate")
def gold_rate():
    now = time.time()

    if _dgjg_cache["data"] and (now - _dgjg_cache["ts"] < CACHE_TTL_SECONDS):
        return jsonify({**_dgjg_cache["data"], "cached": True})

    try:
        rates = scrape_dgjg_rates()
        payload = {
            "rates": rates,
            "currency": "AED",
            "unit": "gram",
            "source": "Dubai Jewellery Group (dubaicityofgold.com)",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }
        _dgjg_cache["data"] = payload
        _dgjg_cache["ts"] = now
        return jsonify({**payload, "cached": False})

    except Exception as exc:  # noqa: BLE001 - want to always return JSON, never crash
        logger.warning("DGJG scrape failed: %s", exc)
        if _dgjg_cache["data"]:
            return jsonify({**_dgjg_cache["data"], "cached": True, "warning": str(exc)})
        return jsonify({"error": "Could not fetch gold rate", "detail": str(exc)}), 502


# ============================================================
# India — Malabar Gold & Diamonds (GraphQL)
# ============================================================

MALABAR_GRAPHQL_URL = "https://www.malabargoldanddiamonds.com/graphql-magento"
MALABAR_QUERY = """
query getMetalRate($filter: MetalRateFilterInput) {
  getMetalRate(filter: $filter) {
    items {
      entry_date
      entry_time
      purity
      unit
      rate
      country
      state
    }
  }
}
"""

_india_cache = {"data": None, "ts": 0}


def scrape_malabar_rates():
    """Call Malabar's GraphQL endpoint and extract 22K/24K rates in INR/gram."""
    resp = requests.post(
        MALABAR_GRAPHQL_URL,
        json={
            "query": MALABAR_QUERY,
            "variables": {"filter": {"metal_type": "gold", "country": "India"}},
        },
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    items = data["data"]["getMetalRate"]["items"]

    rates = {}
    entry_date = None
    for item in items:
        # Normalize purity strings like "22k", "22 K", "22kt" -> "22K"
        digits = re.sub(r"[^0-9]", "", item.get("purity", ""))
        if not digits:
            continue
        karat_key = f"{digits}K"
        rates[karat_key] = float(item["rate"])
        entry_date = entry_date or item.get("entry_date")

    if not rates:
        raise ValueError(f"No rates found in Malabar response: {items}")

    return rates, entry_date


@app.route("/api/gold-rate-india")
def gold_rate_india():
    now = time.time()

    if _india_cache["data"] and (now - _india_cache["ts"] < CACHE_TTL_SECONDS):
        return jsonify({**_india_cache["data"], "cached": True})

    try:
        rates, entry_date = scrape_malabar_rates()
        payload = {
            "rates": rates,
            "currency": "INR",
            "unit": "gram",
            "source": "Malabar Gold & Diamonds",
            "entry_date": entry_date,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }
        _india_cache["data"] = payload
        _india_cache["ts"] = now
        return jsonify({**payload, "cached": False})

    except Exception as exc:  # noqa: BLE001
        logger.warning("Malabar scrape failed: %s", exc)
        if _india_cache["data"]:
            return jsonify({**_india_cache["data"], "cached": True, "warning": str(exc)})
        return jsonify({"error": "Could not fetch India gold rate", "detail": str(exc)}), 502


# ============================================================
# Health check
# ============================================================

@app.route("/")
def health():
    return jsonify({
        "status": "ok",
        "endpoints": ["/api/gold-rate", "/api/gold-rate-india"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
