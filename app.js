(() => {
  "use strict";

  const REFRESH_INTERVAL_SEC = 15 * 60; // 15 minutes

  const state = {
    quotesData: null,
    insightsData: null,
    activeFilter: "all",
    searchQuery: "",
    sortBy: "default",
    compactMode: false,
    theme: localStorage.getItem("us_watch_theme") || "light",
    secondsLeft: REFRESH_INTERVAL_SEC,
    isRefreshing: false,
  };

  // DOM Elements
  const elStatusDot = document.getElementById("market-status-dot");
  const elStatusText = document.getElementById("market-status-text");
  const elQuotesUpdated = document.getElementById("quotes-updated-label");
  const elInsightsUpdated = document.getElementById("insights-updated-label");
  const elBtnRefresh = document.getElementById("btn-refresh-now");
  const elRefreshText = document.getElementById("refresh-btn-text");
  const elBtnCompact = document.getElementById("btn-compact-toggle");
  const elBtnTheme = document.getElementById("btn-theme-toggle");
  const elIndicesSubtitle = document.getElementById("indices-subtitle");
  const elIndicesContainer = document.getElementById("indices-container");
  const elMarketHeadlines = document.getElementById("market-headlines-list");
  const elWatchlistContainer = document.getElementById("watchlist-container");
  const elSearchInput = document.getElementById("search-ticker-input");
  const elSortSelect = document.getElementById("sort-watchlist-select");
  const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));

  function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || Number.isNaN(Number(num))) return "--";
    return Number(num).toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function formatSignedPct(pct) {
    if (pct === null || pct === undefined || Number.isNaN(Number(pct))) return "0.00%";
    const n = Number(pct);
    return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  }

  function formatSignedNum(val) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) return "0.00";
    const n = Number(val);
    return `${n >= 0 ? "+" : ""}${formatNumber(n, 2)}`;
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("us_watch_theme", theme);
    elBtnTheme.textContent = theme === "dark" ? "淺色模式" : "深色模式";
    // Redraw canvases so chart grid/colors match theme
    if (state.quotesData?.indices) {
      requestAnimationFrame(() => drawAllIndexCharts(state.quotesData.indices));
    }
  }

  function sessionBadgeClass(sessionStr) {
    if (!sessionStr) return "post";
    if (sessionStr.includes("夜盤")) return "overnight";
    if (sessionStr.includes("盤前")) return "pre";
    if (sessionStr.includes("盤中")) return "regular";
    return "post";
  }

  function computeLiveMarketStatus() {
    try {
      const now = new Date();
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).formatToParts(now);
      const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
      const wd = map.weekday;
      const hm = parseInt(map.hour, 10) * 60 + parseInt(map.minute, 10);

      if (wd === "Sat") return { text: "美股週末休市 · 顯示最新盤後價", active: false };
      if (wd === "Sun") {
        return hm >= 1200
          ? { text: "美股夜盤交易中 (Overnight)", active: true }
          : { text: "美股週末休市 · 週日 20:00 ET 夜盤開盤", active: false };
      }
      if (hm < 240) return { text: "美股夜盤交易中 (Overnight)", active: true };
      if (hm < 570) return { text: "美股盤前交易中 (Pre-Market)", active: true };
      if (hm < 960) return { text: "美股正規盤交易中 (Regular)", active: true };
      if (hm < 1200) return { text: "美股盤後交易中 (After-Hours)", active: true };
      if (wd === "Fri") return { text: "美股週末休市 · 顯示週五盤後價", active: false };
      return { text: "美股夜盤交易中 (Overnight)", active: true };
    } catch {
      return {
        text: state.quotesData?.marketSession?.statusText || "美股市場監控中",
        active: false,
      };
    }
  }

  function renderHeaderMeta() {
    const status = computeLiveMarketStatus();
    elStatusText.textContent = status.text;
    elStatusDot.classList.toggle("active", status.active);

    if (state.quotesData?.updatedAtTW) {
      elQuotesUpdated.textContent = `股價更新：${state.quotesData.updatedAtTW} (每15分)`;
    }
    if (state.insightsData?.updatedAtTW) {
      elInsightsUpdated.textContent = `頭條/情緒：${state.insightsData.updatedAtTW} (6H/開盤前10分)`;
    }
  }

  // 1. Render Three Major US Indices + Interactive Canvas Charts
  function renderIndices() {
    const indices = state.quotesData?.indices || [];
    if (!indices.length) return;

    const sessionDate = indices[0].sessionDate || "";
    elIndicesSubtitle.textContent = `交易日 ${sessionDate} 正規盤完整走勢 (09:30–16:00 ET) · 漲綠跌紅`;

    elIndicesContainer.innerHTML = indices
      .map((idx, i) => {
        const dirClass = idx.isUp ? "up" : "down";
        return `
          <article class="index-card">
            <div class="index-top">
              <div>
                <div class="index-name">${escapeHtml(idx.name)}</div>
                <div class="index-date">${escapeHtml(idx.enName)} · ${escapeHtml(idx.sessionDate)} 收盤</div>
              </div>
              <span class="delta-pill ${dirClass}">
                ${formatSignedNum(idx.change)} (${formatSignedPct(idx.changePct)})
              </span>
            </div>
            <div class="index-price-row">
              <div class="index-close">${formatNumber(idx.close)}</div>
            </div>
            <div class="chart-wrap">
              <canvas class="index-canvas" id="index-canvas-${i}" data-idx="${i}"></canvas>
              <div class="chart-tooltip" id="index-tooltip-${i}"></div>
            </div>
            <div class="index-range-footer">
              <span>昨收 ${formatNumber(idx.prevClose)}</span>
              <span>區間 ${formatNumber(idx.low)} – ${formatNumber(idx.high)}</span>
            </div>
          </article>
        `;
      })
      .join("");

    requestAnimationFrame(() => drawAllIndexCharts(indices));
  }

  function drawAllIndexCharts(indices) {
    indices.forEach((idx, i) => {
      const canvas = document.getElementById(`index-canvas-${i}`);
      const tooltip = document.getElementById(`index-tooltip-${i}`);
      if (canvas) drawSingleIndexChart(canvas, tooltip, idx);
    });
  }

  function drawSingleIndexChart(canvas, tooltip, idxData, hoverIndex = null) {
    const pts = idxData.points || [];
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height || pts.length < 2) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);

    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const padTop = 10;
    const padBottom = 18;
    const padX = 4;
    const plotW = w - padX * 2;
    const plotH = h - padTop - padBottom;

    const values = pts.map((p) => p.p);
    values.push(idxData.prevClose);
    let minVal = Math.min(...values);
    let maxVal = Math.max(...values);
    if (maxVal - minVal < 0.01) {
      maxVal += 1;
      minVal -= 1;
    }
    const range = maxVal - minVal;

    const xAt = (i) => padX + (i / (pts.length - 1)) * plotW;
    const yAt = (v) => padTop + (1 - (v - minVal) / range) * plotH;

    const isDark = state.theme === "dark";
    const lineColor = idxData.isUp ? "#10b981" : "#ef4444";
    const fillTop = idxData.isUp
      ? isDark ? "rgba(16, 185, 129, 0.25)" : "rgba(16, 185, 129, 0.16)"
      : isDark ? "rgba(239, 68, 68, 0.25)" : "rgba(239, 68, 68, 0.15)";
    const fillBottom = "rgba(0, 0, 0, 0)";

    ctx.clearRect(0, 0, w, h);

    // Previous Close dashed reference line
    const yPrev = yAt(idxData.prevClose);
    ctx.save();
    ctx.strokeStyle = isDark ? "rgba(148, 163, 184, 0.35)" : "rgba(100, 116, 139, 0.35)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padX, yPrev);
    ctx.lineTo(w - padX, yPrev);
    ctx.stroke();
    ctx.restore();

    // Area fill under intraday curve
    const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBottom);

    ctx.beginPath();
    pts.forEach((pt, i) => {
      const x = xAt(i);
      const y = yAt(pt.p);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(xAt(pts.length - 1), padTop + plotH);
    ctx.lineTo(xAt(0), padTop + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Crisp intraday price line
    ctx.beginPath();
    pts.forEach((pt, i) => {
      const x = xAt(i);
      const y = yAt(pt.p);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.85;
    ctx.lineJoin = "round";
    ctx.stroke();

    // Time axis labels (09:30, 12:30, 16:00 ET)
    ctx.fillStyle = isDark ? "#64748b" : "#94a3b8";
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = "left";
    ctx.fillText("09:30", padX, h - 4);
    ctx.textAlign = "center";
    ctx.fillText("12:45", w / 2, h - 4);
    ctx.textAlign = "right";
    ctx.fillText("16:00", w - padX, h - 4);

    // Interactive hover marker
    if (hoverIndex !== null && pts[hoverIndex]) {
      const hp = pts[hoverIndex];
      const hx = xAt(hoverIndex);
      const hy = yAt(hp.p);

      ctx.save();
      ctx.strokeStyle = isDark ? "rgba(226, 232, 240, 0.4)" : "rgba(15, 23, 42, 0.25)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(hx, padTop);
      ctx.lineTo(hx, padTop + plotH);
      ctx.stroke();

      ctx.fillStyle = lineColor;
      ctx.beginPath();
      ctx.arc(hx, hy, 3.8, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      if (tooltip) {
        const pct = idxData.prevClose ? ((hp.p - idxData.prevClose) / idxData.prevClose) * 100 : 0;
        tooltip.textContent = `${hp.et} ET · ${formatNumber(hp.p)} (${formatSignedPct(pct)})`;
        tooltip.style.opacity = "1";
      }
    } else if (tooltip) {
      tooltip.style.opacity = "0";
    }

    if (!canvas.dataset.bound) {
      canvas.dataset.bound = "1";
      const handleMove = (clientX) => {
        const r = canvas.getBoundingClientRect();
        const relX = Math.max(0, Math.min(r.width, clientX - r.left));
        const idx = Math.round((relX / r.width) * (pts.length - 1));
        drawSingleIndexChart(canvas, tooltip, idxData, idx);
      };
      canvas.addEventListener("mousemove", (e) => handleMove(e.clientX));
      canvas.addEventListener("mouseleave", () => drawSingleIndexChart(canvas, tooltip, idxData, null));
      canvas.addEventListener(
        "touchmove",
        (e) => {
          if (e.touches[0]) handleMove(e.touches[0].clientX);
        },
        { passive: true }
      );
      canvas.addEventListener("touchend", () => drawSingleIndexChart(canvas, tooltip, idxData, null));
    }
  }

  // 2. Render Top US Market Headlines
  function renderMarketHeadlines() {
    const items = state.insightsData?.marketHeadlines || [];
    if (!items.length) {
      elMarketHeadlines.innerHTML = `<li class="quiet-note">目前暫無美股頭條資料。</li>`;
      return;
    }

    elMarketHeadlines.innerHTML = items
      .map(
        (h) => `
        <li class="market-headline-item">
          <span class="bullet-dot"></span>
          <div class="headline-body">
            <span>${escapeHtml(h.title)}</span>
            <span class="headline-age">(${escapeHtml(h.age)})</span>
            <a class="source-link" href="${escapeHtml(h.url)}" target="_blank" rel="noopener noreferrer">
              [${escapeHtml(h.source)} ↗]
            </a>
          </div>
        </li>
      `
      )
      .join("");
  }

  function buildSparklineSvg(points, isUp) {
    if (!points || points.length < 2) return "";
    const w = 84;
    const h = 32;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const span = max - min || 1;
    const coords = points
      .map((v, i) => {
        const x = ((i / (points.length - 1)) * (w - 4) + 2).toFixed(1);
        const y = (h - 4 - ((v - min) / span) * (h - 8)).toFixed(1);
        return `${x},${y}`;
      })
      .join(" ");
    const stroke = isUp ? "#10b981" : "#ef4444";
    return `
      <svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
        <polyline
          fill="none"
          stroke="${stroke}"
          stroke-width="1.75"
          stroke-linecap="round"
          stroke-linejoin="round"
          points="${coords}"
        />
      </svg>
    `;
  }

  // 3, 4, 5. Render Watchlist Cards (15m Price + 6H Netizen Sentiment + 6H Headlines)
  function renderWatchlist() {
    const rawList = state.quotesData?.watchlist || [];
    const insightsMap = state.insightsData?.stocks || {};

    let list = rawList.map((item, originalIdx) => {
      const ins = insightsMap[item.symbol] || {};
      const sentiment = ins.sentiment || { buyPct: 50, sellPct: 50, dominant: "buy", summary: "" };
      const headlines = ins.headlines || [];
      return { ...item, originalIdx, sentiment, headlines };
    });

    if (state.activeFilter !== "all") {
      list = list.filter((it) => it.category === state.activeFilter);
    }

    if (state.searchQuery.trim()) {
      const q = state.searchQuery.trim().toLowerCase();
      list = list.filter(
        (it) =>
          it.symbol.toLowerCase().includes(q) ||
          it.displaySymbol.toLowerCase().includes(q) ||
          it.name.toLowerCase().includes(q) ||
          it.enName.toLowerCase().includes(q)
      );
    }

    if (state.sortBy === "change-desc") {
      list.sort((a, b) => b.changePct - a.changePct);
    } else if (state.sortBy === "change-asc") {
      list.sort((a, b) => a.changePct - b.changePct);
    } else if (state.sortBy === "buy-desc") {
      list.sort((a, b) => b.sentiment.buyPct - a.sentiment.buyPct);
    } else if (state.sortBy === "sell-desc") {
      list.sort((a, b) => b.sentiment.sellPct - a.sentiment.sellPct);
    } else {
      list.sort((a, b) => a.originalIdx - b.originalIdx);
    }

    elWatchlistContainer.classList.toggle("compact-mode", state.compactMode);

    if (!list.length) {
      elWatchlistContainer.innerHTML = `<div class="quiet-note">找不到符合條件的觀察標的。</div>`;
      return;
    }

    elWatchlistContainer.innerHTML = list
      .map((item) => {
        const dirClass = item.isUp ? "up" : "down";
        const sBadge = sessionBadgeClass(item.session);
        const sent = item.sentiment;
        const isBuyMore = sent.buyPct >= sent.sellPct;
        const verdictClass = isBuyMore ? "buy" : "sell";
        const verdictText = isBuyMore
          ? `想買 ${sent.buyPct}%`
          : `想賣 ${sent.sellPct}%`;

        let subQuoteParts = [];
        if (item.extChangePct !== null && item.extChangePct !== undefined) {
          subQuoteParts.push(`正規收盤 ${formatNumber(item.regularPrice)} (${formatSignedPct(item.regularChangePct)})`);
          subQuoteParts.push(`${item.session} ${formatSignedPct(item.extChangePct)}`);
        } else {
          subQuoteParts.push(`區間 ${formatNumber(item.dayLow)} – ${formatNumber(item.dayHigh)}`);
          if (item.updatedAt) subQuoteParts.push(`${item.updatedAt}`);
        }

        const has6h = item.headlines.some((h) => h.within6h !== false);
        const headlinesHeaderLabel = has6h ? "近 6 小時重點頭條" : "近期重點動態 (近 6 小時無突發新聞)";

        const newsHtml = item.headlines.length
          ? `<ul class="stock-news-list">
              ${item.headlines
                .map(
                  (hl) => `
                  <li class="stock-news-item">
                    <span class="bullet-dot"></span>
                    <div class="headline-body">
                      <span>${escapeHtml(hl.title)}</span>
                      <span class="headline-age">(${escapeHtml(hl.age)})</span>
                      <a class="source-link" href="${escapeHtml(hl.url)}" target="_blank" rel="noopener noreferrer">
                        [${escapeHtml(hl.source)} ↗]
                      </a>
                    </div>
                  </li>
                `
                )
                .join("")}
            </ul>`
          : `<div class="quiet-note">近 6 小時暫無重大新聞</div>`;

        return `
          <article class="stock-card" data-symbol="${escapeHtml(item.symbol)}">
            <div class="stock-header">
              <div class="stock-id-group">
                <div class="ticker-row">
                  <span class="stock-ticker">${escapeHtml(item.displaySymbol)}</span>
                  <span class="session-badge ${sBadge}">${escapeHtml(item.session)}</span>
                </div>
                <div class="stock-name" title="${escapeHtml(item.enName)}">${escapeHtml(item.name)}</div>
              </div>

              <div class="stock-quote-group">
                <div class="quote-main-row">
                  <span class="stock-price">${formatNumber(item.price)}</span>
                  <span class="delta-pill ${dirClass}">${formatSignedPct(item.changePct)}</span>
                </div>
                <div class="quote-sub-row">${escapeHtml(subQuoteParts.join(" · "))}</div>
              </div>
            </div>

            <div class="sentiment-strip">
              <div class="sentiment-info">
                <div class="sentiment-top-row">
                  <span class="sentiment-title">6H 網友情緒指數</span>
                  <span class="sentiment-verdict ${verdictClass}">${escapeHtml(verdictText)}</span>
                </div>
                <div class="sentiment-bar-track" title="想買 ${sent.buyPct}% / 想賣 ${sent.sellPct}%">
                  <div class="sentiment-bar-buy" style="width: ${sent.buyPct}%"></div>
                </div>
                <div class="sentiment-meta-row">
                  <span style="color: var(--up-text)">想買 ${sent.buyPct}%</span>
                  <span>${escapeHtml(sent.summary || "")}</span>
                  <span style="color: var(--down-text)">想賣 ${sent.sellPct}%</span>
                </div>
              </div>
              <div class="sparkline-box">
                ${buildSparklineSvg(item.sparkline, item.isUp)}
              </div>
            </div>

            <div class="stock-headlines">
              <div class="stock-headlines-label">
                <span>${headlinesHeaderLabel}</span>
              </div>
              ${newsHtml}
            </div>
          </article>
        `;
      })
      .join("");
  }

  async function loadAllData(isManual = false) {
    if (state.isRefreshing) return;
    state.isRefreshing = true;
    elBtnRefresh.disabled = true;
    elRefreshText.textContent = "同步中…";

    try {
      const bust = Date.now();
      const [qResp, iResp] = await Promise.all([
        fetch(`./data/quotes.json?t=${bust}`, { cache: "no-store" }),
        fetch(`./data/insights.json?t=${bust}`, { cache: "no-store" }),
      ]);

      if (qResp.ok) {
        state.quotesData = await qResp.json();
      }
      if (iResp.ok) {
        state.insightsData = await iResp.json();
      }

      renderHeaderMeta();
      renderIndices();
      renderMarketHeadlines();
      renderWatchlist();
      state.secondsLeft = REFRESH_INTERVAL_SEC;
    } catch (err) {
      console.error("Failed to load watchlist data:", err);
    } finally {
      state.isRefreshing = false;
      elBtnRefresh.disabled = false;
      updateCountdownLabel();
      if (isManual) {
        elRefreshText.textContent = "已更新 ✓";
        setTimeout(updateCountdownLabel, 1400);
      }
    }
  }

  function updateCountdownLabel() {
    if (state.isRefreshing) return;
    const m = String(Math.floor(state.secondsLeft / 60)).padStart(2, "0");
    const s = String(state.secondsLeft % 60).padStart(2, "0");
    elRefreshText.textContent = `立即更新 (${m}:${s})`;
  }

  function startTimers() {
    setInterval(() => {
      if (state.secondsLeft <= 1) {
        loadAllData(false);
      } else {
        state.secondsLeft -= 1;
        updateCountdownLabel();
      }
      if (state.secondsLeft % 60 === 0) {
        renderHeaderMeta();
      }
    }, 1000);
  }

  // Event Listeners
  elBtnRefresh.addEventListener("click", () => loadAllData(true));

  elBtnCompact.addEventListener("click", () => {
    state.compactMode = !state.compactMode;
    elBtnCompact.textContent = state.compactMode ? "詳細檢視" : "精簡檢視";
    renderWatchlist();
  });

  elBtnTheme.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeFilter = btn.dataset.filter || "all";
      renderWatchlist();
    });
  });

  elSearchInput.addEventListener("input", (e) => {
    state.searchQuery = e.target.value || "";
    renderWatchlist();
  });

  elSortSelect.addEventListener("change", (e) => {
    state.sortBy = e.target.value || "default";
    renderWatchlist();
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (state.quotesData?.indices) {
        drawAllIndexCharts(state.quotesData.indices);
      }
    }, 120);
  });

  // Initialize
  applyTheme(state.theme);
  loadAllData(false);
  startTimers();
})();
