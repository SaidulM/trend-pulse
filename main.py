#!/usr/bin/env python3
"""
Trend Pulse v2
==============
Daily trending-topic collector -> Google Sheets.

Categories (one worksheet/tab each):
  - Technology
  - Islamic
  - Trending (US)

Platforms per category (2 topics each per day):
  Google Trends, YouTube, Reddit, Google News, Bing News, Quora

Features:
  - Shows popularity (searches / views / upvotes) where available
  - Gemini AI picks the 2 best topics per platform and keeps
    categories distinct from each other
  - Skips topics already saved in the sheet (no duplicates)
  - Rows older than RETENTION_DAYS (60) are deleted automatically
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests
import gspread
from google.oauth2.service_account import Credentials

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
TIMEOUT = 25
RETENTION_DAYS = 60
TOPICS_PER_PLATFORM = 2
GEO = "US"

HEADERS_ROW = ["Date", "Platform", "Topic", "Popularity (Searches/Views)",
               "Description", "Link", "Source"]

CATEGORIES = ["Technology", "Islamic", "Trending (US)"]

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def log(msg):
    print(msg, flush=True)


def env_first(*names):
    """Return the first non-empty environment variable among names."""
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return ""


SERVICE_ACCOUNT_JSON = env_first(
    "GOOGLE_SHEETS_CREDENTIALS", "GOOGLE_CREDENTIALS", "GCP_SERVICE_ACCOUNT",
    "SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT", "GOOGLE_SERVICE_ACCOUNT_JSON")
SHEET_ID = env_first("SHEET_ID", "SPREADSHEET_ID", "GOOGLE_SHEET_ID", "SHEETS_ID")
GEMINI_KEY = env_first("GEMINI_API_KEY", "GOOGLE_GEMINI_API_KEY", "GEMINI_KEY")
YOUTUBE_KEY = env_first("YOUTUBE_API_KEY", "YT_API_KEY", "YOUTUBE_KEY",
                        "GOOGLE_YOUTUBE_API_KEY")


# ----------------------------------------------------------------------------
# HTTP helper
# ----------------------------------------------------------------------------
def safe_get(url, headers=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=TIMEOUT,
                             headers=headers or {"User-Agent": UA})
            if r.status_code == 429:
                time.sleep(4 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            if attempt == retries - 1:
                log(f"    ! GET failed: {url[:90]} ({e})")
                return None
            time.sleep(2)
    return None


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def human_int(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def mk(topic, platform, popularity="", description="", link="", source=""):
    return {"topic": (topic or "").strip(),
            "platform": platform,
            "popularity": popularity,
            "description": strip_html(description)[:250],
            "link": link,
            "source": source}


# ----------------------------------------------------------------------------
# Fetchers
# ----------------------------------------------------------------------------
def fetch_google_trends():
    """Realtime US trending searches with approximate search volume."""
    urls = [
        f"https://trends.google.com/trending/rss?geo={GEO}",
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={GEO}",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
            ns = {"ht": "https://trends.google.com/trending/rss"}
            ns2 = {"ht": "https://trends.google.co.in/trends/trendingsearches/daily"}
            items = []
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                traffic = (item.findtext("ht:approx_traffic", namespaces=ns)
                           or item.findtext("ht:approx_traffic", namespaces=ns2)
                           or "").strip()
                news_title = (item.findtext("ht:news_item/ht:news_item_title", namespaces=ns)
                              or item.findtext("ht:news_item/ht:news_item_title", namespaces=ns2)
                              or "")
                news_url = (item.findtext("ht:news_item/ht:news_item_url", namespaces=ns)
                            or item.findtext("ht:news_item/ht:news_item_url", namespaces=ns2)
                            or "")
                if title:
                    pop = f"{traffic} searches" if traffic else ""
                    items.append(mk(title, "Google Trends", pop, news_title,
                                    news_url or f"https://trends.google.com/trending?geo={GEO}&q={quote(title)}",
                                    "Google Trends US"))
            if items:
                return items
        except Exception as e:
            log(f"    ! trends parse error: {e}")
    return []


def fetch_youtube_most_popular(video_category_id=None):
    if not YOUTUBE_KEY:
        return []
    url = ("https://www.googleapis.com/youtube/v3/videos"
           f"?part=snippet,statistics&chart=mostPopular&regionCode={GEO}"
           f"&maxResults=10&key={YOUTUBE_KEY}")
    if video_category_id:
        url += f"&videoCategoryId={video_category_id}"
    r = safe_get(url)
    if not r:
        return []
    items = []
    for v in r.json().get("items", []):
        sn, st = v.get("snippet", {}), v.get("statistics", {})
        views = human_int(st.get("viewCount"))
        items.append(mk(sn.get("title"), "YouTube",
                        f"{views} views" if views else "",
                        sn.get("description", "")[:250],
                        f"https://www.youtube.com/watch?v={v.get('id')}",
                        sn.get("channelTitle", "YouTube")))
    return items


def fetch_youtube_search(query, days=3):
    """Most-viewed recent videos for a query (used for Islamic category)."""
    if not YOUTUBE_KEY:
        return []
    published_after = (datetime.now(timezone.utc) - timedelta(days=days)
                       ).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = ("https://www.googleapis.com/youtube/v3/search"
           f"?part=snippet&q={quote(query)}&type=video&order=viewCount"
           f"&publishedAfter={published_after}&relevanceLanguage=en"
           f"&maxResults=10&key={YOUTUBE_KEY}")
    r = safe_get(url)
    if not r:
        return []
    ids = [it["id"]["videoId"] for it in r.json().get("items", [])
           if it.get("id", {}).get("videoId")]
    if not ids:
        return []
    r2 = safe_get("https://www.googleapis.com/youtube/v3/videos"
                  f"?part=snippet,statistics&id={','.join(ids)}&key={YOUTUBE_KEY}")
    if not r2:
        return []
    items = []
    for v in r2.json().get("items", []):
        sn, st = v.get("snippet", {}), v.get("statistics", {})
        views = human_int(st.get("viewCount"))
        items.append(mk(sn.get("title"), "YouTube",
                        f"{views} views" if views else "",
                        sn.get("description", "")[:250],
                        f"https://www.youtube.com/watch?v={v.get('id')}",
                        sn.get("channelTitle", "YouTube")))
    items.sort(key=lambda x: x["popularity"], reverse=True)
    return items


def fetch_reddit(subreddit):
    """Hot posts with upvote counts. JSON API first, RSS fallback."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=12"
    r = safe_get(url, headers={"User-Agent": f"trend-pulse/2.0 (by u/trendpulse{random.randint(1,999)})"})
    if r:
        try:
            items = []
            for child in r.json().get("data", {}).get("children", []):
                d = child.get("data", {})
                if d.get("stickied"):
                    continue
                ups = human_int(d.get("ups"))
                items.append(mk(d.get("title"), "Reddit",
                                f"{ups} upvotes" if ups else "",
                                (d.get("selftext") or "")[:250],
                                "https://www.reddit.com" + d.get("permalink", ""),
                                f"r/{subreddit}"))
            if items:
                return items
        except Exception:
            pass
    # RSS fallback (no upvote counts)
    r = safe_get(f"https://www.reddit.com/r/{subreddit}/hot.rss",
                 headers={"User-Agent": "trend-pulse-rss/2.0"})
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = []
        for e in root.findall(".//a:entry", ns):
            title = (e.findtext("a:title", namespaces=ns) or "").strip()
            link_el = e.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            if title:
                items.append(mk(title, "Reddit", "", "", link, f"r/{subreddit}"))
        return items
    except Exception:
        return []


