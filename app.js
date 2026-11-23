(() => {
  "use strict";

  const FAST_QUOTE_INTERVAL_SEC = 8;
  const FULL_SYNC_INTERVAL_SEC = 60;
  const LIVE_DATA_SYNC_TICKS = 3; // every 3 × 8s = 24s also check fresh live-data (for US Overnight & TW TWSE 5s)
  const LIVE_REPO = "EgoTsai/us-stock-watch";
  const LIVE_BRANCH = "live-data";

  const urlParams = new URLSearchParams(window.location.search);
  const initialMarket =
    urlParams.get("market") === "tw" || window.location.hash === "#tw"
      ? "tw"
      : urlParams.get("market") === "us" || window.location.hash === "#us"
      ? "us"
      : localStorage.getItem("stock_watch_market") || "us";

  const state = {
    market: initialMarket === "tw" ? "tw" : "us",
    cache: {
      us: { baseQuotes: null, quotes: null, insights: null, flash: null, realtime: false },
      tw: { baseQuotes: null, quotes: null, insights: null, flash: null, realtime: false },
    },
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
    secondsLeft: FAST_QUOTE_INTERVAL_SEC,
    fullSyncSecondsLeft: FULL_SYNC_INTERVAL_SEC,
    fastTickCount: 0,
    isRefreshing: false,
    isFastTicking: false,
    realtimeActive: false,
  };

  // DOM Elements
  const elBrandTitle = document.getElementById("brand-title-text");
  const elBtnMarketUs = document.getElementById("btn-market-us");
  const elBtnMarketTw = document.getElementById("btn-market-tw");
  const elBtnQuickSwitch = document.getElementById("btn-quick-switch-market");
  const elStatusDot = document.getElementById("market-status-dot");
  const elStatusText = document.getElementById("market-status-text");
  const elQuotesUpdated = document.getElementById("quotes-updated-label");
  const elInsightsUpdated = document.getElementById("insights-updated-label");
  const elBtnRefresh = document.getElementById("btn-refresh-now");
  const elRefreshText = document.getElementById("refresh-btn-text");
  const elBtnExpandAll = document.getElementById("btn-expand-all");
  const elBtnTheme = document.getElementById("btn-theme-toggle");
  const elFlashLabelTitle = document.getElementById("flash-label-title");
  const elFlashTrack = document.getElementById("flash-marquee-track");
  const elBtnFlashPause = document.getElementById("btn-flash-pause");
  const elBtnFlashDrawer = document.getElementById("btn-flash-drawer");
  const elFlashDrawerBtnText = document.getElementById("flash-drawer-btn-text");
  const elFlashDrawer = document.getElementById("flash-wire-drawer");
  const elFlashPillUrgent = document.getElementById("flash-pill-urgent");
  const elFlashPillHoldings = document.getElementById("flash-pill-holdings");
  const elFlashUpdatedNote = document.getElementById("flash-updated-note");
  const elFlashTimeline = document.getElementById("flash-timeline-list");
  const flashFilterButtons = Array.from(document.querySelectorAll(".flash-filter-pill"));
  const elHeadingIndices = document.getElementById("heading-indices");
  const elIndicesSubtitle = document.getElementById("indices-subtitle");
  const elIndicesContainer = document.getElementById("indices-container");
  const elHeadingHeadlines = document.getElementById("heading-headlines");
  const elMarketHeadlines = document.getElementById("market-headlines-list");
  const elHeadingWatchlist = document.getElementById("heading-watchlist");
  const elWatchlistSubtitle = document.getElementById("watchlist-subtitle");
  const elWatchlistFilterTabs = document.getElementById("watchlist-filter-tabs");
  const elWatchlistRows = document.getElementById("watchlist-rows-container");
  const elHeadingCio = document.getElementById("heading-cio");
  const elCioSubtitle = document.getElementById("cio-subtitle");
  const elCioContainer = document.getElementById("cio-advisory-container");
  const elFooterColorRule = document.getElementById("footer-color-rule");
  const elFooterScheduleNote = document.getElementById("footer-schedule-note");
  const elSearchInput = document.getElementById("search-ticker-input");
  const elSortSelect = document.getElementById("sort-watchlist-select");
  const elColHeader = document.getElementById("moomoo-col-header");
  const colSortHeaders = Array.from(document.querySelectorAll(".col-sortable"));

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

  function getUpDownStroke(isUp) {
    const isTw = state.market === "tw";
    if (isTw) {
      return isUp ? "#ef4444" : "#10b981";
    }
    return isUp ? "#10b981" : "#ef4444";
  }

  function getUpDownRgba(isUp, alpha) {
    const isTw = state.market === "tw";
    const useRed = isTw ? isUp : !isUp;
    return useRed ? `rgba(239, 68, 68, ${alpha})` : `rgba(16, 185, 129, ${alpha})`;
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

  function renderFilterTabsForMarket() {
    if (!elWatchlistFilterTabs) return;
    const rawList = state.quotesData?.watchlist || [];
    const total = rawList.length;
    const holdCnt = rawList.filter((x) => x.isHolding).length;

    let tabsConfig = [];
    if (state.market === "tw") {
      const semiCnt = rawList.filter((x) => x.category === "semi").length;
      const aiCnt = rawList.filter((x) => x.category === "ai").length;
      const etfCnt = rawList.filter((x) => x.category === "etf").length;
      tabsConfig = [
        { id: "tab-all", filter: "all", label: `全部 (${total || 16})` },
        { id: "tab-holdings", filter: "holdings", label: `核心焦點 (${holdCnt || 8})` },
        { id: "tab-semi", filter: "semi", label: `IC設計 / 晶圓封測 (${semiCnt || 5})` },
        { id: "tab-ai", filter: "ai", label: `AI伺服器 / 散熱 (${aiCnt || 7})` },
        { id: "tab-etf", filter: "etf", label: `市值 / 科技 ETF (${etfCnt || 4})` },
      ];
    } else {
      const techCnt = rawList.filter((x) => x.category === "tech").length;
      const semiCnt = rawList.filter((x) => x.category === "semi").length;
      const macroCnt = rawList.filter((x) => x.category === "macro").length;
      tabsConfig = [
        { id: "tab-all", filter: "all", label: `全部 (${total || 21})` },
        { id: "tab-holdings", filter: "holdings", label: `我的持倉 (${holdCnt || 7})` },
        { id: "tab-tech", filter: "tech", label: `科技巨頭 (${techCnt || 5})` },
        { id: "tab-semi", filter: "semi", label: `半導體 (${semiCnt || 7})` },
        { id: "tab-macro", filter: "macro", label: `ETF / 期貨 / 波動率 (${macroCnt || 9})` },
      ];
    }

    if (!tabsConfig.some((t) => t.filter === state.activeFilter)) {
      state.activeFilter = "all";
    }

    elWatchlistFilterTabs.innerHTML = tabsConfig
      .map(
        (t) =>
          `<button type="button" class="tab-btn ${state.activeFilter === t.filter ? "active" : ""}" id="${t.id}" data-filter="${t.filter}">${escapeHtml(t.label)}</button>`
      )
      .join("");
  }

  function applyMarketStaticLabels() {
    const isTw = state.market === "tw";
    document.documentElement.setAttribute("data-market", state.market);
    localStorage.setItem("stock_watch_market", state.market);

    if (elBrandTitle) {
      elBrandTitle.textContent = isTw ? "台股即時觀察站" : "美股即時觀察站";
    }
    document.title = isTw
      ? "台股即時觀察站 — 加權/0050/0052走勢・AI半導體供應鏈・投資長操作建議"
      : "美股即時觀察站 — 三大指數・核心持倉與觀察名單・投資長操作建議";

    if (elBtnMarketUs) elBtnMarketUs.classList.toggle("active", !isTw);
    if (elBtnMarketTw) elBtnMarketTw.classList.toggle("active", isTw);
    if (elBtnQuickSwitch) {
      elBtnQuickSwitch.textContent = isTw ? "⇄ 切換至美股即時觀察站" : "⇄ 切換至台股即時觀察站";
      elBtnQuickSwitch.title = isTw
        ? "一鍵切換回美股即時觀察站（漲綠跌紅）"
        : "一鍵切換至台股即時觀察站（漲紅跌綠）";
    }

    if (elFlashLabelTitle) {
      elFlashLabelTitle.textContent = isTw ? "台股AI・重磅快報" : "科技30・重磅快報";
    }
    if (elFlashPillUrgent) {
      elFlashPillUrgent.textContent = isTw ? "重磅・法說・法人" : "重磅・升降息・當機";
    }
    if (elFlashPillHoldings) {
      elFlashPillHoldings.textContent = isTw ? "關聯AI核心股" : "關聯我的持倉";
    }
    if (elHeadingIndices) {
      elHeadingIndices.textContent = isTw ? "台股大盤與核心市值 / 科技指標走勢" : "美股三大市場走勢與報價";
    }
    if (elHeadingHeadlines) {
      elHeadingHeadlines.textContent = isTw ? "台股頭條重點整理" : "美股頭條重點整理";
    }
    if (elHeadingWatchlist) {
      elHeadingWatchlist.textContent = isTw
        ? "AI 與半導體供應鏈＋市值型 ETF 觀察名單（核心焦點置頂）"
        : "核心觀察名單（持倉優先置頂）";
    }
    if (elWatchlistSubtitle) {
      elWatchlistSubtitle.textContent = isTw
        ? "每 8 秒自動即時同步台股盤中報價（證交所官方源 45 秒極速校正，按「立即更新」秒級直連） · 點擊橫列展開 6H 頭條"
        : "每 8 秒自動即時同步盤前 / 盤中 / 盤後價（夜盤 45 秒極速同步，按「立即更新」秒級直連） · 點擊橫列展開 6H 頭條";
    }
    if (elHeadingCio) {
      elHeadingCio.textContent = isTw
        ? "投資長 (CIO & CRO) 台股 AI 供應鏈＆ETF 操作建議"
        : "投資長 (CIO & CRO) 觀察名單前 6 大操作建議";
    }
    if (elCioSubtitle) {
      elCioSubtitle.textContent = isTw
        ? "依據加權指數、台積電 ADR 溢價、外資動向與 AI 伺服器供應鏈位階動態更新"
        : "動態掃描觀察名單即時價位、52週位階、6H頭條情緒與 VIX 波動率，精選前 6 大操作焦點（不綁定個人持倉）";
    }
    if (elFooterColorRule) {
      elFooterColorRule.innerHTML = isTw
        ? `台股規範：<strong style="color: var(--up-text)">紅色＝上漲 / 想買居多</strong> · <strong style="color: var(--down-text)">綠色＝下跌 / 想賣居多</strong>`
        : `美股規範：<strong style="color: var(--up-text)">綠色＝上漲 / 想買居多</strong> · <strong style="color: var(--down-text)">紅色＝下跌 / 想賣居多</strong>`;
    }
    if (elFooterScheduleNote) {
      elFooterScheduleNote.textContent = isTw
        ? "排程：瀏覽器每 8 秒即時跳價 · 後台每 45 秒同步台股證交所官方行情 · 6H 頭條與投資長建議每 6 小時更新"
        : "排程：瀏覽器每 8 秒即時跳價 · 後台每 45 秒同步美股夜盤與盤前/盤後 · 6H 頭條與投資長建議定時更新";
    }
  }

  async function switchMarket(targetMarket) {
    const next = targetMarket === "tw" ? "tw" : "us";
    if (state.market === next && state.quotesData) return;

    state.market = next;
    state.activeFilter = "all";
    state.expandedSymbols.clear();
    applyMarketStaticLabels();

    const cached = state.cache[next];
    if (cached && cached.quotes) {
      state.baseQuotesData = cached.baseQuotes;
      state.quotesData = cached.quotes;
      state.insightsData = cached.insights;
      state.flashData = cached.flash;
      state.realtimeActive = cached.realtime;
      renderFilterTabsForMarket();
      renderHeaderMeta();
      renderFlashWire();
      renderIndices();
      renderMarketHeadlines();
      renderWatchlist();
      renderCioAdvisory();
      await hydrateUntranslatedDom();
      loadAllData(false);
    } else {
      await loadAllData(false);
    }
  }

  function sessionBadgeClass(sessionStr) {
    if (!sessionStr) return "post";
    if (sessionStr.includes("夜盤")) return "overnight";
    if (sessionStr.includes("盤前") || sessionStr.includes("試撮")) return "pre";
    if (sessionStr.includes("盤中")) return "regular";
    return "post";
  }

  function computeLiveMarketStatus() {
    if (state.market === "tw") {
      try {
        const now = new Date();
        const parts = new Intl.DateTimeFormat("en-US", {
          timeZone: "Asia/Taipei",
          weekday: "short",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).formatToParts(now);
        const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
        const wd = map.weekday;
        const hm = parseInt(map.hour, 10) * 60 + parseInt(map.minute, 10);

        if (wd === "Sat" || wd === "Sun") {
          return { text: "台股週末休市 · 顯示最新收盤報價", active: false };
        }
        if (hm >= 510 && hm < 540) {
          return { text: "台股盤前試撮合中 (08:30–09:00 TW)", active: true };
        }
        if (hm >= 540 && hm < 810) {
          return { text: "台股正規盤交易中 (09:00–13:30 TW)", active: true };
        }
        if (hm >= 810 && hm < 870) {
          return { text: "台股盤後定價交易中 (13:30–14:30 TW)", active: false };
        }
        return { text: "台股已收盤 · 顯示最新收盤與美股ADR連動", active: false };
      } catch {
        return {
          text: state.quotesData?.marketSession?.statusText || "台股市場監控中",
          active: false,
        };
      }
    }

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
      const modeTag = state.realtimeActive ? "(8秒即時)" : "(45秒極速同步)";
      elQuotesUpdated.textContent = `股價更新：${state.quotesData.updatedAtTW} ${modeTag}`;
    }
    if (state.insightsData?.updatedAtTW) {
      elInsightsUpdated.textContent =
        state.market === "tw"
          ? `頭條/情緒：${state.insightsData.updatedAtTW} (6H同步)`
          : `頭條/情緒：${state.insightsData.updatedAtTW} (6H/開盤前10分)`;
    }
  }

  function parseSessionMinutesFromOpen(hmStr, isTw = false) {
    if (!hmStr || typeof hmStr !== "string" || !hmStr.includes(":")) return null;
    const [hh, mm] = hmStr.split(":").map((n) => parseInt(n, 10));
    if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
    if (isTw) {
      return Math.max(0, Math.min(270, hh * 60 + mm - 540));
    }
    return Math.max(0, Math.min(390, hh * 60 + mm - 570));
  }

  // 1. Three Major Indices (US or TW)
  function renderIndices() {
    const indices = state.quotesData?.indices || [];
    if (!indices.length) return;

    const isTw = state.market === "tw";
    const tzTag = isTw ? "TW" : "ET";
    const ruleTag = isTw ? "漲紅跌綠" : "漲綠跌紅";
    const sessionRange = isTw ? "09:00–13:30 TW" : "09:30–16:00 ET";
    const sessionDate = indices[0].sessionDate || "";
    const anyLive = indices.some((idx) => idx.isLive);
    const lastHm = indices[0].lastTimeET || "";
    elIndicesSubtitle.textContent = anyLive
      ? `交易日 ${sessionDate} 盤中即時走勢 (${lastHm} ${tzTag} 更新) · ${ruleTag}`
      : `交易日 ${sessionDate} 正規盤收盤走勢 (${sessionRange}) · ${ruleTag}`;

    elIndicesContainer.innerHTML = indices
      .map((idx, i) => {
        const dirClass = idx.isUp ? "up" : "down";
        const statusMetaHtml = idx.isLive
          ? `<span class="live-idx-badge">● 盤中即時 ${escapeHtml(idx.lastTimeET || "")} ${tzTag}</span>`
          : `<span>${escapeHtml(idx.sessionDate)} 收盤</span>`;
        return `
          <article class="index-card" data-idx-symbol="${escapeHtml(idx.symbol)}">
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

    const isTw = state.market === "tw" || idxData.tzLabel === "TW";
    const totalSessionMins = isTw ? 270 : 390;
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
        const m = parseSessionMinutesFromOpen(pts[i]?.et, isTw);
        if (m !== null) {
          return padX + (m / totalSessionMins) * plotW;
        }
      }
      return padX + (i / (pts.length - 1)) * plotW;
    };
    const yAt = (v) => padTop + (1 - (v - minVal) / range) * plotH;

    const isDark = state.theme === "dark";
    const lineColor = getUpDownStroke(idxData.isUp);
    const fillTop = getUpDownRgba(idxData.isUp, isDark ? 0.25 : 0.16);

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
      ctx.fillStyle = getUpDownRgba(idxData.isUp, 0.25);
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
    ctx.fillText(idxData.openHm || (isTw ? "09:00" : "09:30"), padX, h - 3);
    ctx.textAlign = "center";
    ctx.fillText(idxData.midHm || (isTw ? "11:15" : "12:45"), w / 2, h - 3);
    ctx.textAlign = "right";
    ctx.fillText(idxData.closeHm || (isTw ? "13:30" : "16:00"), w - padX, h - 3);

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
        const tz = isTw ? "TW" : "ET";
        tooltip.textContent = `${hp.et} ${tz} · ${formatNumber(hp.p)} (${formatSignedPct(pct)})`;
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
      elMarketHeadlines.innerHTML = `<li class="quiet-note">目前暫無頭條資料。</li>`;
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
    const stroke = getUpDownStroke(isUp);
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
      const topGroupTitle =
        state.market === "tw"
          ? `★ 核心 AI 供應鏈 ＆ 市值型 ETF 焦點 (${holdingsGroup.length})`
          : `★ 我的核心持倉 (${holdingsGroup.length})`;

      if (holdingsGroup.length) {
        htmlParts.push(`
          <div class="moomoo-group-banner">
            <span>${topGroupTitle}</span>
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

  const WATCHLIST_CIO_PROFILES = {
    VOO: {
      role: "S&P 500 大盤核心",
      style: "index",
      pairGroup: "us_index",
      thesis: "美國前 500 大龍頭市值加權基準，拉回即為中長線定期與分批建倉首選。",
    },
    QQQ: {
      role: "那指 100 成長基準",
      style: "index",
      pairGroup: "us_index",
      thesis: "大型科技與 AI 權值指標，適合順勢配置或大盤明顯回檔時分批承接。",
    },
    TQQQ: {
      role: "那指 3 倍做多槓桿",
      style: "leveraged",
      pairGroup: "leveraged",
      thesis: "日內 3 倍複利槓桿具高波動耗損（Volatility Decay），僅宜極短線順勢或止穩後小倉波段。",
    },
    SOXL: {
      role: "費半 3 倍做多槓桿",
      style: "leveraged",
      pairGroup: "leveraged",
      thesis: "半導體 3 倍槓桿日內劇烈震盪，急跌切忌盲目接刀，務必等費半權值止穩再觀察。",
    },
    UCO: {
      role: "原油 2 倍做多槓桿",
      style: "leveraged",
      pairGroup: "oil",
      thesis: "追蹤兩倍原油槓桿與期貨正逆價差損耗，僅適合作為短線事件型通膨避險工具。",
    },
    GOOG: {
      role: "AI 搜尋・雲端 ＆ TPU 核心",
      style: "core_tech",
      pairGroup: null,
      thesis: "自研 TPU 晶片降低外購 GPU 依賴、雲端與搜尋現金流護城河深厚，估值相對具防禦支撐。",
    },
    MSFT: {
      role: "企業雲端與 AI 軟體龍頭",
      style: "core_tech",
      pairGroup: null,
      thesis: "Azure 與企業訂閱現金流穩健，非基本面短期利空引發之急跌往往提供中長線折價買點。",
    },
    META: {
      role: "AI 廣告變現與開源生態",
      style: "core_tech",
      pairGroup: null,
      thesis: "AI 精準廣告推升利潤率與自由現金流，震盪期高 Beta 屬性常創造波段承接與收租空間。",
    },
    TSLA: {
      role: "實體 AI・Robotaxi 高波標的",
      style: "high_beta_tech",
      pairGroup: null,
      thesis: "高隱含波動率 (IV) 與情緒擺盪劇烈，適合紀律區間操作或賣方收租策略，忌追高殺低。",
    },
    SPCX: {
      role: "SpaceX 太空探索主題",
      style: "thematic",
      pairGroup: null,
      thesis: "星鏈與航太龍頭題材彈性極高、同步伴隨估值與融資波動，適合右側順勢小倉參與。",
    },
    TSM: {
      role: "先進製程與 CoWoS 獨佔樞紐",
      style: "core_semi",
      pairGroup: null,
      thesis: "無論 GPU 或雲端巨頭自研 ASIC 誰勝出，3/2 奈米與先進封裝訂單皆由台積電獨攬。",
    },
    NVDA: {
      role: "AI 算力晶片霸主",
      style: "high_beta_semi",
      pairGroup: null,
      thesis: "資料中心算力市佔核心，惟高基期與財測/治理訊息易放大單日振幅，宜等站穩均價再行動。",
    },
    AVGO: {
      role: "客製化 AI ASIC ＆ 網通龍頭",
      style: "core_semi",
      pairGroup: null,
      thesis: "雲端大廠擴大自研 ASIC 與高速光網升級之核心贏家，兼具網通現金流與高韌性。",
    },
    AMD: {
      role: "資料中心 GPU 第二供應商",
      style: "high_beta_semi",
      pairGroup: null,
      thesis: "受惠雲端分散算力採購，但估值對毛利率與伺服器成長預期敏感，宜等均線止穩介入。",
    },
    MU: {
      role: "HBM 高頻寬記憶體循環龍頭",
      style: "high_beta_semi",
      pairGroup: null,
      thesis: "HBM 需求帶動獲利循環同時具高振幅特性，急漲急跌時務必分批節奏操作。",
    },
    INTC: {
      role: "晶圓代工轉型觀察股",
      style: "turnaround",
      pairGroup: null,
      thesis: "先進代工轉型仍處良率與現金流驗證期，波動劇烈且缺乏趨勢護城河，維持低權重追蹤。",
    },
    IAU: {
      role: "實體黃金通膨與避險資產",
      style: "hedge",
      pairGroup: null,
      thesis: "與科技權值相關性低，適合作為實質利率波動與股市震盪期間的資產配置穩定器。",
    },
    IBIT: {
      role: "比特幣現貨 ETF",
      style: "crypto",
      pairGroup: null,
      thesis: "全球美元流動性與風險偏好放大器，振幅遠超納指，宜嚴設部位上限並追蹤 ETF 資金流向。",
    },
    "CL=F": {
      role: "WTI 輕原油宏觀通膨指標",
      style: "commodity",
      pairGroup: "oil",
      thesis: "能源價格直接牽動通膨黏著度與聯準會政策路徑，急漲易壓抑科技成長股估值倍數。",
    },
  };

  const CIO_CATALYST_KEYWORDS = [
    "當機", "癱瘓", "故障", "辭職", "卸任", "換帥", "拒絕", "封殺", "禁令", "出口",
    "關稅", "反壟斷", "訴訟", "調查", "財報", "財測", "上修", "下修", "調升", "降評",
    "融資", "擴建", "13f", "勞資", "暴跌", "飆漲", "風波", "警鐘", "危機", "outage",
    "resign", "ban", "export", "antitrust", "earnings", "guidance", "downgrade", "upgrade", "tariff",
  ];

  const CIO_HEADLINE_NOISE = [
    "油菜籽", "中油", "92無鉛", "95無鉛", "印度 vix", "台股盤中", "連接器大廠", "概念股",
  ];

  function pickCleanCioHeadline(sym, headlines, usedTitles = null) {
    for (const h of headlines || []) {
      const t = String(h?.title || "").trim();
      if (!t) continue;
      if (usedTitles && usedTitles.has(t)) continue;
      const low = t.toLowerCase();
      if (CIO_HEADLINE_NOISE.some((bad) => low.includes(bad))) continue;
      if (
        (sym === "CL=F" || sym === "UCO") &&
        !["原油", "油價", "wti", "opec", "crude", "oil", "brent"].some((k) => low.includes(k))
      ) {
        continue;
      }
      return h;
    }
    return null;
  }

  function buildLiveUsCioAdvisory() {
    const stocksQuotes = state.quotesData?.watchlist || [];
    const indicesData = state.quotesData?.indices || [];
    const stockInsights = state.insightsData?.stocks || {};
    if (!stocksQuotes.length) return state.insightsData?.cioAdvisory || null;

    const sMap = new Map(stocksQuotes.map((s) => [s.symbol, s]));
    const iMap = new Map(indicesData.map((x) => [x.symbol, x]));

    const vixQ = sMap.get("^VIX") || {};
    const vix = Number(vixQ.price) || 18.0;
    const vixChg = Number(vixQ.changePct) || 0.0;
    const spxChg = Number(iMap.get("^GSPC")?.changePct) || 0.0;
    const ixicChg = Number(iMap.get("^IXIC")?.changePct) || 0.0;
    const boxxP = Number(sMap.get("BOXX")?.price) || 119.0;
    const oilQ = sMap.get("CL=F") || {};
    const oilP = Number(oilQ.price) || 0.0;
    const oilChg = Number(oilQ.changePct) || 0.0;

    let regimeTag = "";
    let regimeTone = "neutral";
    let regimeSummary = "";

    if (vix >= 23) {
      regimeTag = `高波動謹慎期 (VIX ${vix.toFixed(2)})`;
      regimeTone = "caution";
      regimeSummary =
        `VIX 處於 ${vix.toFixed(2)} (${formatSignedPct(vixChg)}) 高波動區，標普 ${formatSignedPct(spxChg)}、那指 ${formatSignedPct(ixicChg)}。` +
        `高 IV 環境嚴禁追價 3 倍槓桿 ETF（TQQQ/SOXL），資金宜以 BOXX ($${boxxP.toFixed(2)}) 等類現金作緩衝，僅鎖定觀察名單中具支撐或錯殺之核心標的分批佈局。`;
    } else if (vix >= 18) {
      regimeTag = `震盪分歧・精選標的期 (VIX ${vix.toFixed(2)})`;
      regimeTone = "neutral";
      regimeSummary =
        `VIX 位於 ${vix.toFixed(2)} (${formatSignedPct(vixChg)})，標普 ${formatSignedPct(spxChg)}、那指 ${formatSignedPct(ixicChg)}，市場呈現板塊輪動與事件驅動分化。` +
        `WTI 原油報 $${oilP.toFixed(2)} (${formatSignedPct(oilChg)})；操作上宜依觀察名單前 6 大訊號強弱汰弱留強，避免在震盪中過度擴張槓桿。`;
    } else {
      regimeTag = `低波動順風期 (VIX ${vix.toFixed(2)})`;
      regimeTone = "bull";
      regimeSummary =
        `VIX 回落至 ${vix.toFixed(2)} (${formatSignedPct(vixChg)}) 穩定區間，標普 ${formatSignedPct(spxChg)}、那指 ${formatSignedPct(ixicChg)} 風險偏好健康。` +
        `順勢抱牢大型科技與指數核心標的，槓桿型 ETF 遇急漲則宜紀律落袋調節，不隨市場情緒過度追高。`;
    }

    const scored = [];
    for (const sq of stocksQuotes) {
      const sym = sq.symbol;
      if (sym === "^VIX" || sym === "BOXX") continue;
      const prof = WATCHLIST_CIO_PROFILES[sym];
      if (!prof) continue;

      const price = Number(sq.price) || 0;
      if (price <= 0) continue;
      const prevC = Number(sq.prevClose) || price;
      const chg = Number(sq.changePct) || 0;
      const dayHi = Number(sq.dayHigh) || price;
      const dayLo = Number(sq.dayLow) || price;
      const high52 = Math.max(Number(sq.high52w) || price, price);

      const dd52w = high52 > 0 ? ((price - high52) / high52) * 100.0 : 0.0;
      const rangePct = prevC > 0 && dayHi > dayLo ? ((dayHi - dayLo) / prevC) * 100.0 : 0.0;
      const posInDay = dayHi > dayLo ? (price - dayLo) / (dayHi - dayLo) : 0.5;
      const alphaSpx = chg - spxChg;

      const ins = stockInsights[sym] || {};
      const sent = ins.sentiment || {};
      const buyPct = Number(sent.buyPct ?? 50);
      const sellPct = Number(sent.sellPct ?? 50);
      const allHeadlines = ins.headlines || [];
      const topHl = pickCleanCioHeadline(sym, allHeadlines);

      const style = prof.style;
      let score = Math.min(34.0, Math.abs(chg) * 5.0);

      const isIntradayFade =
        rangePct >= 3.2 && posInDay <= 0.25 && dayHi >= prevC * 1.012 && chg > -4.5;
      const isIntradayRebound =
        rangePct >= 3.2 && posInDay >= 0.75 && dayLo <= prevC * 0.988 && chg < 4.5;
      if (rangePct >= 3.2) {
        score += Math.min(14.0, (rangePct - 2.2) * 3.2);
      }
      if (isIntradayFade || isIntradayRebound) {
        score += 8.0;
      }
      if (Math.abs(alphaSpx) >= 1.2) {
        score += Math.min(14.0, Math.abs(alphaSpx) * 2.5);
      }

      let hasUrgentNews = false;
      if (topHl) {
        const hlLow = String(topHl.title || "").toLowerCase();
        hasUrgentNews = CIO_CATALYST_KEYWORDS.some((k) => hlLow.includes(k));
        if (style === "turnaround" && hlLow.includes("輝達") && Math.abs(chg) < 4.0) {
          hasUrgentNews = false;
        }
        if (hasUrgentNews) score += 16.0;
        else if (topHl.within6h) score += 6.0;
      }

      const maxSent = Math.max(buyPct, sellPct);
      if (maxSent >= 64) score += 8.0;
      if ((chg <= -1.5 && sellPct >= 65) || (chg >= 1.5 && buyPct >= 68)) score += 4.0;

      if (style === "index") {
        if (dd52w <= -5.0 || Math.abs(chg) >= 1.2 || vix >= 22) score += 14.0;
      } else if (style === "core_tech" || style === "core_semi") {
        score += 9.0;
        if (chg <= -1.5 && dd52w <= -5.0 && dd52w >= -32.0) score += 5.0;
      } else if (style === "high_beta_tech" || style === "high_beta_semi") {
        score += 4.0;
        if (sym === "NVDA") score += 6.0;
      } else if (style === "turnaround") {
        score -= 10.0;
      } else if (style === "hedge") {
        if ((vix >= 22 && chg >= 0.5) || Math.abs(chg) >= 2.0) score += 9.0;
      } else if (style === "crypto") {
        if (Math.abs(chg) >= 2.5) score += 6.0;
      } else if (style === "leveraged") {
        if (Math.abs(chg) >= 4.0 || rangePct >= 7.0) score += 6.0;
        else score -= 10.0;
      } else if (style === "commodity") {
        if (Math.abs(chg) >= 2.0) score += 6.0;
        else score -= 6.0;
      }

      let action = "持續追蹤觀察";
      let actionType = "hold";
      let focusTag = "核心觀察";
      let detail = "";

      if (style === "leveraged") {
        if (chg <= -3.5 || (isIntradayFade && rangePct >= 6.0)) {
          action = "高波動警戒・禁追刀";
          actionType = "alert";
          focusTag = "槓桿風控警示";
          detail =
            `單日波幅達 ${rangePct.toFixed(1)}%（區間 $${dayLo.toFixed(2)}–$${dayHi.toFixed(2)}，距 52 週高點 ${dd52w.toFixed(1)}%）。` +
            `在 VIX ${vix.toFixed(2)} 環境下多倍槓桿複利耗損驚人，嚴禁盤中急跌盲目攤平，務必待現股權值止跌出量後再評估。`;
        } else if (chg >= 3.5) {
          action = "急彈調節・落袋減碼";
          actionType = "watch";
          focusTag = "槓桿獲利管理";
          detail =
            `單日強彈 ${formatSignedPct(chg)}（區間 $${dayLo.toFixed(2)}–$${dayHi.toFixed(2)}），短線情緒快速升溫（想買 ${buyPct}%）。` +
            "槓桿 ETF 不宜長抱吃震盪耗損，建議逢急漲分批鎖定利潤、降回常規風險水位。";
        } else {
          action = "極端振幅・控管倉位";
          actionType = rangePct >= 6.0 ? "alert" : "watch";
          focusTag = "槓桿震盪提示";
          detail = `盤中震幅高達 ${rangePct.toFixed(1)}%（報 $${price.toFixed(2)}，距 52 週高點 ${dd52w.toFixed(1)}%）。${prof.thesis}`;
        }
      } else if (style === "index") {
        if (dd52w <= -5.0 && chg <= -1.0) {
          action = "估值修正・分批佈局點";
          actionType = "bull";
          focusTag = "指數分批買點";
          detail =
            `現價 $${price.toFixed(2)} 較 52 週高點 $${high52.toFixed(2)} 已回落 ${dd52w.toFixed(1)}%（今日 ${formatSignedPct(chg)}），進入中長線指數折價擊球區。` +
            `配合 BOXX ($${boxxP.toFixed(2)}) 現金緩衝，適合分 2–3 批紀律承接，保留空間因應 VIX ${vix.toFixed(2)} 餘震。`;
        } else if (dd52w <= -5.0) {
          action = "回測區間・分批承接";
          actionType = "bull";
          focusTag = "指數長線買點";
          detail = `報 $${price.toFixed(2)}（${formatSignedPct(chg)}），仍處 52 週高點下方 ${dd52w.toFixed(1)}% 的中期折價帶。${prof.thesis}建議依預設跌幅階梯分批佈局。`;
        } else if (chg >= 1.5) {
          action = "趨勢健康・勿追價";
          actionType = "hold";
          focusTag = "大盤強勢";
          detail = `單日走強 ${formatSignedPct(chg)}（想買 ${buyPct}%），大盤動能轉佳；建議維持既有配置，待回測均線再行加碼。`;
        } else {
          action = "指數基準・按紀律配置";
          actionType = "hold";
          focusTag = "大盤基準";
          detail = `現報 $${price.toFixed(2)}（${formatSignedPct(chg)}，距 52 週高點 ${dd52w.toFixed(1)}%）。${prof.thesis}`;
        }
      } else if (style === "hedge") {
        if (chg <= -2.0) {
          action = "避險資產回檔・等債息止穩";
          actionType = "watch";
          focusTag = "避險資產異動";
          detail =
            `黃金單日回落 ${formatSignedPct(chg)} 至 $${price.toFixed(2)}（距 52 週高點 ${dd52w.toFixed(1)}%），反映強勢美元與實質利率重定價壓力。` +
            "建議等待美元與殖利率衝高鈍化後，再檢視低相關避險配置比例。";
        } else if (chg >= 1.2) {
          action = "避險買盤點火・發揮保護力";
          actionType = "bull";
          focusTag = "抗震資金流";
          detail = `逆勢走高 ${formatSignedPct(chg)}（領先標普 ${formatSignedPct(alphaSpx)}），發揮與科技股低相關之資產保護功能，可作為組合波動對沖錨點。`;
        } else {
          action = "宏觀對沖觀察";
          actionType = "hold";
          focusTag = "防禦配置";
          detail = `報 $${price.toFixed(2)}（${formatSignedPct(chg)}）。${prof.thesis}`;
        }
      } else if (style === "commodity") {
        if (chg >= 2.0) {
          action = "油價衝高・警覺通膨回溫";
          actionType = "alert";
          focusTag = "宏觀通膨警訊";
          detail = `WTI 原油強升 ${formatSignedPct(chg)} 至 $${price.toFixed(2)}，能源漲勢恐推升通膨預期並壓抑聯準會寬鬆空間，需留意高估值科技股壓抑風險。`;
        } else {
          action = "油價回落・通膨壓力緩解";
          actionType = chg <= -1.5 ? "bull" : "hold";
          focusTag = "能源與通膨訊號";
          detail = `WTI 原油報 $${price.toFixed(2)}（${formatSignedPct(chg)}，距 52 週高點 ${dd52w.toFixed(1)}%），有利緩解終端通膨黏著疑慮，對成長股估值屬正面微風。`;
        }
      } else if (style === "crypto") {
        if (chg <= -3.0) {
          action = "高波回撤・嚴守倉位紀律";
          actionType = "watch";
          focusTag = "加密流動性觀察";
          detail = `單日下跌 ${formatSignedPct(chg)}（距 52 週高點 ${dd52w.toFixed(1)}%），反映高 Beta 流動性資產同步承壓。宜待現貨 ETF 淨流入回穩且日 K 止跌再評估。`;
        } else if (chg >= 3.0) {
          action = "資金回流・防短線震盪";
          actionType = "bull";
          focusTag = "風險偏好領指標";
          detail = `強漲 ${formatSignedPct(chg)} 領先大盤，風險偏好回暖；加密資產波動遠高於股市，建議維持嚴格部位上限與移動風險控管。`;
        } else {
          action = "高波衛星觀察";
          actionType = "hold";
          focusTag = "流動性指標";
          detail = `報 $${price.toFixed(2)}（${formatSignedPct(chg)}）。${prof.thesis}`;
        }
      } else {
        const isMoat = style === "core_tech" || style === "core_semi";
        if (isIntradayFade) {
          action = "開高殺低・嚴禁接刀";
          actionType = "alert";
          focusTag = "盤中反轉警示";
          detail =
            `盤中劇烈反轉，從高點 $${dayHi.toFixed(2)} 回吐至 $${price.toFixed(2)}（低點 $${dayLo.toFixed(2)}，日內振幅 ${rangePct.toFixed(1)}%，距 52 週高點 ${dd52w.toFixed(1)}%）。` +
            `${prof.thesis}短線賣壓尚未宣洩完畢，宜靜待站回日內均價或收盤止穩。`;
        } else if (hasUrgentNews && chg <= -2.0) {
          action = "突發事件・靜待利空沉澱";
          actionType = "alert";
          focusTag = "事件催化警戒";
          detail =
            `受近期新聞事件牽動跌 ${formatSignedPct(chg)}（6H 想賣 ${sellPct}%，距 52 週高點 ${dd52w.toFixed(1)}%）。` +
            `${prof.thesis}事件發酵期切忌搶反彈，待負面影響範圍釐清與量縮止跌再評估。`;
        } else if (chg <= -3.5) {
          if (isMoat) {
            action = "核心股急跌・觀察止跌分批";
            actionType = "watch";
            focusTag = "優質股折價掃描";
            detail =
              `單日重挫 ${formatSignedPct(chg)}（距 52 週高點修正 ${dd52w.toFixed(1)}%，想賣 ${sellPct}%）呈現情緒性宣洩。` +
              `${prof.thesis}待隔日開盤確認不再破低，可評估分批低接或於遠價外支撐區佈局。`;
          } else {
            action = "高波急殺・等止穩訊號";
            actionType = "alert";
            focusTag = "急跌風險警示";
            detail =
              `單日大跌 ${formatSignedPct(chg)}（振幅 ${rangePct.toFixed(1)}%，距 52 週高點 ${dd52w.toFixed(1)}%）。` +
              `${prof.thesis}高彈性個股下殺動能強，切忌左側重壓接刀。`;
          }
        } else if (chg >= 1.8 || (alphaSpx >= 1.2 && chg >= 0.35)) {
          if (chg >= 3.2) {
            action = "強勢急拉・逢回再觀察";
            actionType = "bull";
            focusTag = "強勢領漲焦點";
            detail =
              `放量領漲 ${formatSignedPct(chg)}（跑贏標普 ${formatSignedPct(alphaSpx)}，6H 想買 ${buyPct}%），資金集中度顯著優於大盤。` +
              `${prof.thesis}強勢股宜採回測短期均線分批追蹤，不追盤中高乖離。`;
          } else {
            action = "相對抗跌・資金避風港";
            actionType = "bull";
            focusTag = "相對強勢領頭";
            detail =
              `逆勢表現 ${formatSignedPct(chg)}（超越標普 ${formatSignedPct(alphaSpx)}），展現基本面防禦與買盤韌性（區間 $${dayLo.toFixed(2)}–$${dayHi.toFixed(2)}）。` +
              `${prof.thesis}`;
          }
        } else if (isIntradayRebound) {
          action = "低檔承接・留意翻紅延續";
          actionType = isMoat ? "bull" : "watch";
          focusTag = "日內反彈訊號";
          detail =
            `盤中自低點 $${dayLo.toFixed(2)} 強勢拉起至 $${price.toFixed(2)}（振幅 ${rangePct.toFixed(1)}%），低接買盤積極進駐。` +
            `${prof.thesis}觀察能否站穩當日開盤價確認短線轉強。`;
        } else if (sellPct >= 64 && chg < 0) {
          action = "情緒悲觀・逆向追蹤支撐";
          actionType = "watch";
          focusTag = "情緒極端背離";
          detail =
            `6H 社群情緒偏空（想賣 ${sellPct}%），目前修正 ${formatSignedPct(chg)}（距 52 週高點 ${dd52w.toFixed(1)}%）。` +
            `${prof.thesis}若無基本面惡化，過度悲觀往往孕育短線反彈契機，等待量縮確認即可。`;
        } else {
          action = "關鍵價位觀察";
          actionType = rangePct >= 3.0 ? "watch" : "hold";
          focusTag = "焦點動態";
          detail = `現價 $${price.toFixed(2)}（${formatSignedPct(chg)}，振幅 ${rangePct.toFixed(1)}%，距 52 週高點 ${dd52w.toFixed(1)}%）。${prof.thesis}`;
        }
      }

      scored.push({
        symbol: sym,
        displaySymbol: sq.displaySymbol || sym,
        name: sq.name || sym,
        category: sq.category || "tech",
        price: round2(price),
        changePct: round2(chg),
        dd52w: Number(dd52w.toFixed(1)),
        rangePct: Number(rangePct.toFixed(1)),
        buyPct,
        sellPct,
        role: prof.role,
        pairGroup: prof.pairGroup,
        style,
        focusTag,
        score,
        action,
        actionType,
        detail,
        allHeadlines,
      });
    }

    scored.sort((a, b) => b.score - a.score);

    const selected = [];
    const pairCounts = {};
    let levCount = 0;
    let semiCount = 0;

    const canPick = (it) => {
      if (it.pairGroup && (pairCounts[it.pairGroup] || 0) >= 1) return false;
      if (it.style === "leveraged" && levCount >= 1) return false;
      if (it.category === "semi" && semiCount >= 3) return false;
      return true;
    };

    const commitPick = (it) => {
      selected.push(it);
      if (it.pairGroup) pairCounts[it.pairGroup] = (pairCounts[it.pairGroup] || 0) + 1;
      if (it.style === "leveraged") levCount += 1;
      if (it.category === "semi") semiCount += 1;
    };

    const topIndex = scored.find((it) => it.style === "index");
    if (topIndex && (topIndex.dd52w <= -5.0 || Math.abs(topIndex.changePct) >= 1.2 || vix >= 22)) {
      commitPick(topIndex);
    }

    for (const item of scored) {
      if (selected.some((x) => x.symbol === item.symbol)) continue;
      if (!canPick(item)) continue;
      commitPick(item);
      if (selected.length >= 6) break;
    }

    if (selected.length < 6) {
      for (const item of scored) {
        if (!selected.some((x) => x.symbol === item.symbol)) {
          selected.push(item);
          if (selected.length >= 6) break;
        }
      }
    }

    selected.sort((a, b) => b.score - a.score);

    const usedTitles = new Set();
    const cards = selected.slice(0, 6).map((it, i) => {
      const hl = pickCleanCioHeadline(it.symbol, it.allHeadlines, usedTitles);
      if (hl?.title) usedTitles.add(hl.title);
      return {
        rank: i + 1,
        symbol: it.symbol,
        displaySymbol: it.displaySymbol,
        name: it.name,
        price: it.price,
        changePct: it.changePct,
        dd52w: it.dd52w,
        rangePct: it.rangePct,
        buyPct: it.buyPct,
        sellPct: it.sellPct,
        role: it.role,
        focusTag: it.focusTag,
        title: `${it.displaySymbol} ${it.name} ($${it.price.toFixed(2)})`,
        action: it.action,
        actionType: it.actionType,
        detail: it.detail,
        headlineTitle: hl?.title || "",
        headlineSource: hl?.source || "",
        headlineUrl: hl?.url || "",
      };
    });

    const tradable = stocksQuotes.filter((s) => s.symbol !== "^VIX" && s.symbol !== "BOXX");
    const upCnt = tradable.filter((s) => Number(s.changePct) > 0).length;
    const downCnt = tradable.filter((s) => Number(s.changePct) < 0).length;
    const bestS = [...tradable].sort((a, b) => Number(b.changePct) - Number(a.changePct))[0];
    const worstS = [...tradable].sort((a, b) => Number(a.changePct) - Number(b.changePct))[0];

    const scannerBullets = [];
    if (bestS && worstS) {
      scannerBullets.push(
        `觀察名單廣度：可交易標的 ${tradable.length} 檔中 ${upCnt} 檔上漲 / ${downCnt} 檔下跌` +
          `（最強：${bestS.displaySymbol} ${formatSignedPct(bestS.changePct)} ｜ 最弱：${worstS.displaySymbol} ${formatSignedPct(worstS.changePct)}）。`
      );
    }
    scannerBullets.push(
      `波動與現金基準：VIX 報 ${vix.toFixed(2)} (${formatSignedPct(vixChg)})、停泊基準 BOXX 報 $${boxxP.toFixed(2)}；` +
        "以上前 6 大焦點完全依即時報價、52 週折價與 6H 頭條情緒動態排名，不預設任何個人持股。"
    );

    return {
      regimeTag,
      regimeTone,
      regimeSummary,
      cards,
      scannerBullets,
    };
  }

  // 6. Render CIO & CRO Institutional Tactical Advisory
  function renderCioAdvisory() {
    const cio =
      state.market === "us" && state.quotesData?.watchlist?.length
        ? buildLiveUsCioAdvisory()
        : state.insightsData?.cioAdvisory;

    if (!cio) {
      elCioContainer.innerHTML = `<div class="quiet-note">正在載入投資長專業操作建議…</div>`;
      return;
    }

    const cardsHtml = (cio.cards || [])
      .map((c) => {
        const rankNum = Number(c.rank);
        const hasRank = c.rank !== null && c.rank !== undefined && c.rank !== "" && Number.isFinite(rankNum) && rankNum > 0;
        const rankPill = hasRank
          ? `<span class="cio-rank-pill ${rankNum <= 2 ? "top2" : ""}">TOP ${rankNum}</span>`
          : "";
        const priceChip =
          hasRank && Number.isFinite(Number(c.price))
            ? `<span class="cio-price-chip ${Number(c.changePct) >= 0 ? "up" : "down"}">$${formatNumber(c.price)} (${formatSignedPct(c.changePct)})</span>`
            : "";
        const displayTitle = hasRank && c.displaySymbol
          ? `${escapeHtml(c.displaySymbol)} ${escapeHtml(c.name || "")}`
          : escapeHtml(c.title);

        const dd52Val = Number(c.dd52w || 0);
        const dd52Formatted = Math.abs(dd52Val) < 0.05 ? "0.0%" : `${dd52Val > 0 ? "+" : ""}${dd52Val.toFixed(1)}%`;
        const metaRowHtml = hasRank
          ? `
            <div class="cio-meta-row">
              ${c.focusTag ? `<span class="cio-focus-tag">${escapeHtml(c.focusTag)}</span>` : ""}
              ${c.role ? `<span class="cio-meta-chip">${escapeHtml(c.role)}</span>` : ""}
              <span class="cio-meta-chip">52W ${dd52Formatted}</span>
              <span class="cio-meta-chip">買${Number(c.buyPct ?? 50)}% / 賣${Number(c.sellPct ?? 50)}%</span>
            </div>
          `
          : "";

        const headlineNoteHtml = c.headlineTitle
          ? `
            <div class="cio-headline-note">
              <span>催化頭條：</span>
              ${
                c.headlineUrl
                  ? `<a class="js-zh-guard" href="${escapeHtml(c.headlineUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.headlineTitle)}</a>`
                  : `<span class="js-zh-guard">${escapeHtml(c.headlineTitle)}</span>`
              }
              ${c.headlineSource ? `<span>(${escapeHtml(c.headlineSource)})</span>` : ""}
            </div>
          `
          : "";

        return `
          <article class="cio-action-card">
            <div class="cio-card-head">
              <div class="cio-card-title-group">
                ${rankPill}
                <span class="cio-card-title">${displayTitle}</span>
                ${priceChip}
              </div>
              <span class="cio-stance-pill ${escapeHtml(c.actionType || "hold")}">${escapeHtml(c.action)}</span>
            </div>
            ${metaRowHtml}
            <p class="cio-card-body">${escapeHtml(c.detail)}</p>
            ${headlineNoteHtml}
          </article>
        `;
      })
      .join("");

    const scannerTitle =
      state.market === "us" ? "觀察名單廣度與宏觀基準" : "觀察名單異動與逆向情緒掃描";

    const scannerHtml = (cio.scannerBullets || []).length
      ? `
        <div class="cio-scanner-box">
          <div class="cio-scanner-title">${scannerTitle}</div>
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
    if (tagStr.includes("FED") || tagStr.includes("法人") || item.isMacro) return "macro";
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

  // 0. Render Breaking News Flash Ticker + 7x24 Wire Drawer
  function renderFlashWire() {
    const items = state.flashData?.items || [];
    const totalCount = items.length;
    const isTw = state.market === "tw";

    if (elFlashDrawerBtnText) {
      elFlashDrawerBtnText.textContent = state.flashDrawerOpen
        ? `收合快報 (${totalCount}) ▴`
        : `快報列表 (${totalCount}) ▾`;
    }

    if (elFlashUpdatedNote && state.flashData?.updatedAtTW) {
      elFlashUpdatedNote.textContent = isTw
        ? `嚴選台股 AI 與半導體供應鏈 ＆ 三大法人/大盤重磅快報 · 最新掃描：${state.flashData.updatedAtTW} (每3分)`
        : `嚴選美國前 30 大科技股 ＆ 聯準會升降息/政策衝擊 · 最新掃描：${state.flashData.updatedAtTW} (每3分)`;
    }

    if (!items.length) {
      elFlashTrack.innerHTML = `<span class="flash-loading-text">目前暫無最新突發快報。</span>`;
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
    "gb200", "gb300", "nvlink", "csp", "bbu", "800g", "taiex", "twse", "nt",
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
    "^TWII": ".TWII",
    "0050.TW": "0050.TW",
    "0052.TW": "0052.TW",
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

  function formatTwDateStr(ms) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date(ms));
    const m = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    return `${m.year}-${m.month}-${m.day}`;
  }

  function formatTwHmStr(ms) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Taipei",
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

  function lookupCnbcQuote(qBySym, sym, mappedSym) {
    const cands = [];
    if (mappedSym) cands.push(String(mappedSym).toUpperCase());
    const u = String(sym || "").toUpperCase();
    cands.push(u);
    if (u.endsWith(".TW")) cands.push(u.slice(0, -3) + "-TW");
    else if (u.endsWith("-TW")) cands.push(u.slice(0, -3) + ".TW");
    for (const k of cands) {
      const cq = qBySym.get(k);
      if (cq && parseCnbcNum(cq.last) !== null) return cq;
    }
    for (const k of cands) {
      const cq = qBySym.get(k);
      if (cq) return cq;
    }
    return null;
  }

  async function applyRealtimeBrowserQuotes(quotesObj, options = {}) {
    if (!quotesObj || typeof quotesObj !== "object") return false;
    const { fetchBars = true, marketOverride = null } = options;
    try {
      const isTw = (marketOverride || state.market) === "tw";
      const idxList = quotesObj.indices || [];
      const watchList = quotesObj.watchlist || [];
      const rawSyms = [
        ...idxList.map((idx) => CNBC_INDEX_MAP[idx.symbol] || idx.symbol),
        ...watchList.map((st) => CNBC_STOCK_MAP[st.symbol] || st.symbol),
      ];
      const expandedSyms = [];
      const seenSyms = new Set();
      for (const s of rawSyms) {
        const list = isTw && String(s).toUpperCase().endsWith(".TW") ? [s, s.slice(0, -3) + "-TW"] : [s];
        for (const cand of list) {
          const cu = String(cand).toUpperCase();
          if (!seenSyms.has(cu)) {
            seenSyms.add(cu);
            expandedSyms.push(cand);
          }
        }
      }
      if (!expandedSyms.length) return false;

      const url =
        "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=" +
        encodeURIComponent(expandedSyms.join("|")) +
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

      // 1. Update Three Major Indices (US or TW)
      const barTasks = [];
      for (const idxObj of idxList) {
        const cSym = (CNBC_INDEX_MAP[idxObj.symbol] || idxObj.symbol).toUpperCase();
        const cq = lookupCnbcQuote(qBySym, idxObj.symbol, cSym);
        if (!cq) continue;

        const regPrice = parseCnbcNum(cq.last);
        const regMs = cq.last_time ? Date.parse(cq.last_time) : 0;
        const regTs = regMs ? Math.floor(regMs / 1000) : 0;
        if (regPrice === null) continue;

        const mktStatus = String(cq.curmktstatus || "").toUpperCase();
        const isLive = mktStatus === "REG_MKT";
        const cnbcDate = regMs ? (isTw ? formatTwDateStr(regMs) : formatEtDateStr(regMs)) : idxObj.sessionDate;
        const cnbcHm = regMs
          ? isTw
            ? formatTwHmStr(regMs)
            : formatEtHmStr(regMs)
          : idxObj.lastTimeET || (isTw ? "13:30" : "16:00");

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
          idxObj.lastTimeET = isLive ? cnbcHm : isTw ? "13:30" : "16:00";
          idxObj.quoteTs = regTs;
          anyUpdated = true;

          if (isTw || !fetchBars) {
            if (Array.isArray(idxObj.points) && idxObj.points.length >= 2) {
              const tail = idxObj.points[idxObj.points.length - 1];
              if (isLive) {
                if (Math.abs(tail.p - idxObj.close) > 0.005 || tail.et !== cnbcHm) {
                  if (tail.et === cnbcHm) {
                    tail.p = idxObj.close;
                    tail.t = regTs || tail.t;
                  } else {
                    idxObj.points.push({ t: regTs || tail.t + 60, et: cnbcHm, p: idxObj.close });
                  }
                }
              } else {
                tail.p = idxObj.close;
              }
            }
          } else {
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
      }

      // 2. Update Watchlist stocks/ETFs/futures (preserving fresher Yahoo Overnight quotes during 20:00-04:00 ET)
      for (const st of watchList) {
        const cSym = (CNBC_STOCK_MAP[st.symbol] || st.symbol).toUpperCase();
        const cq = lookupCnbcQuote(qBySym, st.symbol, cSym);
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
        if (!isTw && ext && mktStatus !== "REG_MKT" && st.symbol !== "^VIX" && st.symbol !== "CL=F") {
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
    // Keep GitHub API calls safely under the 60 req/hr unauthenticated IP cap (refresh SHA every ~70s or on manual click)
    const shaTtlMs = isManual ? 5_000 : 70_000;
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
      if (cached?.sha && Date.now() - cached.ts < shaTtlMs) {
        return `https://raw.githubusercontent.com/${LIVE_REPO}/${cached.sha}/data`;
      }
    } catch {
      // ignore storage error
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
      // fallback to branch raw URL if GitHub API rate-limited
    }
    return `https://raw.githubusercontent.com/${LIVE_REPO}/${LIVE_BRANCH}/data`;
  }

  async function fetchFreshQuotesPayloadOnly(curMarket, isManual = false) {
    const prefix = curMarket === "tw" ? "tw_" : "";
    const qFile = `${prefix}quotes.json`;
    const bust = Date.now();
    const jsDelivrBase = `https://cdn.jsdelivr.net/gh/${LIVE_REPO}@${LIVE_BRANCH}/data`;
    const liveBase = await resolveLiveRawBaseUrl(isManual);
    const isShaUrl = !liveBase.endsWith(`/${LIVE_BRANCH}/data`);
    const rawSuffix = isShaUrl ? "" : `?t=${bust}`;

    const [cdnQ, rawQ] = await Promise.all([
      fetchJsonSafe(`${jsDelivrBase}/${qFile}?t=${bust}`),
      fetchJsonSafe(`${liveBase}/${qFile}${rawSuffix}`),
    ]);
    const mCache = state.cache[curMarket];
    return pickFresherPayload(cdnQ, rawQ, mCache?.baseQuotes);
  }

  function triggerTickFlash(el, dir) {
    if (!el || !dir) return;
    el.classList.remove("tick-flash-up", "tick-flash-down");
    void el.offsetWidth;
    el.classList.add(dir > 0 ? "tick-flash-up" : "tick-flash-down");
  }

  function applyLiveQuotePatchesToDom(prevIdxPrices, prevStockPrices) {
    const indices = state.quotesData?.indices || [];
    const watchList = state.quotesData?.watchlist || [];
    const isTw = state.market === "tw";
    const tzTag = isTw ? "TW" : "ET";

    // 1. Patch Index cards in-place (zero canvas flicker)
    let anyIdxMoved = false;
    indices.forEach((idx, i) => {
      const card = elIndicesContainer.querySelector(`.index-card[data-idx-symbol="${CSS.escape(idx.symbol)}"]`);
      if (!card) return;
      const oldP = prevIdxPrices.get(idx.symbol);
      const diff = oldP !== undefined ? idx.close - oldP : 0;
      const dirClass = idx.isUp ? "up" : "down";

      const closeEl = card.querySelector(".index-close");
      if (closeEl) {
        closeEl.textContent = formatNumber(idx.close);
        if (Math.abs(diff) > 0.004) {
          triggerTickFlash(closeEl, diff);
          anyIdxMoved = true;
        }
      }
      const pillEl = card.querySelector(".delta-pill");
      if (pillEl) {
        pillEl.className = `delta-pill ${dirClass}`;
        pillEl.textContent = `${formatSignedNum(idx.change)} (${formatSignedPct(idx.changePct)})`;
      }
      const liveBadgeEl = card.querySelector(".live-idx-badge");
      if (liveBadgeEl && idx.isLive) {
        liveBadgeEl.textContent = `● 盤中即時 ${idx.lastTimeET || ""} ${tzTag}`;
      }
      const footerSpans = card.querySelectorAll(".index-range-footer span");
      if (footerSpans.length >= 2) {
        footerSpans[0].textContent = `昨收 ${formatNumber(idx.prevClose)}`;
        footerSpans[1].textContent = `當日區間 ${formatNumber(idx.low)} – ${formatNumber(idx.high)}`;
      }
      if (anyIdxMoved) {
        const canvas = document.getElementById(`index-canvas-${i}`);
        const tooltip = document.getElementById(`index-tooltip-${i}`);
        if (canvas) drawSingleIndexChart(canvas, tooltip, idx);
      }
    });

    // 2. Patch Watchlist rows (or cleanly re-render if actively sorting by price/change)
    const changedDirs = new Map();
    for (const st of watchList) {
      const oldP = prevStockPrices.get(st.symbol);
      if (oldP !== undefined && Math.abs(st.price - oldP) > 0.004) {
        changedDirs.set(st.symbol, st.price - oldP);
      }
    }

    const sortDependsOnQuote =
      state.sortBy.includes("change") || state.sortBy.includes("price");

    if (sortDependsOnQuote && changedDirs.size > 0) {
      renderWatchlist();
      changedDirs.forEach((diff, sym) => {
        const row = elWatchlistRows.querySelector(`.moomoo-row[data-symbol="${CSS.escape(sym)}"]`);
        if (row) triggerTickFlash(row.querySelector(".price-main"), diff);
      });
      return;
    }

    for (const st of watchList) {
      const row = elWatchlistRows.querySelector(`.moomoo-row[data-symbol="${CSS.escape(st.symbol)}"]`);
      if (!row) continue;

      const dirClass = st.isUp ? "up" : "down";
      const sBadge = sessionBadgeClass(st.session);
      const priceMainEl = row.querySelector(".price-main");
      const priceSubEl = row.querySelector(".price-sub");
      const chgBadgeEl = row.querySelector(".moomoo-chg-badge");
      const chgAmtEl = row.querySelector(".chg-amt-sub");
      const sessBadgeEl = row.querySelector(".session-badge");
      const sparkEl = row.querySelector(".cell-spark");

      if (priceMainEl) {
        priceMainEl.textContent = formatNumber(st.price);
        const diff = changedDirs.get(st.symbol);
        if (diff) triggerTickFlash(priceMainEl, diff);
      }
      if (priceSubEl) {
        priceSubEl.textContent =
          st.extChangePct !== null && st.extChangePct !== undefined
            ? `收盤 ${formatNumber(st.regularPrice)} · ${st.session} ${formatSignedPct(st.extChangePct)}`
            : `高 ${formatNumber(st.dayHigh)} · 低 ${formatNumber(st.dayLow)}`;
      }
      if (chgBadgeEl) {
        chgBadgeEl.className = `moomoo-chg-badge ${dirClass}`;
        chgBadgeEl.textContent = formatSignedPct(st.changePct);
      }
      if (chgAmtEl) {
        chgAmtEl.className = `chg-amt-sub ${dirClass}`;
        chgAmtEl.textContent = formatSignedNum(st.change);
      }
      if (sessBadgeEl) {
        sessBadgeEl.className = `session-badge ${sBadge}`;
        sessBadgeEl.textContent = st.session;
      }
      if (sparkEl && changedDirs.has(st.symbol)) {
        sparkEl.innerHTML = buildSparklineSvg(st.sparkline, st.isUp);
      }
    }
  }

  async function runFastQuoteTick() {
    if (document.hidden || state.isRefreshing || state.isFastTicking || !state.quotesData) return;
    const tickMarket = state.market;
    state.isFastTicking = true;
    state.fastTickCount += 1;

    try {
      const prevIdxPrices = new Map((state.quotesData.indices || []).map((x) => [x.symbol, x.close]));
      const prevStockPrices = new Map((state.quotesData.watchlist || []).map((x) => [x.symbol, x.price]));

      // Every 3rd fast tick (~24s), also pull fresh live-data quotes.json (crucial for US 24H Overnight & TW TWSE 5s official quotes)
      let baseQ = state.baseQuotesData || state.quotesData;
      let mergedLiveData = false;
      if (state.fastTickCount % LIVE_DATA_SYNC_TICKS === 0) {
        const freshBase = await fetchFreshQuotesPayloadOnly(tickMarket, false);
        if (state.market !== tickMarket) return;
        if (freshBase && freshBase.generatedAt !== state.baseQuotesData?.generatedAt) {
          state.baseQuotesData = freshBase;
          baseQ = freshBase;
          mergedLiveData = true;
        }
      }

      const workingQ = JSON.parse(JSON.stringify(mergedLiveData ? baseQ : state.quotesData));
      const cnbcUpdated = await applyRealtimeBrowserQuotes(workingQ, {
        fetchBars: false,
        marketOverride: tickMarket,
      });
      if (state.market !== tickMarket) return;

      if (cnbcUpdated || mergedLiveData) {
        state.realtimeActive = cnbcUpdated || state.realtimeActive;
        if (!cnbcUpdated && mergedLiveData) {
          workingQ.updatedAtTW = baseQ.updatedAtTW || formatTwFullStr(Date.now());
        }
        state.quotesData = workingQ;
        if (state.cache[tickMarket]) {
          state.cache[tickMarket].baseQuotes = state.baseQuotesData;
          state.cache[tickMarket].quotes = state.quotesData;
          state.cache[tickMarket].realtime = state.realtimeActive;
        }
        applyLiveQuotePatchesToDom(prevIdxPrices, prevStockPrices);
        renderHeaderMeta();
      }
    } catch {
      // silent retry on next 8s tick
    } finally {
      state.isFastTicking = false;
      state.secondsLeft = computeLiveMarketStatus().active ? FAST_QUOTE_INTERVAL_SEC : 30;
      updateCountdownLabel();
    }
  }

  async function loadAllData(isManual = false) {
    if (state.isRefreshing) return;
    state.isRefreshing = true;
    elBtnRefresh.disabled = true;
    elRefreshText.textContent = "即時同步中…";

    const curMarket = state.market;
    const prefix = curMarket === "tw" ? "tw_" : "";
    const qFile = `${prefix}quotes.json`;
    const iFile = `${prefix}insights.json`;
    const fFile = `${prefix}flash.json`;

    try {
      const bust = Date.now();
      const jsDelivrBase = `https://cdn.jsdelivr.net/gh/${LIVE_REPO}@${LIVE_BRANCH}/data`;
      if (isManual) {
        await Promise.race([
          fetch(`https://purge.jsdelivr.net/gh/${LIVE_REPO}@${LIVE_BRANCH}/data/${qFile}`, { cache: "no-store" }).catch(
            () => {}
          ),
          new Promise((r) => setTimeout(r, 250)),
        ]);
      }

      const liveBasePromise = resolveLiveRawBaseUrl(isManual);

      const localPromises = Promise.all([
        fetchJsonSafe(`./data/${qFile}?t=${bust}`),
        fetchJsonSafe(`./data/${iFile}?t=${bust}`),
        fetchJsonSafe(`./data/${fFile}?t=${bust}`),
      ]);

      const cdnPromises = Promise.all([
        fetchJsonSafe(`${jsDelivrBase}/${qFile}?t=${bust}`),
        fetchJsonSafe(`${jsDelivrBase}/${iFile}?t=${bust}`),
        fetchJsonSafe(`${jsDelivrBase}/${fFile}?t=${bust}`),
      ]);

      // Always fetch raw.githubusercontent.com for quotes in parallel so stale jsDelivr cache can never block fresh 45s quotes
      const rawQuotesPromise = liveBasePromise.then((liveBase) => {
        const isShaUrl = !liveBase.endsWith(`/${LIVE_BRANCH}/data`);
        const qSuffix = isShaUrl ? "" : `?t=${bust}`;
        return fetchJsonSafe(`${liveBase}/${qFile}${qSuffix}`);
      });

      const [[localQ, localI, localF], [cdnQ, cdnI, cdnF], rawQ] = await Promise.all([
        localPromises,
        cdnPromises,
        rawQuotesPromise,
      ]);

      let liveI = null;
      let liveF = null;
      if (!cdnI || !cdnF) {
        const liveBase = await liveBasePromise;
        const isShaUrl = !liveBase.endsWith(`/${LIVE_BRANCH}/data`);
        const qSuffix = isShaUrl ? "" : `?t=${bust}`;
        [liveI, liveF] = await Promise.all([
          !cdnI ? fetchJsonSafe(`${liveBase}/${iFile}${qSuffix}`) : null,
          !cdnF ? fetchJsonSafe(`${liveBase}/${fFile}${qSuffix}`) : null,
        ]);
      }

      if (state.market !== curMarket) return;

      const mCache = state.cache[curMarket];
      const nextBaseQ = pickFresherPayload(cdnQ, rawQ, localQ, mCache?.baseQuotes);
      const nextI = pickFresherPayload(cdnI, liveI, localI, mCache?.insights);
      const nextF = pickFresherPayload(cdnF, liveF, localF, mCache?.flash);

      if (nextBaseQ) {
        state.baseQuotesData = nextBaseQ;
        const workingQ = JSON.parse(JSON.stringify(nextBaseQ));
        state.realtimeActive = await applyRealtimeBrowserQuotes(workingQ, {
          fetchBars: true,
          marketOverride: curMarket,
        });
        if (state.market !== curMarket) return;
        state.quotesData = workingQ;
      }
      if (nextI) state.insightsData = nextI;
      if (nextF) state.flashData = nextF;

      await sanitizeDataTranslations();

      state.cache[curMarket] = {
        baseQuotes: state.baseQuotesData,
        quotes: state.quotesData,
        insights: state.insightsData,
        flash: state.flashData,
        realtime: state.realtimeActive,
      };

      renderFilterTabsForMarket();
      renderHeaderMeta();
      renderFlashWire();
      renderIndices();
      renderMarketHeadlines();
      renderWatchlist();
      renderCioAdvisory();
      await hydrateUntranslatedDom();
      state.secondsLeft = computeLiveMarketStatus().active ? FAST_QUOTE_INTERVAL_SEC : 30;
      state.fullSyncSecondsLeft = FULL_SYNC_INTERVAL_SEC;
    } catch (err) {
      console.error("Failed to load watchlist data:", err);
    } finally {
      state.isRefreshing = false;
      elBtnRefresh.disabled = false;
      updateCountdownLabel();
      if (isManual) {
        elRefreshText.textContent = "已即時更新 ✓";
        setTimeout(updateCountdownLabel, 1200);
      }
    }
  }

  function updateCountdownLabel() {
    if (state.isRefreshing) return;
    const s = String(Math.max(0, state.secondsLeft)).padStart(2, "0");
    elRefreshText.textContent = `立即更新 (${s}s)`;
  }

  function startTimers() {
    setInterval(() => {
      if (document.hidden) return;
      state.fullSyncSecondsLeft -= 1;
      if (state.fullSyncSecondsLeft <= 0) {
        state.fullSyncSecondsLeft = FULL_SYNC_INTERVAL_SEC;
        loadAllData(false);
        return;
      }
      if (state.secondsLeft <= 1) {
        runFastQuoteTick();
      } else {
        state.secondsLeft -= 1;
        updateCountdownLabel();
      }
    }, 1000);

    // Instant refresh the moment user returns to this browser tab / unlocks phone
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !state.isRefreshing && !state.isFastTicking) {
        runFastQuoteTick();
      }
    });
  }

  // Market switcher buttons
  if (elBtnMarketUs) {
    elBtnMarketUs.addEventListener("click", () => switchMarket("us"));
  }
  if (elBtnMarketTw) {
    elBtnMarketTw.addEventListener("click", () => switchMarket("tw"));
  }
  if (elBtnQuickSwitch) {
    elBtnQuickSwitch.addEventListener("click", () => {
      switchMarket(state.market === "us" ? "tw" : "us");
    });
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

  // Delegate filter tab clicks
  if (elWatchlistFilterTabs) {
    elWatchlistFilterTabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".tab-btn");
      if (!btn) return;
      Array.from(elWatchlistFilterTabs.querySelectorAll(".tab-btn")).forEach((b) =>
        b.classList.remove("active")
      );
      btn.classList.add("active");
      state.activeFilter = btn.dataset.filter || "all";
      renderWatchlist();
    });
  }

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

  applyMarketStaticLabels();
  applyTheme(state.theme);
  loadAllData(false);
  startTimers();
})();
