(() => {
  "use strict";

  const REFRESH_INTERVAL_SEC = 15 * 60;

  const state = {
    quotesData: null,
    insightsData: null,
    flashData: null,
    flashPaused: false,
    flashDrawerOpen: false,
    flashFilter: "all",
    activeFilter: "all",
    searchQuery: "",
    sortBy: "default",
    expandAll: false,
    expandedSymbols: new Set(),
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
  const elBtnExpandAll = document.getElementById("btn-expand-all");
  const elBtnTheme = document.getElementById("btn-theme-toggle");
  const elFlashTrack = document.getElementById("flash-marquee-track");
  const elBtnFlashPause = document.getElementById("btn-flash-pause");
  const elBtnFlashDrawer = document.getElementById("btn-flash-drawer");
  const elFlashDrawerBtnText = document.getElementById("flash-drawer-btn-text");
  const elFlashDrawer = document.getElementById("flash-wire-drawer");
  const elFlashUpdatedNote = document.getElementById("flash-updated-note");
  const elFlashTimeline = document.getElementById("flash-timeline-list");
  const flashFilterButtons = Array.from(document.querySelectorAll(".flash-filter-pill"));
  const elIndicesSubtitle = document.getElementById("indices-subtitle");
  const elIndicesContainer = document.getElementById("indices-container");
  const elMarketHeadlines = document.getElementById("market-headlines-list");
  const elWatchlistRows = document.getElementById("watchlist-rows-container");
  const elCioContainer = document.getElementById("cio-advisory-container");
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

  // 1. Three Major US Indices
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
            <div class="index-close">${formatNumber(idx.close)}</div>
            <div class="chart-wrap">
              <canvas class="index-canvas" id="index-canvas-${i}" data-idx="${i}"></canvas>
              <div class="chart-tooltip" id="index-tooltip-${i}"></div>
            </div>
            <div class="index-range-footer">
              <span>昨收 ${formatNumber(idx.prevClose)}</span>
              <span>當日區間 ${formatNumber(idx.low)} – ${formatNumber(idx.high)}</span>
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
    const padTop = 8;
    const padBottom = 16;
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

    ctx.clearRect(0, 0, w, h);

    // Previous close reference line
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

    const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, "rgba(0, 0, 0, 0)");

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

    ctx.fillStyle = isDark ? "#64748b" : "#94a3b8";
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = "left";
    ctx.fillText("09:30", padX, h - 3);
    ctx.textAlign = "center";
    ctx.fillText("12:45", w / 2, h - 3);
    ctx.textAlign = "right";
    ctx.fillText("16:00", w - padX, h - 3);

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
      ctx.arc(hx, hy, 3.6, 0, Math.PI * 2);
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

  // 2. Market Headlines
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
    const w = 82;
    const h = 30;
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
    const firstY = (h - 4 - ((points[0] - min) / span) * (h - 8)).toFixed(1);
    const stroke = isUp ? "#10b981" : "#ef4444";
    return `
      <svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
        <line x1="2" y1="${firstY}" x2="${w - 2}" y2="${firstY}" stroke="rgba(148,163,184,0.35)" stroke-width="1" stroke-dasharray="2,2" />
        <polyline
          fill="none"
          stroke="${stroke}"
          stroke-width="1.65"
          stroke-linecap="round"
          stroke-linejoin="round"
          points="${coords}"
        />
      </svg>
    `;
  }

  function sortItemsWithinGroup(arr) {
    const copy = [...arr];
    if (state.sortBy === "change-desc") {
      copy.sort((a, b) => b.changePct - a.changePct);
    } else if (state.sortBy === "change-asc") {
      copy.sort((a, b) => a.changePct - b.changePct);
    } else if (state.sortBy === "buy-desc") {
      copy.sort((a, b) => b.sentiment.buyPct - a.sentiment.buyPct);
    } else if (state.sortBy === "sell-desc") {
      copy.sort((a, b) => b.sentiment.sellPct - a.sentiment.sellPct);
    } else {
      copy.sort((a, b) => a.originalIdx - b.originalIdx);
    }
    return copy;
  }

  function buildSingleRowHtml(item) {
    const dirClass = item.isUp ? "up" : "down";
    const sBadge = sessionBadgeClass(item.session);
    const sent = item.sentiment;
    const isBuyMore = sent.buyPct >= sent.sellPct;
    const sentDomClass = isBuyMore ? "buy" : "sell";
    const sentDomText = isBuyMore ? `想買 ${sent.buyPct}%` : `想賣 ${sent.sellPct}%`;
    const sentMinorText = isBuyMore ? `賣 ${sent.sellPct}%` : `買 ${sent.buyPct}%`;

    const isExpanded = state.expandAll || state.expandedSymbols.has(item.symbol);
    const holdingBadgeHtml = item.isHolding
      ? `<span class="holding-tag">${escapeHtml(item.holdingBadge || "持倉")}</span>`
      : "";

    let priceSubText = "";
    if (item.extChangePct !== null && item.extChangePct !== undefined) {
      priceSubText = `收盤 ${formatNumber(item.regularPrice)} · ${item.session} ${formatSignedPct(item.extChangePct)}`;
    } else {
      priceSubText = `高 ${formatNumber(item.dayHigh)} · 低 ${formatNumber(item.dayLow)}`;
    }

    const topHl = item.headlines[0];
    const inlineHeadlineHtml = topHl
      ? `<div class="inline-hl-wrap">
          <span>${escapeHtml(topHl.title)}</span>
          <span class="headline-age">(${escapeHtml(topHl.age)})</span>
          <a class="source-link" href="${escapeHtml(topHl.url)}" target="_blank" rel="noopener noreferrer">[${escapeHtml(topHl.source)} ↗]</a>
        </div>`
      : `<span class="quiet-note" style="padding:0">近 6 小時暫無重大新聞</span>`;

    const drawerHeadlinesHtml = item.headlines.length
      ? `<ul class="drawer-news-list">
          ${item.headlines
            .map(
              (hl) => `
              <li class="drawer-news-item">
                <span class="bullet-dot"></span>
                <div class="headline-body">
                  <span>${escapeHtml(hl.title)}</span>
                  <span class="headline-age">(${escapeHtml(hl.age)})</span>
                  <a class="source-link" href="${escapeHtml(hl.url)}" target="_blank" rel="noopener noreferrer">[${escapeHtml(hl.source)} ↗]</a>
                </div>
              </li>
            `
            )
            .join("")}
        </ul>`
      : `<div class="quiet-note" style="padding:0">近 6 小時無突發新聞</div>`;

    return `
      <div class="moomoo-row ${item.isHolding ? "is-holding" : ""} ${isExpanded ? "expanded" : ""}" data-symbol="${escapeHtml(item.symbol)}">
        <div class="moomoo-row-main" role="button" tabindex="0" aria-expanded="${isExpanded}">
          <div class="cell-symbol">
            <div class="symbol-line">
              <span class="ticker-code">${escapeHtml(item.displaySymbol)}</span>
              ${holdingBadgeHtml}
              <span class="session-badge ${sBadge}">${escapeHtml(item.session)}</span>
            </div>
            <div class="company-cn" title="${escapeHtml(item.enName)}">${escapeHtml(item.name)}</div>
          </div>

          <div class="cell-spark">
            ${buildSparklineSvg(item.sparkline, item.isUp)}
          </div>

          <div class="cell-price">
            <div class="price-main">${formatNumber(item.price)}</div>
            <div class="price-sub">${escapeHtml(priceSubText)}</div>
          </div>

          <div class="cell-change">
            <span class="moomoo-chg-badge ${dirClass}">${formatSignedPct(item.changePct)}</span>
            <span class="chg-amt-sub ${dirClass}">${formatSignedNum(item.change)}</span>
          </div>

          <div class="cell-sentiment">
            <div class="sent-row-top">
              <span class="sent-dominant ${sentDomClass}">${escapeHtml(sentDomText)}</span>
              <span class="sent-minor">${escapeHtml(sentMinorText)}</span>
            </div>
            <div class="sent-dual-bar" title="想買 ${sent.buyPct}% / 想賣 ${sent.sellPct}%">
              <div class="sent-dual-buy" style="width: ${sent.buyPct}%"></div>
            </div>
          </div>

          <div class="cell-headline">
            ${inlineHeadlineHtml}
          </div>

          <div class="cell-expand">
            <span class="expand-pill">${isExpanded ? "▴" : "▾"} ${item.headlines.length}則</span>
          </div>
        </div>

        <div class="moomoo-row-drawer">
          <div class="drawer-meta-bar">
            <span>正規收盤：<strong>${formatNumber(item.regularPrice)}</strong> (${formatSignedPct(item.regularChangePct)})</span>
            <span>當日區間：<strong>${formatNumber(item.dayLow)} – ${formatNumber(item.dayHigh)}</strong></span>
            <span>52週高點：<strong>${formatNumber(item.high52w)}</strong></span>
            <span>情緒結構：${escapeHtml(sent.summary || "綜合買賣力道")}</span>
          </div>
          ${drawerHeadlinesHtml}
        </div>
      </div>
    `;
  }

  // 3, 4, 5. Render Firstrade / Futu Moomoo Horizontal Watchlist (Holdings Pinned Top)
  function renderWatchlist() {
    const rawList = state.quotesData?.watchlist || [];
    const insightsMap = state.insightsData?.stocks || {};

    let list = rawList.map((item, originalIdx) => {
      const ins = insightsMap[item.symbol] || {};
      const sentiment = ins.sentiment || { buyPct: 50, sellPct: 50, dominant: "buy", summary: "" };
      const headlines = ins.headlines || [];
      return { ...item, originalIdx, sentiment, headlines };
    });

    if (state.activeFilter === "holdings") {
      list = list.filter((it) => it.isHolding);
    } else if (state.activeFilter !== "all") {
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

    if (!list.length) {
      elWatchlistRows.innerHTML = `<div class="quiet-note">找不到符合條件的觀察標的。</div>`;
      return;
    }

    // Always separate Holdings on Top vs Rest of Watchlist below
    const holdingsGroup = sortItemsWithinGroup(list.filter((it) => it.isHolding));
    const watchGroup = sortItemsWithinGroup(list.filter((it) => !it.isHolding));

    let htmlParts = [];
    if (holdingsGroup.length) {
      htmlParts.push(`
        <div class="moomoo-group-banner">
          <span>★ 我的核心持倉 (${holdingsGroup.length})</span>
          <span>優先置頂監控</span>
        </div>
      `);
      htmlParts.push(holdingsGroup.map(buildSingleRowHtml).join(""));
    }

    if (watchGroup.length) {
      htmlParts.push(`
        <div class="moomoo-group-banner">
          <span>☆ 自選觀察名單 (${watchGroup.length})</span>
          <span>市場焦點與潛在機會</span>
        </div>
      `);
      htmlParts.push(watchGroup.map(buildSingleRowHtml).join(""));
    }

    elWatchlistRows.innerHTML = htmlParts.join("");
  }

  // 6. Render CIO & CRO Institutional Tactical Advisory
  function renderCioAdvisory() {
    const cio = state.insightsData?.cioAdvisory;
    if (!cio) {
      elCioContainer.innerHTML = `<div class="quiet-note">正在載入投資長專業操作建議…</div>`;
      return;
    }

    const cardsHtml = (cio.cards || [])
      .map(
        (c) => `
        <article class="cio-action-card">
          <div class="cio-card-head">
            <span class="cio-card-title">${escapeHtml(c.title)}</span>
            <span class="cio-stance-pill ${escapeHtml(c.actionType || "hold")}">${escapeHtml(c.action)}</span>
          </div>
          <p class="cio-card-body">${escapeHtml(c.detail)}</p>
        </article>
      `
      )
      .join("");

    const scannerHtml = (cio.scannerBullets || []).length
      ? `
        <div class="cio-scanner-box">
          <div class="cio-scanner-title">觀察名單異動與逆向情緒掃描</div>
          <ul class="cio-scanner-list">
            ${cio.scannerBullets
              .map(
                (b) => `
                <li class="cio-scanner-item">
                  <span class="bullet-dot"></span>
                  <span>${escapeHtml(b)}</span>
                </li>
              `
              )
              .join("")}
          </ul>
        </div>
      `
      : "";

    elCioContainer.innerHTML = `
      <div class="cio-regime-banner">
        <div class="cio-regime-top">
          <span class="cio-badge">投資長市場判讀</span>
          <strong>${escapeHtml(cio.regimeTag || "")}</strong>
        </div>
        <p class="cio-regime-text">${escapeHtml(cio.regimeSummary || "")}</p>
      </div>
      <div class="cio-cards-grid">
        ${cardsHtml}
      </div>
      ${scannerHtml}
    `;
  }

  function flashTagClass(tagStr, item) {
    if (tagStr.includes("當機") || item.isOutage) return "outage";
    if (tagStr.includes("FED") || item.isMacro) return "macro";
    if (item.affectsHoldings) return "holding";
    return "";
  }

  function buildFlashTagsHtml(item) {
    const urgentHtml = item.urgent ? `<span class="flash-urgent-pill">重磅</span>` : "";
    const tagsHtml = (item.tags || [])
      .map(
        (t) =>
          `<span class="flash-tag-pill ${flashTagClass(t, item)}">${escapeHtml(t)}</span>`
      )
      .join("");
    return `${urgentHtml}${tagsHtml}`;
  }

  // 0. Render Top-30 US Tech & Fed Breaking News Flash Ticker + 7x24 Wire Drawer
  function renderFlashWire() {
    const items = state.flashData?.items || [];
    const totalCount = items.length;

    if (elFlashDrawerBtnText) {
      elFlashDrawerBtnText.textContent = state.flashDrawerOpen
        ? `收合快報 (${totalCount}) ▴`
        : `快報列表 (${totalCount}) ▾`;
    }

    if (elFlashUpdatedNote && state.flashData?.updatedAtTW) {
      elFlashUpdatedNote.textContent = `嚴選美國前 30 大科技股 ＆ 聯準會升降息/政策衝擊 · 最新掃描：${state.flashData.updatedAtTW} (每15分)`;
    }

    if (!items.length) {
      elFlashTrack.innerHTML = `<span class="flash-loading-text">目前暫無最新美國前 30 大科技股與聯準會突發快報。</span>`;
      elFlashTrack.style.animation = "none";
      renderFlashDrawer();
      return;
    }

    const durationSec = Math.max(42, Math.round(items.length * 6.8));
    elFlashTrack.style.setProperty("--flash-duration", `${durationSec}s`);
    elFlashTrack.style.animation = "";

    const singlePassHtml = items
      .map(
        (it) => `
        <a class="flash-tape-item" href="${escapeHtml(it.url)}" target="_blank" rel="noopener noreferrer">
          <span class="flash-time-mono">${escapeHtml(it.clockTW || it.age)}</span>
          ${buildFlashTagsHtml(it)}
          <span class="flash-tape-title">${escapeHtml(it.title)}</span>
          <span class="flash-tape-src">(${escapeHtml(it.source)} ↗)</span>
        </a>
        <span class="flash-tape-sep" aria-hidden="true">•</span>
      `
      )
      .join("");

    // Duplicate track content once for seamless -50% infinite loop
    elFlashTrack.innerHTML = singlePassHtml + singlePassHtml;
    elFlashTrack.classList.toggle("paused", state.flashPaused);

    renderFlashDrawer();
  }

  function renderFlashDrawer() {
    if (!elFlashTimeline) return;
    let items = state.flashData?.items || [];

    if (state.flashFilter === "urgent") {
      items = items.filter((it) => it.urgent || it.isMacro || it.isOutage);
    } else if (state.flashFilter === "holdings") {
      items = items.filter((it) => it.affectsHoldings);
    }

    if (!items.length) {
      elFlashTimeline.innerHTML = `<li class="quiet-note" style="grid-column: 1 / -1; padding: 6px 2px;">目前此分類暫無快報項目。</li>`;
      return;
    }

    elFlashTimeline.innerHTML = items
      .map(
        (it) => `
        <li class="flash-timeline-item">
          <div class="flash-timeline-meta">
            <span class="flash-time-mono" title="${escapeHtml(it.timeTW)}">${escapeHtml(it.clockTW || it.age)}</span>
            ${buildFlashTagsHtml(it)}
          </div>
          <div class="flash-timeline-body">
            <span>${escapeHtml(it.title)}</span>
            <span class="headline-age">(${escapeHtml(it.age)})</span>
            <a class="source-link" href="${escapeHtml(it.url)}" target="_blank" rel="noopener noreferrer">[${escapeHtml(it.source)} ↗]</a>
          </div>
        </li>
      `
      )
      .join("");
  }

  async function loadAllData(isManual = false) {
    if (state.isRefreshing) return;
    state.isRefreshing = true;
    elBtnRefresh.disabled = true;
    elRefreshText.textContent = "同步中…";

    try {
      const bust = Date.now();
      const [qResp, iResp, fResp] = await Promise.all([
        fetch(`./data/quotes.json?t=${bust}`, { cache: "no-store" }),
        fetch(`./data/insights.json?t=${bust}`, { cache: "no-store" }),
        fetch(`./data/flash.json?t=${bust}`, { cache: "no-store" }),
      ]);

      if (qResp.ok) state.quotesData = await qResp.json();
      if (iResp.ok) state.insightsData = await iResp.json();
      if (fResp.ok) state.flashData = await fResp.json();

      renderHeaderMeta();
      renderFlashWire();
      renderIndices();
      renderMarketHeadlines();
      renderWatchlist();
      renderCioAdvisory();
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
      if (state.secondsLeft % 60 === 0) renderHeaderMeta();
    }, 1000);
  }

  // Flash ticker pause & 7x24 drawer controls
  if (elBtnFlashPause) {
    elBtnFlashPause.addEventListener("click", () => {
      state.flashPaused = !state.flashPaused;
      elFlashTrack.classList.toggle("paused", state.flashPaused);
      elBtnFlashPause.textContent = state.flashPaused ? "▶" : "⏸";
      elBtnFlashPause.setAttribute("aria-label", state.flashPaused ? "繼續播放跑馬燈" : "暫停跑馬燈");
    });
  }

  if (elBtnFlashDrawer) {
    elBtnFlashDrawer.addEventListener("click", () => {
      state.flashDrawerOpen = !state.flashDrawerOpen;
      elFlashDrawer.hidden = !state.flashDrawerOpen;
      elBtnFlashDrawer.setAttribute("aria-expanded", String(state.flashDrawerOpen));
      const cnt = (state.flashData?.items || []).length;
      elFlashDrawerBtnText.textContent = state.flashDrawerOpen
        ? `收合快報 (${cnt}) ▴`
        : `快報列表 (${cnt}) ▾`;
    });
  }

  flashFilterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      flashFilterButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.flashFilter = btn.dataset.flashFilter || "all";
      renderFlashDrawer();
    });
  });

  // Delegate row click to expand/collapse drawer (ignoring direct clicks on news links)
  elWatchlistRows.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    const rowEl = e.target.closest(".moomoo-row");
    if (!rowEl) return;
    const sym = rowEl.dataset.symbol;
    if (!sym) return;

    if (state.expandAll) {
      state.expandAll = false;
      elBtnExpandAll.textContent = "展開全部頭條";
      const allSyms = (state.quotesData?.watchlist || []).map((x) => x.symbol);
      state.expandedSymbols = new Set(allSyms.filter((s) => s !== sym));
    } else if (state.expandedSymbols.has(sym)) {
      state.expandedSymbols.delete(sym);
    } else {
      state.expandedSymbols.add(sym);
    }
    renderWatchlist();
  });

  elBtnRefresh.addEventListener("click", () => loadAllData(true));

  elBtnExpandAll.addEventListener("click", () => {
    state.expandAll = !state.expandAll;
    state.expandedSymbols.clear();
    elBtnExpandAll.textContent = state.expandAll ? "收合全部頭條" : "展開全部頭條";
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
      if (state.quotesData?.indices) drawAllIndexCharts(state.quotesData.indices);
    }, 120);
  });

  applyTheme(state.theme);
  loadAllData(false);
  startTimers();
})();