def fetch_google_news(query=None, topic=None):
    """Google News RSS: either a search query or a section topic (e.g. TECHNOLOGY)."""
    if topic:
        url = (f"https://news.google.com/rss/headlines/section/topic/{topic}"
               f"?hl=en-US&gl=US&ceid=US:en")
    else:
        url = (f"https://news.google.com/rss/search?q={quote(query)}+when:2d"
               f"&hl=en-US&gl=US&ceid=US:en")
    r = safe_get(url)
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:12]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = strip_html(item.findtext("description") or "")[:250]
            src = item.find("source")
            src_name = src.text if src is not None else "Google News"
            # Google News titles end with " - Source"; keep topic clean
            clean = re.sub(r"\s+-\s+[^-]+$", "", title)
            if clean:
                items.append(mk(clean, "Google News", "", desc, link, src_name))
        return items
    except Exception:
        return []


def _parse_rss_items(content, platform, source, limit=12):
    root = ET.fromstring(content)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = strip_html(item.findtext("description") or "")[:250]
        if title:
            items.append(mk(title, platform, "", desc, link, source))
    return items


def fetch_bing_news(query):
    """Bing: news RSS first; falls back to Bing web-search RSS (always open)."""
    urls = [
        f"https://www.bing.com/news/search?q={quote(query)}&format=rss&setmkt=en-US",
        f"https://www.bing.com/search?q={quote(query)}&format=rss",
    ]
    for url in urls:
        r = safe_get(url)
        if not r:
            continue
        try:
            items = _parse_rss_items(r.content, "Bing Search", "Bing")
            if items:
                return items
        except Exception:
            continue  # Bing served HTML instead of RSS -> try next endpoint
    return []


