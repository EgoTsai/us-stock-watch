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
    "stock price, news, quote", "quote & history", " by tk ", "#導購推薦", "本影片講述了",
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
        if d_et.weekday() >= 5:
            continue
        hm = d_et.hour * 60 + d_et.minute
        if 9 * 60 + 30 <= hm <= 16 * 60 + 5:
            d_key = d_et.strftime("%Y-%m-%d")
            by_date.setdefault(d_key, []).append((ts, float(c), float(h), float(l)))

    sorted_dates = sorted(by_date.keys())
    now_et = dt.datetime.now(NY_TZ)
    today_key = now_et.strftime("%Y-%m-%d")
    hm_now = now_et.hour * 60 + now_et.minute

    target_date = sorted_dates[-1] if sorted_dates else today_key
    if not by_date.get(target_date) and len(sorted_dates) >= 2:
        target_date = sorted_dates[-2]

    bars = by_date.get(target_date, [])
    target_idx = sorted_dates.index(target_date) if target_date in sorted_dates else -1
    prev_bars = by_date[sorted_dates[target_idx - 1]] if target_idx > 0 else []

    q_reg_time = int(q.get("regularMarketTime") or 0)
    q_reg_date = dt.datetime.fromtimestamp(q_reg_time, NY_TZ).strftime("%Y-%m-%d") if q_reg_time else ""
    market_state = (q.get("marketState") or "").upper()
    is_live = bool(
        (target_date == today_key or q_reg_date == today_key)
        and now_et.weekday() < 5
        and (market_state == "REGULAR" or (9 * 60 + 30 <= hm_now < 16 * 60))
    )

    if q_reg_date == target_date and q.get("regularMarketPrice") is not None:
        close_price = round(float(q["regularMarketPrice"]), 2)
        prev_close = round(float(q.get("regularMarketPreviousClose") or (prev_bars[-1][1] if prev_bars else close_price)), 2)
    elif is_live and q.get("regularMarketPrice") is not None:
        target_date = q_reg_date or today_key
        close_price = round(float(q["regularMarketPrice"]), 2)
        prev_close = round(float(q.get("regularMarketPreviousClose") or (bars[-1][1] if bars else close_price)), 2)
        bars = by_date.get(target_date, [])
    else:
        close_price = round(bars[-1][1], 2) if bars else round(float(q.get("regularMarketPrice") or 0), 2)
        prev_close = round(prev_bars[-1][1], 2) if prev_bars else round(float(q.get("regularMarketPreviousClose") or close_price), 2)

    change = round(close_price - prev_close, 2)
    change_pct = round((change / prev_close * 100) if prev_close else 0.0, 2)
    bar_high = max((b[2] for b in bars), default=close_price)
    bar_low = min((b[3] for b in bars), default=close_price)
    if q_reg_date == target_date:
        if q.get("regularMarketDayHigh") is not None:
            bar_high = max(bar_high, float(q["regularMarketDayHigh"]), close_price)
        if q.get("regularMarketDayLow") is not None:
            bar_low = min(bar_low, float(q["regularMarketDayLow"]), close_price)
    day_high = round(bar_high, 2)
    day_low = round(bar_low, 2)

    points = []
    for ts, c, _, _ in bars:
        t_et = dt.datetime.fromtimestamp(ts, NY_TZ).strftime("%H:%M")
        points.append({"t": ts, "et": t_et, "p": round(c, 2)})

    if is_live:
        live_ts = q_reg_time or int(now_et.timestamp())
        live_et = dt.datetime.fromtimestamp(live_ts, NY_TZ).strftime("%H:%M")
        if not points or abs(points[-1]["p"] - close_price) > 0.005 or points[-1]["et"] != live_et:
            points.append({"t": live_ts, "et": live_et, "p": close_price})
        if len(points) == 1:
            open_val = round(float(q.get("regularMarketOpen") or prev_close), 2)
            points.insert(0, {"t": live_ts - 60, "et": "09:30", "p": open_val})
    else:
        if points and abs(points[-1]["p"] - close_price) > 0.01:
            points.append({"t": points[-1]["t"] + 60, "et": "16:00", "p": close_price})

    last_time_et = points[-1]["et"] if points else ("16:00" if not is_live else now_et.strftime("%H:%M"))
    quote_ts = q_reg_time or (points[-1]["t"] if points else 0)

    return {
        "symbol": sym,
        "displaySymbol": idx_cfg["displaySymbol"],
        "name": idx_cfg["name"],
        "enName": idx_cfg["enName"],
        "sessionDate": target_date,
        "isLive": is_live,
        "statusLabel": "盤中即時" if is_live else "收盤",
        "lastTimeET": last_time_et,
        "quoteTs": int(quote_ts),
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
        "quoteTs": int(latest_ts),
        "prevClose": round(float(reg_prev_close), 2),
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


_TRANSLATE_SEM = threading.Semaphore(2)
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
    "vanguard", "russell", "invesco", "proshares", "ishares", "blackrock", "spdr", "vonv", "nyse",
}


def cjk_char_count(text: str) -> int:
    return sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")


def needs_zh_translation(text: str) -> bool:
    if not text:
        return False
    cjk_cnt = cjk_char_count(text)
    if cjk_cnt == 0:
        return bool(re.search(r"[A-Za-z]{3,}", text))
    en_words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", text)]
    ordinary_en = [w for w in en_words if w not in ALLOWED_EN_TERMS]
    if cjk_cnt < 4 and len(ordinary_en) >= 2:
        return True
    if len(ordinary_en) >= 4 and len(ordinary_en) > cjk_cnt * 0.35:
        return True
    for clause in re.findall(r"(?:[A-Za-z][A-Za-z0-9'-]*[\s,;:]+){3,}[A-Za-z][A-Za-z0-9'-]*", text):
        c_words = [w.lower() for w in re.findall(r"[A-Za-z]{2,}", clause)]
        if sum(1 for w in c_words if w not in ALLOWED_EN_TERMS) >= 3:
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


def _translate_single_call(chunk: str) -> str:
    q = urllib.parse.quote(chunk)
    for attempt in range(2):
        try:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q={q}"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            raw = json.loads(urllib.request.urlopen(req, timeout=7).read().decode("utf-8"))
            out = post_polish_zh("".join(seg[0] for seg in raw[0] if seg and seg[0]))
            if cjk_char_count(out) >= 2:
                time.sleep(0.05)
                return out
        except Exception:
            time.sleep(0.35 * (attempt + 1))

    try:
        url2 = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=zh-TW&q={q}"
        req2 = urllib.request.Request(url2, headers={"User-Agent": USER_AGENT})
        raw2 = json.loads(urllib.request.urlopen(req2, timeout=7).read().decode("utf-8"))
        if isinstance(raw2, list) and raw2:
            first = raw2[0]
            out2 = post_polish_zh(first[0] if isinstance(first, list) else str(first))
            if cjk_char_count(out2) >= 2:
                return out2
    except Exception:
        pass
    return post_polish_zh(chunk)


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

        out = _translate_single_call(text)
        # If multi-sentence output still leaves an untranslated English sentence, translate sentence-by-sentence
        if needs_zh_translation(out):
            parts = re.split(r"(?<=[。！？.!?])\s*", out)
            if len(parts) > 1:
                fixed_parts = [
                    _translate_single_call(p) if needs_zh_translation(p) else post_polish_zh(p)
                    for p in parts
                    if p.strip()
                ]
                out = "".join(
                    fp if fp.endswith(("。", "！", "？", "…", ".")) else fp + " "
                    for fp in fixed_parts
                ).strip()

        _TRANSLATE_CACHE[text] = out
        return out


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


_RSS_SEM = threading.Semaphore(3)


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
    with _RSS_SEM:
        xml_bytes = None
        for attempt in range(2):
            try:
                xml_bytes = urllib.request.urlopen(req, timeout=8).read()
                time.sleep(0.08)
                break
            except Exception as exc:
                if attempt == 0 and "429" in str(exc):
                    time.sleep(0.6)
                else:
                    print(f"[warn] RSS failed ({query[:30]}): {exc}", file=sys.stderr)
        if not xml_bytes:
            return []
    try:
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
        print(f"[warn] RSS parse failed ({query[:30]}): {exc}", file=sys.stderr)

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


