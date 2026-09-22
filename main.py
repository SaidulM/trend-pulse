import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from xml.etree import ElementTree as ET
from collections import defaultdict

COUNTRIES = ['India', 'USA', 'UK']
GEO = {'India': 'IN', 'USA': 'US', 'UK': 'GB'}

# ─── প্রতি ক্যাটাগরিতে সর্বোচ্চ কত টপিক ───
LIMIT_PER_CATEGORY = 10

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
    'Entertainment': ['movie', 'film', 'actor', 'actress', 'bollywood', 'hollywood',
                      'music', 'song', 'album', 'netflix', 'series', 'show', 'tv',
                      'celebrity', 'box office', 'trailer'],
    'Sports': ['cricket', 'football', 'soccer', 'nba', 'ipl', 'match', 'tournament',
               'olympic', 'fifa', 'world cup', 'player', 'team', 'score', 'league']
}

# ─── নতুন প্ল্যাটফর্ম যোগ করতে চাইলে এখানে একটি ফাংশন বানিয়ে
#     PLATFORMS ডিকশনারিতে নাম যোগ করলেই হবে ───

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
                items.append({'topic': title, 'source': link, 'volume': traffic})
        return items
    except Exception as e:
        print(f'Google Trends {geo}: {e}')
        return []

def fetch_google_news(geo):
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
                items.append({'topic': title, 'source': link, 'volume': ''})
        return items
    except Exception as e:
        print(f'Google News {geo}: {e}')
        return []

def fetch_reddit(sub):
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
                'volume': f"{d.get('score', 0)} upvotes"
            })
        return items
    except Exception as e:
        print(f'Reddit {sub}: {e}')
        return []

def fetch_youtube(region):
    instances = [
        'https://pipedapi.kavin.rocks',
        'https://api.piped.yt',
        'https://pipedapi.adminforge.de'
    ]
    for base in instances:
        try:
            r = requests.get(f'{base}/trending?region={region}', timeout=20)
            if r.status_code != 200:
                continue
            data = r.json()
            return [{
                'topic': v.get('title', ''),
                'source': f"https://youtube.com{v.get('url','')}",
                'volume': f"{v.get('views', 0)} views"
            } for v in data[:30]]
        except Exception as e:
            print(f'YouTube {base}: {e}')
            continue
    return []

# ─── PLATFORMS: এখানে নতুন প্ল্যাটফর্ম যোগ করুন ───
def get_platforms(country):
    geo = GEO[country]
    sub_map = {
        'India': ['india', 'IndianStockMarket', 'IndiaSpeaks'],
        'USA': ['all', 'technology', 'worldnews'],
        'UK': ['unitedkingdom', 'uknews', 'ukpolitics']
    }
    platforms = {
        'Google Trends': fetch_google_trends(geo),
        'Google News': fetch_google_news(geo),
        'YouTube': fetch_youtube(geo)
    }
    for sub in sub_map[country]:
        platforms[f'Reddit/{sub}'] = fetch_reddit(sub)
    return platforms

def get_client():
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
    config = ss.worksheet('Config')
    records = config.get_all_values()
    for i, row in enumerate(records, start=1):
        if len(row) >= 1 and row[0] == 'Last Country':
            config.update_cell(i, 2, country)
            return
    config.append_row(['Last Country', country])

def main():
    client = get_client()
    ss = client.open('Trend Data')

    country = get_next_country(ss)
    print(f'▶ This run: {country}')

    ws = ss.worksheet(country)
    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    platforms = get_platforms(country)

    rows = []
    seen = set()

    for platform_name, items in platforms.items():
        cat_counter = defaultdict(int)
        for item in items:
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
                country, platform_name, cat, topic,
                item['source'], item.get('volume', ''),
                estimate_competition(topic), '', '', today
            ])

    if rows:
        ws.append_rows(rows, value_input_option='USER_ENTERED')

    save_last_country(ss, country)
    print(f'✅ {country}: {len(rows)} rows added')

if __name__ == '__main__':
    main()
