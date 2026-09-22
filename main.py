import os
import json
import requests
import gspread
import re
from google.oauth2.service_account import Credentials
from datetime import datetime
from collections import defaultdict
from xml.etree import ElementTree as ET

COUNTRIES = ['India', 'USA', 'UK']
GEO = {'India': 'IN', 'USA': 'US', 'UK': 'GB'}
LIMIT_PER_CATEGORY = 5

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


def categorize(topic):
    t = ' ' + topic.lower() + ' '
    for cat, kws in CATEGORIES.items():
        if any(kw in t for kw in kws):
            return cat
    return 'General'


def estimate_competition(topic):
    words = len(topic.split())
    if words <= 2:
        return 'High'
    elif words <= 4:
        return 'Medium'
    return 'Low'


def fetch_google_trends(geo):
    """Google Trends RSS — প্রমাণিত কাজ করে"""
    url = f'https://trends.google.com/trending/rss?geo={geo}'
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {'ht': 'https://trends.google.com/trending/rss'}
        items = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            traffic = (item.findtext('ht:approx_traffic', namespaces=ns) or '').strip()
            if title:
                items.append({
                    'topic': title, 'source': link, 'volume': traffic,
                    'platform': 'Google Trends'
                })
        print(f'  [Google Trends] {len(items)} items')
        return items
    except Exception as e:
        print(f'  [Google Trends] ERROR: {e}')
        return []


def fetch_google_news(geo):
    """Google News RSS — প্রমাণিত কাজ করে"""
    url = f'https://news.google.com/rss?hl=en-{geo}&gl={geo}&ceid={geo}:en'
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:30]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            if title:
                items.append({
                    'topic': title, 'source': link, 'volume': '',
                    'platform': 'Google News'
                })
        print(f'  [Google News] {len(items)} items')
        return items
    except Exception as e:
        print(f'  [Google News] ERROR: {e}')
        return []


def fetch_reddit(sub):
    """Reddit পাবলিক JSON"""
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
        print(f'  [Reddit/{sub}] {len(items)} items')
        return items
    except Exception as e:
        print(f'  [Reddit/{sub}] ERROR: {e}')
        return []


def fetch_hackernews():
    """Hacker News Firebase API"""
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
        print(f'  [Hacker News] {len(items)} items')
        return items
    except Exception as e:
        print(f'  [Hacker News] ERROR: {e}')
        return []


def fetch_github_trending():
    """GitHub Trending স্ক্র্যাপ"""
    try:
        r = requests.get('https://github.com/trending', timeout=30,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        items = []
        matches = re.findall(r'<h2 class="h3 lh-condensed">\s*<a href="([^"]+)"',
                             r.text, re.DOTALL)[:15]
        for m in matches:
            repo = m.strip('/')
            items.append({
                'topic': repo.replace('/', ' / '),
                'source': f'https://github.com/{repo}',
                'volume': '',
                'platform': 'GitHub Trending'
            })
        print(f'  [GitHub Trending] {len(items)} items')
        return items
    except Exception as e:
        print(f'  [GitHub Trending] ERROR: {e}')
        return []


def fetch_product_hunt():
    """Product Hunt RSS"""
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
                    'topic': title, 'source': link, 'volume': '',
                    'platform': 'Product Hunt'
                })
        print(f'  [Product Hunt] {len(items)} items')
        return items
    except Exception as e:
        print(f'  [Product Hunt] ERROR: {e}')
        return []


def get_client():
    creds_dict = json.loads(os.environ['GOOGLE_SHEETS_CREDENTIALS'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def get_next_country(ss):
    config = ss.worksheet('Config')
    records = config.get_all_values()
    last = 'UK'
    for row in records:
        if len(row) >= 2 and row[0] == 'Last Country':
            last = row[1] or 'UK'
    idx = COUNTRIES.index(last) if last in COUNTRIES else -1
    return COUNTRIES[(idx + 1) % len(COUNTRIES)]


def save_last_country(ss, country):
    config = ss.worksheet('Config')
    records = config.get_all_values()
    for i, row in enumerate(records, start=1):
        if len(row) >= 1 and row[0] == 'Last Country':
            config.update_cell(i, 2, country)
            return
    config.append_row(['Last Country', country])


def collect_all_sources(country):
    geo = GEO[country]
    all_items = []

    all_items.extend(fetch_google_trends(geo))
    all_items.extend(fetch_google_news(geo))

    sub_map = {
        'India': ['india', 'IndianStockMarket', 'IndiaSpeaks'],
        'USA': ['all', 'technology', 'worldnews'],
        'UK': ['unitedkingdom', 'uknews', 'ukpolitics']
    }
    for sub in sub_map[country]:
        all_items.extend(fetch_reddit(sub))

    if country == 'USA':
        all_items.extend(fetch_hackernews())

    all_items.extend(fetch_github_trending())
    all_items.extend(fetch_product_hunt())

    return all_items


def main():
    print('▶ Starting...')
    client = get_client()
    ss = client.open('Trend Data')

    country = get_next_country(ss)
    print(f'▶ This run: {country}')

    ws = ss.worksheet(country)
    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    all_items = collect_all_sources(country)
    print(f'▶ Total raw items: {len(all_items)}')

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
            '', '', today
        ])

    print(f'▶ Rows after filter: {len(rows)}')
    print(f'▶ Categories: {dict(cat_counter)}')

    if rows:
        ws.append_rows(rows, value_input_option='USER_ENTERED')
        print(f'✅ {country}: {len(rows)} rows added')
    else:
        print('⚠ No rows to add')


if __name__ == '__main__':
    main()
