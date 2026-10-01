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

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest",
                 "gemini-2.0-flash-lite", "gemini-1.5-flash"]

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
# Google Search (Autocomplete) — REAL queries people are typing in the US
# ----------------------------------------------------------------------------
def fetch_google_searches(seeds, limit=35, group=""):
    """Live, high-interest search phrases from Google's free Autocomplete API.
    This is exactly 'what people are searching for' — ideal article topics."""
    items, seen = [], set()
    for seed in seeds:
        url = ("https://suggestqueries.google.com/complete/search"
               f"?client=firefox&hl=en&gl=us&q={quote(seed)}")
        r = safe_get(url)
        if not r:
            continue
        try:
            suggestions = json.loads(r.text)[1]
        except Exception:
            continue
        for rank, s in enumerate(suggestions[:8]):
            s = s.strip()
            key = s.lower()
            if not s or key == seed.lower() or key in seen or UNSAFE.search(s):
                continue
            seen.add(key)
            it = mk(s, "Google Search",
                    "Top US search" if rank < 3 else "US search query",
                    f'People in the US are actively searching: "{s}"',
                    f"https://www.google.com/search?q={quote(s)}",
                    "Google Autocomplete (US)")
            if group:
                it["group"] = group
            items.append(it)
        if len(items) >= limit:
            break
        time.sleep(0.3)
    return items


# সিড-কিওয়ার্ড: এগুলো থেকে Google নিজেই দেখাবে মানুষ এখন ঠিক কী খুঁজছে।
# প্রতিদিন সিড-লিস্ট ঘুরিয়ে নেওয়া হয়, তাই প্রতিদিন নতুন নতুন টপিক আসে।
AI_SEEDS = [
    "how to use ai for", "best ai tools for", "how does chatgpt",
    "can ai help me", "best free ai", "how to make money with ai",
    "ai for beginners", "what is the best ai app for", "how to learn ai",
    "is chatgpt good for",
]
GADGET_SEEDS = [
    "best laptop for", "best phone for", "iphone vs", "best smartwatch for",
    "best wireless earbuds for", "how to fix my phone", "best budget gadgets",
    "best tablet for", "is it worth buying", "best home security camera",
]
ISLAMIC_SEEDS = [
    "dua for", "how to pray", "quran verses about", "what does islam say about",
    "islamic meaning of", "how to make wudu", "surah for", "prophet muhammad",
    "is it haram to", "ramadan", "how to perform", "islamic dream meaning of",
    "benefits of reading surah", "dhikr for", "sunnah of",
]


def rotate(lst, n):
    """Rotate a list so different seeds lead on different days (variety)."""
    n = n % len(lst)
    return lst[n:] + lst[:n]


def clean(items):
    """Drop junk/homepage/generic-thread items from any platform list."""
    return [it for it in items if it["topic"] and not is_junk(it["topic"])]


def relevant(items, pattern):
    """Keep only items matching the category pattern."""
    return [it for it in items
            if pattern.search(it["topic"] + " " + it["description"])]

TECH_WORDS = re.compile(
    r"\b(ai|iphone|android|google|apple|microsoft|tesla|spacex|nvidia|intel|amd|"
    r"openai|chatgpt|gemini|robot|tech|app|software|chip|crypto|bitcoin|gpu|"
    r"samsung|meta|amazon|playstation|xbox|nintendo|cyber|hack|update|launch|"
    r"galaxy|pixel|windows|ios|macbook|laptop|phone|gaming|game)\b", re.I)

ISLAM_WORDS = re.compile(
    r"\b(islam|islamic|muslim|quran|koran|ramadan|eid|hajj|umrah|mosque|masjid|"
    r"halal|dua|surah|allah|prophet|muhammad|mecca|makkah|madinah)\b", re.I)


def collect_technology():
    day = datetime.now(timezone.utc).timetuple().tm_yday
    data = {}
    # Google Search: ঠিক দুই গ্রুপ — একটি AI, একটি Gadget (রিয়েল US সার্চ কোয়েরি)
    ai = fetch_google_searches(rotate(AI_SEEDS, day)[:5], group="AI")
    gadget = fetch_google_searches(rotate(GADGET_SEEDS, day)[:5], group="Gadget")
    data["Google Search"] = clean(ai) + clean(gadget)
    data["YouTube"] = clean(fetch_youtube_most_popular(video_category_id=28))
    data["Reddit"] = clean(fetch_reddit("technology"))
    data["Google News"] = clean(fetch_google_news(topic="TECHNOLOGY"))
    bing = clean(fetch_bing_news("technology news"))
    data["Bing News"] = relevant(bing, TECH_WORDS) or bing
    quora = clean(fetch_quora("technology AI gadgets smartphone"))
    data["Quora"] = relevant(quora, TECH_WORDS) or quora
    return data