WATCHLIST_CIO_PROFILES: dict[str, dict] = {
    "VOO": {
        "role": "S&P 500 大盤核心",
        "style": "index",
        "pairGroup": "us_index",
        "thesis": "美國前 500 大龍頭市值加權基準，拉回即為中長線定期與分批建倉首選。",
    },
    "QQQ": {
        "role": "那指 100 成長基準",
        "style": "index",
        "pairGroup": "us_index",
        "thesis": "大型科技與 AI 權值指標，適合順勢配置或大盤明顯回檔時分批承接。",
    },
    "TQQQ": {
        "role": "那指 3 倍做多槓桿",
        "style": "leveraged",
        "pairGroup": "leveraged",
        "thesis": "日內 3 倍複利槓桿具高波動耗損（Volatility Decay），僅宜極短線順勢或止穩後小倉波段。",
    },
    "SOXL": {
        "role": "費半 3 倍做多槓桿",
        "style": "leveraged",
        "pairGroup": "leveraged",
        "thesis": "半導體 3 倍槓桿日內劇烈震盪，急跌切忌盲目接刀，務必等費半權值止穩再觀察。",
    },
    "UCO": {
        "role": "原油 2 倍做多槓桿",
        "style": "leveraged",
        "pairGroup": "oil",
        "thesis": "追蹤兩倍原油槓桿與期貨正逆價差損耗，僅適合作為短線事件型通膨避險工具。",
    },
    "GOOG": {
        "role": "AI 搜尋・雲端 ＆ TPU 核心",
        "style": "core_tech",
        "pairGroup": None,
        "thesis": "自研 TPU 晶片降低外購 GPU 依賴、雲端與搜尋現金流護城河深厚，估值相對具防禦支撐。",
    },
    "MSFT": {
        "role": "企業雲端與 AI 軟體龍頭",
        "style": "core_tech",
        "pairGroup": None,
        "thesis": "Azure 與企業訂閱現金流穩健，非基本面短期利空引發之急跌往往提供中長線折價買點。",
    },
    "META": {
        "role": "AI 廣告變現與開源生態",
        "style": "core_tech",
        "pairGroup": None,
        "thesis": "AI 精準廣告推升利潤率與自由現金流，震盪期高 Beta 屬性常創造波段承接與收租空間。",
    },
    "TSLA": {
        "role": "實體 AI・Robotaxi 高波標的",
        "style": "high_beta_tech",
        "pairGroup": None,
        "thesis": "高隱含波動率 (IV) 與情緒擺盪劇烈，適合紀律區間操作或賣方收租策略，忌追高殺低。",
    },
    "SPCX": {
        "role": "SpaceX 太空探索主題",
        "style": "thematic",
        "pairGroup": None,
        "thesis": "星鏈與航太龍頭題材彈性極高、同步伴隨估值與融資波動，適合右側順勢小倉參與。",
    },
    "TSM": {
        "role": "先進製程與 CoWoS 獨佔樞紐",
        "style": "core_semi",
        "pairGroup": None,
        "thesis": "無論 GPU 或雲端巨頭自研 ASIC 誰勝出，3/2 奈米與先進封裝訂單皆由台積電獨攬。",
    },
    "NVDA": {
        "role": "AI 算力晶片霸主",
        "style": "high_beta_semi",
        "pairGroup": None,
        "thesis": "資料中心算力市佔核心，惟高基期與財測/治理訊息易放大單日振幅，宜等站穩均價再行動。",
    },
    "AVGO": {
        "role": "客製化 AI ASIC ＆ 網通龍頭",
        "style": "core_semi",
        "pairGroup": None,
        "thesis": "雲端大廠擴大自研 ASIC 與高速光網升級之核心贏家，兼具網通現金流與高韌性。",
    },
    "AMD": {
        "role": "資料中心 GPU 第二供應商",
        "style": "high_beta_semi",
        "pairGroup": None,
        "thesis": "受惠雲端分散算力採購，但估值對毛利率與伺服器成長預期敏感，宜等均線止穩介入。",
    },
    "MU": {
        "role": "HBM 高頻寬記憶體循環龍頭",
        "style": "high_beta_semi",
        "pairGroup": None,
        "thesis": "HBM 需求帶動獲利循環同時具高振幅特性，急漲急跌時務必分批節奏操作。",
    },
    "INTC": {
        "role": "晶圓代工轉型觀察股",
        "style": "turnaround",
        "pairGroup": None,
        "thesis": "先進代工轉型仍處良率與現金流驗證期，波動劇烈且缺乏趨勢護城河，維持低權重追蹤。",
    },
    "IAU": {
        "role": "實體黃金通膨與避險資產",
        "style": "hedge",
        "pairGroup": None,
        "thesis": "與科技權值相關性低，適合作為實質利率波動與股市震盪期間的資產配置穩定器。",
    },
    "IBIT": {
        "role": "比特幣現貨 ETF",
        "style": "crypto",
        "pairGroup": None,
        "thesis": "全球美元流動性與風險偏好放大器，振幅遠超納指，宜嚴設部位上限並追蹤 ETF 資金流向。",
    },
    "CL=F": {
        "role": "WTI 輕原油宏觀通膨指標",
        "style": "commodity",
        "pairGroup": "oil",
        "thesis": "能源價格直接牽動通膨黏著度與聯準會政策路徑，急漲易壓抑科技成長股估值倍數。",
    },
}

CIO_CATALYST_KEYWORDS = (
    "當機", "癱瘓", "故障", "辭職", "卸任", "換帥", "拒絕", "封殺", "禁令", "出口",
    "關稅", "反壟斷", "訴訟", "調查", "財報", "財測", "上修", "下修", "調升", "降評",
    "融資", "擴建", "13f", "勞資", "暴跌", "飆漲", "風波", "警鐘", "危機", "outage",
    "resign", "ban", "export", "antitrust", "earnings", "guidance", "downgrade", "upgrade", "tariff",
)

CIO_HEADLINE_NOISE = (
    "油菜籽", "中油", "92無鉛", "95無鉛", "印度 vix", "台股盤中", "連接器大廠", "概念股",
)


def _clean_cio_headline(sym: str, headlines: list[dict], used_titles: set[str] | None = None) -> dict | None:
    for h in headlines or []:
        t = (h.get("title") or "").strip()
        if not t:
            continue
        if used_titles is not None and t in used_titles:
            continue
        low = t.lower()
        if any(bad in low for bad in CIO_HEADLINE_NOISE):
            continue
        if sym in ("CL=F", "UCO") and not any(k in low for k in ("原油", "油價", "wti", "opec", "crude", "oil", "brent")):
            continue
        return h
    return None


