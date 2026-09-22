import os
import json
import asyncio
import requests
import gspread
import re
from google.oauth2.service_account import Credentials
from datetime import datetime
from collections import defaultdict
from xml.etree import ElementTree as ET

# ─── trendspyg (Google Trends, category filter) ───
from trendspyg import download_google_trends_rss

# ─── trend-pulse (20+ sources, zero auth) ───
from trend_pulse.aggregator import TrendAggregator

# ─── TikTokApi ───
from TikTokApi import TikTokApi

# ─── Configuration ───
COUNTRIES = ['India', 'USA', 'UK']
GEO = {'India': 'IN', 'USA': 'US', 'UK': 'GB'}
LIMIT_PER_CATEGORY = 5  # প্রতিটি প্ল্যাটফর্মে প্রতি ক্যাটাগরিতে সর্বোচ্চ ৫টি

# ─── আপনার ক্যাটাগরি ───
CATEGORIES = {
    'AI': ['ai ', ' ai', 'artificial intelligence', 'chatgpt', 'gemini', 'openai',
           'machine learning', 'deep learning', 'llm', 'claude', 'copilot', 'neural'],
    'Tech': ['tech', 'software', 'app ', 'gadget', 'iphone', 'android', 'computer',
             'laptop', 'samsung', 'pixel', 'windows', 'apple', 'microsoft', 'chip',
             'semiconductor', 'gpu', 'nvidia', 'intel', 'amd'],
    'Business': ['business', 'stock', 'market', 'economy', 'finance', 'crypto',
                 'bitcoin', 'ethereum', 'startup', 'ipo', 'invest', 'trade',
                 'inflation', 'gdp', 'bank', 'rupee', 'dollar', 'nasdaq', 'sensex'],
    'Islamic': ['islam', 'muslim', 'quran', 'hadith', 'ramadan', 'prayer', 'hajj',
                'umrah', 'eid', 'mosque', 'halal', 'prophet', 'sunnah', 'dua'],
    'Health': ['health', 'covid', 'vaccine', 'fitness', 'diet', 'medicine', 'hospital',
               'cancer', 'diabetes', 'mental health', 'yoga', 'nutrition', 'doctor',
               'weight loss', 'gym', 'workout'],
    'World News': ['war', 'conflict', 'election', 'protest', 'crisis', 'attack',
                   'ukraine', 'gaza', 'israel', 'russia', 'china', 'iran', 'nato',
                   'president', 'minister', 'parliament', 'military'],
    'Best Products': ['best ', 'top ', 'review', 'buy', 'deal', 'offer', 'sale',
                      'cheap', 'price', 'discount', 'launch', 'compare'],
}

# ─── trendspyg ক্যাটাগরি ম্যাপিং ───
TRENDSPYG_CATEGORIES = ['technology', 'business', 'health', 'sports', 'entertainment', 'science']


def categorize(topic):
    """কীওয়ার্ড ম্যাচিং করে ক্যাটাগরি নির্ধারণ"""
    t = ' ' + topic.lower() + ' '
    for cat, kws in CATEGORIES.items():
        if any(kw in t for kw in kws):
            return cat
    return 'General'


def estimate_competition(topic):
    """কীওয়ার্ডের দৈর্ঘ্য দিয়ে competition অনুমান"""
    words = len(topic.split())
    if words <= 2:
        return 'High'
    elif words <= 4:
        return 'Medium'
    return 'Low'


def fetch_google_trends_categorized(geo):
    """trendspyg দিয়ে ক্যাটাগরি-ভিত্তিক Google Trends ডেটা"""
    all_items = []
    for cat_key in TRENDSPYG_CATEGORIES:
        try:
            env = download_google_trends_rss(geo=geo, normalize=True, category=cat_key)
            for trend in env.get('trends', []):
                all_items.append({
                    'topic': trend.get('keyword', ''),
                    'source': trend.get('news', [{}])[0].get('url', '') if trend.get('news') else '',
                    'volume': f"{trend.get('volume_min', 0):,}+",
                    'platform': f'Google Trends ({cat_key})'
                })
        except Exception as e:
            print(f'  trendspyg {cat_key} {geo}: {e}')
    return all_items