def collect_islamic():
    day = datetime.now(timezone.utc).timetuple().tm_yday
    data = {}
    data["Google Search"] = clean(
        fetch_google_searches(rotate(ISLAMIC_SEEDS, day)[:7]))
    yt = clean(fetch_youtube_search("islamic lecture OR islam OR quran recitation"))
    data["YouTube"] = relevant(yt, ISLAM_WORDS) or yt
    data["Reddit"] = clean(fetch_reddit("islam"))
    # News/Bing/Quora: ক্যাটেগরির বাইরের টপিক একদম ঢুকবে না (strict filter)
    data["Google News"] = relevant(clean(fetch_google_news(
        query="islam OR muslim OR quran OR ramadan OR hajj")), ISLAM_WORDS)
    data["Bing News"] = relevant(clean(fetch_bing_news("islam muslim quran")),
                                 ISLAM_WORDS)
    data["Quora"] = relevant(clean(fetch_quora("islam quran dua")), ISLAM_WORDS)
    return data


def collect_trending():
    data = {}
    data["Google Trends"] = clean(fetch_google_trends())
    data["YouTube"] = clean(fetch_youtube_most_popular())
    data["Reddit"] = clean(fetch_reddit("popular"))
    data["Google News"] = clean(fetch_google_news(topic="WORLD"))
    data["Bing News"] = clean(fetch_bing_news("trending viral news US"))
    data["Quora"] = clean(fetch_quora("trending questions"))
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
        log("    ! No Gemini key — fallback selection")
        return None
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0.2},
    }
    for model in GEMINI_MODELS:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={GEMINI_KEY}")
        for attempt in range(3):
            try:
                r = requests.post(url, json=body, timeout=90)
            except Exception as e:
                log(f"    ! Gemini {model} network error: {str(e)[:120]}")
                break
            if r.status_code == 429:
                log(f"    Gemini {model}: rate-limited (429), waiting 25s "
                    f"(attempt {attempt + 1}/3)")
                time.sleep(25)
                continue
            if r.status_code == 404:
                log(f"    Gemini {model}: not available (404), trying next model")
                break
            if r.status_code != 200:
                log(f"    ! Gemini {model}: HTTP {r.status_code}: {r.text[:150]}")
                break
            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "",
                              text.strip(), flags=re.M).strip()
                return json.loads(text)
            except Exception as e:
                log(f"    ! Gemini {model} bad response: {str(e)[:120]}")
                break
    log("    ! ALL Gemini models failed — using deterministic fallback")
    return None


def select_with_gemini(category, platform_items, already_used):
    """Ask Gemini to pick the best TOPICS_PER_PLATFORM per platform and add an
    article angle for each. Returns {platform: [(index, angle), ...]} or None."""
    catalog = {}
    for platform, items in platform_items.items():
        catalog[platform] = [
            {"i": i, "topic": it["topic"], "popularity": it["popularity"],
             **({"group": it["group"]} if it.get("group") else {})}
            for i, it in enumerate(items[:15])
        ]
    prompt = (
        "You are an expert SEO content strategist curating daily topics for a "
        "blogger who writes helpful articles for a US audience.\n"
        f"Category: {category}\n"
        f"Pick EXACTLY {TOPICS_PER_PLATFORM} items per platform (fewer only if "
        "the platform has fewer candidates). Selection rules, in priority order:\n"
        "1. PREFER topics with clear informational search intent — things people "
        "actively search to learn, understand, solve a problem, or decide "
        "something (how-to, what-is, best-X, guides). These make great articles.\n"
        "2. Prefer higher popularity numbers (searches/views/upvotes) when shown.\n"
        f"3. The topic must genuinely belong to '{category}' "
        "(Islamic = only Islam-related; Technology = only tech-related; "
        "'Trending (US)' = whatever Americans are hottest on right now).\n"
        "4. AVOID low-value picks: one-line gossip, pure clickbait, website "
        "homepages, or anything a blogger could not write a useful article about.\n"
        "5. NEVER pick a topic identical or nearly identical to anything in "
        "ALREADY_USED, and no near-duplicates across platforms in this selection.\n"
        "6. If a platform's candidates carry a 'group' field, pick exactly ONE "
        "item from EACH distinct group (e.g. one 'AI' topic and one 'Gadget' "
        "topic for Google Search in Technology).\n"
        "For every pick also write 'angle': ONE short sentence (max 18 words) "
        "suggesting the article angle a blogger should take.\n"
        'Return ONLY JSON: {"<platform>": [{"i": 0, "angle": "..."}, '
        '{"i": 3, "angle": "..."}], ...}\n\n'
        f"CANDIDATES:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
        f"ALREADY_USED (recent sheet topics + other categories today):\n"
        f"{json.dumps(sorted(already_used)[:300], ensure_ascii=False)}"
    )
    result = gemini_generate(prompt)
    if not isinstance(result, dict):
        return None
    out = {}
    for platform, picks in result.items():
        if platform not in platform_items or not isinstance(picks, list):
            continue
        valid = []
        for p in picks:
            if isinstance(p, dict) and isinstance(p.get("i"), int):
                i, angle = p["i"], str(p.get("angle") or "")
            elif isinstance(p, int):
                i, angle = p, ""
            else:
                continue
            if 0 <= i < len(platform_items[platform]):
                valid.append((i, angle.strip()))
        out[platform] = valid[:TOPICS_PER_PLATFORM]
    return out


