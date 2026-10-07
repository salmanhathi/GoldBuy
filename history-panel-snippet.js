// ============ PRICE HISTORY (uaegoldprice.com, 22K/24K/18K only) ============
const HISTORY_RANGES = {
    '5d':  { label: '5 Days' },
    '10d': { label: '10 Days' },
    '30d': { label: '30 Days' },
    '1y':  { label: 'vs Last Year' }
};
const HISTORY_AVAILABLE_KARATS = ['22K', '24K', '18K'];

let historyPanelOpen = false;
let currentHistoryRange = '5d';
let historyCache = {}; // range -> payload, so switching toggles doesn't re-fetch every click

function toggleHistoryPanel() {
    historyPanelOpen = !historyPanelOpen;
    const panel = document.getElementById('historyPanel');
    panel.style.display = historyPanelOpen ? 'block' : 'none';
    if (historyPanelOpen) {
        renderHistoryPanel();
    }
}

async function fetchHistoryRange(range) {
    if (historyCache[range]) return historyCache[range];
    try {
        const res = await fetch(`${HISTORY_API_URL}?range=${range}`);
        if (!res.ok) throw new Error('Backend returned ' + res.status);
        const data = await res.json();
        historyCache[range] = data;
        return data;
    } catch (err) {
        return { error: true };
    }
}

async function setHistoryRange(range) {
    currentHistoryRange = range;
    await renderHistoryPanel();
}

async function renderHistoryPanel() {
    const panel = document.getElementById('historyPanel');

    // Toggle buttons
    let html = `<div class="step-card" style="margin-top: 0.8rem;">
        <div class="step-title" style="margin-bottom: 0.8rem;">Price History (uaegoldprice.com)</div>
        <div class="button-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 1rem;">`;
    Object.keys(HISTORY_RANGES).forEach(r => {
        html += `<button class="button ${r === currentHistoryRange ? 'active' : ''}" onclick="setHistoryRange('${r}')">${HISTORY_RANGES[r].label}</button>`;
    });
    html += `</div><div id="historyContent">Loading…</div></div>`;
    panel.innerHTML = html;

    const contentEl = document.getElementById('historyContent');

    if (!HISTORY_AVAILABLE_KARATS.includes(currentPurity)) {
        contentEl.innerHTML = `<div class="form-hint">History isn't published for ${currentPurity} by this source — pick 22K, 24K or 18K above to see price history.</div>`;
        return;
    }

    const data = await fetchHistoryRange(currentHistoryRange);
    if (data.error || !data.today) {
        contentEl.innerHTML = `<div class="form-hint">⚠️ Couldn't load history right now — try again shortly.</div>`;
        return;
    }
    if (!data.compare) {
        contentEl.innerHTML = `<div class="form-hint">⚠️ ${data.note || 'No comparison data available for this range.'}</div>`;
        return;
    }

    const todayRate = data.today[currentPurity];
    const compareRate = data.compare[currentPurity];
    const diff = todayRate - compareRate;
    const diffPercent = (diff / compareRate) * 100;
    const isUp = diff > 0;
    const isFlat = Math.abs(diff) < 0.005;

    contentEl.innerHTML = `
        <div class="result-row">
            <span class="result-label">Today (${data.today.date})</span>
            <span class="result-value">AED ${todayRate.toFixed(2)}</span>
        </div>
        <div class="result-row">
            <span class="result-label">${HISTORY_RANGES[currentHistoryRange].label} ago (${data.compare.date})</span>
            <span class="result-value">AED ${compareRate.toFixed(2)}</span>
        </div>
        <div class="result-row" style="border-bottom: none;">
            <span class="result-label">Change</span>
            <span class="result-value" style="color: ${isFlat ? 'var(--text-secondary)' : isUp ? 'var(--error-color)' : 'var(--success-color)'};">
                ${isFlat ? '→ No change' : (isUp ? '↑' : '↓') + ' AED ' + Math.abs(diff).toFixed(2) + ' (' + (isUp ? '+' : '') + diffPercent.toFixed(2) + '%)'}
            </span>
        </div>
    `;
}
