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
from datetime import date, datetime, timedelta

from flask import Flask, jsonify, request
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
# UAE — Price History (uaegoldprice.com, 22K/24K/18K only)
# ============================================================

HISTORY_BASE_URL = "https://www.uaegoldprice.com/gold-price-history/gold-price-in-{month}-{year}/"
HISTORY_KARATS = ["22K", "24K", "18K"]
MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

_history_month_cache = {}  # {(year, month): {"rows": [...], "ts": float}}


def _parse_aed(value_str):
    return float(value_str.replace("AED", "").replace(",", "").strip())


def scrape_history_month(year, month):
    """Fetch one month's AED history table from uaegoldprice.com.
    Returns a list of {"date": date_obj, "22K": x, "24K": x, "18K": x}, ascending by date.
    Cached per (year, month) for the same TTL as everything else.
    """
    cache_key = (year, month)
    cached = _history_month_cache.get(cache_key)
    now = time.time()
    if cached and (now - cached["ts"] < CACHE_TTL_SECONDS):
        return cached["rows"]

    url = HISTORY_BASE_URL.format(month=MONTH_NAMES[month - 1], year=year)
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")  # first table on the page is the AED section
    if table is None:
        raise ValueError(f"No table found on {url}")

    rows = []
    for tr in table.find_all("tr")[1:]:  # skip header row
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 4:
            continue
        try:
            row_date = datetime.strptime(cells[0], "%d-%b-%Y").date()
            rows.append({
                "date": row_date,
                "22K": _parse_aed(cells[1]),
                "24K": _parse_aed(cells[2]),
                "18K": _parse_aed(cells[3]),
            })
        except (ValueError, IndexError):
            continue  # skip any malformed row rather than failing the whole scrape

    rows.sort(key=lambda r: r["date"])
    _history_month_cache[cache_key] = {"rows": rows, "ts": now}
    return rows


def get_recent_rows(min_days):
    """Collect enough rows (walking back through previous months as needed) to
    cover at least `min_days` of history ending today, sorted ascending by date.
    """
    today = date.today()
    all_rows = []
    year, month = today.year, today.month

    # Walk back month by month until we have enough rows or hit 6 months (safety cap)
    for _ in range(6):
        month_rows = scrape_history_month(year, month)
        all_rows = month_rows + all_rows
        if len(all_rows) > min_days:
            break
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    # Dedupe by date (safety) and sort ascending
    by_date = {r["date"]: r for r in all_rows}
    return sorted(by_date.values(), key=lambda r: r["date"])


def row_to_payload(row):
    return {"date": row["date"].strftime("%d-%b-%Y"), **{k: row[k] for k in HISTORY_KARATS}}


@app.route("/api/gold-rate-history")
def gold_rate_history():
    """
    Query param: range = 5d | 10d | 30d | 1y   (default 5d)

    Returns:
      {"range": "5d",
       "today": {"date": "05-Oct-2026", "22K": 465.0, "24K": 502.0, "18K": 382.0},
       "compare": {"date": "01-Oct-2026", "22K": 464.25, "24K": 501.50, "18K": 381.50},
       "source": "uaegoldprice.com", "currency": "AED", "unit": "gram",
       "fetched_at": "...", "cached": bool}

    If a comparison point can't be found (e.g. 1-year lookback before the
    site's archive starts), "compare" is null and "note" explains why.
    """
    range_param = request.args.get("range", "5d")
    now = time.time()

    try:
        if range_param == "1y":
            today = date.today()
            try:
                target_date = today.replace(year=today.year - 1)
            except ValueError:
                # Feb 29 with no Feb 29 last year -> fall back to Feb 28
                target_date = today.replace(year=today.year - 1, day=28)

            today_rows = get_recent_rows(1)
            today_row = today_rows[-1] if today_rows else None

            try:
                year_ago_rows = scrape_history_month(target_date.year, target_date.month)
                compare_row = next((r for r in year_ago_rows if r["date"] == target_date), None)
            except Exception:
                compare_row = None

            payload = {
                "range": "1y",
                "today": row_to_payload(today_row) if today_row else None,
                "compare": row_to_payload(compare_row) if compare_row else None,
                "source": "uaegoldprice.com",
                "currency": "AED",
                "unit": "gram",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            }
            if not compare_row:
                payload["note"] = f"No archived rate found for {target_date.strftime('%d-%b-%Y')}"

        else:
            days_map = {"5d": 5, "10d": 10, "30d": 30}
            days = days_map.get(range_param, 5)

            rows = get_recent_rows(days)
            if len(rows) < 2:
                raise ValueError("Not enough history rows returned")

            today_row = rows[-1]
            compare_row = rows[-(days + 1)] if len(rows) > days else rows[0]

            payload = {
                "range": range_param,
                "today": row_to_payload(today_row),
                "compare": row_to_payload(compare_row),
                "source": "uaegoldprice.com",
                "currency": "AED",
                "unit": "gram",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            }

        return jsonify({**payload, "cached": False})

    except Exception as exc:
        logger.warning("History fetch failed (range=%s): %s", range_param, exc)
        return jsonify({"error": "Could not fetch gold price history", "detail": str(exc)}), 502


# ============================================================
# Health check
# ============================================================

@app.route("/")
def health():
    return jsonify({
        "status": "ok",
        "endpoints": ["/api/gold-rate", "/api/gold-rate-india", "/api/gold-rate-history"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
