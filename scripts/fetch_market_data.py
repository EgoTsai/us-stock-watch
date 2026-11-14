#!/usr/bin/env python3
"""
US Stock Watchlist Data Pipeline
Fetches:
1. Previous/latest completed trading session intraday chart + closing price & % for Dow (^DJI), Nasdaq (^IXIC), S&P 500 (^GSPC)
2. Top US market headlines (concise bullet points + source links, authoritative financial sources prioritized)
3. 15-minute watchlist quotes across all sessions (夜盤 Overnight, 盤前 Pre-Market, 盤中 Regular, 盤後 After-Hours)
4. Per-stock 6-hour key headlines (strict relevance filter, updated every 6h + 10 mins before US market open)
5. Per-stock 6-hour netizen sentiment index (想買 % green vs 想賣 % red)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import email.utils
import html
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
TW_TZ = ZoneInfo("Asia/Taipei")
UTC_TZ = dt.timezone.utc

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

INDICES = [
    {"symbol": "^DJI", "displaySymbol": "DJI", "name": "道瓊工業指數", "enName": "Dow Jones Industrial Average"},
    {"symbol": "^IXIC", "displaySymbol": "IXIC", "name": "納斯達克指數", "enName": "Nasdaq Composite"},
    {"symbol": "^GSPC", "displaySymbol": "SPX", "name": "標普 500 指數", "enName": "S&P 500 Index"},
]

WATCHLIST = [
    {
        "symbol": "GOOG",
        "displaySymbol": "GOOG",
        "name": "Alphabet (Google)",
        "enName": "ALPHABET INC-CL C",
        "category": "tech",
        "twQuery": '"Google" OR "Alphabet" OR "GOOG"',
        "enQuery": '"GOOG" OR "Alphabet" OR "Google stock"',
        "mustMatch": ["goog", "google", "alphabet", "gemini", "waymo", "youtube", "tpu"],
        "pttKey": "GOOG",
    },
    {
        "symbol": "MU",
        "displaySymbol": "MU",
        "name": "美光科技",
        "enName": "MICRON TECHNOLOGY INC",
        "category": "semi",
        "twQuery": '"美光" OR "Micron"',
        "enQuery": '"Micron" OR "MU stock"',
        "mustMatch": ["美光", "micron", "hbm", "dram", "記憶體", "mu "],
        "pttKey": "美光",
    },
    {
        "symbol": "NVDA",
        "displaySymbol": "NVDA",
        "name": "輝達",
        "enName": "NVIDIA CORP",
        "category": "semi",
        "twQuery": '"輝達" OR "NVDA"',
        "enQuery": '"Nvidia" OR "NVDA"',
        "mustMatch": ["輝達", "nvidia", "nvda", "blackwell", "rubin", "kress", "柯蕾絲", "克雷斯"],
        "pttKey": "輝達",
    },
    {
        "symbol": "QQQ",
        "displaySymbol": "QQQ",
        "name": "Invesco 納指100 ETF",
        "enName": "INVESCO QQQ TRUST SERIES 1",
        "category": "macro",
        "twQuery": '"QQQ" OR "那斯達克" OR "納斯達克"',
        "enQuery": '"QQQ" OR "Nasdaq 100" OR "Nasdaq"',
        "mustMatch": ["qqq", "那斯達克", "納斯達克", "那指", "納指", "nasdaq", "科技股"],
        "pttKey": "QQQ",
    },
    {
        "symbol": "SPCX",
        "displaySymbol": "SPCX",
        "name": "太空探索技術 (SpaceX)",
        "enName": "SPACE EXPLORATION TECHN-CL A",
        "category": "tech",
        "twQuery": '"SpaceX" OR "SPCX" OR "星艦"',
        "enQuery": '"SPCX" OR "SpaceX" OR "Starlink"',
        "mustMatch": ["spacex", "spcx", "starship", "starlink", "星艦", "星鏈", "太空探索"],
        "pttKey": "SpaceX",
    },
    {
        "symbol": "TSLA",
        "displaySymbol": "TSLA",
        "name": "特斯拉",
        "enName": "TESLA INC",
        "category": "tech",
        "twQuery": '"特斯拉" OR "TSLA"',
        "enQuery": '"Tesla" OR "TSLA"',
        "mustMatch": ["特斯拉", "tesla", "tsla", "cybercab", "robotaxi", "optimus", "fsd"],
        "pttKey": "特斯拉",
    },
    {
        "symbol": "TSM",
        "displaySymbol": "TSM",
        "name": "台積電 ADR",
        "enName": "TAIWAN SEMICONDUCTOR-SP ADR",
        "category": "semi",
        "twQuery": '"台積電ADR" OR "台積電" 美股',
        "enQuery": '"TSMC" OR "TSM stock" OR "Taiwan Semiconductor"',
        "mustMatch": ["台積電", "台積", "tsmc", "tsm", "cowos", "魏哲家"],
        "pttKey": "台積",
    },
    {
        "symbol": "VOO",
        "displaySymbol": "VOO",
        "name": "Vanguard 標普500 ETF",
        "enName": "VANGUARD S&P 500 ETF",
        "category": "macro",
        "twQuery": '"VOO" OR "標普500" OR "S&P 500"',
        "enQuery": '"VOO" OR "S&P 500"',
        "mustMatch": ["voo", "標普", "s&p 500", "s&p500", "sp500", "vanguard"],
        "pttKey": "VOO",
    },
    {
        "symbol": "CL=F",
        "displaySymbol": "CL @NYMEX",
        "name": "NYMEX WTI 輕原油期貨",
        "enName": "WTI CRUDE OIL FUTURES (NYMEX)",
        "category": "macro",
        "twQuery": '"國際油價" OR "紐約原油" OR "WTI原油" OR "西德州原油"',
        "enQuery": '"WTI crude" OR "crude oil" OR "oil prices"',
        "mustMatch": ["油價", "原油", "wti", "西德州", "布蘭特", "opec", "crude", "oil"],
        "pttKey": "油價",
    },
    {
        "symbol": "SOXL",
        "displaySymbol": "SOXL",
        "name": "Direxion 半導體3倍做多",
        "enName": "DIREXION DAILY SEMI BULL 3X",
        "category": "semi",
        "twQuery": '"SOXL" OR "費城半導體" OR "費半"',
        "enQuery": '"SOXL" OR "semiconductor ETF" OR "PHLX Semiconductor"',
        "mustMatch": ["soxl", "費半", "費城半導體", "半導體", "semiconductor", "chip"],
        "pttKey": "SOXL",
    },
    {
        "symbol": "MSFT",
        "displaySymbol": "MSFT",
        "name": "微軟",
        "enName": "MICROSOFT CORP",
        "category": "tech",
        "twQuery": '"微軟" OR "Microsoft" OR "MSFT"',
        "enQuery": '"Microsoft" OR "MSFT"',
        "mustMatch": ["微軟", "microsoft", "msft", "azure", "copilot", "openai"],
        "pttKey": "微軟",
    },
    {
        "symbol": "META",
        "displaySymbol": "META",
        "name": "Meta 平台",
        "enName": "META PLATFORMS INC-CLASS A",
        "category": "tech",
        "twQuery": '"Meta" 美股 OR "祖克柏"',
        "enQuery": '"Meta Platforms" OR "META stock"',
        "mustMatch": ["meta", "祖克柏", "zuckerberg", "llama", "instagram", "threads"],
        "pttKey": "META",
    },
    {
        "symbol": "^VIX",
        "displaySymbol": "VIX",
        "name": "CBOE 波動率恐慌指數",
        "enName": "CBOE VOLATILITY INDEX",
        "category": "macro",
        "twQuery": '"VIX" OR "恐慌指數"',
        "enQuery": '"VIX" OR "volatility index" market',
        "mustMatch": ["vix", "恐慌指數", "波動率", "volatility", "避險", "美股"],
        "pttKey": "VIX",
    },
    {
        "symbol": "IBIT",
        "displaySymbol": "IBIT",
        "name": "iShares 比特幣信託 ETF",
        "enName": "ISHARES BITCOIN TRUST ETF",
        "category": "macro",
        "twQuery": '"比特幣" OR "IBIT"',
        "enQuery": '"IBIT" OR "Bitcoin ETF" OR "Bitcoin"',
        "mustMatch": ["比特幣", "bitcoin", "btc", "ibit", "加密貨幣"],
        "pttKey": "比特幣",
    },
    {
        "symbol": "AMD",
        "displaySymbol": "AMD",
        "name": "超微半導體 (AMD)",
        "enName": "ADVANCED MICRO DEVICES",
        "category": "semi",
        "twQuery": '"超微" OR "蘇姿丰" OR "AMD"',
        "enQuery": '"AMD" OR "Advanced Micro Devices"',
        "mustMatch": ["超微", "amd", "蘇姿丰", "mi3", "mi4", "ryzen", "epyc"],
        "pttKey": "AMD",
    },
    {
        "symbol": "INTC",
        "displaySymbol": "INTC",
        "name": "英特爾",
        "enName": "INTEL CORP",
        "category": "semi",
        "twQuery": '"英特爾" OR "Intel" OR "INTC"',
        "enQuery": '"Intel" OR "INTC"',
        "mustMatch": ["英特爾", "intel", "intc", "18a", "晶圓代工"],
        "pttKey": "INTC",
    },
    {
        "symbol": "IAU",
        "displaySymbol": "IAU",
        "name": "iShares 黃金信託 ETF",
        "enName": "ISHARES GOLD TRUST",
        "category": "macro",
        "twQuery": '"國際金價" OR "黃金價格" OR "現貨黃金"',
        "enQuery": '"Gold price" OR "IAU ETF" OR "gold futures"',
        "mustMatch": ["金價", "黃金", "gold", "iau", "盎司"],
        "pttKey": "黃金",
    },
    {
        "symbol": "UCO",
        "displaySymbol": "UCO",
        "name": "ProShares 兩倍做多原油",
        "enName": "PROSHARES ULTRA BLOOMBERG CRUDE",
        "category": "macro",
        "twQuery": '"原油" OR "國際油價" OR "WTI"',
        "enQuery": '"UCO" OR "Bloomberg Crude Oil" OR "crude oil ETF"',
        "mustMatch": ["uco", "原油", "油價", "wti", "brent", "crude", "oil", "opec"],
        "pttKey": "原油",
    },
    {
        "symbol": "AVGO",
        "displaySymbol": "AVGO",
        "name": "博通",
        "enName": "BROADCOM INC",
        "category": "semi",
        "twQuery": '"博通" OR "Broadcom" OR "AVGO"',
        "enQuery": '"Broadcom" OR "AVGO"',
        "mustMatch": ["博通", "broadcom", "avgo", "asic", "陳福陽"],
        "pttKey": "博通",
    },
]

TABLOID_BLACKLIST = [
    "炎亞綸", "男友", "女友", "女星", "男星", "藝人", "娛樂", "星座", "生肖", "命理", "風水", "減肥", "糖尿病", "八點檔",
]

TIER1_SOURCES = {
    "鉅亨網", "經濟日報", "工商時報", "Yahoo股市", "Yahoo奇摩股市", "Yahoo 財經", "自由財經",
    "中央社", "MoneyDJ理財網", "財訊", "聯合新聞網", "科技新報", "商周", "今周刊",
    "Reuters", "Bloomberg", "CNBC", "WSJ", "The Wall Street Journal", "MarketWatch", "Barron's", "Yahoo Finance",
}
BLOG_SOURCES = {"CMoney投資網誌", "鉅亨號", "方格子", "Vocus", "Facebook", "Threads"}

BULL_WORDS = [
    "大漲", "飆漲", "飆升", "強彈", "反彈", "走高", "收紅", "創高", "新高", "買進", "加碼",
    "上調", "調升", "優於預期", "超預期", "利多", "看多", "看好", "抄底", "護盤", "突圍",
    "大勝", "暴增", "強勁", "成長", "獲利增", "領漲", "回升", "買盤", "搶進", "大買", "漲逾",
    "surge", "soar", "rally", "jump", "gain", "climb", "beat", "upgrade", "buy",
    "bull", "bullish", "outperform", "strong", "record", "breakout", "rebound", "boost", "upbeat",
]

BEAR_WORDS = [
    "大跌", "暴跌", "重挫", "慘崩", "崩跌", "走低", "收黑", "破底", "新低", "賣出", "減碼",
    "下調", "下修", "不如預期", "遜於預期", "利空", "看空", "看淡", "拋售", "砍價", "辭職",
    "撤換", "罷免", "醜聞", "調查", "訴訟", "裁員", "警告", "重摔", "拖累", "殺盤", "下臺", "跌沒停", "跌超", "失守",
    "plunge", "tumble", "drop", "fall", "slide", "sink", "crash", "slump", "miss",
    "downgrade", "sell", "bear", "bearish", "underperform", "weak", "oust", "resign", "probe", "lawsuit", "cut",
]

SIMPLIFIED_HINTS = set("收盘涨跌们这为发经现电业动盘后个标纳达伟积体导银")


class YahooClient:
    def __init__(self) -> None:
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [("User-Agent", USER_AGENT), ("Accept", "application/json,*/*")]
        self.crumb = ""
        self._init_crumb()

    def _init_crumb(self) -> None:
        try:
            self.opener.open("https://fc.yahoo.com", timeout=6)
        except Exception:
            pass
        try:
            resp = self.opener.open("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=8)
            self.crumb = resp.read().decode("utf-8").strip()
        except Exception as exc:
            print(f"[warn] crumb init failed: {exc}", file=sys.stderr)

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        if not self.crumb:
            return {}
        sym_str = urllib.parse.quote(",".join(symbols), safe=",")
        crumb_q = urllib.parse.quote(self.crumb)
        url = f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={sym_str}&crumb={crumb_q}"
        try:
            raw = self.opener.open(url, timeout=12).read().decode("utf-8")
            items = json.loads(raw).get("quoteResponse", {}).get("result", [])
            return {it["symbol"]: it for it in items if "symbol" in it}
        except Exception as exc:
            print(f"[warn] get_quotes failed: {exc}", file=sys.stderr)
            return {}

    def get_chart(self, symbol: str, interval: str = "5m", range_str: str = "2d", prepost: bool = True) -> dict:
        sym_q = urllib.parse.quote(symbol)
        pp = "true" if prepost else "false"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym_q}?interval={interval}&range={range_str}&includePrePost={pp}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            raw = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
            res = json.loads(raw).get("chart", {}).get("result")
            return res[0] if res else {}
        except Exception as exc:
            print(f"[warn] get_chart({symbol}) failed: {exc}", file=sys.stderr)
            return {}

    def get_option_call_ratio(self, symbol: str) -> tuple[float | None, int]:
        if symbol in ("CL=F",) or not self.crumb:
            return None, 0
        sym_q = urllib.parse.quote(symbol)
        crumb_q = urllib.parse.quote(self.crumb)
        url = f"https://query2.finance.yahoo.com/v7/finance/options/{sym_q}?crumb={crumb_q}"
        try:
            raw = self.opener.open(url, timeout=8).read().decode("utf-8")
            res = json.loads(raw).get("optionChain", {}).get("result", [])
            if not res or not res[0].get("options"):
                return None, 0
            opt0 = res[0]["options"][0]
            call_vol = sum((c.get("volume") or 0) for c in opt0.get("calls", []))
            put_vol = sum((p.get("volume") or 0) for p in opt0.get("puts", []))
            total = call_vol + put_vol
            if total < 50:
                return None, total
            return call_vol / total, total
        except Exception:
            return None, 0


def classify_et_session(ts: int) -> str:
    dt_et = dt.datetime.fromtimestamp(ts, NY_TZ)
    hm = dt_et.hour * 60 + dt_et.minute
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "盤中"
    if 16 * 60 <= hm < 20 * 60:
        return "盤後"
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "盤前"
    return "夜盤"


def get_market_session_overview() -> dict:
    now_et = dt.datetime.now(NY_TZ)
    wd = now_et.weekday()
    hm = now_et.hour * 60 + now_et.minute

    if wd == 5:
        status, code = "週末休市（顯示最新盤後報價）", "WEEKEND"
    elif wd == 6:
        if hm >= 20 * 60:
            status, code = "美股夜盤交易中 (Overnight)", "OVERNIGHT"
        else:
            status, code = "週末休市（週日 20:00 ET 夜盤開盤）", "WEEKEND"
    else:
        if hm < 4 * 60:
            status, code = "美股夜盤交易中 (Overnight)", "OVERNIGHT"
        elif hm < 9 * 60 + 30:
            status, code = "美股盤前交易中 (Pre-Market)", "PRE"
        elif hm < 16 * 60:
            status, code = "美股正規盤交易中 (Regular)", "REGULAR"
        elif hm < 20 * 60:
            status, code = "美股盤後交易中 (After-Hours)", "POST"
        else:
            if wd == 4:
                status, code = "美股週末休市（顯示週五盤後最新價）", "WEEKEND"
            else:
                status, code = "美股夜盤交易中 (Overnight)", "OVERNIGHT"

    return {
        "statusText": status,
        "sessionCode": code,
        "etTime": now_et.strftime("%Y-%m-%d %H:%M ET"),
        "twTime": dt.datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M 台灣時間"),
    }


def build_index_data(yc: YahooClient, idx_cfg: dict, q_map: dict[str, dict]) -> dict:
    sym = idx_cfg["symbol"]
    chart = yc.get_chart(sym, interval="5m", range_str="5d", prepost=False)
    q = q_map.get(sym, {})

    timestamps = chart.get("timestamp") or []
    quote_ind = (chart.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote_ind.get("close") or []
    highs = quote_ind.get("high") or []
    lows = quote_ind.get("low") or []

    by_date: dict[str, list[tuple[int, float, float, float]]] = {}
    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        h = highs[i] if i < len(highs) and highs[i] is not None else c
        l = lows[i] if i < len(lows) and lows[i] is not None else c
        d_et = dt.datetime.fromtimestamp(ts, NY_TZ)
        hm = d_et.hour * 60 + d_et.minute
        if 9 * 60 + 30 <= hm <= 16 * 60 + 5:
            d_key = d_et.strftime("%Y-%m-%d")
            by_date.setdefault(d_key, []).append((ts, float(c), float(h), float(l)))

    sorted_dates = sorted(by_date.keys())
    now_et = dt.datetime.now(NY_TZ)
    today_key = now_et.strftime("%Y-%m-%d")
    hm_now = now_et.hour * 60 + now_et.minute

    target_date = sorted_dates[-1] if sorted_dates else today_key
    if target_date == today_key and hm_now < 16 * 60 and len(sorted_dates) >= 2:
        target_date = sorted_dates[-2]

    bars = by_date.get(target_date, [])
    target_idx = sorted_dates.index(target_date) if target_date in sorted_dates else -1
    prev_bars = by_date[sorted_dates[target_idx - 1]] if target_idx > 0 else []

    q_reg_time = q.get("regularMarketTime") or 0
    q_reg_date = dt.datetime.fromtimestamp(q_reg_time, NY_TZ).strftime("%Y-%m-%d") if q_reg_time else ""

    if q_reg_date == target_date and q.get("regularMarketPrice") is not None:
        close_price = round(float(q["regularMarketPrice"]), 2)
        prev_close = round(float(q.get("regularMarketPreviousClose") or (prev_bars[-1][1] if prev_bars else close_price)), 2)
    else:
        close_price = round(bars[-1][1], 2) if bars else round(float(q.get("regularMarketPrice") or 0), 2)
        prev_close = round(prev_bars[-1][1], 2) if prev_bars else round(float(q.get("regularMarketPreviousClose") or close_price), 2)

    change = round(close_price - prev_close, 2)
    change_pct = round((change / prev_close * 100) if prev_close else 0.0, 2)
    day_high = round(max((b[2] for b in bars), default=close_price), 2)
    day_low = round(min((b[3] for b in bars), default=close_price), 2)

    points = []
    for ts, c, _, _ in bars:
        t_et = dt.datetime.fromtimestamp(ts, NY_TZ).strftime("%H:%M")
        points.append({"t": ts, "et": t_et, "p": round(c, 2)})
    if points and abs(points[-1]["p"] - close_price) > 0.01:
        points.append({"t": points[-1]["t"] + 60, "et": "16:00", "p": close_price})

    return {
        "symbol": sym,
        "displaySymbol": idx_cfg["displaySymbol"],
        "name": idx_cfg["name"],
        "enName": idx_cfg["enName"],
        "sessionDate": target_date,
        "close": close_price,
        "prevClose": prev_close,
        "change": change,
        "changePct": change_pct,
        "high": day_high,
        "low": day_low,
        "isUp": change >= 0,
        "points": points,
    }


def build_stock_quote(yc: YahooClient, item_cfg: dict, q_map: dict[str, dict]) -> dict:
    sym = item_cfg["symbol"]
    q = q_map.get(sym, {})
    chart = yc.get_chart(sym, interval="5m", range_str="2d", prepost=True)
    meta = chart.get("meta", {})

    reg_price = q.get("regularMarketPrice") or meta.get("regularMarketPrice") or 0.0
    reg_prev_close = q.get("regularMarketPreviousClose") or meta.get("previousClose") or meta.get("chartPreviousClose") or reg_price
    reg_time = int(q.get("regularMarketTime") or meta.get("regularMarketTime") or 0)
    market_state = (q.get("marketState") or "").upper()

    candidates: list[tuple[int, float, str]] = []
    if reg_price:
        reg_lbl = "盤中" if market_state == "REGULAR" else "收盤"
        candidates.append((reg_time, float(reg_price), reg_lbl))

    for field_p, field_t, lbl in [
        ("preMarketPrice", "preMarketTime", "盤前"),
        ("postMarketPrice", "postMarketTime", "盤後"),
        ("overnightMarketPrice", "overnightMarketTime", "夜盤"),
    ]:
        val = q.get(field_p)
        ts = int(q.get(field_t) or 0)
        if val is not None and ts > 0:
            candidates.append((ts, float(val), lbl))

    timestamps = chart.get("timestamp") or []
    quote_ind = (chart.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote_ind.get("close") or []
    opens = quote_ind.get("open") or []
    vols = quote_ind.get("volume") or []

    valid_bars: list[tuple[int, float, float, int]] = []
    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        v = int(vols[i]) if i < len(vols) and vols[i] is not None else 0
        valid_bars.append((int(ts), float(o), float(c), v))

    if valid_bars and sym not in ("^VIX",):
        last_ts, _, last_c, _ = valid_bars[-1]
        best_known_ts = max((c[0] for c in candidates), default=0)
        if last_ts > best_known_ts + 90:
            lbl = "電子盤" if sym == "CL=F" else classify_et_session(last_ts)
            candidates.append((last_ts, last_c, lbl))

    candidates.sort(key=lambda x: x[0])
    if candidates:
        latest_ts, latest_price, session_label = candidates[-1]
    else:
        latest_ts, latest_price, session_label = 0, 0.0, "收盤"

    if sym == "CL=F" and session_label in ("盤中", "盤後", "夜盤", "盤前"):
        session_label = "期貨盤中" if market_state == "REGULAR" else "期貨收盤"
    elif sym == "^VIX":
        session_label = "盤中" if market_state == "REGULAR" else "收盤"

    if session_label in ("盤前", "夜盤") and reg_time > 0 and (latest_ts - reg_time) > 3.5 * 3600:
        base_close = float(reg_price)
    else:
        base_close = float(reg_prev_close) if reg_prev_close else float(reg_price)

    change = latest_price - base_close
    change_pct = (change / base_close * 100.0) if base_close else 0.0

    reg_change_pct = float(q.get("regularMarketChangePercent") or ((reg_price - reg_prev_close) / reg_prev_close * 100 if reg_prev_close else 0.0))
    ext_diff_pct = ((latest_price - reg_price) / reg_price * 100.0) if (reg_price and session_label not in ("盤中", "收盤", "期貨盤中", "期貨收盤")) else None

    spark_raw = [b[2] for b in valid_bars[-96:]]
    step = max(1, len(spark_raw) // 48)
    sparkline = [round(v, 2) for v in spark_raw[::step]][-48:]
    if sparkline and round(latest_price, 2) != sparkline[-1]:
        sparkline.append(round(latest_price, 2))

    cutoff_6h = (valid_bars[-1][0] - 6 * 3600) if valid_bars else 0
    up_vol, down_vol = 0, 0
    for ts, o, c, v in valid_bars:
        if ts >= cutoff_6h:
            weight = max(v, 1)
            if c > o:
                up_vol += weight
            elif c < o:
                down_vol += weight
            else:
                up_vol += weight // 2
                down_vol += weight // 2
    vol_buy_ratio = (up_vol / (up_vol + down_vol)) if (up_vol + down_vol) > 0 else 0.5

    return {
        "symbol": sym,
        "displaySymbol": item_cfg["displaySymbol"],
        "name": item_cfg["name"],
        "enName": item_cfg["enName"],
        "category": item_cfg["category"],
        "price": round(latest_price, 2),
        "change": round(change, 2),
        "changePct": round(change_pct, 2),
        "isUp": change_pct >= 0,
        "session": session_label,
        "updatedAt": dt.datetime.fromtimestamp(latest_ts, TW_TZ).strftime("%m/%d %H:%M") if latest_ts else "",
        "regularPrice": round(float(reg_price), 2),
        "regularChangePct": round(reg_change_pct, 2),
        "extChangePct": round(ext_diff_pct, 2) if ext_diff_pct is not None else None,
        "dayHigh": round(float(q.get("regularMarketDayHigh") or meta.get("regularMarketDayHigh") or latest_price), 2),
        "dayLow": round(float(q.get("regularMarketDayLow") or meta.get("regularMarketDayLow") or latest_price), 2),
        "sparkline": sparkline,
        "_volBuyRatio6h": round(vol_buy_ratio, 4),
    }


def translate_en_to_zhtw(text: str) -> str:
    if not text or any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    try:
        q = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        raw = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
        return "".join(seg[0] for seg in raw[0] if seg and seg[0]).strip()
    except Exception:
        return text


def clean_headline_title(title: str, source: str) -> str:
    title = html.unescape(title or "").strip()
    if source and title.endswith(f" - {source}"):
        title = title[: -len(f" - {source}")].strip()
    elif " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts[1]) <= 24:
            title = parts[0].strip()
    return title


def is_tabloid_or_simplified(title: str, check_simplified: bool = True) -> bool:
    low = title.lower()
    if any(bad in low for bad in TABLOID_BLACKLIST):
        return True
    if check_simplified and sum(1 for ch in title if ch in SIMPLIFIED_HINTS) >= 2:
        return True
    return False


def matches_keywords(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    low = f" {title.lower()} "
    return any(kw.lower() in low for kw in keywords)


def title_similarity(a: str, b: str) -> float:
    sa = {a[i : i + 2] for i in range(max(0, len(a) - 1))}
    sb = {b[i : i + 2] for i in range(max(0, len(b) - 1))}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def fetch_google_news_rss(
    query: str,
    lang: str = "zh-TW",
    max_age_hours: float = 24.0,
    must_match: list[str] | None = None,
) -> list[dict]:
    if lang == "zh-TW":
        params = f"q={urllib.parse.quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    else:
        params = f"q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    url = f"https://news.google.com/rss/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    now_utc = dt.datetime.now(UTC_TZ)
    items: list[dict] = []
    try:
        xml_bytes = urllib.request.urlopen(req, timeout=8).read()
        root = ET.fromstring(xml_bytes)
        for el in root.findall("./channel/item"):
            raw_title = el.findtext("title") or ""
            link = (el.findtext("link") or "").strip()
            source = (el.findtext("source") or "財經快訊").strip()
            pub_str = el.findtext("pubDate") or ""
            if not raw_title or not link:
                continue
            try:
                pub_dt = email.utils.parsedate_to_datetime(pub_str).astimezone(UTC_TZ)
            except Exception:
                pub_dt = now_utc
            age_h = max(0.0, (now_utc - pub_dt).total_seconds() / 3600.0)
            if age_h > max_age_hours:
                continue
            title = clean_headline_title(raw_title, source)
            if is_tabloid_or_simplified(title, check_simplified=(lang == "zh-TW")):
                continue
            if must_match and not matches_keywords(title, must_match):
                continue
            tier_bonus = 1 if source in TIER1_SOURCES else (-1 if source in BLOG_SOURCES else 0)
            items.append(
                {
                    "title": title,
                    "source": source,
                    "url": link,
                    "pubTs": int(pub_dt.timestamp()),
                    "ageHours": round(age_h, 2),
                    "tier": tier_bonus,
                    "lang": lang,
                }
            )
    except Exception as exc:
        print(f"[warn] RSS failed ({query[:30]}): {exc}", file=sys.stderr)

    items.sort(key=lambda x: (x["tier"], x["pubTs"]), reverse=True)
    return items


def fetch_yahoo_ticker_rss(symbol: str, max_age_hours: float = 6.5) -> list[dict]:
    sym_q = urllib.parse.quote(symbol)
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym_q}&region=US&lang=en-US"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    now_utc = dt.datetime.now(UTC_TZ)
    items: list[dict] = []
    try:
        xml_bytes = urllib.request.urlopen(req, timeout=7).read()
        root = ET.fromstring(xml_bytes)
        for el in root.findall("./channel/item"):
            title = html.unescape(el.findtext("title") or "").strip()
            link = (el.findtext("link") or "").strip()
            pub_str = el.findtext("pubDate") or ""
            if not title or not link:
                continue
            try:
                pub_dt = email.utils.parsedate_to_datetime(pub_str).astimezone(UTC_TZ)
            except Exception:
                pub_dt = now_utc
            age_h = max(0.0, (now_utc - pub_dt).total_seconds() / 3600.0)
            if age_h > max_age_hours:
                continue
            items.append(
                {
                    "title": title,
                    "source": "Yahoo Finance",
                    "url": link,
                    "pubTs": int(pub_dt.timestamp()),
                    "ageHours": round(age_h, 2),
                    "tier": 1,
                    "lang": "en-US",
                }
            )
    except Exception:
        pass
    items.sort(key=lambda x: x["pubTs"], reverse=True)
    return items


def format_age_label(age_h: float) -> str:
    mins = int(round(age_h * 60))
    if mins < 5:
        return "剛剛"
    if mins < 60:
        return f"{mins}分鐘前"
    hrs = int(age_h)
    if hrs < 24:
        return f"{hrs}小時前"
    return f"{hrs // 24}天前"


def fetch_market_headlines() -> list[dict]:
    mkt_must = ["美股", "道瓊", "那斯達克", "納斯達克", "標普", "費半", "聯準會", "華爾街", "輝達", "台積電ADR", "美債", "科技股"]
    q1 = '("美股盤後" OR "美股收盤" OR "道瓊" OR "那斯達克" OR "標普500" OR "費半") when:1d'
    q2 = '("聯準會" OR "華爾街" OR "美債殖利率" OR "輝達") 美股 when:1d'
    pool = (
        fetch_google_news_rss(q1, "zh-TW", max_age_hours=26.0, must_match=mkt_must)
        + fetch_google_news_rss(q2, "zh-TW", max_age_hours=26.0, must_match=mkt_must)
    )
    # Exclude blog/column noise if mainstream newsroom stories are plentiful
    tier_main = [p for p in pool if p["source"] not in BLOG_SOURCES]
    candidates = tier_main if len(tier_main) >= 8 else pool
    # Sort by combination of tier & freshness (within last 18h, authoritative sources rank top)
    candidates.sort(key=lambda x: (x["tier"] * 14400 + x["pubTs"]), reverse=True)

    curated: list[dict] = []
    for item in candidates:
        if any(title_similarity(item["title"], c["title"]) > 0.40 for c in curated):
            continue
        curated.append(
            {
                "title": item["title"],
                "source": item["source"],
                "url": item["url"],
                "age": format_age_label(item["ageHours"]),
                "pubTs": item["pubTs"],
            }
        )
        if len(curated) >= 8:
            break
    return curated


def fetch_apewisdom_map() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for page in (1, 2):
        url = f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            data = json.loads(urllib.request.urlopen(req, timeout=7).read().decode("utf-8"))
            for row in data.get("results", []):
                t = row.get("ticker")
                if t:
                    result[t] = row
        except Exception:
            break
    return result


def fetch_ptt_sentiment(keyword: str) -> tuple[float | None, int]:
    url = f"https://www.ptt.cc/bbs/Stock/search?q={urllib.parse.quote(keyword)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cookie": "over18=1"})
    try:
        raw_html = urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore")
        entries = re.findall(r'<div class="nrec">(.*?)</div>.*?<div class="title">(.*?)</div>', raw_html, re.S)[:10]
        if not entries:
            return None, 0
        bull_pts, bear_pts = 0.0, 0.0
        for nrec_html, title_html in entries:
            nrec = re.sub(r"<.*?>", "", nrec_html).strip()
            title = html.unescape(re.sub(r"<.*?>", "", title_html)).strip()
            weight = 15.0 if nrec == "爆" else (float(nrec) if nrec.isdigit() else (-10.0 if nrec.startswith("X") else 3.0))
            t_bull = sum(1 for w in BULL_WORDS if w in title.lower())
            t_bear = sum(1 for w in BEAR_WORDS if w in title.lower())
            if weight < 0:
                bear_pts += abs(weight)
            elif t_bull > t_bear:
                bull_pts += max(weight, 4.0) * 1.25
            elif t_bear > t_bull:
                bear_pts += max(weight, 4.0) * 1.25
            else:
                bull_pts += max(weight, 2.0) * 0.50
                bear_pts += max(weight, 2.0) * 0.50
        total = bull_pts + bear_pts
        return (bull_pts / total if total > 0 else None), len(entries)
    except Exception:
        return None, 0


def score_headlines_sentiment(texts: list[str]) -> tuple[float | None, int]:
    bull, bear, hits = 0.0, 0.0, 0
    for txt in texts:
        low = txt.lower()
        b_up = sum(1 for w in BULL_WORDS if w in low)
        b_dn = sum(1 for w in BEAR_WORDS if w in low)
        if b_up or b_dn:
            hits += 1
            bull += b_up
            bear += b_dn
    if hits == 0 or (bull + bear) == 0:
        return None, 0
    return bull / (bull + bear), hits


def build_stock_insight(
    yc: YahooClient,
    item_cfg: dict,
    quote_obj: dict,
    apewisdom: dict[str, dict],
) -> tuple[str, dict]:
    sym = item_cfg["symbol"]
    must_kw = item_cfg.get("mustMatch") or []

    # 1. Strictly 6-hour headlines from Google News TW + Google News US + Yahoo Finance Ticker RSS
    tw_6h = fetch_google_news_rss(f"({item_cfg['twQuery']}) when:6h", "zh-TW", max_age_hours=6.5, must_match=must_kw)
    yh_6h = fetch_yahoo_ticker_rss(sym, max_age_hours=6.5)
    en_6h = fetch_google_news_rss(f"({item_cfg['enQuery']}) when:6h", "en-US", max_age_hours=6.5, must_match=must_kw)

    en_merged = yh_6h + en_6h
    en_merged.sort(key=lambda x: x["pubTs"], reverse=True)

    raw_texts_for_sentiment = [x["title"] for x in tw_6h[:10]] + [x["title"] for x in en_merged[:10]]

    selected: list[dict] = []
    # Prefer authoritative TW newsrooms first
    tw_sorted = sorted(tw_6h, key=lambda x: (x["source"] not in BLOG_SOURCES, x["pubTs"]), reverse=True)
    for it in tw_sorted:
        if any(title_similarity(it["title"], s["title"]) > 0.42 for s in selected):
            continue
        selected.append(
            {
                "title": it["title"],
                "source": it["source"],
                "url": it["url"],
                "age": format_age_label(it["ageHours"]),
                "within6h": True,
            }
        )
        if len(selected) >= 3:
            break

    if len(selected) < 3:
        for it in en_merged:
            zh_title = translate_en_to_zhtw(it["title"])
            if is_tabloid_or_simplified(zh_title, check_simplified=False):
                continue
            if any(title_similarity(zh_title, s["title"]) > 0.42 for s in selected):
                continue
            selected.append(
                {
                    "title": zh_title,
                    "source": it["source"],
                    "url": it["url"],
                    "age": format_age_label(it["ageHours"]),
                    "within6h": True,
                }
            )
            if len(selected) >= 3:
                break

    # Quiet weekend/off-hours fallback: fetch latest relevant 24h headline clearly marked within6h=False
    if len(selected) == 0:
        fallback_pool = (
            fetch_google_news_rss(f"({item_cfg['twQuery']}) when:1d", "zh-TW", max_age_hours=36.0, must_match=must_kw)
            + fetch_yahoo_ticker_rss(sym, max_age_hours=48.0)
        )
        for it in fallback_pool[:2]:
            zh_title = translate_en_to_zhtw(it["title"]) if it["lang"] == "en-US" else it["title"]
            raw_texts_for_sentiment.append(it["title"])
            selected.append(
                {
                    "title": zh_title,
                    "source": it["source"],
                    "url": it["url"],
                    "age": format_age_label(it["ageHours"]),
                    "within6h": False,
                }
            )

    # 2. Multi-source 6H Netizen Sentiment Index (想買 % vs 想賣 %)
    weighted_scores: list[tuple[float, float]] = []
    detail_parts: list[str] = []

    news_ratio, _ = score_headlines_sentiment(raw_texts_for_sentiment)
    if news_ratio is not None:
        weighted_scores.append((news_ratio, 0.30))

    ptt_ratio, _ = fetch_ptt_sentiment(item_cfg["pttKey"])
    if ptt_ratio is not None:
        weighted_scores.append((ptt_ratio, 0.20))
        detail_parts.append(f"社群討論 {round(ptt_ratio * 100)}%偏多")

    opt_call_ratio, _ = yc.get_option_call_ratio(sym)
    if opt_call_ratio is not None:
        adj_opt = min(0.90, max(0.10, 0.50 + (opt_call_ratio - 0.53) * 1.15))
        weighted_scores.append((adj_opt, 0.30))
        detail_parts.append(f"買權成交比 {round(opt_call_ratio * 100)}%")

    vol_ratio = float(quote_obj.get("_volBuyRatio6h", 0.5))
    chg_pct = float(quote_obj.get("changePct", 0.0))
    price_bias = min(0.84, max(0.16, 0.50 + (chg_pct / 16.0)))
    flow_score = 0.55 * vol_ratio + 0.45 * price_bias

    aw = apewisdom.get(sym.replace("^", ""))
    if aw and aw.get("mentions"):
        m_now = aw.get("mentions") or 0
        m_prev = aw.get("mentions_24h_ago") or m_now
        buzz_growth = (m_now - m_prev) / max(m_prev, 10)
        flow_score = min(0.88, max(0.12, flow_score + buzz_growth * (0.06 if chg_pct >= 0 else -0.06)))
        detail_parts.append(f"Reddit熱度 #{aw['rank']}")

    weighted_scores.append((flow_score, 0.25))
    detail_parts.append(f"6H主動買盤 {round(vol_ratio * 100)}%")

    total_w = sum(w for _, w in weighted_scores)
    raw_buy = sum(val * w for val, w in weighted_scores) / total_w if total_w else 0.5
    buy_pct = int(round(min(88.0, max(12.0, raw_buy * 100.0))))
    if buy_pct == 50:
        buy_pct = 51 if chg_pct >= 0 else 49
    sell_pct = 100 - buy_pct

    if buy_pct >= 65:
        mood_label = "想買居多"
    elif buy_pct > 50:
        mood_label = "想買略多"
    elif sell_pct >= 65:
        mood_label = "想賣居多"
    else:
        mood_label = "想賣略多"

    return sym, {
        "headlines": selected,
        "sentiment": {
            "buyPct": buy_pct,
            "sellPct": sell_pct,
            "dominant": "buy" if buy_pct > 50 else "sell",
            "label": mood_label,
            "summary": " · ".join(detail_parts[:3]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch US Stock Watchlist quotes & 6H insights.")
    parser.add_argument("--mode", choices=["all", "quotes", "insights"], default="all")
    parser.add_argument(
        "--preopen-check",
        action="store_true",
        help="Only run if current America/New_York time is in the 09:00-09:29 ET pre-open window.",
    )
    args = parser.parse_args()

    if args.preopen_check:
        now_et = dt.datetime.now(NY_TZ)
        if not (now_et.weekday() < 5 and now_et.hour == 9 and now_et.minute <= 29):
            print(f"[skip] Pre-open check: NY time is {now_et.strftime('%H:%M %Z')}, skipping duplicate DST slot.")
            return

    root_dir = Path(__file__).resolve().parent.parent
    data_dir = root_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    yc = YahooClient()
    all_symbols = [x["symbol"] for x in INDICES] + [x["symbol"] for x in WATCHLIST]
    q_map = yc.get_quotes(all_symbols)

    now_tw_str = dt.datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    now_iso = dt.datetime.now(UTC_TZ).isoformat()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        idx_futures = [pool.submit(build_index_data, yc, cfg, q_map) for cfg in INDICES]
        stk_futures = [pool.submit(build_stock_quote, yc, cfg, q_map) for cfg in WATCHLIST]
        indices_data = [f.result() for f in idx_futures]
        stocks_quotes = [f.result() for f in stk_futures]

    if args.mode in ("all", "quotes"):
        clean_stocks = [{k: v for k, v in sq.items() if not k.startswith("_")} for sq in stocks_quotes]
        quotes_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "refreshIntervalMinutes": 15,
            "marketSession": get_market_session_overview(),
            "indices": indices_data,
            "watchlist": clean_stocks,
        }
        (data_dir / "quotes.json").write_text(
            json.dumps(quotes_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/quotes.json ({len(clean_stocks)} stocks, {len(indices_data)} indices)")

    if args.mode in ("all", "insights"):
        apewisdom = fetch_apewisdom_map()
        market_headlines = fetch_market_headlines()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            ins_futures = [
                pool.submit(build_stock_insight, yc, cfg, sq, apewisdom)
                for cfg, sq in zip(WATCHLIST, stocks_quotes)
            ]
            stock_insights = dict(f.result() for f in ins_futures)

        insights_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "scheduleNote": "每 6 小時自動更新 ＋ 美股開盤前 10 分鐘 (09:20 ET) 強制更新",
            "marketHeadlines": market_headlines,
            "stocks": stock_insights,
        }
        (data_dir / "insights.json").write_text(
            json.dumps(insights_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/insights.json ({len(market_headlines)} market headlines, {len(stock_insights)} stocks)")


if __name__ == "__main__":
    main()