JUNK = re.compile(
    r"(free[- ]?talk|daily thread|weekly thread|megathread|open thread|"
    r"verse of the day|discussion thread|moronic monday|"
    r"latest technology news|startup and technology news|"
    r"the latest in technology|today'?s latest|"
    r"breaking news, (analysis|headlines)|^\s*viral trends\s*$|"
    r"^[\w .']{2,30}news\s*[-|–]\s*[\w .']+$|"
    r"^[\w ,&.']{2,35}[-|–]\s*(the )?(new york times|nytimes|cnbc|cnn|bbc|wired|"
    r"reuters|forbes|guardian|wsj|bloomberg|verge|techcrunch)[\w -]{0,10}$|"
    r"^google news\b|^(technology|tech|world|islam)\s*[-|–]|[-|–]\s*latest\s*$|"
    r"\|\s*(reuters|cnn|bbc|techcrunch|the verge)\s*$)", re.I)


def is_junk(topic):
    """Generic threads / website homepages — useless as article topics."""
    return bool(JUNK.search(topic or ""))


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
        for platform, chosen in selection.items():
            for i, angle in chosen:
                it = dict(platform_items[platform][i])
                it["_key"] = platform
                if normalize(it["topic"]) not in used_norm and it["topic"]:
                    if angle:
                        base = it["description"]
                        it["description"] = (f"✍️ Angle: {angle}" +
                                             (f" | {base}" if base else ""))[:250]
                    picks.append(it)
                    used_norm.add(normalize(it["topic"]))
    # Fill any platform that still has < TOPICS_PER_PLATFORM picks.
    # Group-aware: if items carry a group (AI/Gadget), take one per group.
    picked_by_key, groups_done = {}, {}
    for p in picks:
        k = p.get("_key") or p["platform"]
        picked_by_key[k] = picked_by_key.get(k, 0) + 1
        if p.get("group"):
            groups_done.setdefault(k, set()).add(p["group"])
    for platform, items in platform_items.items():
        have = picked_by_key.get(platform, 0)
        done = groups_done.setdefault(platform, set())
        for it in items:
            if have >= TOPICS_PER_PLATFORM:
                break
            g = it.get("group")
            if g and g in done:
                continue
            n = normalize(it["topic"])
            if it["topic"] and n not in used_norm and not is_junk(it["topic"]):
                picks.append(it)
                used_norm.add(n)
                have += 1
                if g:
                    done.add(g)
    return [{k: v for k, v in p.items() if k not in ("_key", "group")}
            for p in picks]


