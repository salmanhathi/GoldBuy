# DGJG Gold Rate API

A tiny Flask backend that scrapes the Dubai Jewellery Group's published gold
rate from `dubaicityofgold.com` and serves it as JSON, so the Gold Buying
Assistant web tool can show live, auto-synced UAE gold prices instead of
requiring manual entry every day.

## Why this exists

`dubaicityofgold.com` has no public API and doesn't allow cross-origin
browser requests (CORS), so a static HTML page can't fetch it directly.
This backend fetches it **server-side** (no CORS restriction there) and
re-serves it with CORS enabled, so the browser-based tool can call it.

## Deploy on Render (same flow as your other tools)

1. Push this folder to a new GitHub repo (e.g. `dgjg-gold-rate-api`)
2. On [render.com](https://render.com) → New → Web Service → connect the repo
3. Render should auto-detect the `Procfile`. If asked:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
4. Deploy. Render gives you a URL like `https://dgjg-gold-rate-api.onrender.com`
5. Test it: open `https://dgjg-gold-rate-api.onrender.com/api/gold-rate` in a
   browser — you should see JSON with today's 5 rates.
6. Open `gold-buying-assistant.html`, find the line near the top of the
   `<script>` block:
   ```js
   const DGJG_API_URL = ''; // <-- paste your Render URL + /api/gold-rate here
   ```
   and set it to your deployed endpoint, e.g.:
   ```js
   const DGJG_API_URL = 'https://dgjg-gold-rate-api.onrender.com/api/gold-rate';
   ```
7. Reload the tool — the top rate panel should now say "🔄 Synced from Dubai
   Jewellery Group" instead of asking for manual entry.

## Notes

- Render's free tier sleeps after inactivity — the first request after a
  while will be slow (~30s) as it wakes up. Fine for personal use; the tool
  falls back to whatever rate you last saved/entered while it's waking up.
- The scraper caches for 10 minutes so it doesn't hit dubaicityofgold.com on
  every page load — be a polite scraper.
- If dubaicityofgold.com changes their page layout, the regex in
  `scrape_dgjg_rates()` in `app.py` may need a small tweak. The `/api/gold-rate`
  endpoint will return a clear error in that case rather than silently
  breaking, and the frontend tool falls back to manual entry automatically.
- This is for personal use pulling publicly displayed information — same
  spirit as your other scrapers (PAC, Product Health Monitor).

## Local testing

```bash
pip install -r requirements.txt
python app.py
# then visit http://localhost:5000/api/gold-rate
```