async def fetch_trend_pulse(geo):
    """trend-pulse দিয়ে ২০+ সোর্স থেকে ডেটা"""
    try:
        agg = TrendAggregator()
        result = await agg.trending(geo=geo, count=50)
        items = []
        for item in result.get('merged_top', []):
            items.append({
                'topic': item.get('keyword', ''),
                'source': item.get('url', ''),
                'volume': item.get('score', ''),
                'platform': item.get('source_name', 'TrendPulse')
            })
        return items
    except Exception as e:
        print(f'  trend-pulse {geo}: {e}')
        return []


async def fetch_tiktok_trending(count=20):
    """TikTokApi দিয়ে ট্রেন্ডিং ভিডিও"""
    try:
        async with TikTokApi() as api:
            await api.create_sessions(headless=True, num_sessions=1, sleep_after=3)
            items = []
            async for video in api.trending.videos(count=count):
                items.append({
                    'topic': video.as_dict.get('desc', ''),
                    'source': f"https://www.tiktok.com/@{video.author.username}/video/{video.id}",
                    'volume': f"{video.stats.get('playCount', 0):,} views",
                    'platform': 'TikTok'
                })
            return items
    except Exception as e:
        print(f'  TikTok: {e}')
        return []


def fetch_reddit(sub):
    """Reddit পাবলিক JSON (কোনো key লাগে না)"""
    url = f'https://www.reddit.com/r/{sub}/hot.json?limit=30'
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'TrendBot/1.0'})
        r.raise_for_status()
        data = r.json()
        items = []
        for c in data.get('data', {}).get('children', []):
            d = c['data']
            items.append({
                'topic': d.get('title', ''),
                'source': f"https://reddit.com{d.get('permalink','')}",
                'volume': f"{d.get('score', 0)} upvotes",
                'platform': f'Reddit/{sub}'
            })
        return items
    except Exception as e:
        print(f'  Reddit {sub}: {e}')
        return []


def fetch_github_trending():
    """GitHub Trending (স্ক্র্যাপ, কোনো key লাগে না)"""
    try:
        r = requests.get('https://github.com/trending', timeout=30,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        items = []
        for match in re.findall(r'<h2 class="h3 lh-condensed">\s*<a href="([^"]+)"[^>]*>.*?</h2>',
                                r.text, re.DOTALL)[:15]:
            repo = match.strip('/')
            items.append({
                'topic': repo.replace('/', ' / '),
                'source': f'https://github.com/{repo}',
                'volume': '',
                'platform': 'GitHub Trending'
            })
        return items
    except Exception as e:
        print(f'  GitHub Trending: {e}')
        return []


def fetch_product_hunt():
    """Product Hunt RSS (ফ্রি, কোনো key লাগে না)"""
    try:
        r = requests.get('https://www.producthunt.com/feed', timeout=30,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:15]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            if title:
                items.append({
                    'topic': title,
                    'source': link,
                    'volume': '',
                    'platform': 'Product Hunt'
                })
        return items
    except Exception as e:
        print(f'  Product Hunt: {e}')
        return []


def fetch_hackernews():
    """Hacker News ফায়ারবেস API (কোনো key লাগে না)"""
    try:
        r = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=30)
        ids = r.json()[:20]
        items = []
        for i in ids:
            d = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{i}.json', timeout=15).json()
            items.append({
                'topic': d.get('title', ''),
                'source': d.get('url') or f"https://news.ycombinator.com/item?id={i}",
                'volume': f"{d.get('score', 0)} points",
                'platform': 'Hacker News'
            })
        return items
    except Exception as e:
        print(f'  HN: {e}')
        return []


