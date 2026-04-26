"""
crypto/news_impl.py — V5.10-β: Crypto news + sentiment.

Hafif, dependency-light yaklaşım:
  - CoinDesk RSS feed (no API key gerekmez)
  - Bitcoin Magazine RSS
  - Cointelegraph RSS
  - Title + summary çekilir, ticker mention'ları detect edilir
  - Naive sentiment: keyword-based (positive: surge, rally, gain, bullish;
                                   negative: dump, crash, hack, ban)
  - Brain'e {ticker: {sentiment_score, headlines, sources}} formatında verilir

Daha sofistike alternatifler (V5.11+):
  - CryptoPanic API (key gerekir, daha sağlam aggregator)
  - Claude'a haberlerin özetini yaptırmak (sentiment'ı Claude değerlendirir)
  - News volume spike detection (1 saat içinde X haber = catalyst)

Caching: 10dk TTL — haber feed'leri yavaş, çok sık çekmek gereksiz.
"""

import re
import time
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError
from xml.etree import ElementTree as ET


# Crypto news RSS feeds (no API key required)
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("BitcoinMagazine", "https://bitcoinmagazine.com/.rss/full/"),
]

# Ticker mention detection — değiştirilebilir
TICKER_KEYWORDS = {
    "BTC/USD": ["bitcoin", "btc"],
    "ETH/USD": ["ethereum", "eth", "ether"],
    "SOL/USD": ["solana", "sol"],
    "XRP/USD": ["xrp", "ripple"],
    "DOGE/USD": ["dogecoin", "doge"],
    "ADA/USD": ["cardano", "ada"],
    "AVAX/USD": ["avalanche", "avax"],
    "LINK/USD": ["chainlink", "link"],
    "DOT/USD": ["polkadot", "dot"],
    "LTC/USD": ["litecoin", "ltc"],
    "MATIC/USD": ["polygon", "matic", "pol"],
    "BCH/USD": ["bitcoin cash", "bch"],
    "UNI/USD": ["uniswap", "uni"],
    "AAVE/USD": ["aave"],
    "PEPE/USD": ["pepe"],
    "SHIB/USD": ["shiba", "shib"],
    "ARB/USD": ["arbitrum", "arb"],
    "TRUMP/USD": ["trump"],
}

# Naive sentiment keywords
POSITIVE_KW = [
    "surge", "rally", "gain", "rise", "soar", "bullish", "breakout",
    "all-time high", "ath", "boom", "moon", "skyrocket", "pump",
    "approve", "approval", "etf", "institutional", "adoption",
    "partnership", "upgrade", "milestone", "record",
]

NEGATIVE_KW = [
    "crash", "dump", "plunge", "drop", "fall", "tumble", "decline",
    "bearish", "bear market", "selloff", "liquidat", "rug", "scam",
    "hack", "exploit", "stolen", "ban", "regulation", "lawsuit",
    "sec charges", "fraud", "collapse", "bankrupt", "fud",
]


# ─────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────

_news_cache: dict = {"data": None, "ts": 0}
NEWS_CACHE_TTL = 600  # 10 dakika


def _fetch_rss(url: str, timeout: int = 8) -> list[dict]:
    """RSS feed'i parse et — title, link, summary, pubDate."""
    items = []
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 MeridianCrypto/1.0"})
        with urlopen(req, timeout=timeout) as r:
            content = r.read()
        root = ET.fromstring(content)
        # RSS 2.0: channel > item
        channel = root.find("channel") or root
        for item in (channel.findall("item") or [])[:30]:
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            # HTML tag temizle
            desc_clean = re.sub(r"<[^>]+>", "", desc)[:300]
            items.append({
                "title": title,
                "summary": desc_clean,
                "link": link,
                "pubDate": pub,
            })
    except (URLError, ET.ParseError, Exception):
        pass
    return items


def _classify_sentiment(text: str) -> int:
    """Naive sentiment: -3..+3."""
    text_lower = text.lower()
    pos = sum(1 for kw in POSITIVE_KW if kw in text_lower)
    neg = sum(1 for kw in NEGATIVE_KW if kw in text_lower)
    raw = pos - neg
    return max(-3, min(3, raw))


def _detect_tickers(text: str) -> list[str]:
    """Hangi ticker'lar mention edilmiş?"""
    text_lower = text.lower()
    found = []
    for ticker, keywords in TICKER_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(ticker)
    return found


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def get_crypto_news(force_refresh: bool = False) -> dict:
    """
    Tüm RSS feed'lerden son haberleri çek, ticker bazında grupla,
    sentiment hesapla.

    Returns:
        {
          "BTC/USD": {
            "score": +2 (toplam sentiment),
            "headlines": [list of {title, summary, sentiment, source}],
            "summary": "Top headlines string"
          },
          ...
          "_meta": {"sources": [...], "total_articles": N, "fetched_at": ISO},
        }
    """
    global _news_cache
    now = time.time()
    if not force_refresh and _news_cache["data"] and (now - _news_cache["ts"]) < NEWS_CACHE_TTL:
        return _news_cache["data"]

    all_items: list[dict] = []
    sources_used: list[str] = []
    for source, url in RSS_FEEDS:
        items = _fetch_rss(url)
        if items:
            sources_used.append(source)
            for item in items:
                item["source"] = source
                all_items.append(item)

    # Ticker bazında grupla
    by_ticker: dict[str, dict] = {}
    for item in all_items:
        text = item["title"] + " " + item.get("summary", "")
        sentiment = _classify_sentiment(text)
        tickers = _detect_tickers(text)
        for t in tickers:
            entry = by_ticker.setdefault(t, {
                "score": 0, "headlines": [], "summary": "",
                "positive_count": 0, "negative_count": 0, "neutral_count": 0,
            })
            entry["score"] += sentiment
            entry["headlines"].append({
                "title": item["title"],
                "summary": item.get("summary", "")[:200],
                "sentiment": sentiment,
                "source": item.get("source"),
                "link": item.get("link"),
            })
            if sentiment > 0: entry["positive_count"] += 1
            elif sentiment < 0: entry["negative_count"] += 1
            else: entry["neutral_count"] += 1

    # Her ticker için top 3 headline + summary string oluştur
    for t, entry in by_ticker.items():
        # Skor'a göre sırala (en güçlü sentimental olanlar üstte)
        entry["headlines"].sort(key=lambda h: abs(h["sentiment"]), reverse=True)
        entry["headlines"] = entry["headlines"][:5]
        # Brain için kısa özet metni
        emoji = "📈" if entry["score"] > 1 else "📉" if entry["score"] < -1 else "📰"
        entry["summary"] = (
            f"{emoji} score={entry['score']} "
            f"({entry['positive_count']}+ / {entry['negative_count']}- / {entry['neutral_count']}=) | "
            + " | ".join(h["title"][:80] for h in entry["headlines"][:3])
        )

    result = {
        **by_ticker,
        "_meta": {
            "sources": sources_used,
            "total_articles": len(all_items),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }
    _news_cache = {"data": result, "ts": now}
    return result


def get_sentiment_for_brain(tickers: list[str]) -> dict:
    """
    Brain'in run_brain'e geçirebileceği format:
        {ticker: {score: int, summary: str}}
    """
    news = get_crypto_news()
    out = {}
    for t in tickers:
        info = news.get(t, {})
        if info:
            out[t] = {
                "score": info.get("score", 0),
                "summary": info.get("summary", ""),
                "headlines_count": len(info.get("headlines", [])),
            }
    return out