UNSAFE = re.compile(r"\b(naked|nude|nsfw|porn|sex|xxx|adult|erotic|strip)\b", re.I)


def fetch_quora(query):
    """Free Quora discovery via Google News RSS (site:quora.com <query>)."""
    url = (f"https://news.google.com/rss/search?q="
           f"{quote('site:quora.com ' + query)}&hl=en-US&gl=US&ceid=US:en")
    r = safe_get(url)
    if not r:
        return []
    items = []
    try:
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:30]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            title = re.sub(r"\s*-\s*Quora\s*$", "", title).strip()
            if not title or title.lower() == "quora" or UNSAFE.search(title):
                continue
            items.append(mk(title, "Quora", "", "", link, "Quora"))
            if len(items) >= 12:
                break
    except Exception:
        pass
    return items


# ----------------------------------------------------------------------------
# Per-category collection
# ----------------------------------------------------------------------------
TECH_WORDS = re.compile(
    r"\b(ai|iphone|android|google|apple|microsoft|tesla|spacex|nvidia|intel|amd|"
    r"openai|chatgpt|gemini|robot|tech|app|software|chip|crypto|bitcoin|gpu|"
    r"samsung|meta|amazon|playstation|xbox|nintendo|cyber|hack|update|launch|"
    r"galaxy|pixel|windows|ios|macbook|laptop|phone|gaming|game)\b", re.I)


def collect_technology():
    data = {}
    trends = fetch_google_trends()
    data["Google Trends"] = [t for t in trends if TECH_WORDS.search(t["topic"] + " " + t["description"])]
    if not data["Google Trends"]:
        data["Google Trends"] = []
    data["YouTube"] = fetch_youtube_most_popular(video_category_id=28)
    data["Reddit"] = fetch_reddit("technology")
    data["Google News"] = fetch_google_news(topic="TECHNOLOGY")
    data["Bing News"] = fetch_bing_news("technology news")
    data["Quora"] = fetch_quora("technology AI gadgets")
    return data


def collect_islamic():
    data = {}
    data["Google Trends"] = []  # daily US trends rarely contain Islamic topics
    data["YouTube"] = fetch_youtube_search("islamic lecture OR islam OR quran recitation")
    data["Reddit"] = fetch_reddit("islam")
    data["Google News"] = fetch_google_news(query="islam OR muslim OR quran OR ramadan OR hajj")
    data["Bing News"] = fetch_bing_news("islam muslim")
    data["Quora"] = fetch_quora("islam quran")
    return data


