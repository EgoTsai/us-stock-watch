# 美股即時觀察站 (US Stock Watchlist)

清爽、簡潔的美股線上觀察面板，透過 GitHub Pages 與 GitHub Actions 全自動更新。

## 線上網址
- **GitHub Pages**: [https://egotsai.github.io/us-stock-watch/](https://egotsai.github.io/us-stock-watch/)

## 核心功能
1. **美股三大市場走勢與收盤**：道瓊 (`^DJI`)、納斯達克 (`^IXIC`)、標普 500 (`^GSPC`) 前一完整交易日分時走勢圖與收盤漲跌幅（**漲綠跌紅**）。
2. **美股頭條重點整理**：精選主流財經媒體重點條列，每則皆附原文連結。
3. **19 檔核心觀察名單（每 15 分鐘自動更新）**：涵蓋 `GOOG`、`MU`、`NVDA`、`QQQ`、`SPCX`、`TSLA`、`TSM`、`VOO`、`CL=F (NYMEX 原油)`、`SOXL`、`MSFT`、`META`、`VIX`、`IBIT`、`AMD`、`INTC`、`IAU`、`UCO`、`AVGO`，自動判別並顯示 **夜盤 / 盤前 / 盤中 / 盤後** 最新成交價。
4. **個股 6 小時重點頭條**：每 6 小時自動更新，並於**美股開盤前 10 分鐘 (`09:20 ET`)** 強制刷新一次。
5. **個股 6 小時網友情緒指數**：綜合社群討論熱度、選擇權買賣權成交比與近 6 小時主動買賣盤量能，**想買居多顯示綠色百分比、想賣居多顯示紅色百分比**，同步於每 6 小時及美股開盤前 10 分鐘更新。