# ----------------------------------------------------------------------------
# Google Sheets
# ----------------------------------------------------------------------------
def get_spreadsheet():
    if not SERVICE_ACCOUNT_JSON:
        sys.exit("ERROR: service-account JSON secret not found. Set one of: "
                 "GOOGLE_SHEETS_CREDENTIALS / GOOGLE_CREDENTIALS / GCP_SERVICE_ACCOUNT "
                 "/ SERVICE_ACCOUNT_JSON / GOOGLE_SERVICE_ACCOUNT_JSON")
    try:
        info = json.loads(SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as e:
        sys.exit("ERROR: the service-account secret is NOT valid JSON "
                 f"({e}). Re-paste the FULL content of the downloaded .json "
                 "key file into the GitHub secret (including { and }).")

    # Auto-repair common paste problems in private_key
    pk = info.get("private_key", "")
    if "\\n" in pk and "\n" not in pk.replace("\\n", ""):
        info["private_key"] = pk.replace("\\n", "\n")
    missing = [k for k in ("client_email", "private_key", "project_id")
               if not info.get(k)]
    if missing:
        sys.exit(f"ERROR: service-account JSON is missing fields: {missing}. "
                 "The secret is probably a partial paste — re-paste the whole file.")

    email = info.get("client_email", "")
    masked = email[:6] + "***" + email[email.find("@"):] if "@" in email else "?"
    log(f"service account: {masked}")

    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"])
    client = gspread.authorize(creds)
    try:
        if SHEET_ID:
            return client.open_by_key(SHEET_ID)
        log("WARN: no SHEET_ID secret found, trying to open by name 'Trend Data'")
        return client.open("Trend Data")
    except Exception as e:
        err = str(e)
        if "invalid_grant" in err or "Invalid JWT" in err:
            sys.exit(
                "ERROR: Google rejected the service-account key (invalid_grant / "
                "Invalid JWT Signature).\n"
                "FIX (Bangla): এই key টা আর বৈধ নেই। নতুন key বানাতে হবে:\n"
                "  1) console.cloud.google.com → IAM & Admin → Service Accounts\n"
                "  2) service account টা খোলো → KEYS ট্যাব → ADD KEY → "
                "Create new key → JSON → Download\n"
                "  3) ডাউনলোড হওয়া .json ফাইলের পুরো লেখাটা কপি করে GitHub → "
                "Settings → Secrets → GOOGLE_SERVICE_ACCOUNT_JSON সিক্রেটে "
                "Update করে পেস্ট করো\n"
                "  4) Google Sheet-টা service account-এর email-এর সাথে Editor "
                "হিসেবে Share করা আছে কি না দেখো\n"
                f"Original error: {err[:300]}")
        if "PERMISSION_DENIED" in err or "403" in err:
            sys.exit(
                "ERROR: the service account has NO access to this spreadsheet.\n"
                f"FIX: Google Sheet → Share → add {email} as Editor.\n"
                f"Original error: {err[:300]}")
        if "404" in err or "not found" in err.lower():
            sys.exit(
                "ERROR: spreadsheet not found — the SHEET_ID secret looks wrong.\n"
                "FIX: copy the ID from the sheet URL: "
                "docs.google.com/spreadsheets/d/<THIS_PART>/edit\n"
                f"Original error: {err[:300]}")
        raise


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


def prepare_sheet(ws):
    """Delete rows older than RETENTION_DAYS AND today's rows (a re-run on the
    same day REPLACES today's picks instead of piling up duplicates).
    Returns the set of topics from previous days (for dedupe)."""
    values = ws.get_all_values()
    if len(values) <= 1:
        return set()
    now = datetime.now(timezone.utc)
    cutoff = now.replace(tzinfo=None) - timedelta(days=RETENTION_DAYS)
    today_d = now.date()
    keep, removed_old, removed_today = [values[0]], 0, 0
    topics = set()
    for row in values[1:]:
        d = parse_date(row[0]) if row else None
        if d is not None and d < cutoff:
            removed_old += 1
            continue
        if d is not None and d.date() == today_d:
            removed_today += 1
            continue
        keep.append(row)
        if len(row) > 2:
            topics.add(row[2])
    if removed_old or removed_today:
        ws.clear()
        ws.update(values=keep, range_name="A1")
        if removed_old:
            log(f"    cleaned {removed_old} rows older than {RETENTION_DAYS} days")
        if removed_today:
            log(f"    replacing {removed_today} rows from today with fresh picks")
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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used_topics = set()  # across categories today -> keeps categories distinct

    total = 0
    for category in CATEGORIES:
        log(f"\n[{category}]")
        ws = get_worksheet(ss, category)
        existing = prepare_sheet(ws)  # removes expired + today's rows

        try:
            platform_items = COLLECTORS[category]()
        except Exception as e:
            log(f"    ! collector crashed: {e}")
            continue

        for p, items in platform_items.items():
            log(f"    {p}: {len(items)} candidates")

        already = existing | used_topics
        picks = pick_topics(category, platform_items, already)

        rows = []
        for it in picks:
            rows.append([today, it["platform"], it["topic"], it["popularity"],
                         it["description"], it["link"], it["source"]])
            used_topics.add(it["topic"])
            log(f"    + [{it['platform']}] {it['topic'][:70]}"
                f"{' | ' + it['popularity'] if it['popularity'] else ''}")

        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            log(f"    ✅ wrote {len(rows)} rows")
            total += len(rows)
        else:
            log("    ⚠ nothing new to add")

    log(f"\n== Done: {total} rows written ==")


if __name__ == "__main__":
    main()