def build_cio_advisory(
    indices_data: list[dict],
    stocks_quotes: list[dict],
    stock_insights: dict[str, dict],
) -> dict:
    """Generates dynamic, position-agnostic Top-6 Watchlist CIO & CRO recommendations."""
    s_map = {s["symbol"]: s for s in stocks_quotes}
    i_map = {x["symbol"]: x for x in indices_data}

    vix_q = s_map.get("^VIX", {})
    vix = float(vix_q.get("price") or 18.0)
    vix_chg = float(vix_q.get("changePct") or 0.0)
    spx_chg = float(i_map.get("^GSPC", {}).get("changePct") or 0.0)
    ixic_chg = float(i_map.get("^IXIC", {}).get("changePct") or 0.0)
    boxx_p = float(s_map.get("BOXX", {}).get("price") or 119.0)
    oil_q = s_map.get("CL=F", {})
    oil_p = float(oil_q.get("price") or 0.0)
    oil_chg = float(oil_q.get("changePct") or 0.0)

    # 1. Macro & Volatility Regime Verdict (completely independent of personal holdings)
    if vix >= 23:
        regime_tag = f"高波動謹慎期 (VIX {vix:.2f})"
        regime_tone = "caution"
        regime_summary = (
            f"VIX 處於 {vix:.2f} ({vix_chg:+.2f}%) 高波動區，標普 {spx_chg:+.2f}%、那指 {ixic_chg:+.2f}%。"
            f"高 IV 環境嚴禁追價 3 倍槓桿 ETF（TQQQ/SOXL），資金宜以 BOXX (${boxx_p:.2f}) 等類現金作緩衝，僅鎖定觀察名單中具支撐或錯殺之核心標的分批佈局。"
        )
    elif vix >= 18:
        regime_tag = f"震盪分歧・精選標的期 (VIX {vix:.2f})"
        regime_tone = "neutral"
        regime_summary = (
            f"VIX 位於 {vix:.2f} ({vix_chg:+.2f}%)，標普 {spx_chg:+.2f}%、那指 {ixic_chg:+.2f}%，市場呈現板塊輪動與事件驅動分化。"
            f"WTI 原油報 ${oil_p:.2f} ({oil_chg:+.2f}%)；操作上宜依觀察名單前 6 大訊號強弱汰弱留強，避免在震盪中過度擴張槓桿。"
        )
    else:
        regime_tag = f"低波動順風期 (VIX {vix:.2f})"
        regime_tone = "bull"
        regime_summary = (
            f"VIX 回落至 {vix:.2f} ({vix_chg:+.2f}%) 穩定區間，標普 {spx_chg:+.2f}%、那指 {ixic_chg:+.2f}% 風險偏好健康。"
            "順勢抱牢大型科技與指數核心標的，槓桿型 ETF 遇急漲則宜紀律落袋調節，不隨市場情緒過度追高。"
        )

    # 2. Multi-Factor Scoring Across All Actionable Watchlist Symbols
    scored: list[dict] = []
    for sq in stocks_quotes:
        sym = sq["symbol"]
        if sym in ("^VIX", "BOXX"):
            continue
        prof = WATCHLIST_CIO_PROFILES.get(sym)
        if not prof:
            continue

        price = float(sq.get("price") or 0.0)
        if price <= 0:
            continue
        prev_c = float(sq.get("prevClose") or price)
        chg = float(sq.get("changePct") or 0.0)
        day_hi = float(sq.get("dayHigh") or price)
        day_lo = float(sq.get("dayLow") or price)
        high52 = max(float(sq.get("high52w") or price), price)

        dd52w = ((price - high52) / high52 * 100.0) if high52 > 0 else 0.0
        range_pct = ((day_hi - day_lo) / prev_c * 100.0) if (prev_c > 0 and day_hi > day_lo) else 0.0
        pos_in_day = ((price - day_lo) / (day_hi - day_lo)) if day_hi > day_lo else 0.5
        alpha_spx = chg - spx_chg

        ins = stock_insights.get(sym, {})
        sent = ins.get("sentiment") or {}
        buy_pct = int(sent.get("buyPct", 50))
        sell_pct = int(sent.get("sellPct", 50))
        top_hl = _clean_cio_headline(sym, ins.get("headlines") or [])

        style = prof["style"]
        score = 0.0

        # A. Daily price shock
        score += min(34.0, abs(chg) * 5.0)

        # B. Intraday volatility & genuine reversal fade/rebound
        is_intraday_fade = range_pct >= 3.2 and pos_in_day <= 0.25 and day_hi >= prev_c * 1.012 and chg > -4.5
        is_intraday_rebound = range_pct >= 3.2 and pos_in_day >= 0.75 and day_lo <= prev_c * 0.988 and chg < 4.5
        if range_pct >= 3.2:
            score += min(14.0, (range_pct - 2.2) * 3.2)
        if is_intraday_fade or is_intraday_rebound:
            score += 8.0

        # C. Relative alpha divergence vs S&P 500
        if abs(alpha_spx) >= 1.2:
            score += min(14.0, abs(alpha_spx) * 2.5)

        # D. 6H headline catalyst (skip turnaround secondary mentions unless sharp drop)
        has_urgent_news = False
        if top_hl:
            hl_low = top_hl.get("title", "").lower()
            has_urgent_news = any(k in hl_low for k in CIO_CATALYST_KEYWORDS)
            if style == "turnaround" and "輝達" in hl_low and abs(chg) < 4.0:
                has_urgent_news = False
            if has_urgent_news:
                score += 16.0
            elif top_hl.get("within6h"):
                score += 6.0

        # E. Sentiment extremes / contrarian divergence
        max_sent = max(buy_pct, sell_pct)
        if max_sent >= 64:
            score += 8.0
        if (chg <= -1.5 and sell_pct >= 65) or (chg >= 1.5 and buy_pct >= 68):
            score += 4.0

        # F. Asset tier & 52-week strategic positioning
        if style == "index":
            if dd52w <= -5.0 or abs(chg) >= 1.2 or vix >= 22:
                score += 14.0
        elif style in ("core_tech", "core_semi"):
            score += 9.0
            if chg <= -1.5 and -32.0 <= dd52w <= -5.0:
                score += 5.0
        elif style in ("high_beta_tech", "high_beta_semi"):
            score += 4.0
            if sym == "NVDA":
                score += 6.0
        elif style == "turnaround":
            score -= 10.0
        elif style == "hedge":
            if (vix >= 22 and chg >= 0.5) or abs(chg) >= 2.0:
                score += 9.0
        elif style == "crypto":
            if abs(chg) >= 2.5:
                score += 6.0
        elif style == "leveraged":
            if abs(chg) >= 4.0 or range_pct >= 7.0:
                score += 6.0
            else:
                score -= 10.0
        elif style == "commodity":
            if abs(chg) >= 2.0:
                score += 6.0
            else:
                score -= 6.0

        # Build crisp, specific institutional recommendation based on live state
        action = "持續追蹤觀察"
        action_type = "hold"
        focus_tag = "核心觀察"
        detail_parts = []

        if style == "leveraged":
            if chg <= -3.5 or (is_intraday_fade and range_pct >= 6.0):
                action = "高波動警戒・禁追刀"
                action_type = "alert"
                focus_tag = "槓桿風控警示"
                detail_parts.append(
                    f"單日波幅達 {range_pct:.1f}%（區間 ${day_lo:.2f}–${day_hi:.2f}，距 52 週高點 {dd52w:.1f}%）。"
                    f"在 VIX {vix:.2f} 環境下多倍槓桿複利耗損驚人，嚴禁盤中急跌盲目攤平，務必待現股權值止跌出量後再評估。"
                )
            elif chg >= 3.5:
                action = "急彈調節・落袋減碼"
                action_type = "watch"
                focus_tag = "槓桿獲利管理"
                detail_parts.append(
                    f"單日強彈 {chg:+.2f}%（區間 ${day_lo:.2f}–${day_hi:.2f}），短線情緒快速升溫（想買 {buy_pct}%）。"
                    "槓桿 ETF 不宜長抱吃震盪耗損，建議逢急漲分批鎖定利潤、降回常規風險水位。"
                )
            else:
                action = "極端振幅・控管倉位"
                action_type = "alert" if range_pct >= 6.0 else "watch"
                focus_tag = "槓桿震盪提示"
                detail_parts.append(
                    f"盤中震幅高達 {range_pct:.1f}%（報 ${price:.2f}，距 52 週高點 {dd52w:.1f}%）。{prof['thesis']}"
                )
        elif style == "index":
            if dd52w <= -5.0 and chg <= -1.0:
                action = "估值修正・分批佈局點"
                action_type = "bull"
                focus_tag = "指數分批買點"
                detail_parts.append(
                    f"現價 ${price:.2f} 較 52 週高點 ${high52:.2f} 已回落 {dd52w:.1f}%（今日 {chg:+.2f}%），進入中長線指數折價擊球區。"
                    f"配合 BOXX (${boxx_p:.2f}) 現金緩衝，適合分 2–3 批紀律承接，保留空間因應 VIX {vix:.2f} 餘震。"
                )
            elif dd52w <= -5.0:
                action = "回測區間・分批承接"
                action_type = "bull"
                focus_tag = "指數長線買點"
                detail_parts.append(
                    f"報 ${price:.2f}（{chg:+.2f}%），仍處 52 週高點下方 {dd52w:.1f}% 的中期折價帶。{prof['thesis']}建議依預設跌幅階梯分批佈局。"
                )
            elif chg >= 1.5:
                action = "趨勢健康・勿追價"
                action_type = "hold"
                focus_tag = "大盤強勢"
                detail_parts.append(
                    f"單日走強 {chg:+.2f}%（想買 {buy_pct}%），大盤動能轉佳；建議維持既有配置，待回測均線再行加碼。"
                )
            else:
                action = "指數基準・按紀律配置"
                action_type = "hold"
                focus_tag = "大盤基準"
                detail_parts.append(
                    f"現報 ${price:.2f}（{chg:+.2f}%，距 52 週高點 {dd52w:.1f}%）。{prof['thesis']}"
                )
        elif style == "hedge":
            if chg <= -2.0:
                action = "避險資產回檔・等債息止穩"
                action_type = "watch"
                focus_tag = "避險資產異動"
                detail_parts.append(
                    f"黃金單日回落 {chg:+.2f}% 至 ${price:.2f}（距 52 週高點 {dd52w:.1f}%），反映強勢美元與實質利率重定價壓力。"
                    "建議等待美元與殖利率衝高鈍化後，再檢視低相關避險配置比例。"
                )
            elif chg >= 1.2:
                action = "避險買盤點火・發揮保護力"
                action_type = "bull"
                focus_tag = "抗震資金流"
                detail_parts.append(
                    f"逆勢走高 {chg:+.2f}%（領先標普 {alpha_spx:+.2f}%），發揮與科技股低相關之資產保護功能，可作為組合波動對沖錨點。"
                )
            else:
                action = "宏觀對沖觀察"
                action_type = "hold"
                focus_tag = "防禦配置"
                detail_parts.append(f"報 ${price:.2f}（{chg:+.2f}%）。{prof['thesis']}")
        elif style == "commodity":
            if chg >= 2.0:
                action = "油價衝高・警覺通膨回溫"
                action_type = "alert"
                focus_tag = "宏觀通膨警訊"
                detail_parts.append(
                    f"WTI 原油強升 {chg:+.2f}% 至 ${price:.2f}，能源漲勢恐推升通膨預期並壓抑聯準會寬鬆空間，需留意高估值科技股壓抑風險。"
                )
            else:
                action = "油價回落・通膨壓力緩解"
                action_type = "bull" if chg <= -1.5 else "hold"
                focus_tag = "能源與通膨訊號"
                detail_parts.append(
                    f"WTI 原油報 ${price:.2f}（{chg:+.2f}%，距 52 週高點 {dd52w:.1f}%），有利緩解終端通膨黏著疑慮，對成長股估值屬正面微風。"
                )
        elif style == "crypto":
            if chg <= -3.0:
                action = "高波回撤・嚴守倉位紀律"
                action_type = "watch"
                focus_tag = "加密流動性觀察"
                detail_parts.append(
                    f"單日下跌 {chg:+.2f}%（距 52 週高點 {dd52w:.1f}%），反映高 Beta 流動性資產同步承壓。宜待現貨 ETF 淨流入回穩且日 K 止跌再評估。"
                )
            elif chg >= 3.0:
                action = "資金回流・防短線震盪"
                action_type = "bull"
                focus_tag = "風險偏好領指標"
                detail_parts.append(
                    f"強漲 {chg:+.2f}% 領先大盤，風險偏好回暖；加密資產波動遠高於股市，建議維持嚴格部位上限與移動風險控管。"
                )
            else:
                action = "高波衛星觀察"
                action_type = "hold"
                focus_tag = "流動性指標"
                detail_parts.append(f"報 ${price:.2f}（{chg:+.2f}%）。{prof['thesis']}")
        else:
            # Individual equities (core_tech, core_semi, high_beta_tech, high_beta_semi, thematic, turnaround)
            is_moat = style in ("core_tech", "core_semi")
            if is_intraday_fade:
                action = "開高殺低・嚴禁接刀"
                action_type = "alert"
                focus_tag = "盤中反轉警示"
                detail_parts.append(
                    f"盤中劇烈反轉，從高點 ${day_hi:.2f} 回吐至 ${price:.2f}（低點 ${day_lo:.2f}，日內振幅 {range_pct:.1f}%，距 52 週高點 {dd52w:.1f}%）。"
                    f"{prof['thesis']}短線賣壓尚未宣洩完畢，宜靜待站回日內均價或收盤止穩。"
                )
            elif has_urgent_news and chg <= -2.0:
                action = "突發事件・靜待利空沉澱"
                action_type = "alert"
                focus_tag = "事件催化警戒"
                detail_parts.append(
                    f"受近期新聞事件牽動跌 {chg:+.2f}%（6H 想賣 {sell_pct}%，距 52 週高點 {dd52w:.1f}%）。"
                    f"{prof['thesis']}事件發酵期切忌搶反彈，待負面影響範圍釐清與量縮止跌再評估。"
                )
            elif chg <= -3.5:
                if is_moat:
                    action = "核心股急跌・觀察止跌分批"
                    action_type = "watch"
                    focus_tag = "優質股折價掃描"
                    detail_parts.append(
                        f"單日重挫 {chg:+.2f}%（距 52 週高點修正 {dd52w:.1f}%，想賣 {sell_pct}%）呈現情緒性宣洩。"
                        f"{prof['thesis']}待隔日開盤確認不再破低，可評估分批低接或於遠價外支撐區佈局。"
                    )
                else:
                    action = "高波急殺・等止穩訊號"
                    action_type = "alert"
                    focus_tag = "急跌風險警示"
                    detail_parts.append(
                        f"單日大跌 {chg:+.2f}%（振幅 {range_pct:.1f}%，距 52 週高點 {dd52w:.1f}%）。"
                        f"{prof['thesis']}高彈性個股下殺動能強，切忌左側重壓接刀。"
                    )
            elif chg >= 1.8 or (alpha_spx >= 1.2 and chg >= 0.35):
                if chg >= 3.2:
                    action = "強勢急拉・逢回再觀察"
                    action_type = "bull"
                    focus_tag = "強勢領漲焦點"
                    detail_parts.append(
                        f"放量領漲 {chg:+.2f}%（跑贏標普 {alpha_spx:+.2f}%，6H 想買 {buy_pct}%），資金集中度顯著優於大盤。"
                        f"{prof['thesis']}強勢股宜採回測短期均線分批追蹤，不追盤中高乖離。"
                    )
                else:
                    action = "相對抗跌・資金避風港"
                    action_type = "bull"
                    focus_tag = "相對強勢領頭"
                    detail_parts.append(
                        f"逆勢表現 {chg:+.2f}%（超越標普 {alpha_spx:+.2f}%），展現基本面防禦與買盤韌性（區間 ${day_lo:.2f}–${day_hi:.2f}）。"
                        f"{prof['thesis']}"
                    )
            elif is_intraday_rebound:
                action = "低檔承接・留意翻紅延續"
                action_type = "bull" if is_moat else "watch"
                focus_tag = "日內反彈訊號"
                detail_parts.append(
                    f"盤中自低點 ${day_lo:.2f} 強勢拉起至 ${price:.2f}（振幅 {range_pct:.1f}%），低接買盤積極進駐。"
                    f"{prof['thesis']}觀察能否站穩當日開盤價確認短線轉強。"
                )
            elif sell_pct >= 64 and chg < 0:
                action = "情緒悲觀・逆向追蹤支撐"
                action_type = "watch"
                focus_tag = "情緒極端背離"
                detail_parts.append(
                    f"6H 社群情緒偏空（想賣 {sell_pct}%），目前修正 {chg:+.2f}%（距 52 週高點 {dd52w:.1f}%）。"
                    f"{prof['thesis']}若無基本面惡化，過度悲觀往往孕育短線反彈契機，等待量縮確認即可。"
                )
            else:
                action = "關鍵價位觀察"
                action_type = "watch" if range_pct >= 3.0 else "hold"
                focus_tag = "焦點動態"
                detail_parts.append(
                    f"現價 ${price:.2f}（{chg:+.2f}%，振幅 {range_pct:.1f}%，距 52 週高點 {dd52w:.1f}%）。{prof['thesis']}"
                )

        scored.append(
            {
                "symbol": sym,
                "displaySymbol": sq.get("displaySymbol", sym),
                "name": sq.get("name", sym),
                "category": sq.get("category", "tech"),
                "price": round(price, 2),
                "changePct": round(chg, 2),
                "dd52w": round(dd52w, 1),
                "rangePct": round(range_pct, 1),
                "buyPct": buy_pct,
                "sellPct": sell_pct,
                "role": prof["role"],
                "pairGroup": prof["pairGroup"],
                "style": style,
                "focusTag": focus_tag,
                "score": round(score, 2),
                "action": action,
                "actionType": action_type,
                "detail": "".join(detail_parts),
                "_allHeadlines": ins.get("headlines") or [],
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Pairwise & Sector Diversification Selection (Balanced Top 6)
    selected: list[dict] = []
    pair_counts: dict[str, int] = {}
    lev_count = 0
    semi_count = 0

    def _can_pick(item: dict) -> bool:
        pg = item["pairGroup"]
        if pg and pair_counts.get(pg, 0) >= 1:
            return False
        if item["style"] == "leveraged" and lev_count >= 1:
            return False
        if item["category"] == "semi" and semi_count >= 3:
            return False
        return True

    def _commit_pick(item: dict) -> None:
        nonlocal lev_count, semi_count
        selected.append(item)
        pg = item["pairGroup"]
        if pg:
            pair_counts[pg] = pair_counts.get(pg, 0) + 1
        if item["style"] == "leveraged":
            lev_count += 1
        if item["category"] == "semi":
            semi_count += 1

    # Always reserve 1 broad index anchor if VOO/QQQ shows pullback/volatility priority
    top_index = next((it for it in scored if it["style"] == "index"), None)
    if top_index and (top_index["dd52w"] <= -5.0 or abs(top_index["changePct"]) >= 1.2 or vix >= 22):
        _commit_pick(top_index)

    for item in scored:
        if any(x["symbol"] == item["symbol"] for x in selected):
            continue
        if not _can_pick(item):
            continue
        _commit_pick(item)
        if len(selected) >= 6:
            break

    # Ensure exactly 6 items if strict caps excluded too many
    if len(selected) < 6:
        chosen_syms = {x["symbol"] for x in selected}
        for item in scored:
            if item["symbol"] not in chosen_syms:
                selected.append(item)
                chosen_syms.add(item["symbol"])
                if len(selected) >= 6:
                    break

    # Re-sort selected 6 by signal priority score descending so TOP 1..6 reflects true priority rank
    selected.sort(key=lambda x: x["score"], reverse=True)

    used_hl_titles: set[str] = set()
    cards = []
    for idx, it in enumerate(selected[:6], start=1):
        clean_hl = _clean_cio_headline(it["symbol"], it["_allHeadlines"], used_hl_titles)
        if clean_hl and clean_hl.get("title"):
            used_hl_titles.add(clean_hl["title"])
        cards.append(
            {
                "rank": idx,
                "symbol": it["symbol"],
                "displaySymbol": it["displaySymbol"],
                "name": it["name"],
                "price": it["price"],
                "changePct": it["changePct"],
                "dd52w": it["dd52w"],
                "rangePct": it["rangePct"],
                "buyPct": it["buyPct"],
                "sellPct": it["sellPct"],
                "role": it["role"],
                "focusTag": it["focusTag"],
                "title": f"{it['displaySymbol']} {it['name']} (${it['price']:.2f})",
                "action": it["action"],
                "actionType": it["actionType"],
                "detail": it["detail"],
                "headlineTitle": clean_hl.get("title") if clean_hl else "",
                "headlineSource": clean_hl.get("source") if clean_hl else "",
                "headlineUrl": clean_hl.get("url") if clean_hl else "",
            }
        )

    # 3. Concise Watchlist Breadth & Anchor Summary
    tradable = [s for s in stocks_quotes if s["symbol"] not in ("^VIX", "BOXX")]
    up_cnt = sum(1 for s in tradable if float(s.get("changePct") or 0) > 0)
    down_cnt = sum(1 for s in tradable if float(s.get("changePct") or 0) < 0)
    best_s = max(tradable, key=lambda x: float(x.get("changePct") or 0), default=None)
    worst_s = min(tradable, key=lambda x: float(x.get("changePct") or 0), default=None)

    scanner_bullets = []
    if best_s and worst_s:
        scanner_bullets.append(
            f"觀察名單廣度：可交易標的 {len(tradable)} 檔中 {up_cnt} 檔上漲 / {down_cnt} 檔下跌"
            f"（最強：{best_s['displaySymbol']} {best_s['changePct']:+.2f}% ｜ 最弱：{worst_s['displaySymbol']} {worst_s['changePct']:+.2f}%）。"
        )
    scanner_bullets.append(
        f"波動與現金基準：VIX 報 {vix:.2f} ({vix_chg:+.2f}%)、停泊基準 BOXX 報 ${boxx_p:.2f}；"
        "以上前 6 大焦點完全依即時報價、52 週折價與 6H 頭條情緒動態排名，不預設任何個人持股。"
    )

    return {
        "regimeTag": regime_tag,
        "regimeTone": regime_tone,
        "regimeSummary": regime_summary,
        "cards": cards,
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


TW_INDICES = [
    {"symbol": "^TWII", "cnbcSymbol": ".TWII", "displaySymbol": "TAIEX", "name": "台股加權指數", "enName": "TAIEX Weighted Index"},
    {"symbol": "0050.TW", "cnbcSymbol": "0050.TW", "displaySymbol": "0050", "name": "元大台灣50", "enName": "Yuanta Taiwan Top 50 ETF"},
    {"symbol": "0052.TW", "cnbcSymbol": "0052.TW", "displaySymbol": "0052", "name": "富邦科技 (半導體領航)", "enName": "Fubon Taiwan Technology ETF"},
]

TW_WATCHLIST = [
    # === Group 1: 核心 AI 晶片・伺服器與市值型 ETF 焦點 (User Selected 8 Core) ===
    {
        "symbol": "2330.TW",
        "displaySymbol": "2330",
        "name": "台積電",
        "enName": "TSMC (Taiwan Semiconductor)",
        "category": "semi",
        "isHolding": True,
        "holdingBadge": "AI晶圓龍頭",
        "twQuery": '"台積電" OR "2330" 台股',
        "enQuery": '"TSMC" OR "2330.TW"',
        "mustMatch": ["台積電", "台積", "2330", "cowos", "魏哲家", "tsmc"],
        "pttKey": "2330",
    },
    {
        "symbol": "2454.TW",
        "displaySymbol": "2454",
        "name": "聯發科",
        "enName": "MediaTek Inc.",
        "category": "semi",
        "isHolding": True,
        "holdingBadge": "AI邊緣/ASIC",
        "twQuery": '"聯發科" OR "2454" OR "天璣"',
        "enQuery": '"MediaTek" OR "2454.TW"',
        "mustMatch": ["聯發科", "2454", "蔡明介", "蔡力行", "天璣", "mediatek"],
        "pttKey": "聯發科",
    },
    {
        "symbol": "2317.TW",
        "displaySymbol": "2317",
        "name": "鴻海",
        "enName": "Hon Hai Precision (Foxconn)",
        "category": "ai",
        "isHolding": True,
        "holdingBadge": "GB200/300機櫃",
        "twQuery": '"鴻海" OR "2317" OR "劉揚偉"',
        "enQuery": '"Foxconn" OR "Hon Hai"',
        "mustMatch": ["鴻海", "2317", "劉揚偉", "foxconn", "hon hai", "gb200", "gb300"],
        "pttKey": "鴻海",
    },
    {
        "symbol": "2382.TW",
        "displaySymbol": "2382",
        "name": "廣達",
        "enName": "Quanta Computer Inc.",
        "category": "ai",
        "isHolding": True,
        "holdingBadge": "AI伺服器龍頭",
        "twQuery": '"廣達" OR "2382" OR "林百里"',
        "enQuery": '"Quanta Computer" OR "2382.TW"',
        "mustMatch": ["廣達", "2382", "林百里", "雲達", "quanta"],
        "pttKey": "廣達",
    },
    {
        "symbol": "3017.TW",
        "displaySymbol": "3017",
        "name": "奇鋐",
        "enName": "Asia Vital Components (AVC)",
        "category": "ai",
        "isHolding": True,
        "holdingBadge": "AI液冷散熱",
        "twQuery": '"奇鋐" OR "3017" OR "水冷散熱"',
        "enQuery": '"Asia Vital Components" OR "3017.TW"',
        "mustMatch": ["奇鋐", "3017", "水冷", "液冷", "散熱"],
        "pttKey": "奇鋐",
    },
    {
        "symbol": "6669.TW",
        "displaySymbol": "6669",
        "name": "緯穎",
        "enName": "Wiwynn Corporation",
        "category": "ai",
        "isHolding": True,
        "holdingBadge": "CSP純AI伺服器",
        "twQuery": '"緯穎" OR "6669"',
        "enQuery": '"Wiwynn" OR "6669.TW"',
        "mustMatch": ["緯穎", "6669", "洪麗寗", "wiwynn", "伺服器"],
        "pttKey": "緯穎",
    },
    {
        "symbol": "0050.TW",
        "displaySymbol": "0050",
        "name": "元大台灣50 ETF",
        "enName": "Yuanta Taiwan Top 50 ETF",
        "category": "etf",
        "isHolding": True,
        "holdingBadge": "市值型核心",
        "twQuery": '"0050" OR "元大台灣50"',
        "enQuery": '"0050.TW" OR "Taiwan Top 50 ETF"',
        "mustMatch": ["0050", "台灣50", "元大台灣50", "市值型", "台股etf"],
        "pttKey": "0050",
    },
    {
        "symbol": "006208.TW",
        "displaySymbol": "006208",
        "name": "富邦台50 ETF",
        "enName": "Fubon FTSE TWSE Taiwan 50 ETF",
        "category": "etf",
        "isHolding": True,
        "holdingBadge": "低內扣市值型",
        "twQuery": '"006208" OR "富邦台50"',
        "enQuery": '"006208.TW" OR "Fubon Taiwan 50"',
        "mustMatch": ["006208", "富邦台50", "0050", "市值型"],
        "pttKey": "006208",
    },

    # === Group 2: AI 與半導體供應鏈・熱門 ETF 觀察名單 ===
    {
        "symbol": "2308.TW",
        "displaySymbol": "2308",
        "name": "台達電",
        "enName": "Delta Electronics Inc.",
        "category": "ai",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"台達電" OR "2308"',
        "enQuery": '"Delta Electronics" OR "2308.TW"',
        "mustMatch": ["台達電", "2308", "海英俊", "鄭平", "BBU", "電源"],
        "pttKey": "台達電",
    },
    {
        "symbol": "3711.TW",
        "displaySymbol": "3711",
        "name": "日月光投控",
        "enName": "ASE Technology Holding",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"日月光" OR "3711" OR "CoWoS封測"',
        "enQuery": '"ASE Technology" OR "3711.TW"',
        "mustMatch": ["日月光", "3711", "封測", "cowos", "ase"],
        "pttKey": "日月光",
    },
    {
        "symbol": "3661.TW",
        "displaySymbol": "3661",
        "name": "世芯-KY",
        "enName": "Alchip Technologies Ltd.",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"世芯" OR "3661" OR "ASIC"',
        "enQuery": '"Alchip" OR "3661.TW"',
        "mustMatch": ["世芯", "3661", "alchip", "asic", "矽智財", "ip股"],
        "pttKey": "世芯",
    },
    {
        "symbol": "3443.TW",
        "displaySymbol": "3443",
        "name": "創意",
        "enName": "Global Unichip Corp. (GUC)",
        "category": "semi",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"創意" 3443 OR "矽智財" 創意 OR "GUC"',
        "enQuery": '"Global Unichip" OR "3443.TW"',
        "mustMatch": ["創意", "3443", "矽智財", "hbm", "asic", "台積電"],
        "pttKey": "創意",
    },
    {
        "symbol": "3231.TW",
        "displaySymbol": "3231",
        "name": "緯創",
        "enName": "Wistron Corporation",
        "category": "ai",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"緯創" OR "3231"',
        "enQuery": '"Wistron" OR "3231.TW"',
        "mustMatch": ["緯創", "3231", "林憲銘", "wistron", "ai伺服器"],
        "pttKey": "緯創",
    },
    {
        "symbol": "2345.TW",
        "displaySymbol": "2345",
        "name": "智邦",
        "enName": "Accton Technology Corp.",
        "category": "ai",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"智邦" OR "2345" OR "800G交換器"',
        "enQuery": '"Accton Technology" OR "2345.TW"',
        "mustMatch": ["智邦", "2345", "交換器", "800g", "網通", "accton"],
        "pttKey": "智邦",
    },
    {
        "symbol": "0052.TW",
        "displaySymbol": "0052",
        "name": "富邦科技 ETF",
        "enName": "Fubon Taiwan Technology Tracker",
        "category": "etf",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"0052" OR "富邦科技" OR "科技ETF"',
        "enQuery": '"0052.TW" OR "Taiwan Technology ETF"',
        "mustMatch": ["0052", "富邦科技", "科技etf", "半導體etf", "台積電"],
        "pttKey": "0052",
    },
    {
        "symbol": "00878.TW",
        "displaySymbol": "00878",
        "name": "國泰永續高股息 ETF",
        "enName": "Cathay Sustainability High Dividend ETF",
        "category": "etf",
        "isHolding": False,
        "holdingBadge": "",
        "twQuery": '"00878" OR "國泰永續高股息" OR "高股息ETF"',
        "enQuery": '"00878.TW"',
        "mustMatch": ["00878", "高股息", "國泰永續", "配息", "除息"],
        "pttKey": "00878",
    },
]

TW_FLASH_ENTITIES: list[tuple[str, str, list[str]]] = [
    ("2330", "台積電", ["台積電", "2330", "魏哲家", "cowos", "2奈米"]),
    ("2454", "聯發科", ["聯發科", "2454", "蔡力行", "天璣"]),
    ("2317", "鴻海", ["鴻海", "2317", "劉揚偉", "gb200", "gb300"]),
    ("2382", "廣達", ["廣達", "2382", "林百里", "雲達"]),
    ("3017", "奇鋐", ["奇鋐", "3017", "水冷", "液冷"]),
    ("6669", "緯穎", ["緯穎", "6669", "洪麗寗"]),
    ("2308", "台達電", ["台達電", "2308", "bbu"]),
    ("3711", "日月光", ["日月光", "3711", "封測"]),
    ("3661", "世芯", ["世芯", "3661", "asic"]),
    ("3443", "創意", ["創意", "3443"]),
    ("3231", "緯創", ["緯創", "3231"]),
    ("2345", "智邦", ["智邦", "2345", "800g"]),
    ("0050", "0050", ["0050", "006208", "台灣50", "富邦台50"]),
]


def fetch_cnbc_quote_map(cnbc_symbols: list[str]) -> dict[str, dict]:
    if not cnbc_symbols:
        return {}
    url = (
        "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
        + urllib.parse.quote("|".join(cnbc_symbols), safe="|.")
        + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        raw = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
        arr = raw.get("FormattedQuoteResult", {}).get("FormattedQuote", [])
        return {str(it.get("symbol", "")).upper(): it for it in arr if isinstance(it, dict) and it.get("symbol")}
    except Exception as exc:
        print(f"[warn] fetch_cnbc_quote_map failed: {exc}", file=sys.stderr)
        return {}


def _parse_cnbc_float(val: object) -> float | None:
    if val is None:
        return None
    s = str(val).replace(",", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def get_tw_market_session_overview() -> dict:
    now_tw = dt.datetime.now(TW_TZ)
    wd = now_tw.weekday()
    hm = now_tw.hour * 60 + now_tw.minute

    if wd >= 5:
        status, code = "台股週末休市 · 顯示週五收盤報價", "WEEKEND"
    elif 8 * 60 + 30 <= hm < 9 * 60:
        status, code = "台股試撮合階段 (08:30–09:00 TW)", "PRE"
    elif 9 * 60 <= hm < 13 * 60 + 30:
        status, code = "台股盤中交易中 (09:00–13:30 TW)", "REGULAR"
    elif 13 * 60 + 30 <= hm < 14 * 60 + 30:
        status, code = "台股盤後定價交易 (13:30–14:30 TW)", "POST"
    else:
        status, code = "台股已收盤 · 聚焦台積電ADR與美股連動", "CLOSED"

    return {
        "statusText": status,
        "sessionCode": code,
        "etTime": dt.datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M ET"),
        "twTime": now_tw.strftime("%Y-%m-%d %H:%M 台灣時間"),
    }


def build_tw_index_data(yc: YahooClient, idx_cfg: dict, q_map: dict[str, dict], cnbc_map: dict[str, dict]) -> dict:
    sym = idx_cfg["symbol"]
    c_sym = idx_cfg.get("cnbcSymbol", sym).upper()
    chart = yc.get_chart(sym, interval="5m", range_str="5d", prepost=False)
    q = q_map.get(sym, {})
    cq = cnbc_map.get(c_sym, {})

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
        d_tw = dt.datetime.fromtimestamp(ts, TW_TZ)
        if d_tw.weekday() >= 5:
            continue
        hm = d_tw.hour * 60 + d_tw.minute
        if 9 * 60 <= hm <= 13 * 60 + 35:
            d_key = d_tw.strftime("%Y-%m-%d")
            by_date.setdefault(d_key, []).append((ts, float(c), float(h), float(l)))

    sorted_dates = sorted(by_date.keys())
    now_tw = dt.datetime.now(TW_TZ)
    today_key = now_tw.strftime("%Y-%m-%d")
    hm_now = now_tw.hour * 60 + now_tw.minute

    target_date = sorted_dates[-1] if sorted_dates else today_key
    bars = by_date.get(target_date, [])
    target_idx = sorted_dates.index(target_date) if target_date in sorted_dates else -1
    prev_bars = by_date[sorted_dates[target_idx - 1]] if target_idx > 0 else []

    q_reg_time = int(q.get("regularMarketTime") or 0)
    is_live = bool(
        target_date == today_key
        and now_tw.weekday() < 5
        and (9 * 60 <= hm_now < 13 * 60 + 32)
    )

    cnbc_last = _parse_cnbc_float(cq.get("last"))
    cnbc_prev = _parse_cnbc_float(cq.get("previous_day_closing"))
    cnbc_hi = _parse_cnbc_float(cq.get("high"))
    cnbc_lo = _parse_cnbc_float(cq.get("low"))

    close_price = round(
        cnbc_last
        if cnbc_last is not None
        else float(q.get("regularMarketPrice") or (bars[-1][1] if bars else 0.0)),
        2,
    )
    if cnbc_prev is not None and cnbc_prev > 0:
        prev_close = round(cnbc_prev, 2)
    elif sym != "^TWII" and q.get("regularMarketPreviousClose"):
        prev_close = round(float(q["regularMarketPreviousClose"]), 2)
    elif prev_bars:
        prev_close = round(prev_bars[-1][1], 2)
    else:
        prev_close = close_price

    change = round(close_price - prev_close, 2)
    change_pct = round((change / prev_close * 100.0) if prev_close else 0.0, 2)

    bar_high = max((b[2] for b in bars), default=close_price)
    bar_low = min((b[3] for b in bars), default=close_price)
    if cnbc_hi is not None:
        bar_high = max(bar_high, cnbc_hi, close_price)
    if cnbc_lo is not None:
        bar_low = min(bar_low, cnbc_lo, close_price)
    day_high = round(bar_high, 2)
    day_low = round(bar_low, 2)

    points = []
    for ts, c, _, _ in bars:
        t_tw = dt.datetime.fromtimestamp(ts, TW_TZ).strftime("%H:%M")
        points.append({"t": ts, "et": t_tw, "p": round(c, 2)})

    if is_live:
        live_ts = q_reg_time or int(now_tw.timestamp())
        live_hm = dt.datetime.fromtimestamp(live_ts, TW_TZ).strftime("%H:%M")
        if not points or abs(points[-1]["p"] - close_price) > 0.005 or points[-1]["et"] != live_hm:
            points.append({"t": live_ts, "et": live_hm, "p": close_price})
    elif points and abs(points[-1]["p"] - close_price) > 0.01:
        points.append({"t": points[-1]["t"] + 60, "et": "13:30", "p": close_price})

    last_time_tw = points[-1]["et"] if points else ("13:30" if not is_live else now_tw.strftime("%H:%M"))
    quote_ts = q_reg_time or (points[-1]["t"] if points else int(now_tw.timestamp()))

    return {
        "symbol": sym,
        "displaySymbol": idx_cfg["displaySymbol"],
        "name": idx_cfg["name"],
        "enName": idx_cfg["enName"],
        "sessionDate": target_date,
        "isLive": is_live,
        "statusLabel": "盤中即時" if is_live else "收盤",
        "lastTimeET": last_time_tw,
        "tzLabel": "TW",
        "openHm": "09:00",
        "midHm": "11:15",
        "closeHm": "13:30",
        "quoteTs": int(quote_ts),
        "close": close_price,
        "prevClose": prev_close,
        "change": change,
        "changePct": change_pct,
        "high": day_high,
        "low": day_low,
        "isUp": change >= 0,
        "points": points,
    }


def build_tw_stock_quote(yc: YahooClient, item_cfg: dict, q_map: dict[str, dict], cnbc_map: dict[str, dict]) -> dict:
    sym = item_cfg["symbol"]
    q = q_map.get(sym, {})
    cq = cnbc_map.get(sym.upper(), {})
    chart = yc.get_chart(sym, interval="5m", range_str="2d", prepost=False)
    meta = chart.get("meta", {})

    cnbc_last = _parse_cnbc_float(cq.get("last"))
    cnbc_prev = _parse_cnbc_float(cq.get("previous_day_closing"))
    cnbc_hi = _parse_cnbc_float(cq.get("high"))
    cnbc_lo = _parse_cnbc_float(cq.get("low"))

    reg_price = cnbc_last if cnbc_last is not None else float(q.get("regularMarketPrice") or meta.get("regularMarketPrice") or 0.0)
    prev_close = cnbc_prev if cnbc_prev is not None else float(q.get("regularMarketPreviousClose") or meta.get("previousClose") or reg_price)
    reg_time = int(q.get("regularMarketTime") or meta.get("regularMarketTime") or int(time.time()))

    now_tw = dt.datetime.now(TW_TZ)
    hm_now = now_tw.hour * 60 + now_tw.minute
    is_live = bool(now_tw.weekday() < 5 and (9 * 60 <= hm_now < 13 * 60 + 32))
    session_label = "盤中" if is_live else "收盤"

    change = reg_price - prev_close
    change_pct = (change / prev_close * 100.0) if prev_close else 0.0

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

    spark_raw = [b[2] for b in valid_bars[-96:]]
    step = max(1, len(spark_raw) // 48)
    sparkline = [round(v, 2) for v in spark_raw[::step]][-48:]
    if sparkline and round(reg_price, 2) != sparkline[-1]:
        sparkline.append(round(reg_price, 2))

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

    day_high = cnbc_hi if cnbc_hi is not None else float(q.get("regularMarketDayHigh") or meta.get("regularMarketDayHigh") or reg_price)
    day_low = cnbc_lo if cnbc_lo is not None else float(q.get("regularMarketDayLow") or meta.get("regularMarketDayLow") or reg_price)

    return {
        "symbol": sym,
        "displaySymbol": item_cfg["displaySymbol"],
        "name": item_cfg["name"],
        "enName": item_cfg["enName"],
        "category": item_cfg["category"],
        "isHolding": bool(item_cfg.get("isHolding", False)),
        "holdingBadge": item_cfg.get("holdingBadge", ""),
        "price": round(reg_price, 2),
        "change": round(change, 2),
        "changePct": round(change_pct, 2),
        "isUp": change_pct >= 0,
        "session": session_label,
        "quoteTs": int(reg_time),
        "prevClose": round(prev_close, 2),
        "updatedAt": dt.datetime.fromtimestamp(reg_time, TW_TZ).strftime("%m/%d %H:%M") if reg_time else "",
        "regularPrice": round(reg_price, 2),
        "regularChangePct": round(change_pct, 2),
        "extChangePct": None,
        "dayHigh": round(max(day_high, reg_price), 2),
        "dayLow": round(min(day_low, reg_price), 2),
        "high52w": round(float(q.get("fiftyTwoWeekHigh") or meta.get("fiftyTwoWeekHigh") or reg_price), 2),
        "sparkline": sparkline,
        "_volBuyRatio6h": round(vol_buy_ratio, 4),
    }


def fetch_tw_market_headlines() -> list[dict]:
    tw_must = ["台股", "加權", "台積電", "外資", "投信", "三大法人", "AI", "半導體", "聯發科", "鴻海", "廣達", "0050", "台指期"]
    q1 = '("台股" OR "加權指數" OR "外資" OR "三大法人" OR "台指期") (台積電 OR AI OR 半導體 OR 電子股) when:1d'
    q2 = '("2330" OR "台積電" OR "聯發科" OR "鴻海" OR "廣達" OR "奇鋐" OR "緯穎" OR "0050") 台股 when:1d'
    pool = (
        fetch_google_news_rss(q1, "zh-TW", max_age_hours=26.0, must_match=tw_must)
        + fetch_google_news_rss(q2, "zh-TW", max_age_hours=26.0, must_match=tw_must)
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


def fetch_tw_flash() -> list[dict]:
    queries = [
        (
            '("台積電" OR "聯發科" OR "鴻海" OR "廣達" OR "奇鋐" OR "緯穎" OR "台達電" OR "日月光") (法說 OR 財報 OR 營收 OR CoWoS OR GB200 OR 漲停 OR 跌停 OR 外資 OR 目標價) when:2d',
            "zh-TW",
            36.0,
        ),
        (
            '("台股" OR "加權指數" OR "外資買超" OR "外資賣超" OR "三大法人" OR "央行" OR "金管會" OR "國安基金") when:1d',
            "zh-TW",
            28.0,
        ),
        (
            '("世芯" OR "創意" OR "緯創" OR "智邦" OR "0050" OR "006208" OR "0052" OR "00878") 台股 when:2d',
            "zh-TW",
            36.0,
        ),
    ]
    pool: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(fetch_google_news_rss, q, lang, max_h) for q, lang, max_h in queries]
        for f in futs:
            pool.extend(f.result())

    sorted_pool = sorted(pool, key=lambda x: (x["tier"] * 10800 + x["pubTs"]), reverse=True)
    selected: list[dict] = []
    ticker_counts: dict[str, int] = {}

    for it in sorted_pool:
        src = it["source"]
        if src in FLASH_BLOCKED_SOURCES:
            continue
        raw_t = clean_headline_title(it["title"], src)
        low = f" {raw_t.lower()} "
        if any(cb in low for cb in FLASH_CLICKBAIT_NOISE):
            continue

        matched_tickers = [sym for sym, _, kws in TW_FLASH_ENTITIES if any(k in low for k in kws)]
        is_macro = any(mk in low for mk in ["外資", "三大法人", "投信", "加權", "央行", "金管會", "國安基金", "台指期", "匯率", "台幣"])
        if not matched_tickers and not is_macro:
            continue

        primary_key = matched_tickers[0] if matched_tickers else "法人/大盤"
        if ticker_counts.get(primary_key, 0) >= 2:
            continue

        zh_title = clean_headline_title(translate_en_to_zhtw(raw_t), src)
        if cjk_char_count(zh_title) < 2:
            continue
        if any(title_similarity(zh_title, s["title"]) > 0.38 for s in selected):
            continue

        ticker_counts[primary_key] = ticker_counts.get(primary_key, 0) + 1
        tags: list[str] = []
        if is_macro:
            tags.append("法人/大盤")
        tags.extend(matched_tickers[:2])
        if not tags:
            tags.append("台股AI")

        urgent = any(uk in low for uk in FLASH_URGENT_KEYWORDS + ["漲停", "跌停", "法說", "營收創高", "外資大買", "外資大賣"])
        affects_holdings = bool(is_macro or (set(matched_tickers) & {"2330", "2454", "2317", "2382", "3017", "6669", "0050"}))

        selected.append(
            {
                "title": zh_title,
                "source": src,
                "url": it["url"],
                "tags": tags[:2],
                "urgent": urgent,
                "isOutage": False,
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


def build_tw_cio_advisory(
    tw_indices: list[dict],
    tw_stocks: list[dict],
    tw_insights: dict[str, dict],
    us_stocks: list[dict] | None = None,
) -> dict:
    s_map = {s["symbol"]: s for s in tw_stocks}
    i_map = {x["symbol"]: x for x in tw_indices}
    us_map = {s["symbol"]: s for s in (us_stocks or [])}

    taiex = i_map.get("^TWII", {})
    taiex_p = taiex.get("close", 40300.0)
    taiex_chg = taiex.get("changePct", 0.0)

    s2330 = s_map.get("2330.TW", {})
    s2454 = s_map.get("2454.TW", {})
    s2317 = s_map.get("2317.TW", {})
    s2382 = s_map.get("2382.TW", {})
    s3017 = s_map.get("3017.TW", {})
    s6669 = s_map.get("6669.TW", {})
    s0050 = s_map.get("0050.TW", {})
    s006208 = s_map.get("006208.TW", {})
    tsm_adr = us_map.get("TSM", {})

    if taiex_chg <= -1.2:
        regime_tag = f"外資調節震盪期 (加權 {taiex_chg:+.2f}%)"
        regime_tone = "caution"
        regime_summary = (
            f"台股加權指數報 {taiex_p:,.2f} ({taiex_chg:+.2f}%)，隨美股費半與輝達財報前觀望情緒連動回檔。"
            "操作策略嚴守「買黑不買紅」：高本益比散熱與組裝股拉回時分批低接，並優先以 0050 / 006208 捕捉大盤回檔買點。"
        )
    elif taiex_chg >= 1.0:
        regime_tag = f"多頭攻堅順風期 (加權 {taiex_chg:+.2f}%)"
        regime_tone = "bull"
        regime_summary = (
            f"加權指數強勢上攻至 {taiex_p:,.2f} ({taiex_chg:+.2f}%)，權值股與 AI 伺服器供應鏈同步點火。"
            "核心部位續抱讓獲利奔跑，短線乖離過大個股切忌追高，可逢高鎖定部分波段獲利。"
        )
    else:
        regime_tag = f"高檔區間換手・個股表現期 (加權 {taiex_chg:+.2f}%)"
        regime_tone = "neutral"
        regime_summary = (
            f"加權指數於 {taiex_p:,.2f} ({taiex_chg:+.2f}%) 區間震盪整理，資金在先進製程、IC設計與 AI 伺服器間良性輪動。"
            "維持市值型 ETF 底倉，聚焦基本面營收創高且法人籌碼集中的 AI 龍頭。"
        )

    adr_p = tsm_adr.get("price", 374.0)
    adr_chg = tsm_adr.get("changePct", 0.0)
    cards = [
        {
            "title": f"2330 台積電 (NT${s2330.get('price', 0):,.0f}) ＆ 2454 聯發科 (NT${s2454.get('price', 0):,.0f}) — 雙晶片核心",
            "action": "逢低分批佈局",
            "actionType": "hold",
            "detail": (
                f"台積電 ADR 最新報 ${adr_p:.2f} ({adr_chg:+.2f}%)，台股現貨展現強勁低接買盤（CoWoS 與 2 奈米產能滿載至 2027 年）；"
                f"聯發科 ({s2454.get('changePct', 0):+.2f}%) 受惠天璣旗艦晶片與雲端 AI ASIC 專案推進，雙龍頭拉回皆為中長線核心買點。"
            ),
        },
        {
            "title": f"2317 鴻海 (NT${s2317.get('price', 0):,.1f}) ＆ 2382 廣達 (NT${s2382.get('price', 0):,.1f}) — AI 伺服器機櫃雙雄",
            "action": "區間守穩續抱",
            "actionType": "hold",
            "detail": (
                f"鴻海 ({s2317.get('changePct', 0):+.2f}%) 與廣達 ({s2382.get('changePct', 0):+.2f}%) 為輝達 Blackwell / GB200 / GB300 整機櫃出貨主力，"
                "下檔具高殖利率與低本益比保護，建議沿月季線支撐區間操作，不隨短線外資期貨結算噪音殺低。"
            ),
        },
        {
            "title": f"3017 奇鋐 (NT${s3017.get('price', 0):,.0f}) ＆ 6669 緯穎 (NT${s6669.get('price', 0):,.0f}) — 高彈性液冷與 ASIC 伺服器",
            "action": "嚴控部位・等止跌紅K",
            "actionType": "watch" if min(s3017.get("changePct", 0), s6669.get("changePct", 0)) < -3.0 else "hold",
            "detail": (
                f"奇鋐 ({s3017.get('changePct', 0):+.2f}%) 掌握 CSP 液冷散熱水冷板高市佔，緯穎 ({s6669.get('changePct', 0):+.2f}%) 深度綁定雲端大廠自研 ASIC 伺服器。"
                "高價股 Beta 值高、受美股科技股修正波動較大，務必等量縮止跌紅 K 再分批承接，嚴禁單筆重倉追高。"
            ),
        },
        {
            "title": f"0050 (NT${s0050.get('price', 0):,.2f}) ＆ 006208 (NT${s006208.get('price', 0):,.2f}) — 市值型 ETF 長線引擎",
            "action": "大盤回檔優先加碼",
            "actionType": "bull" if taiex_chg <= -1.5 else "hold",
            "detail": (
                f"0050 ({s0050.get('changePct', 0):+.2f}%) 與 006208 ({s006208.get('changePct', 0):+.2f}%) 涵蓋逾 55% 台積電與台灣前 50 大權值龍頭。"
                "每當加權指數單日回檔逾 1.5%–2% 時，即為紀律執行定期定額與逢低單筆加碼的最佳擊球區。"
            ),
        },
    ]

    non_core = [s for s in tw_stocks if not s.get("isHolding")]
    biggest_drop = min(tw_stocks, key=lambda x: x["changePct"], default=None)
    strongest_gain = max(tw_stocks, key=lambda x: x["changePct"], default=None)
    scanner_bullets = []
    if strongest_gain and strongest_gain["changePct"] > 0:
        sg_sent = tw_insights.get(strongest_gain["symbol"], {}).get("sentiment", {})
        scanner_bullets.append(
            f"盤面抗跌領頭羊：{strongest_gain['displaySymbol']} {strongest_gain['name']} 逆勢表現 {strongest_gain['changePct']:+.2f}% "
            f"(6H 網友想買 {sg_sent.get('buyPct', 50)}%)，法人買盤相對穩健。"
        )
    if biggest_drop and biggest_drop["changePct"] <= -3.0:
        bd_sent = tw_insights.get(biggest_drop["symbol"], {}).get("sentiment", {})
        scanner_bullets.append(
            f"短線修正觀察：{biggest_drop['displaySymbol']} {biggest_drop['name']} 回檔 {biggest_drop['changePct']:+.2f}% "
            f"(6H 網友想賣 {bd_sent.get('sellPct', 50)}%)，高估值 AI 供應鏈短線獲利了結賣壓湧現，宜靜待籌碼沉澱。"
        )
    if non_core:
        s0052 = s_map.get("0052.TW")
        if s0052:
            scanner_bullets.append(
                f"高含積量 ETF 追蹤：0052 富邦科技最新報 NT${s0052['price']:,.2f} ({s0052['changePct']:+.2f}%)，"
                "台積電權重高達約 65%，適合看好先進製程獨佔優勢但想分散單一個股波動的投資人。"
            )

    return {
        "regimeTag": regime_tag,
        "regimeTone": regime_tone,
        "regimeSummary": regime_summary,
        "cards": cards,
        "scannerBullets": scanner_bullets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch US & Taiwan Stock Watchlist quotes, flash & 6H insights.")
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
    tw_indices_data: list[dict] = []
    tw_stocks_quotes: list[dict] = []

    if args.mode in ("all", "quotes", "insights"):
        yc = YahooClient()
        tw_all_syms = list({x["symbol"] for x in TW_INDICES} | {x["symbol"] for x in TW_WATCHLIST})
        all_symbols = [x["symbol"] for x in INDICES] + [x["symbol"] for x in WATCHLIST] + tw_all_syms
        q_map = yc.get_quotes(all_symbols)
        cnbc_tw_syms = list({x.get("cnbcSymbol", x["symbol"]) for x in TW_INDICES} | {x["symbol"] for x in TW_WATCHLIST})
        cnbc_tw_map = fetch_cnbc_quote_map(cnbc_tw_syms)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            idx_futures = [pool.submit(build_index_data, yc, cfg, q_map) for cfg in INDICES]
            stk_futures = [pool.submit(build_stock_quote, yc, cfg, q_map) for cfg in WATCHLIST]
            tw_idx_futures = [pool.submit(build_tw_index_data, yc, cfg, q_map, cnbc_tw_map) for cfg in TW_INDICES]
            tw_stk_futures = [pool.submit(build_tw_stock_quote, yc, cfg, q_map, cnbc_tw_map) for cfg in TW_WATCHLIST]

            indices_data = [f.result() for f in idx_futures]
            stocks_quotes = [f.result() for f in stk_futures]
            tw_indices_data = [f.result() for f in tw_idx_futures]
            tw_stocks_quotes = [f.result() for f in tw_stk_futures]

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
        print(f"[ok] Wrote data/quotes.json ({len(clean_stocks)} US stocks, {len(indices_data)} US indices)")

        clean_tw_stocks = [{k: v for k, v in sq.items() if not k.startswith("_")} for sq in tw_stocks_quotes]
        tw_quotes_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "refreshIntervalMinutes": 3,
            "marketSession": get_tw_market_session_overview(),
            "indices": tw_indices_data,
            "watchlist": clean_tw_stocks,
        }
        (data_dir / "tw_quotes.json").write_text(
            json.dumps(tw_quotes_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/tw_quotes.json ({len(clean_tw_stocks)} TW stocks, {len(tw_indices_data)} TW indices)")

    if args.mode in ("all", "quotes", "flash"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_us = pool.submit(fetch_tech30_flash)
            f_tw = pool.submit(fetch_tw_flash)
            flash_items = f_us.result()
            tw_flash_items = f_tw.result()

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

        tw_flash_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "refreshIntervalMinutes": 3,
            "universeNote": "嚴選台股 AI 與半導體權值股（台積電/聯發科/鴻海/廣達/奇鋐/緯穎）＆ 三大法人/大盤重磅快報",
            "items": tw_flash_items,
        }
        (data_dir / "tw_flash.json").write_text(
            json.dumps(tw_flash_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/tw_flash.json ({len(tw_flash_items)} TW AI & Semiconductor flash items)")

    if args.mode in ("all", "insights"):
        apewisdom = fetch_apewisdom_map()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_mh_us = pool.submit(fetch_market_headlines)
            f_mh_tw = pool.submit(fetch_tw_market_headlines)
            market_headlines = f_mh_us.result()
            tw_market_headlines = f_mh_tw.result()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ins_futures = [
                pool.submit(build_stock_insight, yc, cfg, sq, apewisdom)
                for cfg, sq in zip(WATCHLIST, stocks_quotes)
            ]
            tw_ins_futures = [
                pool.submit(build_stock_insight, yc, cfg, sq, {})
                for cfg, sq in zip(TW_WATCHLIST, tw_stocks_quotes)
            ]
            stock_insights = dict(f.result() for f in ins_futures)
            tw_stock_insights = dict(f.result() for f in tw_ins_futures)

        cio_advisory = build_cio_advisory(indices_data, stocks_quotes, stock_insights)
        tw_cio_advisory = build_tw_cio_advisory(tw_indices_data, tw_stocks_quotes, tw_stock_insights, stocks_quotes)

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
        print(f"[ok] Wrote data/insights.json ({len(market_headlines)} US headlines, {len(stock_insights)} stocks)")

        tw_insights_payload = {
            "generatedAt": now_iso,
            "updatedAtTW": now_tw_str,
            "scheduleNote": "每 6 小時自動更新 ＋ 台股盤中即時同步",
            "marketHeadlines": tw_market_headlines,
            "stocks": tw_stock_insights,
            "cioAdvisory": tw_cio_advisory,
        }
        (data_dir / "tw_insights.json").write_text(
            json.dumps(tw_insights_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] Wrote data/tw_insights.json ({len(tw_market_headlines)} TW headlines, {len(tw_stock_insights)} stocks)")


if __name__ == "__main__":
    main()