def get_client():
    """Google Sheets ক্লায়েন্ট"""
    creds_dict = json.loads(os.environ['GOOGLE_SHEETS_CREDENTIALS'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def get_next_country(ss):
    """Rotation: India → USA → UK → India ..."""
    config = ss.worksheet('Config')
    records = config.get_all_values()
    last = 'UK'
    for row in records:
        if len(row) >= 2 and row[0] == 'Last Country':
            last = row[1] or 'UK'
    idx = COUNTRIES.index(last) if last in COUNTRIES else -1
    return COUNTRIES[(idx + 1) % len(COUNTRIES)]


def save_last_country(ss, country):
    """Config ট্যাবে last country সেভ"""
    config = ss.worksheet('Config')
    records = config.get_all_values()
    for i, row in enumerate(records, start=1):
        if len(row) >= 1 and row[0] == 'Last Country':
            config.update_cell(i, 2, country)
            return
    config.append_row(['Last Country', country])


def collect_all_sources(country):
    """একটি দেশের জন্য সব সোর্স থেকে ডেটা সংগ্রহ"""
    geo = GEO[country]
    all_items = []

    # ১. Google Trends (trendspyg — ক্যাটাগরি ফিল্টার সহ)
    all_items.extend(fetch_google_trends_categorized(geo))

    # ২. trend-pulse (২০+ সোর্স একসাথে)
    try:
        pulse_items = asyncio.run(fetch_trend_pulse(geo))
        all_items.extend(pulse_items)
    except Exception as e:
        print(f'trend-pulse error: {e}')

    # ৩. TikTok
    try:
        tiktok_items = asyncio.run(fetch_tiktok_trending())
        all_items.extend(tiktok_items)
    except Exception as e:
        print(f'TikTok error: {e}')

    # ৪. Reddit (একাধিক সাবরেডিট)
    sub_map = {
        'India': ['india', 'IndianStockMarket', 'IndiaSpeaks'],
        'USA': ['all', 'technology', 'worldnews'],
        'UK': ['unitedkingdom', 'uknews', 'ukpolitics']
    }
    for sub in sub_map[country]:
        all_items.extend(fetch_reddit(sub))

    # ৫. Hacker News (শুধু USA-তে, ডুপ্লিকেট এড়াতে)
    if country == 'USA':
        all_items.extend(fetch_hackernews())

    # ৬. GitHub Trending (সব দেশে)
    all_items.extend(fetch_github_trending())

    # ৭. Product Hunt (সব দেশে)
    all_items.extend(fetch_product_hunt())

    return all_items


def main():
    client = get_client()
    ss = client.open('Trend Data')

    country = get_next_country(ss)
    print(f'▶ This run: {country}')

    ws = ss.worksheet(country)
    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    # ─── সব সোর্স থেকে ডেটা ───
    all_items = collect_all_sources(country)

    # ─── ডুপ্লিকেট সরানো + ক্যাটাগরি অনুযায়ী গ্রুপ ───
    seen = set()
    rows = []
    cat_counter = defaultdict(int)

    for item in all_items:
        topic = item['topic'].strip()
        if not topic:
            continue
        key = topic.lower()
        if key in seen:
            continue

        cat = categorize(topic)
        if cat_counter[cat] >= LIMIT_PER_CATEGORY:
            continue

        seen.add(key)
        cat_counter[cat] += 1

        rows.append([
            country,
            item.get('platform', 'Unknown'),
            cat,
            topic,
            item.get('source', ''),
            item.get('volume', ''),
            estimate_competition(topic),
            '',  # CPC (ফ্রিতে পাওয়া যায় না)
            '',  # Rank
            today
        ])

    # ─── শিটে লেখা ───
    if rows:
        ws.append_rows(rows, value_input_option='USER_ENTERED')

    save_last_country(ss, country)

    print(f'✅ {country}: {len(rows)} rows added')
    print(f'  Categories: {dict(cat_counter)}')


if __name__ == '__main__':
    main()