def collect_trending():
    data = {}
    data["Google Trends"] = fetch_google_trends()
    data["YouTube"] = fetch_youtube_most_popular()
    data["Reddit"] = fetch_reddit("popular")
    data["Google News"] = fetch_google_news(topic="WORLD")
    data["Bing News"] = fetch_bing_news("trending viral news US")
    data["Quora"] = fetch_quora("trending this week")
    return data


COLLECTORS = {
    "Technology": collect_technology,
    "Islamic": collect_islamic,
    "Trending (US)": collect_trending,
}


# ----------------------------------------------------------------------------
# Gemini selection
# ----------------------------------------------------------------------------
def gemini_generate(prompt):
    if not GEMINI_KEY:
        return None
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0.2},
    }
    for model in GEMINI_MODELS:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={GEMINI_KEY}")
        try:
            r = requests.post(url, json=body, timeout=60)
            if r.status_code in (404, 429):
                continue
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except Exception as e:
            log(f"    ! Gemini {model} failed: {e}")
            continue
    return None


def select_with_gemini(category, platform_items, already_used):
    """Ask Gemini to pick the best TOPICS_PER_PLATFORM per platform.
    Returns {platform: [indices]} or None on failure."""
    catalog = {}
    for platform, items in platform_items.items():
        catalog[platform] = [
            {"i": i, "topic": it["topic"], "popularity": it["popularity"]}
            for i, it in enumerate(items[:12])
        ]
    prompt = (
        "You curate a daily trending-topics sheet.\n"
        f"Category: {category}\n"
        f"Pick EXACTLY {TOPICS_PER_PLATFORM} items per platform (fewer only if "
        "the platform has fewer candidates). Rules:\n"
        f"1. Choose the MOST trending/popular/interesting topics for '{category}'. "
        "Prefer items with higher popularity numbers.\n"
        "2. Topic must genuinely fit the category "
        "(for 'Islamic' only Islam-related; for 'Technology' only tech-related; "
        "'Trending (US)' = whatever is hottest in the United States).\n"
        "3. Do NOT pick a topic that is the same as, or nearly identical to, any "
        "topic in the ALREADY_USED list, and do not pick near-duplicates across "
        "platforms within this selection.\n"
        "Return ONLY JSON like {\"Google Trends\": [0, 3], \"YouTube\": [1, 2], ...} "
        "using each platform name as key and selected candidate 'i' values.\n\n"
        f"CANDIDATES:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
        f"ALREADY_USED (recent topics in sheet + other categories today):\n"
        f"{json.dumps(sorted(already_used)[:300], ensure_ascii=False)}"
    )
    result = gemini_generate(prompt)
    if not isinstance(result, dict):
        return None
    out = {}
    for platform, idxs in result.items():
        if platform in platform_items and isinstance(idxs, list):
            valid = [i for i in idxs if isinstance(i, int)
                     and 0 <= i < len(platform_items[platform])]
            out[platform] = valid[:TOPICS_PER_PLATFORM]
    return out


def normalize(topic):
    return re.sub(r"[^a-z0-9\u0980-\u09FF\u0600-\u06FF ]", "",
                  (topic or "").lower()).strip()


def pick_topics(category, platform_items, already_used):
    """Final picks: Gemini first, deterministic fallback. Returns list of items."""
    used_norm = {normalize(t) for t in already_used}
    picks = []

    selection = select_with_gemini(category, platform_items, already_used)
    if selection:
        log("    Gemini selection OK")
        for platform, idxs in selection.items():
            for i in idxs:
                it = platform_items[platform][i]
                if normalize(it["topic"]) not in used_norm and it["topic"]:
                    picks.append(it)
                    used_norm.add(normalize(it["topic"]))
    # Fill any platform that still has < TOPICS_PER_PLATFORM picks
    for platform, items in platform_items.items():
        have = sum(1 for p in picks if p["platform"] == platform)
        for it in items:
            if have >= TOPICS_PER_PLATFORM:
                break
            n = normalize(it["topic"])
            if it["topic"] and n not in used_norm:
                picks.append(it)
                used_norm.add(n)
                have += 1
    return picks


