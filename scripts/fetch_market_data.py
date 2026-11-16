#!/usr/bin/env python3
"""
US Stock Watchlist Data Pipeline
Fetches:
1. Previous/latest completed trading session intraday chart + closing price & % for Dow (^DJI), Nasdaq (^IXIC), S&P 500 (^GSPC)
2. Top US market headlines (concise bullet points + source links, authoritative financial sources prioritized)
3. 15-minute watchlist quotes across all sessions (夜盤 Overnight, 盤前 Pre-Market, 盤中 Regular, 盤後 After-Hours),
   with user's portfolio holdings prioritized at the top
4. Per-stock 6-hour key headlines (updated every 6h + 10 mins before US market open)
5. Per-stock 6-hour netizen sentiment index (想買 % green vs 想賣 % red)
6. Dynamic CIO (Chief Investment Officer) tactical portfolio & market advisory
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
import threading
import time
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

# Holdings prioritized at the very top, followed by the rest of the watchlist
WATCHLIST = [
    # === Group 1: 我的核心持倉 (Prioritized First) ===
    {
        "symbol": "GOOG",
        "displaySymbol": "GOOG",
        "name": "Alphabet (Google)",
        "enName": "ALPHABET INC-CL C",
        "category": "tech",
        "isHolding": True,
        "holdingBadge": "現股持倉",
        "twQuery": '"Google" OR "Alphabet" OR "GOOG"',
        "enQuery": '"GOOG" OR "Alphabet" OR "Google stock"',
        "mustMatch": ["goog", "google", "alphabet", "gemini", "waymo", "youtube", "tpu"],
        "pttKey": "GOOG",
    },
    {
        "symbol": "TSM",
        "displaySymbol": "TSM",
        "name": "台積電 ADR",
        "enName": "TAIWAN SEMICONDUCTOR-SP ADR",
        "category": "semi",
        "isHolding": True,
        "holdingBadge": "現股＋CC",
        "twQuery": '"台積電ADR" OR "台積電" 美股',
        "enQuery": '"TSMC" OR "TSM stock" OR "Taiwan Semiconductor"',
        "mustMatch": ["台積電", "台積", "tsmc", "tsm", "cowos", "魏哲家"],
        "pttKey": "台積",
    },
    {
        "symbol": "TSLA",
        "displaySymbol": "TSLA",
        "name": "特斯拉",
        "enName": "TESLA INC",
        "category": "tech",
        "isHolding": True,
        "holdingBadge": "現股＋CC",
        "twQuery": '"特斯拉" OR "TSLA"',
        "enQuery": '"Tesla" OR "TSLA"',
        "mustMatch": ["特斯拉", "tesla", "tsla", "cybercab", "robotaxi", "optimus", "fsd"],
        "pttKey": "特斯拉",
    },
    {
        "symbol": "NVDA",
        "displaySymbol": "NVDA",
        "name": "輝達",
        "enName": "NVIDIA CORP",
        "category": "semi",
        "isHolding": True,
        "holdingBadge": "賣Put持倉",
        "twQuery": '"輝達" OR "NVDA"',
        "enQuery": '"Nvidia" OR "NVDA"',
        "mustMatch": ["輝達", "nvidia", "nvda", "blackwell", "rubin", "kress", "柯蕾絲", "克雷斯"],
        "pttKey": "輝達",
    },
    {
        "symbol": "TQQQ",
        "displaySymbol": "TQQQ",
        "name": "ProShares 納指3倍做多",
        "enName": "PROSHARES ULTRAPRO QQQ",
        "category": "macro",
        "isHolding": True,
        "holdingBadge": "衛星持倉",
        "twQuery": '"TQQQ" OR "那斯達克" 槓桿 OR "那指"',
        "enQuery": '"TQQQ" OR "ProShares UltraPro QQQ"',
        "mustMatch": ["tqqq", "那斯達克", "納斯達克", "那指", "納指", "qqq", "nasdaq"],
        "pttKey": "TQQQ",
    },
    {
        "symbol": "BOXX",
        "displaySymbol": "BOXX",
        "name": "Alpha Architect 箱型套利現金池",
        "enName": "ALPHA ARCHITECT 1-3M BOX ETF",
        "category": "macro",
        "isHolding": True,
        "holdingBadge": "現金擔保池",
        "twQuery": '"美債殖利率" OR "聯準會" 利率 OR "短債"',
        "enQuery": '"BOXX ETF" OR "Treasury bills" yield OR "Fed rate"',
        "mustMatch": ["boxx", "美債", "短債", "殖利率", "聯準會", "treasury", "fed", "yield"],
        "pttKey": "美債",
    },
    {
        "symbol": "IAU",
        "displaySymbol": "IAU",
        "name": "iShares 黃金信託 ETF",
        "enName": "ISHARES GOLD TRUST",
        "category": "macro",
        "isHolding": True,
        "holdingBadge": "黃金避險",
        "twQuery": '"國際金價" OR "黃金價格" OR "現貨黃金"',
        "enQuery": '"Gold price" OR "IAU ETF" OR "gold futures"',
        "mustMatch": ["金價", "黃金", "gold", "iau", "盎司"],
        "pttKey": "黃金",
    },

    # === Group 2: 自選觀察名單 ===
    {
        "symbol": "VOO",
        "displaySymbol": "VOO",
        "name": "Vanguard 標普500 ETF",
        "enName": "VANGUARD S&P 500 ETF",
        "category": "macro",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"VOO" OR "標普500" OR "S&P 500"',
        "enQuery": '"VOO" OR "S&P 500"',
        "mustMatch": ["voo", "標普", "s&p 500", "s&p500", "sp500", "vanguard"],
        "pttKey": "VOO",
    },
    {
        "symbol": "QQQ",
        "displaySymbol": "QQQ",
        "name": "Invesco 納指100 ETF",
        "enName": "INVESCO QQQ TRUST SERIES 1",
        "category": "macro",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"QQQ" OR "那斯達克" OR "納斯達克"',
        "enQuery": '"QQQ" OR "Nasdaq 100" OR "Nasdaq"',
        "mustMatch": ["qqq", "那斯達克", "納斯達克", "那指", "納指", "nasdaq", "科技股"],
        "pttKey": "QQQ",
    },
    {
        "symbol": "MSFT",
        "displaySymbol": "MSFT",
        "name": "微軟",
        "enName": "MICROSOFT CORP",
        "category": "tech",
        "isHolding": False,
        "holdingBadge": "",
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
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"Meta" 美股 OR "祖克柏"',
        "enQuery": '"Meta Platforms" OR "META stock"',
        "mustMatch": ["meta", "祖克柏", "zuckerberg", "llama", "instagram", "threads"],
        "pttKey": "META",
    },
    {
        "symbol": "SPCX",
        "displaySymbol": "SPCX",
        "name": "太空探索技術 (SpaceX)",
        "enName": "SPACE EXPLORATION TECHN-CL A",
        "category": "tech",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"SpaceX" OR "SPCX" OR "星艦"',
        "enQuery": '"SPCX" OR "SpaceX" OR "Starlink"',
        "mustMatch": ["spacex", "spcx", "starship", "starlink", "星艦", "星鏈", "太空探索"],
        "pttKey": "SpaceX",
    },
    {
        "symbol": "MU",
        "displaySymbol": "MU",
        "name": "美光科技",
        "enName": "MICRON TECHNOLOGY INC",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"美光" OR "Micron"',
        "enQuery": '"Micron" OR "MU stock"',
        "mustMatch": ["美光", "micron", "hbm", "dram", "記憶體", "mu "],
        "pttKey": "美光",
    },
    {
        "symbol": "AMD",
        "displaySymbol": "AMD",
        "name": "超微半導體 (AMD)",
        "enName": "ADVANCED MICRO DEVICES",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"超微" OR "蘇姿丰" OR "AMD"',
        "enQuery": '"AMD" OR "Advanced Micro Devices"',
        "mustMatch": ["超微", "amd", "蘇姿丰", "mi3", "mi4", "ryzen", "epyc"],
        "pttKey": "AMD",
    },
    {
        "symbol": "AVGO",
        "displaySymbol": "AVGO",
        "name": "博通",
        "enName": "BROADCOM INC",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"博通" OR "Broadcom" OR "AVGO"',
        "enQuery": '"Broadcom" OR "AVGO"',
        "mustMatch": ["博通", "broadcom", "avgo", "asic", "陳福陽"],
        "pttKey": "博通",
    },
    {
        "symbol": "INTC",
        "displaySymbol": "INTC",
        "name": "英特爾",
        "enName": "INTEL CORP",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"英特爾" OR "Intel" OR "INTC"',
        "enQuery": '"Intel" OR "INTC"',
        "mustMatch": ["英特爾", "intel", "intc", "18a", "晶圓代工"],
        "pttKey": "INTC",
    },
    {
        "symbol": "SOXL",
        "displaySymbol": "SOXL",
        "name": "Direxion 半導體3倍做多",
        "enName": "DIREXION DAILY SEMI BULL 3X",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"SOXL" OR "費城半導體" OR "費半"',
        "enQuery": '"SOXL" OR "semiconductor ETF" OR "PHLX Semiconductor"',
        "mustMatch": ["soxl", "費半", "費城半導體", "半導體", "semiconductor", "chip"],
        "pttKey": "SOXL",
    },
    {
        "symbol": "IBIT",
        "displaySymbol": "IBIT",
        "name": "iShares 比特幣信託 ETF",
        "enName": "ISHARES BITCOIN TRUST ETF",
        "category": "macro",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"比特幣" OR "IBIT"',
        "enQuery": '"IBIT" OR "Bitcoin ETF" OR "Bitcoin"',
        "mustMatch": ["比特幣", "bitcoin", "btc", "ibit", "加密貨幣"],
        "pttKey": "比特幣",
    },
    {
        "symbol": "CL=F",
        "displaySymbol": "CL @NYMEX",
        "name": "NYMEX WTI 輕原油期貨",
        "enName": "WTI CRUDE OIL FUTURES (NYMEX)",
        "category": "macro",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"國際油價" OR "紐約原油" OR "WTI原油" OR "西德州原油"',
        "enQuery": '"WTI crude" OR "crude oil" OR "oil prices"',
        "mustMatch": ["油價", "原油", "wti", "西德州", "布蘭特", "opec", "crude", "oil"],
        "pttKey": "油價",
    },
    {
        "symbol": "UCO",
        "displaySymbol": "UCO",
        "name": "ProShares 兩倍做多原油",
        "enName": "PROSHARES ULTRA BLOOMBERG CRUDE",
        "category": "macro",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"原油" OR "國際油價" OR "WTI"',
        "enQuery": '"UCO ETF" OR "Bloomberg Crude Oil" OR "crude oil ETF"',
        "mustMatch": ["uco ", "uco)", "原油", "油價", "wti", "brent", "crude", "oil", "opec"],
        "pttKey": "原油",
    },
    {
        "symbol": "^VIX",
        "displaySymbol": "VIX",
        "name": "CBOE 波動率恐慌指數",
        "enName": "CBOE VOLATILITY INDEX",
        "category": "macro",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"VIX" OR "恐慌指數"',
        "enQuery": '"VIX" OR "volatility index" market',
        "mustMatch": ["vix", "恐慌指數", "波動率", "volatility", "避險", "美股"],
        "pttKey": "VIX",
    },
]

TABLOID_BLACKLIST = [
    "炎亞綸", "男友", "女友", "女星", "男星", "藝人", "娛樂", "星座", "生肖", "命理", "風水", "減肥", "糖尿病", "八點檔",
    "股市爆料同學會", "爆料同學會", "[free-tv]", "ncaa", "college football", "live stream",
    "stock price, news, quote", "quote & history", " by tk ",
]

TIER1_SOURCES = {
    "鉅亨網", "經濟日報", "工商時報", "Yahoo股市", "Yahoo奇摩股市", "Yahoo 財經", "自由財經",
    "中央社", "MoneyDJ理財網", "財訊", "聯合新聞網", "科技新報", "商周", "今周刊",
    "Reuters", "Bloomberg", "CNBC", "WSJ", "The Wall Street Journal", "MarketWatch", "Barron's", "Yahoo Finance",
}
BLOG_SOURCES = {"CMoney", "CMoney投資網誌", "股市爆料同學會", "鉅亨號", "方格子", "Vocus", "Facebook", "Threads"}

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
        for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
            try:
                resp = self.opener.open(f"https://{host}/v1/test/getcrumb", timeout=8)
                crumb_val = resp.read().decode("utf-8").strip()
                if crumb_val:
                    self.crumb = crumb_val
                    break
            except Exception as exc:
                print(f"[warn] crumb init ({host}) failed: {exc}", file=sys.stderr)

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        if not self.crumb:
            return {}
        sym_str = urllib.parse.quote(",".join(symbols), safe=",")
        crumb_q = urllib.parse.quote(self.crumb)
        for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
            url = (
                f"https://{host}/v7/finance/quote"
                f"?symbols={sym_str}&overnightPrice=true&crumb={crumb_q}"
            )
            try:
                raw = self.opener.open(url, timeout=12).read().decode("utf-8")
                items = json.loads(raw).get("quoteResponse", {}).get("result", [])
                if items:
                    return {it["symbol"]: it for it in items if "symbol" in it}
            except Exception as exc:
                print(f"[warn] get_quotes ({host}) failed: {exc}", file=sys.stderr)
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
        if symbol in ("CL=F", "BOXX") or not self.crumb:
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

    cur_session_code = get_market_session_overview()["sessionCode"]

    for field_p, field_t, lbl in [
        ("preMarketPrice", "preMarketTime", "盤前"),
        ("postMarketPrice", "postMarketTime", "盤後"),
        ("overnightMarketPrice", "overnightMarketTime", "夜盤"),
    ]:
        val = q.get(field_p)
        ts = int(q.get(field_t) or 0)
        if val is not None:
            if ts <= 0 and lbl == "夜盤" and (market_state == "OVERNIGHT" or cur_session_code == "OVERNIGHT"):
                ts = int(time.time())
            if ts > 0:
                candidates.append((ts, float(val), lbl))

    # Zero-crumb fallback: Yahoo chart meta exposes live Blue Ocean ATS price via fulldayPrice during OVERNIGHT
    if (
        cur_session_code == "OVERNIGHT"
        and sym not in ("CL=F", "^VIX")
        and not any(lbl == "夜盤" for _, _, lbl in candidates)
    ):
        fullday_p = meta.get("fulldayPrice")
        if fullday_p is not None and float(fullday_p) > 0:
            candidates.append((int(time.time()), float(fullday_p), "夜盤"))

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

    if sym == "CL=F" and session_label in ("盤中", "盤後", "夜盤", "盤前", "電子盤"):
        if market_state == "REGULAR":
            if cur_session_code == "OVERNIGHT":
                session_label = "期貨夜盤"
            elif cur_session_code == "PRE":
                session_label = "期貨盤前"
            else:
                session_label = "期貨盤中"
        else:
            session_label = "期貨收盤"
    elif sym == "^VIX":
        session_label = "盤中" if market_state == "REGULAR" else "收盤"

    if session_label == "夜盤" and q.get("overnightMarketChange") is not None and q.get("overnightMarketChangePercent") is not None:
        change = float(q["overnightMarketChange"])
        change_pct = float(q["overnightMarketChangePercent"])
    elif session_label == "盤前" and q.get("preMarketChange") is not None and q.get("preMarketChangePercent") is not None:
        change = float(q["preMarketChange"])
        change_pct = float(q["preMarketChangePercent"])
    else:
        if session_label in ("盤前", "夜盤") and reg_price:
            base_close = float(reg_price)
        else:
            base_close = float(reg_prev_close) if reg_prev_close else float(reg_price)
        change = latest_price - base_close
        change_pct = (change / base_close * 100.0) if base_close else 0.0

    reg_change_pct = float(q.get("regularMarketChangePercent") or ((reg_price - reg_prev_close) / reg_prev_close * 100 if reg_prev_close else 0.0))
    if session_label == "夜盤" and q.get("overnightMarketChangePercent") is not None:
        ext_diff_pct = float(q["overnightMarketChangePercent"])
    elif reg_price and session_label not in ("盤中", "收盤", "期貨盤中", "期貨夜盤", "期貨盤前", "期貨收盤"):
        ext_diff_pct = (latest_price - reg_price) / reg_price * 100.0
    else:
        ext_diff_pct = None

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
        "isHolding": bool(item_cfg.get("isHolding", False)),
        "holdingBadge": item_cfg.get("holdingBadge", ""),
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
        "high52w": round(float(q.get("fiftyTwoWeekHigh") or meta.get("fiftyTwoWeekHigh") or latest_price), 2),
        "sparkline": sparkline,
        "_volBuyRatio6h": round(vol_buy_ratio, 4),
    }


_TRANSLATE_SEM = threading.Semaphore(3)
_TRANSLATE_CACHE: dict[str, str] = {}

ALLOWED_EN_TERMS = {
    "ai", "agi", "llm", "gpu", "cpu", "tpu", "npu", "asic", "hbm", "hbm3e", "hbm4", "dram", "nand",
    "cowos", "etf", "adr", "ipo", "ceo", "cfo", "coo", "fed", "fomc", "cpi", "pce", "gdp", "sec", "doj", "ftc",
    "aws", "azure", "gcp", "openai", "chatgpt", "gemini", "claude", "llama", "deepseek", "anthropic",
    "apple", "iphone", "ipad", "mac", "macbook", "ios", "microsoft", "windows", "nvidia", "nvda", "blackwell", "rubin",
    "google", "alphabet", "goog", "waymo", "youtube", "meta", "tesla", "tsla", "fsd", "optimus", "cybercab",
    "tsmc", "tsm", "amd", "avgo", "broadcom", "intel", "intc", "micron", "mu", "qualcomm", "qcom",
    "oracle", "orcl", "netflix", "nflx", "salesforce", "crm", "cisco", "csco", "ibm", "palantir", "pltr",
    "spacex", "spcx", "starlink", "uber", "adobe", "adbe", "crowdstrike", "crwd", "linux", "gcc",
    "voo", "qqq", "tqqq", "soxl", "boxx", "iau", "ibit", "uco", "wti", "nymex", "opec", "vix", "nasdaq",
}


def cjk_char_count(text: str) -> int:
    return sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")


def needs_zh_translation(text: str) -> bool:
    if not text:
        return False
    cjk_cnt = cjk_char_count(text)
    if cjk_cnt == 0:
        return True
    en_words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", text)]
    ordinary_en = [w for w in en_words if w not in ALLOWED_EN_TERMS]
    if cjk_cnt < 4 and len(ordinary_en) >= 2:
        return True
    if len(ordinary_en) >= 4:
        return True
    return False


def post_polish_zh(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "英偉達": "輝達",
        "美聯儲": "聯準會",
        "特斯聯": "特斯拉",
        "超威半導體": "超微 (AMD)",
        "博通公司": "博通",
        "谷歌": "Google",
        "元平台": "Meta",
    }
    for src_w, dst_w in replacements.items():
        text = text.replace(src_w, dst_w)
    return text.strip()


def translate_en_to_zhtw(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if not needs_zh_translation(text):
        return post_polish_zh(text)
    if text in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[text]

    with _TRANSLATE_SEM:
        if text in _TRANSLATE_CACHE:
            return _TRANSLATE_CACHE[text]

        q = urllib.parse.quote(text)
        # Primary endpoint: translate.googleapis.com (sl=en preserves existing Chinese while translating all English phrases)
        for attempt in range(2):
            try:
                url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q={q}"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                raw = json.loads(urllib.request.urlopen(req, timeout=7).read().decode("utf-8"))
                out = post_polish_zh("".join(seg[0] for seg in raw[0] if seg and seg[0]))
                if cjk_char_count(out) >= 2:
                    _TRANSLATE_CACHE[text] = out
                    return out
            except Exception:
                time.sleep(0.35 * (attempt + 1))

        # Secondary fallback endpoint: clients5.google.com
        try:
            url2 = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=zh-TW&q={q}"
            req2 = urllib.request.Request(url2, headers={"User-Agent": USER_AGENT})
            raw2 = json.loads(urllib.request.urlopen(req2, timeout=7).read().decode("utf-8"))
            if isinstance(raw2, list) and raw2:
                first = raw2[0]
                out2 = post_polish_zh(first[0] if isinstance(first, list) else str(first))
                if cjk_char_count(out2) >= 2:
                    _TRANSLATE_CACHE[text] = out2
                    return out2
        except Exception:
            pass

    return post_polish_zh(text)


def extract_clean_summary(raw_desc: str, clean_title: str) -> str:
    if not raw_desc:
        return ""
    txt = html.unescape(re.sub(r"<.*?>", " ", raw_desc))
    txt = re.sub(r"\s+", " ", txt).strip()
    txt = re.sub(r"^Key Takeaways\s*:?\s*", "", txt, flags=re.I).strip()
    if len(txt) < 18:
        return ""
    if title_similarity(txt[: len(clean_title) + 10], clean_title) > 0.55:
        return ""
    if len(txt) > 160:
        cut = txt[:160].rsplit(" ", 1)[0] if " " in txt[:160] else txt[:160]
        txt = cut.rstrip(".,;:") + "…"
    return txt


def clean_headline_title(title: str, source: str) -> str:
    title = html.unescape(title or "").strip()
    if source and title.endswith(f" - {source}"):
        title = title[: -len(f" - {source}")].strip()
    elif " - " in title:
        parts = title.rsplit(" - ", 1)
        if len(parts[1]) <= 24:
            title = parts[0].strip()
    if "|" in title:
        title = title.split("|")[0].strip()
    for noise_tag in ("（不斷更新）", "(不斷更新)", "【不斷更新】"):
        title = title.replace(noise_tag, "").strip()
    return post_polish_zh(title)


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
                    "summary": "",
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


def fetch_yahoo_ticker_rss(
    symbol: str,
    max_age_hours: float = 6.5,
    must_match: list[str] | None = None,
) -> list[dict]:
    sym_q = urllib.parse.quote(symbol)
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym_q}&region=US&lang=en-US"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    now_utc = dt.datetime.now(UTC_TZ)
    items: list[dict] = []
    try:
        xml_bytes = urllib.request.urlopen(req, timeout=7).read()
        root = ET.fromstring(xml_bytes)
        for el in root.findall("./channel/item"):
            raw_title = el.findtext("title") or ""
            raw_desc = el.findtext("description") or ""
            link = (el.findtext("link") or "").strip()
            pub_str = el.findtext("pubDate") or ""
            title = clean_headline_title(raw_title, "Yahoo Finance")
            if not title or not link:
                continue
            if is_tabloid_or_simplified(title, check_simplified=False):
                continue
            if must_match and not matches_keywords(f"{title} {raw_desc}", must_match):
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
                    "summary": extract_clean_summary(raw_desc, title),
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
    tier_main = [p for p in pool if p["source"] not in BLOG_SOURCES]
    candidates = tier_main if len(tier_main) >= 8 else pool
    candidates.sort(key=lambda x: (x["tier"] * 14400 + x["pubTs"]), reverse=True)

    curated: list[dict] = []
    for item in candidates:
        zh_title = clean_headline_title(translate_en_to_zhtw(item["title"]), item["source"])
        if cjk_char_count(zh_title) < 2:
            continue
        if any(title_similarity(zh_title, c["title"]) > 0.40 for c in curated):
            continue
        curated.append(
            {
                "title": zh_title,
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


def _format_translated_headline_entry(it: dict, within_6h: bool) -> dict | None:
    zh_title = clean_headline_title(translate_en_to_zhtw(it["title"]), it["source"])
    if cjk_char_count(zh_title) < 2:
        return None
    if is_tabloid_or_simplified(zh_title, check_simplified=False):
        return None
    raw_sum = it.get("summary") or ""
    zh_sum = translate_en_to_zhtw(raw_sum) if raw_sum else ""
    if zh_sum and (cjk_char_count(zh_sum) < 2 or title_similarity(zh_sum, zh_title) > 0.55):
        zh_sum = ""
    return {
        "title": zh_title,
        "summary": zh_sum,
        "source": it["source"],
        "url": it["url"],
        "age": format_age_label(it["ageHours"]),
        "within6h": within_6h,
    }


def build_stock_insight(
    yc: YahooClient,
    item_cfg: dict,
    quote_obj: dict,
    apewisdom: dict[str, dict],
) -> tuple[str, dict]:
    sym = item_cfg["symbol"]
    must_kw = item_cfg.get("mustMatch") or []

    tw_6h = fetch_google_news_rss(f"({item_cfg['twQuery']}) when:6h", "zh-TW", max_age_hours=6.5, must_match=must_kw)
    yh_6h = fetch_yahoo_ticker_rss(sym, max_age_hours=6.5, must_match=must_kw)
    en_6h = fetch_google_news_rss(f"({item_cfg['enQuery']}) when:6h", "en-US", max_age_hours=6.5, must_match=must_kw)

    en_merged = yh_6h + en_6h
    en_merged.sort(key=lambda x: x["pubTs"], reverse=True)

    raw_texts_for_sentiment = [x["title"] for x in tw_6h[:10]] + [x["title"] for x in en_merged[:10]]

    selected: list[dict] = []
    tw_non_blog = [x for x in tw_6h if x["source"] not in BLOG_SOURCES]
    tw_sorted = sorted(tw_non_blog, key=lambda x: (x["tier"], x["pubTs"]), reverse=True)
    for it in tw_sorted:
        entry = _format_translated_headline_entry(it, within_6h=True)
        if not entry:
            continue
        if any(title_similarity(entry["title"], s["title"]) > 0.42 for s in selected):
            continue
        selected.append(entry)
        if len(selected) >= 3:
            break

    if len(selected) < 3:
        for it in en_merged:
            if it["source"] in BLOG_SOURCES:
                continue
            entry = _format_translated_headline_entry(it, within_6h=True)
            if not entry:
                continue
            if any(title_similarity(entry["title"], s["title"]) > 0.42 for s in selected):
                continue
            selected.append(entry)
            if len(selected) >= 3:
                break

    if len(selected) == 0:
        fallback_pool = (
            fetch_google_news_rss(f"({item_cfg['twQuery']}) when:1d", "zh-TW", max_age_hours=36.0, must_match=must_kw)
            + fetch_yahoo_ticker_rss(sym, max_age_hours=48.0, must_match=must_kw)
        )
        for it in fallback_pool:
            if it["source"] in BLOG_SOURCES:
                continue
            entry = _format_translated_headline_entry(it, within_6h=False)
            if not entry:
                continue
            if any(title_similarity(entry["title"], s["title"]) > 0.42 for s in selected):
                continue
            raw_texts_for_sentiment.append(it["title"])
            selected.append(entry)
            if len(selected) >= 2:
                break

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


def build_cio_advisory(
    indices_data: list[dict],
    stocks_quotes: list[dict],
    stock_insights: dict[str, dict],
) -> dict:
    """Generates dynamic, data-driven institutional CIO & CRO tactical recommendations."""
    s_map = {s["symbol"]: s for s in stocks_quotes}
    i_map = {x["symbol"]: x for x in indices_data}

    vix = s_map.get("^VIX", {}).get("price", 18.0)
    vix_chg = s_map.get("^VIX", {}).get("changePct", 0.0)
    spx_chg = i_map.get("^GSPC", {}).get("changePct", 0.0)
    ixic_chg = i_map.get("^IXIC", {}).get("changePct", 0.0)

    goog = s_map.get("GOOG", {})
    tsm = s_map.get("TSM", {})
    tsla = s_map.get("TSLA", {})
    nvda = s_map.get("NVDA", {})
    tqqq = s_map.get("TQQQ", {})
    voo = s_map.get("VOO", {})

    # 1. Macro & Volatility Regime Verdict
    if vix >= 23:
        regime_tag = "高波動防禦期 (VIX ≥ 23)"
        regime_tone = "caution"
        regime_summary = (
            f"恐慌指數 VIX 升至 {vix:.2f} ({vix_chg:+.2f}%)，選擇權隱含波動率 (IV) 極度肥美。"
            "嚴禁追買 3 倍槓桿 ETF，優先運用現金擔保池於極端支撐位收租 (Sell Put)，或分批承接大盤指數。"
        )
    elif vix >= 18:
        regime_tag = "震盪分歧・賣方收租優勢期"
        regime_tone = "neutral"
        regime_summary = (
            f"目前 VIX 處於 {vix:.2f} ({vix_chg:+.2f}%)，標普 {spx_chg:+.2f}%、納指 {ixic_chg:+.2f}%，科技權值股進入事件與估值重估震盪。"
            "權利金溢價高於歷史均值，最有利於核心持股 Covered Call 收斂時間價值 (Theta)，不宜在平盤附近盲目消耗現金池。"
        )
    else:
        regime_tag = "低波動順風期 (VIX < 18)"
        regime_tone = "bull"
        regime_summary = (
            f"VIX 回落至 {vix:.2f} 穩定區間，市場風險偏好回溫。"
            "核心科技股續抱讓獲利奔跑；賣出 Covered Call 履約價宜拉遠至 Delta 0.15–0.20，避免主升段被提前買走。"
        )

    # 2. Core Holdings Tactical Cards
    holdings_notes = []

    # GOOG + TSM
    goog_p = goog.get("price", 0)
    tsm_p = tsm.get("price", 0)
    holdings_notes.append(
        {
            "title": f"GOOG (${goog_p:.2f}) ＆ TSM (${tsm_p:.2f}) — AI 基建雙核心",
            "action": "續抱收租",
            "actionType": "hold",
            "detail": (
                "輝達管理層震盪加速雲端巨頭自研 ASIC / TPU 佈局，GOOG 直接受惠；"
                f"無論 GPU 或 ASIC 市佔如何消長，先進製程與 CoWoS 訂單皆由台積電獨攬。TSM 現價距上方 $430 / $460 掩護買權具充足緩衝，靜待時間價值收斂。"
            ),
        }
    )

    # TSLA
    tsla_p = tsla.get("price", 0)
    tsla_buf = ((410.0 - tsla_p) / tsla_p * 100) if tsla_p else 0
    if tsla_p >= 408:
        tsla_act, tsla_type = "留意轉倉 ($410C)", "watch"
        tsla_txt = f"現價 ${tsla_p:.2f} 已逼近 $410 Covered Call 履約區，若帶量站穩 $415 可考慮向上向外轉倉 (Roll Up & Out) 鎖住價差與新權利金。"
    else:
        tsla_act, tsla_type = "安全收租中", "hold"
        tsla_txt = f"現價 ${tsla_p:.2f} 距離 $410 Covered Call 尚有 +{tsla_buf:.1f}% 安全墊，短線拉回正好讓賣方選擇權快速獲利，無須額外動作。"
    holdings_notes.append(
        {
            "title": f"TSLA (${tsla_p:.2f}) — 波段持股與掩護買權",
            "action": tsla_act,
            "actionType": tsla_type,
            "detail": tsla_txt,
        }
    )

    # NVDA Short Put Risk Control
    nvda_p = nvda.get("price", 0)
    if nvda_p <= 155:
        nvda_act, nvda_type = "高度警戒・考慮降級轉倉", "alert"
        nvda_txt = (
            f"現價 ${nvda_p:.2f} 已跌破 $160 履約價並逼近 $151.38 損平防線與 $148.95 關鍵支撐！"
            "財報與臨時 CEO 展望公布前波動劇烈，建議將 $160 Put 向下向外轉倉 (Roll Down & Out) 至 $135–$140 安全區。"
        )
    elif nvda_p <= 165:
        nvda_act, nvda_type = "財報前嚴守風控", "watch"
        nvda_txt = (
            f"現價 ${nvda_p:.2f} 正處於 $160 Put 履約價邊緣（距損平線 $151.38 尚有約 ${nvda_p - 151.38:.1f} 緩衝）。"
            "下週財報與換帥後首場法說會前存在跳空風險：保守者可趁盤中反彈平倉撤退；續抱者務必緊盯 $149 頸線，失守即執行向下轉倉。"
        )
    else:
        nvda_act, nvda_type = "趁反彈停利減碼", "bull"
        nvda_txt = (
            f"現價反彈至 ${nvda_p:.2f}，已脫離 $160 Put 威脅區。鑑於永久 CEO 未定、創辦人溢價壓縮，"
            "建議於權利金獲利達 50%–65% 時提前買回平倉，將保證金釋放給確定性更高的 TSM 或 VOO。"
        )
    holdings_notes.append(
        {
            "title": f"NVDA (${nvda_p:.2f}) — 賣出 $160 Put 風控焦點",
            "action": nvda_act,
            "actionType": nvda_type,
            "detail": nvda_txt,
        }
    )

    # BOXX -> VOO Deployment & TQQQ Leverage Check
    voo_p = voo.get("price", 689.0)
    voo_high = max(voo.get("high52w", 718.47), voo_p)
    voo_dd_52w = ((voo_p - voo_high) / voo_high * 100) if voo_high else 0.0
    month_ref = max(voo.get("dayHigh", 698.8), 696.0)
    buy_zone_1 = round(month_ref * 0.97, 0)  # -3% from recent swing high (~$675-$678)
    buy_zone_2 = round(month_ref * 0.95, 0)  # -5% from recent swing high (~$661-$664)

    if voo_p <= buy_zone_1:
        voo_act, voo_type = "觸發第一批現股買點！", "bull"
        voo_txt = (
            f"VOO 現價 ${voo_p:.2f} 已跌入近月高點回檔 -3% 擊球區 (≤ ${buy_zone_1:.0f}，距歷史高點 ${voo_high:.2f} 修正 {voo_dd_52w:.1f}%)！"
            f"可賣出部分 BOXX 啟動第一批 VOO 長線現股建倉；第二批加碼點設於 ${buy_zone_2:.0f}。"
        )
    else:
        voo_act, voo_type = "按兵不動・BOXX 領息", "hold"
        voo_txt = (
            f"VOO 現價 ${voo_p:.2f}（距 52 週高點 ${voo_high:.2f} 回落 {voo_dd_52w:.1f}%），尚未觸及近月波段 -3% 目標買點 (${buy_zone_1:.0f})。"
            f"維持紀律續抱 BOXX 穩領 ~4.3% 免扣稅收益並充當保證金防彈衣，等回測 ${buy_zone_1:.0f} / ${buy_zone_2:.0f} 再分批換倉現股；"
            f"TQQQ (${tqqq.get('price', 0):.2f}) 維持輕倉，逢納指反彈分批降槓桿。"
        )
    holdings_notes.append(
        {
            "title": f"BOXX 現金池 ➔ VOO (${voo_p:.2f}) ＆ TQQQ 槓桿控管",
            "action": voo_act,
            "actionType": voo_type,
            "detail": voo_txt,
        }
    )

    # 3. Watchlist Opportunity & Contrarian Sentiment Scanner
    non_holdings = [s for s in stocks_quotes if not s.get("isHolding") and s["symbol"] not in ("^VIX", "CL=F", "UCO")]
    biggest_drop = min(non_holdings, key=lambda x: x["changePct"], default=None)
    strongest_gain = max(non_holdings, key=lambda x: x["changePct"], default=None)

    scanner_bullets = []
    if biggest_drop and biggest_drop["changePct"] <= -4.0:
        bd_sym = biggest_drop["symbol"]
        bd_sent = stock_insights.get(bd_sym, {}).get("sentiment", {})
        scanner_bullets.append(
            f"重挫觀察：{biggest_drop['displaySymbol']} ({biggest_drop['name']}) 單日回落 {biggest_drop['changePct']:+.2f}% "
            f"(6H 網友想賣 {bd_sent.get('sellPct', 50)}%)。3 倍槓桿或高估值晶片股急跌時切忌盲目接刀，若欲收租應等單日止跌紅 K 再評估價外深處 Put。"
        )
    if strongest_gain and strongest_gain["changePct"] >= 1.0:
        sg_sym = strongest_gain["symbol"]
        sg_sent = stock_insights.get(sg_sym, {}).get("sentiment", {})
        scanner_bullets.append(
            f"相對強勢：{strongest_gain['displaySymbol']} ({strongest_gain['name']}) 逆勢表現 {strongest_gain['changePct']:+.2f}% "
            f"(6H 網友想買 {sg_sent.get('buyPct', 50)}%)，展現資金避風港與輪動韌性。"
        )

    spcx = s_map.get("SPCX")
    if spcx:
        spcx_sent = stock_insights.get("SPCX", {}).get("sentiment", {})
        scanner_bullets.append(
            f"熱門題材追蹤：SPCX (SpaceX) 最新報 ${spcx['price']:.2f} ({spcx['changePct']:+.2f}%，網友想買 {spcx_sent.get('buyPct', 50)}%)，"
            "目前處於高本益比與高波動消化期，適合列入右側突破觀察，暫不納入重倉核心。"
        )

    return {
        "regimeTag": regime_tag,
        "regimeTone": regime_tone,
        "regimeSummary": regime_summary,
        "cards": holdings_notes,
        "scannerBullets": scanner_bullets,
    }


TOP30_TECH_ENTITIES: list[tuple[str, str, list[str]]] = [
    ("AAPL", "蘋果", ["apple", "iphone", "ipad", "macbook", "蘋果", "庫克", "tim cook"]),
    ("MSFT", "微軟", ["microsoft", "azure", "outlook", "windows", "teams", "copilot", "微軟", "納德拉", "nadella"]),
    ("NVDA", "輝達", ["nvidia", "nvda", "blackwell", "rubin", "輝達", "黃仁勳", "jensen huang", "colette kress"]),
    ("GOOG", "Google", ["alphabet", "google", "waymo", "gemini", "youtube", "谷歌", "deepmind"]),
    ("AMZN", "亞馬遜", ["amazon", "aws", "亞馬遜", "jassy"]),
    ("META", "Meta", ["meta", "facebook", "instagram", "whatsapp", "llama", "祖克柏", "zuckerberg"]),
    ("TSLA", "特斯拉", ["tesla", "tsla", "cybercab", "robotaxi", "optimus", "特斯拉", "馬斯克", "musk"]),
    ("AVGO", "博通", ["broadcom", "avgo", "博通", "陳福陽", "hock tan"]),
    ("ORCL", "甲骨文", ["oracle", "orcl", "甲骨文", "艾利森", "ellison"]),
    ("NFLX", "Netflix", ["netflix", "nflx", "網飛"]),
    ("CRM", "Salesforce", ["salesforce", "benioff"]),
    ("AMD", "AMD", ["amd", "advanced micro", "超微", "蘇姿丰", "lisa su"]),
    ("CSCO", "思科", ["cisco", "csco", "思科"]),
    ("IBM", "IBM", ["ibm"]),
    ("PLTR", "Palantir", ["palantir", "pltr", "karp"]),
    ("NOW", "ServiceNow", ["servicenow"]),
    ("SPCX", "SpaceX", ["spacex", "spcx", "starlink", "starship", "星鏈", "星艦"]),
    ("UBER", "Uber", ["uber", "優步"]),
    ("INTU", "Intuit", ["intuit", "turbotax", "quickbooks"]),
    ("ADBE", "Adobe", ["adobe", "adbe", "firefly"]),
    ("QCOM", "高通", ["qualcomm", "qcom", "snapdragon", "高通"]),
    ("TXN", "德儀", ["texas instruments", "德州儀器", "德儀"]),
    ("AMAT", "應材", ["applied materials", "amat", "應用材料", "應材"]),
    ("MU", "美光", ["micron", "美光", "hbm"]),
    ("PANW", "PaloAlto", ["palo alto networks", "panw", "派拓"]),
    ("ANET", "Arista", ["arista networks", "anet"]),
    ("LRCX", "科林", ["lam research", "lrcx", "科林研發"]),
    ("KLAC", "科磊", ["kla corp", "klac", "科磊"]),
    ("CRWD", "CrowdStrike", ["crowdstrike", "crwd"]),
    ("INTC", "英特爾", ["intel", "intc", "英特爾", "陳立武", "lip-bu tan"]),
]

FLASH_FED_ENTITIES = [
    "聯準會", "鮑爾", "鮑威爾", "fomc", "federal reserve", "fed ", "fed官員", "powell",
]

FLASH_TECH_POLICY_KEYWORDS = [
    "晶片禁令", "晶片出口", "出口管制", "晶片關稅", "科技關稅", "美國商務部", "美國司法部",
]

FLASH_FOREIGN_CB_NOISE = [
    "英格蘭銀行", "英國央行", "歐洲央行", "日本央行", "日銀", "澳洲央行", "加拿大央行", "韓國央行",
]

FLASH_OUTAGE_KEYWORDS = [
    "當機", "大當機", "死機", "癱瘓", "斷線", "中斷", "藍白畫面", "故障", "駭客", "資安", "漏洞",
    "outage", "disruption", "restored", "cyberattack", "data breach", "service down",
]

FLASH_URGENT_KEYWORDS = FLASH_OUTAGE_KEYWORDS + [
    "升息", "降息", "升降息", "利率決議", "放鷹", "放鴿", "rate hike", "rate cut",
    "緊急", "辭職", "卸任", "換帥", "禁令", "出口管制", "反壟斷", "調查",
    "重挫", "暴跌", "飆漲", "財報", "上修", "下修", "財測",
]

FLASH_TW_LOCAL_NOISE = [
    "台股", "漲停", "跌停", "外資買超", "外資賣超", "投信", "三大法人",
    "0050", "00878", "00919", "00929", "00940", "緯創", "廣達", "技嘉", "鴻海",
    "奇鋐", "雙鴻", "老ai", "概念股", "台指期", "盤中速報",
]

FLASH_CLICKBAIT_NOISE = [
    "here's what", "here’s what", "what it does mean", "what to know", "what you need to know",
    "should you buy", "why i'm buying", "millionaire", "motley fool", "stocks to buy",
    "這對你來說意味著什麼", "該買嗎", "討論區", "股票評論", "股吧", "交流社區", "美元：", "匯市", "股價預測",
]

FLASH_BLOCKED_SOURCES = BLOG_SOURCES | {
    "Moomoo", "moomoo.com", "www.tmgm.com", "TMGM", "FXStreet", "DailyFX", "LiteFinance",
}

FLASH_EN_TRUSTED_SOURCES = {
    "WSJ", "The Wall Street Journal", "Reuters", "Bloomberg", "CNBC", "Yahoo Finance",
    "Financial Times", "Barron's", "MarketWatch", "TechCrunch", "The Verge", "AP News",
}

HOLDING_TECH_TICKERS = {"GOOG", "TSLA", "NVDA"}


def fetch_tech30_flash() -> list[dict]:
    """Fetches high-signal breaking news strictly relevant to Top-30 US Tech stocks & US Fed/Tech-Policy catalysts."""
    queries = [
        (
            '("聯準會" OR "鮑爾" OR "FOMC" OR "Fed" OR "晶片出口" OR "晶片禁令") (升息 OR 降息 OR 利率 OR 美股 OR 科技股 OR 晶片) when:2d',
            "zh-TW",
            36.0,
        ),
        (
            '("微軟" OR "蘋果" OR "Google" OR "亞馬遜" OR "Meta" OR "輝達" OR "特斯拉") ("當機" OR "死機" OR "癱瘓" OR "故障" OR "財報" OR "裁員" OR "收購" OR "禁令" OR "反壟斷" OR "重挫" OR "大漲") when:2d',
            "zh-TW",
            30.0,
        ),
        (
            '("蘋果" OR "微軟" OR "Google" OR "亞馬遜" OR "Meta" OR "博通" OR "甲骨文" OR "Netflix") (AI OR 晶片 OR 雲端 OR 財報 OR 股價) when:1d',
            "zh-TW",
            28.0,
        ),
        (
            '("超微" OR "AMD" OR "美光" OR "高通" OR "英特爾" OR "Palantir" OR "SpaceX" OR "思科" OR "Salesforce" OR "Adobe" OR "CrowdStrike") 美股 when:2d',
            "zh-TW",
            36.0,
        ),
        (
            '("Microsoft" OR "Azure" OR "AWS" OR "Google Cloud" OR "Apple" OR "Meta" OR "CrowdStrike" OR "Nvidia") (outage OR disruption OR restored OR antitrust OR export) when:2d',
            "en-US",
            30.0,
        ),
        (
            '("Federal Reserve" OR "Powell" OR "FOMC") ("rate hike" OR "rate cut" OR inflation) tech when:2d',
            "en-US",
            30.0,
        ),
    ]

    pool: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_google_news_rss, q, lang, max_h) for q, lang, max_h in queries]
        for f in futs:
            pool.extend(f.result())

    sorted_pool = sorted(pool, key=lambda x: (x["tier"] * 10800 + x["pubTs"]), reverse=True)
    selected: list[dict] = []
    ticker_counts: dict[str, int] = {}
    seen_outage_keys: set[str] = set()

    for it in sorted_pool:
        src = it["source"]
        if src in FLASH_BLOCKED_SOURCES or "tmgm" in src.lower() or "fx" in src.lower():
            continue
        if it["lang"] == "en-US" and src not in FLASH_EN_TRUSTED_SOURCES:
            continue

        raw_t = clean_headline_title(it["title"], src)
        low = f" {raw_t.lower()} "
        if any(bad in low for bad in FLASH_TW_LOCAL_NOISE):
            continue
        if any(cb in low for cb in FLASH_CLICKBAIT_NOISE):
            continue

        matched_tickers = [sym for sym, _, kws in TOP30_TECH_ENTITIES if any(k in low for k in kws)]
        is_fed = any(fk in low for fk in FLASH_FED_ENTITIES)
        is_policy = any(pk in low for pk in FLASH_TECH_POLICY_KEYWORDS)
        if any(fcb in low for fcb in FLASH_FOREIGN_CB_NOISE) and not is_fed and not matched_tickers:
            continue

        is_macro = is_fed or is_policy
        is_outage = any(ok in low for ok in FLASH_OUTAGE_KEYWORDS)

        if not matched_tickers and not is_macro:
            continue

        primary_key = matched_tickers[0] if matched_tickers else "FED"
        if is_outage:
            outage_key = f"outage:{primary_key}"
            if outage_key in seen_outage_keys:
                continue

        max_cap = 3 if primary_key == "FED" else 2
        if ticker_counts.get(primary_key, 0) >= max_cap:
            continue

        zh_title = clean_headline_title(translate_en_to_zhtw(raw_t), it["source"])
        if cjk_char_count(zh_title) < 2:
            continue
        if any(cb in zh_title.lower() for cb in FLASH_CLICKBAIT_NOISE):
            continue
        if any(title_similarity(zh_title, s["title"]) > 0.38 for s in selected):
            continue

        ticker_counts[primary_key] = ticker_counts.get(primary_key, 0) + 1
        if is_outage:
            seen_outage_keys.add(f"outage:{primary_key}")

        tags: list[str] = []
        if is_outage:
            tags.append("當機/異常")
        elif is_macro and "FED" not in tags:
            tags.append("FED/宏觀")
        tags.extend(matched_tickers[:2])
        if not tags:
            tags.append("科技30")

        urgent = any(uk in low for uk in FLASH_URGENT_KEYWORDS)
        affects_holdings = bool(is_macro or (set(matched_tickers) & HOLDING_TECH_TICKERS))

        selected.append(
            {
                "title": zh_title,
                "source": it["source"],
                "url": it["url"],
                "tags": tags[:2],
                "urgent": urgent,
                "isOutage": is_outage,
                "isMacro": is_macro,
                "affectsHoldings": affects_holdings,
                "timeTW": dt.datetime.fromtimestamp(it["pubTs"], TW_TZ).strftime("%m/%d %H:%M"),
                "clockTW": dt.datetime.fromtimestamp(it["pubTs"], TW_TZ).strftime("%H:%M"),
                "age": format_age_label(it["ageHours"]),
                "pubTs": it["pubTs"],
            }
        )
        if len(selected) >= 14:
            break

    selected.sort(key=lambda x: x["pubTs"], reverse=True)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch US Stock Watchlist quotes, Tech-30 flash & 6H insights.")
    parser.add_argument("--mode", choices=["all", "quotes", "insights", "flash"], default="all")
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

    now_tw_str = dt.datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    now_iso = dt.datetime.now(UTC_TZ).isoformat()

    indices_data: list[dict] = []
    stocks_quotes: list[dict] = []

    if args.mode in ("all", "quotes", "insights"):
        yc = YahooClient()
        all_symbols = [x["symbol"] for x in INDICES] + [x["symbol"] for x in WATCHLIST]
        q_map = yc.get_quotes(all_symbols)

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
            "refreshIntervalMinutes": 3,
            "marketSession": get_market_session_overview(),
            "indices": indices_data,
            "watchlist": clean_stocks,
        }
        (data_dir / "quotes.json").write_text(
            json.dumps(quotes_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/quotes.json ({len(clean_stocks)} stocks, {len(indices_data)} indices)")

    if args.mode in ("all", "quotes", "flash"):
        flash_items = fetch_tech30_flash()
        flash_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "refreshIntervalMinutes": 3,
            "universeNote": "嚴選美國前 30 大市值科技股動態 ＆ 聯準會升降息/重大宏觀政策快報",
            "items": flash_items,
        }
        (data_dir / "flash.json").write_text(
            json.dumps(flash_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/flash.json ({len(flash_items)} Tech-30 & Fed flash items)")

    if args.mode in ("all", "insights"):
        apewisdom = fetch_apewisdom_map()
        market_headlines = fetch_market_headlines()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            ins_futures = [
                pool.submit(build_stock_insight, yc, cfg, sq, apewisdom)
                for cfg, sq in zip(WATCHLIST, stocks_quotes)
            ]
            stock_insights = dict(f.result() for f in ins_futures)

        cio_advisory = build_cio_advisory(indices_data, stocks_quotes, stock_insights)

        insights_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "scheduleNote": "每 6 小時自動更新 ＋ 美股開盤前 10 分鐘 (09:20 ET) 強制更新",
            "marketHeadlines": market_headlines,
            "stocks": stock_insights,
            "cioAdvisory": cio_advisory,
        }
        (data_dir / "insights.json").write_text(
            json.dumps(insights_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/insights.json ({len(market_headlines)} market headlines, {len(stock_insights)} stocks, CIO advisory included)")


if __name__ == "__main__":
    main()
