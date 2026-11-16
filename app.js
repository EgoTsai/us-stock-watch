(() => {
  "use strict";

  const REFRESH_INTERVAL_SEC = 60;
  const LIVE_REPO = "EgoTsai/us-stock-watch";
  const LIVE_BRANCH = "live-data";

  const state = {
    baseQuotesData: null,
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
    realtimeActive: false,
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
  const elColHeader = document.getElementById("moomoo-col-header");
  const colSortHeaders = Array.from(document.querySelectorAll(".col-sortable"));
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
      const modeTag = state.realtimeActive ? "(即時連線)" : "(每3分)";
      elQuotesUpdated.textContent = `股價更新：${state.quotesData.updatedAtTW} ${modeTag}`;
    }
    if (state.insightsData?.updatedAtTW) {
      elInsightsUpdated.textContent = `頭條/情緒：${state.insightsData.updatedAtTW} (6H/開盤前10分)`;
    }
  }

  function parseEtMinutesFromOpen(etStr) {
    if (!etStr || typeof etStr !== "string" || !etStr.includes(":")) return null;
    const [hh, mm] = etStr.split(":").map((n) => parseInt(n, 10));
    if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
    return Math.max(0, Math.min(390, hh * 60 + mm - 570));
  }

  // 1. Three Major US Indices
  function renderIndices() {
    const indices = state.quotesData?.indices || [];
    if (!indices.length) return;

    const sessionDate = indices[0].sessionDate || "";
    const anyLive = indices.some((idx) => idx.isLive);
    const lastEt = indices[0].lastTimeET || "";
    elIndicesSubtitle.textContent = anyLive
      ? `交易日 ${sessionDate} 盤中即時走勢 (${lastEt} ET 更新) · 漲綠跌紅`
      : `交易日 ${sessionDate} 正規盤收盤走勢 (09:30–16:00 ET) · 漲綠跌紅`;

    elIndicesContainer.innerHTML = indices
      .map((idx, i) => {
        const dirClass = idx.isUp ? "up" : "down";
        const statusMetaHtml = idx.isLive
          ? `<span class="live-idx-badge">● 盤中即時 ${escapeHtml(idx.lastTimeET || "")} ET</span>`
          : `<span>${escapeHtml(idx.sessionDate)} 收盤</span>`;
        return `
          <article class="index-card">
            <div class="index-top">
              <div>
                <div class="index-name">${escapeHtml(idx.name)}</div>
                <div class="index-date"><span>${escapeHtml(idx.enName)} ·</span>${statusMetaHtml}</div>
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

    const xAt = (i) => {
      if (idxData.isLive) {
        const m = parseEtMinutesFromOpen(pts[i]?.et);
        if (m !== null) {
          return padX + (m / 390) * plotW;
        }
      }
      return padX + (i / (pts.length - 1)) * plotW;
    };
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

    // Live pulsing tip dot during regular session
    if (idxData.isLive && pts.length > 0) {
      const lx = xAt(pts.length - 1);
      const ly = yAt(pts[pts.length - 1].p);
      ctx.save();
      ctx.fillStyle = idxData.isUp ? "rgba(16, 185, 129, 0.25)" : "rgba(239, 68, 68, 0.25)";
      ctx.beginPath();
      ctx.arc(lx, ly, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = lineColor;
      ctx.beginPath();
      ctx.arc(lx, ly, 2.8, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

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
        let bestIdx = 0;
        let bestDist = Infinity;
        for (let k = 0; k < pts.length; k++) {
          const d = Math.abs(xAt(k) - relX);
          if (d < bestDist) {
            bestDist = d;
            bestIdx = k;
          }
        }
        drawSingleIndexChart(canvas, tooltip, idxData, bestIdx);
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
            <span class="js-zh-guard">${escapeHtml(h.title)}</span>
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
    const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
    if (state.sortBy === "change-desc" || state.sortBy === "all-change-desc") {
      copy.sort((a, b) => num(b.changePct) - num(a.changePct));
    } else if (state.sortBy === "change-asc" || state.sortBy === "all-change-asc") {
      copy.sort((a, b) => num(a.changePct) - num(b.changePct));
    } else if (state.sortBy === "price-desc") {
      copy.sort((a, b) => num(b.price) - num(a.price));
    } else if (state.sortBy === "price-asc") {
      copy.sort((a, b) => num(a.price) - num(b.price));
    } else if (state.sortBy === "buy-desc") {
      copy.sort((a, b) => num(b.sentiment?.buyPct) - num(a.sentiment?.buyPct));
    } else if (state.sortBy === "sell-desc") {
      copy.sort((a, b) => num(b.sentiment?.sellPct) - num(a.sentiment?.sellPct));
    } else if (state.sortBy === "symbol-asc") {
      copy.sort((a, b) =>
        String(a.displaySymbol || a.symbol).localeCompare(String(b.displaySymbol || b.symbol))
      );
    } else if (state.sortBy === "symbol-desc") {
      copy.sort((a, b) =>
        String(b.displaySymbol || b.symbol).localeCompare(String(a.displaySymbol || a.symbol))
      );
    } else {
      copy.sort((a, b) => a.originalIdx - b.originalIdx);
    }
    return copy;
  }

  function syncSortUiIndicators() {
    if (elSortSelect && elSortSelect.value !== state.sortBy) {
      elSortSelect.value = state.sortBy;
    }

    const colDirMap = {
      symbol:
        state.sortBy === "symbol-asc" ? "asc" : state.sortBy === "symbol-desc" ? "desc" : null,
      price:
        state.sortBy === "price-desc" ? "desc" : state.sortBy === "price-asc" ? "asc" : null,
      change:
        state.sortBy === "change-desc" || state.sortBy === "all-change-desc"
          ? "desc"
          : state.sortBy === "change-asc" || state.sortBy === "all-change-asc"
          ? "asc"
          : null,
      sentiment:
        state.sortBy === "buy-desc" ? "desc" : state.sortBy === "sell-desc" ? "asc" : null,
    };

    colSortHeaders.forEach((hdr) => {
      const col = hdr.dataset.sortCol;
      const dir = colDirMap[col] || null;
      hdr.classList.toggle("sort-asc", dir === "asc");
      hdr.classList.toggle("sort-desc", dir === "desc");
    });
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
          <span class="js-zh-guard">${escapeHtml(topHl.title)}</span>
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
                  <div>
                    <span class="js-zh-guard">${escapeHtml(hl.title)}</span>
                    <span class="headline-age">(${escapeHtml(hl.age)})</span>
                    <a class="source-link" href="${escapeHtml(hl.url)}" target="_blank" rel="noopener noreferrer">[${escapeHtml(hl.source)} ↗]</a>
                  </div>
                  ${hl.summary ? `<div class="drawer-news-summary js-zh-guard">${escapeHtml(hl.summary)}</div>` : ""}
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

    syncSortUiIndicators();

    if (!list.length) {
      elWatchlistRows.innerHTML = `<div class="quiet-note">找不到符合條件的觀察標的。</div>`;
      return;
    }

    let htmlParts = [];
    const mergeAll = state.sortBy.startsWith("all-");
    if (!mergeAll) {
      // Keep Holdings pinned on top and sort within each section
      const holdingsGroup = sortItemsWithinGroup(list.filter((it) => it.isHolding));
      const watchGroup = sortItemsWithinGroup(list.filter((it) => !it.isHolding));

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
    } else {
      const mergedSorted = sortItemsWithinGroup(list);
      htmlParts.push(mergedSorted.map(buildSingleRowHtml).join(""));
    }

    elWatchlistRows.innerHTML = htmlParts.join("");
    hydrateUntranslatedDom();
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
      elFlashUpdatedNote.textContent = `嚴選美國前 30 大科技股 ＆ 聯準會升降息/政策衝擊 · 最新掃描：${state.flashData.updatedAtTW} (每3分)`;
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
          <span class="flash-tape-title js-zh-guard">${escapeHtml(it.title)}</span>
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
            <span class="js-zh-guard">${escapeHtml(it.title)}</span>
            <span class="headline-age">(${escapeHtml(it.age)})</span>
            <a class="source-link" href="${escapeHtml(it.url)}" target="_blank" rel="noopener noreferrer">[${escapeHtml(it.source)} ↗]</a>
          </div>
        </li>
      `
      )
      .join("");
  }

  // Client-side safety net: auto-translates any news title/summary that still contains untranslated English sentences
  const clientZhCache = new Map();
  const ALLOWED_EN_SET = new Set([
    "ai", "agi", "llm", "gpu", "cpu", "tpu", "npu", "asic", "hbm", "hbm3e", "hbm4", "dram", "nand", "cowos",
    "etf", "adr", "ipo", "ceo", "cfo", "coo", "fed", "fomc", "cpi", "pce", "gdp", "sec", "doj", "ftc",
    "aws", "azure", "gcp", "openai", "chatgpt", "gemini", "claude", "llama", "deepseek", "anthropic",
    "apple", "iphone", "ipad", "mac", "macbook", "ios", "microsoft", "windows", "nvidia", "nvda", "blackwell", "rubin",
    "google", "alphabet", "goog", "waymo", "youtube", "meta", "tesla", "tsla", "fsd", "optimus", "cybercab",
    "tsmc", "tsm", "amd", "avgo", "broadcom", "intel", "intc", "micron", "mu", "qualcomm", "qcom",
    "oracle", "orcl", "netflix", "nflx", "salesforce", "crm", "cisco", "csco", "ibm", "palantir", "pltr",
    "spacex", "spcx", "starlink", "uber", "adobe", "adbe", "crowdstrike", "crwd", "linux", "gcc",
    "voo", "qqq", "tqqq", "soxl", "boxx", "iau", "ibit", "uco", "wti", "nymex", "opec", "vix", "nasdaq",
    "vanguard", "russell", "invesco", "proshares", "ishares", "blackrock", "spdr", "vonv", "nyse",
  ]);

  function textNeedsZh(str) {
    if (!str) return false;
    const cjk = (str.match(/[\u4e00-\u9fff]/g) || []).length;
    if (cjk === 0) return /[A-Za-z]{3,}/.test(str);
    const words = (str.match(/[A-Za-z]{2,}/g) || []).map((w) => w.toLowerCase());
    const ordinary = words.filter((w) => !ALLOWED_EN_SET.has(w));
    if (cjk < 4 && ordinary.length >= 2) return true;
    if (ordinary.length >= 4 && ordinary.length > cjk * 0.35) return true;
    const clauses = str.match(/(?:[A-Za-z][A-Za-z0-9'-]*[\s,;:]+){3,}[A-Za-z][A-Za-z0-9'-]*/g) || [];
    for (const cl of clauses) {
      const cw = (cl.match(/[A-Za-z]{2,}/g) || []).map((w) => w.toLowerCase());
      if (cw.filter((w) => !ALLOWED_EN_SET.has(w)).length >= 3) return true;
    }
    return false;
  }

  async function translateChunkClient(chunk) {
    const raw = (chunk || "").trim();
    if (!raw || !textNeedsZh(raw)) return raw;
    if (clientZhCache.has(raw)) return clientZhCache.get(raw);
    try {
      const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q=${encodeURIComponent(raw)}`;
      const resp = await fetch(url);
      if (!resp.ok) return raw;
      const data = await resp.json();
      const zh = (data[0] || [])
        .map((seg) => (seg && seg[0] ? seg[0] : ""))
        .join("")
        .replace(/英偉達/g, "輝達")
        .replace(/美聯儲/g, "聯準會")
        .trim();
      if (zh && /[\u4e00-\u9fff]/.test(zh)) {
        clientZhCache.set(raw, zh);
        return zh;
      }
    } catch {
      // Ignore transient client fetch error
    }
    return raw;
  }

  async function translateTextClient(raw) {
    const trimmed = (raw || "").trim();
    if (!trimmed || !textNeedsZh(trimmed)) return trimmed;
    let out = await translateChunkClient(trimmed);
    if (textNeedsZh(out)) {
      const parts = out.split(/(?<=[。！？.!?])\s*/).filter(Boolean);
      if (parts.length > 1) {
        const fixed = [];
        for (const p of parts) {
          fixed.push(textNeedsZh(p) ? await translateChunkClient(p) : p);
        }
        out = fixed.join(" ").trim();
        clientZhCache.set(trimmed, out);
      }
    }
    return out;
  }

  async function sanitizeDataTranslations() {
    const tasks = [];
    const queueField = (obj, key) => {
      if (obj && typeof obj[key] === "string" && textNeedsZh(obj[key])) {
        tasks.push(
          translateTextClient(obj[key]).then((zh) => {
            obj[key] = zh;
          })
        );
      }
    };

    if (state.flashData?.items) {
      for (const it of state.flashData.items) queueField(it, "title");
    }
    if (state.insightsData?.marketHeadlines) {
      for (const h of state.insightsData.marketHeadlines) {
        queueField(h, "title");
        queueField(h, "summary");
      }
    }
    if (state.insightsData?.stocks) {
      for (const st of Object.values(state.insightsData.stocks)) {
        for (const h of st.headlines || []) {
          queueField(h, "title");
          queueField(h, "summary");
        }
      }
    }
    if (tasks.length > 0) {
      await Promise.all(tasks);
    }
  }

  async function hydrateUntranslatedDom() {
    const nodes = Array.from(document.querySelectorAll(".js-zh-guard"));
    for (const el of nodes) {
      const raw = (el.textContent || "").trim();
      if (!textNeedsZh(raw)) continue;
      const zh = await translateTextClient(raw);
      if (zh && zh !== raw) el.textContent = zh;
    }
  }

  function pickFresherPayload(...candidates) {
    let best = null;
    let bestTs = -1;
    for (const c of candidates) {
      if (!c || typeof c !== "object") continue;
      const ts = Date.parse(c.generatedAt || "") || 0;
      if (ts > bestTs) {
        bestTs = ts;
        best = c;
      }
    }
    return best;
  }

  async function fetchJsonSafe(url) {
    try {
      const resp = await fetch(url, { cache: "no-store" });
      if (!resp.ok) return null;
      return await resp.json();
    } catch {
      return null;
    }
  }

  const CNBC_INDEX_MAP = {
    "^DJI": ".DJI",
    "^IXIC": ".IXIC",
    "^GSPC": ".SPX",
  };

  const CNBC_STOCK_MAP = {
    "CL=F": "@CL.1",
    "^VIX": ".VIX",
  };

  function round2(n) {
    return Math.round(Number(n) * 100) / 100;
  }

  function parseCnbcNum(val) {
    if (val === null || val === undefined || val === "") return null;
    const cleaned = String(val).replace(/[,%]/g, "").trim();
    if (!cleaned) return null;
    const n = Number.parseFloat(cleaned);
    return Number.isFinite(n) ? n : null;
  }

  function formatEtDateStr(ms) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date(ms));
    const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    return `${m.year}-${m.month}-${m.day}`;
  }

  function formatEtHmStr(ms) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(ms));
    const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    return `${m.hour}:${m.minute}`;
  }

  function formatTwFullStr(ms) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(ms));
    const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    return `${m.year}-${m.month}-${m.day} ${m.hour}:${m.minute}:${m.second}`;
  }

  function formatTwShortStr(ms) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Taipei",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(ms));
    const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    return `${m.month}/${m.day} ${m.hour}:${m.minute}`;
  }

  function getEtSessionCodeNow() {
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
      const wd = m.weekday;
      const hm = parseInt(m.hour, 10) * 60 + parseInt(m.minute, 10);
      if (wd === "Sat") return "WEEKEND";
      if (wd === "Sun") return hm >= 1200 ? "OVERNIGHT" : "WEEKEND";
      if (hm < 240) return "OVERNIGHT";
      if (hm < 570) return "PRE";
      if (hm < 960) return "REGULAR";
      if (hm < 1200) return "POST";
      return wd === "Fri" ? "WEEKEND" : "OVERNIGHT";
    } catch {
      return "REGULAR";
    }
  }

  async function fetchCnbcIntradayIndexBars(cnbcSym, targetDateStr, closePrice, prevClose, lastTimeET, isLive, quoteTs) {
    try {
      const startYmd = formatEtDateStr(Date.now() - 5 * 86400_000).replace(/-/g, "");
      const endYmd = formatEtDateStr(Date.now() + 86400_000).replace(/-/g, "");
      const url = `https://ts-api.cnbc.com/harmony/app/bars/${encodeURIComponent(cnbcSym)}/5M/${startYmd}093000/${endYmd}160500/adjusted/EST5EDT.json?_=${Date.now()}`;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 4500);
      const resp = await fetch(url, { cache: "no-store", signal: ctrl.signal });
      clearTimeout(timer);
      if (!resp.ok) return null;
      const data = await resp.json();
      const rawBars = data?.barData?.priceBars;
      if (!Array.isArray(rawBars) || !rawBars.length) return null;

      const byYmd = new Map();
      for (const b of rawBars) {
        const tt = String(b.tradeTime || "");
        if (tt.length < 12) continue;
        const ymd = tt.slice(0, 8);
        const hhmmss = tt.slice(8, 14).padEnd(6, "0");
        if (hhmmss < "093000" || hhmmss > "160000") continue;
        const closeVal = Number.parseFloat(b.close);
        if (!Number.isFinite(closeVal) || closeVal <= 0) continue;
        const dtCheck = new Date(`${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}T12:00:00Z`);
        const dow = dtCheck.getUTCDay();
        if (dow === 0 || dow === 6) continue;
        if (!byYmd.has(ymd)) byYmd.set(ymd, []);
        byYmd.get(ymd).push({
          t: Math.floor((Number(b.tradeTimeinMills) || Date.now()) / 1000),
          et: `${tt.slice(8, 10)}:${tt.slice(10, 12)}`,
          p: round2(closeVal),
        });
      }

      if (!byYmd.size) return null;
      const wantedYmd = (targetDateStr || "").replace(/-/g, "");
      const sortedYmds = Array.from(byYmd.keys()).sort();
      const chosenYmd = byYmd.has(wantedYmd) ? wantedYmd : sortedYmds[sortedYmds.length - 1];
      const pts = byYmd.get(chosenYmd) || [];
      if (!pts.length) return null;

      if (isLive) {
        const tail = pts[pts.length - 1];
        if (Math.abs(tail.p - closePrice) > 0.005 || tail.et !== lastTimeET) {
          pts.push({ t: quoteTs || tail.t + 60, et: lastTimeET || tail.et, p: closePrice });
        }
        if (pts.length === 1) {
          pts.unshift({ t: (quoteTs || Date.now() / 1000) - 60, et: "09:30", p: prevClose || closePrice });
        }
      } else if (Math.abs(pts[pts.length - 1].p - closePrice) > 0.01) {
        pts.push({ t: pts[pts.length - 1].t + 60, et: "16:00", p: closePrice });
      }

      return {
        sessionDate: `${chosenYmd.slice(0, 4)}-${chosenYmd.slice(4, 6)}-${chosenYmd.slice(6, 8)}`,
        points: pts,
      };
    } catch {
      return null;
    }
  }

  async function applyRealtimeBrowserQuotes(quotesObj) {
    if (!quotesObj || typeof quotesObj !== "object") return false;
    try {
      const idxList = quotesObj.indices || [];
      const watchList = quotesObj.watchlist || [];
      const cnbcSymbols = [
        ...idxList.map((idx) => CNBC_INDEX_MAP[idx.symbol] || idx.symbol),
        ...watchList.map((st) => CNBC_STOCK_MAP[st.symbol] || st.symbol),
      ];
      if (!cnbcSymbols.length) return false;

      const url =
        "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=" +
        encodeURIComponent(cnbcSymbols.join("|")) +
        `&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1&_=${Date.now()}`;

      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 4500);
      const resp = await fetch(url, { cache: "no-store", signal: ctrl.signal });
      clearTimeout(timer);
      if (!resp.ok) return false;

      const payload = await resp.json();
      const rawQuotes = payload?.FormattedQuoteResult?.FormattedQuote;
      if (!Array.isArray(rawQuotes) || !rawQuotes.length) return false;

      const qBySym = new Map();
      for (const rq of rawQuotes) {
        if (rq?.symbol) qBySym.set(String(rq.symbol).toUpperCase(), rq);
      }

      let anyUpdated = false;
      const etSessionNow = getEtSessionCodeNow();

      // 1. Update Three Major US Indices + fetch real-time 5M intraday charts in parallel
      const barTasks = [];
      for (const idxObj of idxList) {
        const cSym = (CNBC_INDEX_MAP[idxObj.symbol] || idxObj.symbol).toUpperCase();
        const cq = qBySym.get(cSym);
        if (!cq) continue;

        const regPrice = parseCnbcNum(cq.last);
        const regMs = cq.last_time ? Date.parse(cq.last_time) : 0;
        const regTs = regMs ? Math.floor(regMs / 1000) : 0;
        if (regPrice === null) continue;

        const mktStatus = String(cq.curmktstatus || "").toUpperCase();
        const isLive = mktStatus === "REG_MKT";
        const cnbcDate = regMs ? formatEtDateStr(regMs) : idxObj.sessionDate;
        const cnbcHm = regMs ? formatEtHmStr(regMs) : idxObj.lastTimeET || "16:00";

        if (regTs >= (idxObj.quoteTs || 0) - 5 || cnbcDate > (idxObj.sessionDate || "")) {
          const prevC = parseCnbcNum(cq.previous_day_closing) ?? idxObj.prevClose ?? regPrice;
          const chg = parseCnbcNum(cq.change) ?? regPrice - prevC;
          const chgPct = parseCnbcNum(cq.change_pct) ?? (prevC ? (chg / prevC) * 100 : 0);
          const hi = parseCnbcNum(cq.high);
          const lo = parseCnbcNum(cq.low);

          idxObj.close = round2(regPrice);
          idxObj.prevClose = round2(prevC);
          idxObj.change = round2(chg);
          idxObj.changePct = round2(chgPct);
          idxObj.high = round2(hi !== null ? Math.max(hi, regPrice) : Math.max(idxObj.high || regPrice, regPrice));
          idxObj.low = round2(lo !== null ? Math.min(lo, regPrice) : Math.min(idxObj.low || regPrice, regPrice));
          idxObj.isUp = idxObj.change >= 0;
          idxObj.sessionDate = cnbcDate;
          idxObj.isLive = isLive;
          idxObj.statusLabel = isLive ? "盤中即時" : "收盤";
          idxObj.lastTimeET = isLive ? cnbcHm : "16:00";
          idxObj.quoteTs = regTs;
          anyUpdated = true;

          barTasks.push(
            fetchCnbcIntradayIndexBars(cSym, cnbcDate, idxObj.close, idxObj.prevClose, idxObj.lastTimeET, isLive, regTs).then(
              (barRes) => {
                if (barRes?.points?.length >= 2) {
                  idxObj.sessionDate = barRes.sessionDate;
                  idxObj.points = barRes.points;
                }
              }
            )
          );
        }
      }

      // 2. Update all 21 Watchlist stocks/ETFs/futures (preserving fresher Yahoo Overnight quotes during 20:00-04:00 ET)
      for (const st of watchList) {
        const cSym = (CNBC_STOCK_MAP[st.symbol] || st.symbol).toUpperCase();
        const cq = qBySym.get(cSym);
        if (!cq) continue;

        const regPrice = parseCnbcNum(cq.last);
        const regMs = cq.last_time ? Date.parse(cq.last_time) : 0;
        const regTs = regMs ? Math.floor(regMs / 1000) : 0;
        if (regPrice === null) continue;

        const prevClose = parseCnbcNum(cq.previous_day_closing) ?? st.prevClose ?? regPrice;
        const regChg = parseCnbcNum(cq.change) ?? regPrice - prevClose;
        const regChgPct = parseCnbcNum(cq.change_pct) ?? (prevClose ? (regChg / prevClose) * 100 : 0);
        const mktStatus = String(cq.curmktstatus || "").toUpperCase();

        let bestTs = regTs;
        let bestPrice = regPrice;
        let bestSession = mktStatus === "REG_MKT" ? "盤中" : "收盤";
        let useExtended = false;

        const ext = cq.ExtendedMktQuote;
        if (ext && mktStatus !== "REG_MKT" && st.symbol !== "^VIX" && st.symbol !== "CL=F") {
          const extP = parseCnbcNum(ext.last);
          const extMs = ext.last_time ? Date.parse(ext.last_time) : 0;
          const extTs = extMs ? Math.floor(extMs / 1000) : 0;
          if (extP !== null && extTs > regTs + 10) {
            bestTs = extTs;
            bestPrice = extP;
            const extType = String(ext.type || "").toUpperCase();
            bestSession = extType.includes("PRE") ? "盤前" : "盤後";
            useExtended = true;
          }
        }

        if (st.symbol === "CL=F") {
          if (mktStatus === "REG_MKT") {
            if (etSessionNow === "OVERNIGHT") bestSession = "期貨夜盤";
            else if (etSessionNow === "PRE") bestSession = "期貨盤前";
            else bestSession = "期貨盤中";
          } else {
            bestSession = "期貨收盤";
          }
        } else if (st.symbol === "^VIX") {
          bestSession = mktStatus === "REG_MKT" ? "盤中" : "收盤";
        }

        // Only apply if CNBC quote is at least as fresh as existing quoteTs (preserves Blue Ocean ATS 夜盤!)
        if (bestTs >= (st.quoteTs || 0) - 5) {
          let chg = regChg;
          let chgPct = regChgPct;
          let extDiffPct = null;

          if (useExtended) {
            extDiffPct = parseCnbcNum(ext.change_pct) ?? (regPrice ? ((bestPrice - regPrice) / regPrice) * 100 : 0);
            if (bestSession === "盤前") {
              chg = parseCnbcNum(ext.change) ?? bestPrice - regPrice;
              chgPct = extDiffPct;
            } else {
              const base = prevClose || regPrice;
              chg = bestPrice - base;
              chgPct = base ? (chg / base) * 100 : 0;
            }
          }

          const hi = parseCnbcNum(cq.high);
          const lo = parseCnbcNum(cq.low);

          st.price = round2(bestPrice);
          st.prevClose = round2(prevClose);
          st.regularPrice = round2(regPrice);
          st.regularChangePct = round2(regChgPct);
          st.change = round2(chg);
          st.changePct = round2(chgPct);
          st.extChangePct = extDiffPct !== null ? round2(extDiffPct) : null;
          st.isUp = st.changePct >= 0;
          st.session = bestSession;
          st.quoteTs = bestTs;
          if (bestTs > 0) st.updatedAt = formatTwShortStr(bestTs * 1000);
          if (hi !== null) st.dayHigh = round2(Math.max(hi, bestPrice));
          if (lo !== null) st.dayLow = round2(Math.min(lo, bestPrice));

          if (Array.isArray(st.sparkline) && st.sparkline.length >= 2) {
            st.sparkline[st.sparkline.length - 1] = st.price;
          }
          anyUpdated = true;
        }
      }

      if (barTasks.length > 0) {
        await Promise.all(barTasks);
      }

      if (anyUpdated) {
        quotesObj.updatedAtTW = formatTwFullStr(Date.now());
      }
      return anyUpdated;
    } catch {
      return false;
    }
  }

  async function resolveLiveRawBaseUrl(isManual = false) {
    const cacheKey = "us_watch_live_sha_v1";
    if (!isManual) {
      try {
        const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
        if (cached?.sha && Date.now() - cached.ts < 45_000) {
          return `https://raw.githubusercontent.com/${LIVE_REPO}/${cached.sha}/data`;
        }
      } catch {
        // ignore storage error
      }
    }

    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 3000);
      const refUrl = `https://api.github.com/repos/${LIVE_REPO}/commits?sha=${LIVE_BRANCH}&per_page=1&_=${Date.now()}`;
      const resp = await fetch(refUrl, { cache: "no-store", signal: ctrl.signal });
      clearTimeout(timer);
      if (resp.ok) {
        const arr = await resp.json();
        const sha = Array.isArray(arr) && arr[0]?.sha ? arr[0].sha : null;
        if (sha) {
          try {
            localStorage.setItem(cacheKey, JSON.stringify({ sha, ts: Date.now() }));
          } catch {
            // ignore storage quota
          }
          return `https://raw.githubusercontent.com/${LIVE_REPO}/${sha}/data`;
        }
      }
    } catch {
      // fallback to jsDelivr + branch raw URL if GitHub API rate-limited
    }
    return `https://raw.githubusercontent.com/${LIVE_REPO}/${LIVE_BRANCH}/data`;
  }

  async function loadAllData(isManual = false) {
    if (state.isRefreshing) return;
    state.isRefreshing = true;
    elBtnRefresh.disabled = true;
    elRefreshText.textContent = "即時同步中…";

    try {
      const bust = Date.now();
      const jsDelivrBase = `https://cdn.jsdelivr.net/gh/${LIVE_REPO}@${LIVE_BRANCH}/data`;
      if (isManual) {
        await Promise.race([
          fetch(`https://purge.jsdelivr.net/gh/${LIVE_REPO}@${LIVE_BRANCH}/data/quotes.json`, { cache: "no-store" }).catch(
            () => {}
          ),
          new Promise((r) => setTimeout(r, 350)),
        ]);
      }

      const localPromises = Promise.all([
        fetchJsonSafe(`./data/quotes.json?t=${bust}`),
        fetchJsonSafe(`./data/insights.json?t=${bust}`),
        fetchJsonSafe(`./data/flash.json?t=${bust}`),
      ]);

      const cdnPromises = Promise.all([
        fetchJsonSafe(`${jsDelivrBase}/quotes.json?t=${bust}`),
        fetchJsonSafe(`${jsDelivrBase}/insights.json?t=${bust}`),
        fetchJsonSafe(`${jsDelivrBase}/flash.json?t=${bust}`),
      ]);

      const [[localQ, localI, localF], [cdnQ, cdnI, cdnF]] = await Promise.all([localPromises, cdnPromises]);

      let liveQ = null;
      let liveI = null;
      let liveF = null;
      if (!cdnQ) {
        const liveBase = await resolveLiveRawBaseUrl(isManual);
        const isShaUrl = !liveBase.endsWith(`/${LIVE_BRANCH}/data`);
        const qSuffix = isShaUrl ? "" : `?t=${bust}`;
        [liveQ, liveI, liveF] = await Promise.all([
          fetchJsonSafe(`${liveBase}/quotes.json${qSuffix}`),
          fetchJsonSafe(`${liveBase}/insights.json${qSuffix}`),
          fetchJsonSafe(`${liveBase}/flash.json${qSuffix}`),
        ]);
      }

      const nextBaseQ = pickFresherPayload(cdnQ, liveQ, localQ, state.baseQuotesData);
      const nextI = pickFresherPayload(cdnI, liveI, localI, state.insightsData);
      const nextF = pickFresherPayload(cdnF, liveF, localF, state.flashData);

      if (nextBaseQ) {
        state.baseQuotesData = nextBaseQ;
        const workingQ = JSON.parse(JSON.stringify(nextBaseQ));
        state.realtimeActive = await applyRealtimeBrowserQuotes(workingQ);
        state.quotesData = workingQ;
      }
      if (nextI) state.insightsData = nextI;
      if (nextF) state.flashData = nextF;

      await sanitizeDataTranslations();

      renderHeaderMeta();
      renderFlashWire();
      renderIndices();
      renderMarketHeadlines();
      renderWatchlist();
      renderCioAdvisory();
      await hydrateUntranslatedDom();
      state.secondsLeft = REFRESH_INTERVAL_SEC;
    } catch (err) {
      console.error("Failed to load watchlist data:", err);
    } finally {
      state.isRefreshing = false;
      elBtnRefresh.disabled = false;
      updateCountdownLabel();
      if (isManual) {
        elRefreshText.textContent = "已即時更新 ✓";
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

  const colCycleMap = {
    change: ["change-desc", "change-asc", "default"],
    price: ["price-desc", "price-asc", "default"],
    sentiment: ["buy-desc", "sell-desc", "default"],
    symbol: ["symbol-asc", "symbol-desc", "default"],
  };

  function toggleColumnSort(col) {
    const cycle = colCycleMap[col];
    if (!cycle) return;
    const normalizedCur = state.sortBy.startsWith("all-")
      ? state.sortBy.replace("all-", "")
      : state.sortBy;
    const curIdx = cycle.indexOf(normalizedCur);
    state.sortBy = curIdx === -1 ? cycle[0] : cycle[(curIdx + 1) % cycle.length];
    renderWatchlist();
  }

  if (elColHeader) {
    elColHeader.addEventListener("click", (e) => {
      const hdr = e.target.closest("[data-sort-col]");
      if (!hdr) return;
      toggleColumnSort(hdr.dataset.sortCol);
    });

    elColHeader.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const hdr = e.target.closest("[data-sort-col]");
      if (!hdr) return;
      e.preventDefault();
      toggleColumnSort(hdr.dataset.sortCol);
    });
  }

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