# ----------------------------------------------------------------------------
# Google Sheets
# ----------------------------------------------------------------------------
def get_spreadsheet():
    if not SERVICE_ACCOUNT_JSON:
        sys.exit("ERROR: service-account JSON secret not found. Set one of: "
                 "GOOGLE_SHEETS_CREDENTIALS / GOOGLE_CREDENTIALS / GCP_SERVICE_ACCOUNT "
                 "/ SERVICE_ACCOUNT_JSON")
    creds = Credentials.from_service_account_info(
        json.loads(SERVICE_ACCOUNT_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"])
    client = gspread.authorize(creds)
    if SHEET_ID:
        return client.open_by_key(SHEET_ID)
    log("WARN: no SHEET_ID secret found, trying to open by name 'Trend Data'")
    return client.open("Trend Data")


def get_worksheet(ss, name):
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=2000, cols=len(HEADERS_ROW))
    values = ws.get_all_values()
    if not values or values[0][:len(HEADERS_ROW)] != HEADERS_ROW:
        if not values:
            ws.append_row(HEADERS_ROW)
        else:
            ws.update(values=[HEADERS_ROW], range_name="A1")
        try:
            ws.freeze(rows=1)
            ws.format("A1:G1", {"textFormat": {"bold": True}})
        except Exception:
            pass
    return ws


def parse_date(s):
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d")
    except Exception:
        return None


def cleanup_old_rows(ws):
    """Delete rows older than RETENTION_DAYS. Returns surviving topics set."""
    values = ws.get_all_values()
    if len(values) <= 1:
        return set()
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    keep, removed = [values[0]], 0
    topics = set()
    for row in values[1:]:
        d = parse_date(row[0]) if row else None
        if d is not None and d < cutoff:
            removed += 1
            continue
        keep.append(row)
        if len(row) > 2:
            topics.add(row[2])
    if removed:
        ws.clear()
        ws.update(values=keep, range_name="A1")
        log(f"    cleaned {removed} rows older than {RETENTION_DAYS} days")
    return topics


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    log("== Trend Pulse v2 ==")
    log(f"creds: {'OK' if SERVICE_ACCOUNT_JSON else 'MISSING'} | "
        f"sheet_id: {'OK' if SHEET_ID else 'missing'} | "
        f"gemini: {'OK' if GEMINI_KEY else 'missing (fallback mode)'} | "
        f"youtube: {'OK' if YOUTUBE_KEY else 'missing (YouTube skipped)'}")

    ss = get_spreadsheet()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    used_topics = set()  # across categories today -> keeps categories distinct

    total = 0
    for category in CATEGORIES:
        log(f"\n[{category}]")
        ws = get_worksheet(ss, category)
        existing = cleanup_old_rows(ws)

        # Re-run safety: note today's rows so we don't duplicate them
        today_d = datetime.utcnow().date()
        todays = [r for r in ws.get_all_values()[1:]
                  if r and parse_date(r[0]) and parse_date(r[0]).date() == today_d]
        if todays:
            log(f"    already has {len(todays)} rows for {today}, topping up only")

        try:
            platform_items = COLLECTORS[category]()
        except Exception as e:
            log(f"    ! collector crashed: {e}")
            continue

        for p, items in platform_items.items():
            log(f"    {p}: {len(items)} candidates")

        already = existing | used_topics | {r[2] for r in todays if len(r) > 2}
        picks = pick_topics(category, platform_items, already)

        rows = []
        for it in picks:
            rows.append([today, it["platform"], it["topic"], it["popularity"],
                         it["description"], it["link"], it["source"]])
            used_topics.add(it["topic"])

        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            log(f"    ✅ appended {len(rows)} rows")
            total += len(rows)
        else:
            log("    ⚠ nothing new to add")

    log(f"\n== Done: {total} new rows ==")


if __name__ == "__main__":
    main()
