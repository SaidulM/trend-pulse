import os
import json
import sys
import requests
import gspread
import re
from google.oauth2.service_account import Credentials
from datetime import datetime
from collections import defaultdict
from xml.etree import ElementTree as ET

def log(msg):
    print(msg, flush=True)

COUNTRIES = ['India', 'USA', 'UK']
GEO = {'India': 'IN', 'USA': 'US', 'UK': 'GB'}
LIMIT_PER_CATEGORY = 5
TIMEOUT = 10

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
    url = f'https://trends.google.com/trending/rss?geo={geo}'
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {'ht': 'https://trends.google.com/trending/rss'}
        items = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            traffic = (item.findtext('ht:approx_traffic', namespaces=ns) or '').strip()
            if title:
                items.append({'topic': title, 'source': link, 'volume': traffic,
                              'platform': 'Google Trends'})
        log(f'  [Google Trends] {len(items)} items')
        return items
    except Exception as e:
        log(f'  [Google Trends] ERROR: {e}')
        return []

def fetch_google_news(geo):
    url = f'https://news.google.com/rss?hl=en-{geo}&gl={geo}&ceid={geo}:en'
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:30]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            if title:
                items.append({'topic': title, 'source': link, 'volume': '',
                              'platform': 'Google News'})
        log(f'  [Google News] {len(items)} items')
        return items
    except Exception as e:
        log(f'  [Google News] ERROR: {e}')
        return []

def fetch_hackernews():
    try:
        r = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json',
                         timeout=TIMEOUT)
        ids = r.json()[:15]
        items = []
        for i in ids:
            try:
                d = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{i}.json',
                                 timeout=TIMEOUT).json()
                items.append({
                    'topic': d.get('title', ''),
                    'source': d.get('url') or f"https://news.ycombinator.com/item?id={i}",
                    'volume': f"{d.get('score', 0)} points",
                    'platform': 'Hacker News'
                })
            except Exception:
                continue
        log(f'  [Hacker News] {len(items)} items')
        return items
    except Exception as e:
        log(f'  [Hacker News] ERROR: {e}')
        return []

def fetch_github_trending():
    try:
        r = requests.get('https://github.com/trending', timeout=TIMEOUT,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        items = []
        matches = re.findall(r'<h2 class="h3 lh-condensed">\s*<a href="([^"]+)"',
                             r.text, re.DOTALL)[:15]
        for m in matches:
            repo = m.strip('/')
            items.append({'topic': repo.replace('/', ' / '),
                          'source': f'https://github.com/{repo}',
                          'volume': '', 'platform': 'GitHub Trending'})
        log(f'  [GitHub Trending] {len(items)} items')
        return items
    except Exception as e:
        log(f'  [GitHub Trending] ERROR: {e}')
        return []

def fetch_product_hunt():
    try:
        r = requests.get('https://www.producthunt.com/feed', timeout=TIMEOUT,
                         headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:15]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            if title:
                items.append({'topic': title, 'source': link, 'volume': '',
                              'platform': 'Product Hunt'})
        log(f'  [Product Hunt] {len(items)} items')
        return items
    except Exception as e:
        log(f'  [Product Hunt] ERROR: {e}')
        return []

def get_client():
    log('  [Sheets] Connecting...')
    creds_dict = json.loads(os.environ['GOOGLE_SHEETS_CREDENTIALS'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    log('  [Sheets] Connected')
    return client

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
    log(f'▶ Fetching Google Trends ({geo})...')
    all_items.extend(fetch_google_trends(geo))
    log(f'▶ Fetching Google News ({geo})...')
    all_items.extend(fetch_google_news(geo))
    log(f'▶ Fetching Hacker News...')
    all_items.extend(fetch_hackernews())
    log(f'▶ Fetching GitHub Trending...')
    all_items.extend(fetch_github_trending())
    log(f'▶ Fetching Product Hunt...')
    all_items.extend(fetch_product_hunt())
    return all_items

def main():
    log('▶ Starting script')
    client = get_client()
    log('▶ Opening Google Sheet')
    ss = client.open('Trend Data')
    log('▶ Sheet opened')

    country = get_next_country(ss)
    log(f'▶ This run: {country}')

    ws = ss.worksheet(country)
    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    all_items = collect_all_sources(country)
    log(f'▶ Total raw items: {len(all_items)}')

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

    log(f'▶ Rows after filter: {len(rows)}')
    log(f'▶ Categories: {dict(cat_counter)}')

    if rows:
        ws.append_rows(rows, value_input_option='USER_ENTERED')
        log(f'✅ {country}: {len(rows)} rows added')
    else:
        log('⚠ No rows to add')

    save_last_country(ss, country)
    log('▶ Done')

if __name__ == '__main__':
    main()
