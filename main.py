import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from xml.etree import ElementTree as ET

COUNTRIES = {'India': 'IN', 'USA': 'US', 'UK': 'GB'}

CATEGORIES = {
    'AI': ['ai ', ' ai', 'artificial intelligence', 'chatgpt', 'gemini', 'openai',
           'machine learning', 'deep learning', 'llm', 'claude', 'copilot', 'neural'],
    'Tech': ['tech', 'software', 'app ', 'gadget', 'iphone', 'android', 'computer',
             'laptop', 'samsung', 'google pixel', 'windows', 'apple', 'microsoft',
             'chip', 'semiconductor', 'gpu', 'nvidia', 'intel', 'amd', 'startup tech'],
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
                      'cheap', 'price', 'discount', 'launch', 'new launch', 'compare'],
    'Entertainment': ['movie', 'film', 'actor', 'actress', 'bollywood', 'hollywood',
                      'music', 'song', 'album', 'netflix', 'series', 'show', 'tv',
                      'celebrity', 'box office', 'trailer'],
    'Sports': ['cricket', 'football', 'soccer', 'nba', 'ipl', 'match', 'tournament',
               'olympic', 'fifa', 'world cup', 'player', 'team', 'score', 'league']
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
    else:
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
            pub = (item.findtext('pubDate') or '').strip()
            traffic = (item.findtext('ht:approx_traffic', namespaces=ns) or '').strip()
            if title:
                items.append({
                    'topic': title,
                    'source': link,
                    'date': pub,
                    'volume': traffic
                })
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
        for item in root.findall('.//item')[:25]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            if title:
                items.append({'topic': title, 'source': link, 'date': pub, 'volume': ''})
        return items
    except Exception as e:
        print(f'Google News {geo}: {e}')
        return []

def fetch_reddit(sub):
    url = f'https://www.reddit.com/r/{sub}/hot.json?limit=25'
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'TrendBot/1.0'})
        r.raise_for_status()
        data = r.json()
        items = []
        for c in data.get('data', {}).get('children', []):
            d = c['data']
            score = d.get('score', 0)
            items.append({
                'topic': d.get('title', ''),
                'source': f"https://reddit.com{d.get('permalink','')}",
                'date': datetime.utcfromtimestamp(d.get('created_utc', 0)).isoformat(),
                'volume': f'{score} upvotes'
            })
        return items
    except Exception as e:
        print(f'Reddit {sub}: {e}')
        return []

def fetch_piped_trending(region):
    """YouTube trending via Piped (free, no key)"""
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
            items = []
            for v in data[:20]:
                items.append({
                    'topic': v.get('title', ''),
                    'source': f"https://youtube.com/watch?v={v.get('url','').replace('/watch?v=','')}",
                    'date': datetime.utcfromtimestamp(v.get('uploadedDate', 0) if isinstance(v.get('uploadedDate'), int) else 0).isoformat(),
                    'volume': f"{v.get('views', 0)} views"
                })
            return items
        except Exception as e:
            print(f'Piped {base}: {e}')
            continue
    return []

def fetch_hackernews():
    try:
        r = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=30)
        ids = r.json()[:20]
        items = []
        for i in ids:
            d = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{i}.json', timeout=15).json()
            items.append({
                'topic': d.get('title', ''),
                'source': d.get('url') or f"https://news.ycombinator.com/item?id={i}",
                'date': datetime.utcfromtimestamp(d.get('time', 0)).isoformat(),
                'volume': f"{d.get('score', 0)} points"
            })
        return items
    except Exception as e:
        print(f'HN: {e}')
        return []

def get_client():
    creds_dict = json.loads(os.environ['GOOGLE_SHEETS_CREDENTIALS'])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def main():
    client = get_client()
    ss = client.open('Trend Data')
    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    subreddits = {
        'India': ['india', 'IndianStockMarket', 'IndiaSpeaks', 'bollywood'],
        'USA': ['all', 'technology', 'business', 'worldnews'],
        'UK': ['unitedkingdom', 'uknews', 'ukpolitics']
    }

    for country, geo in COUNTRIES.items():
        ws = ss.worksheet(country)
        rows = []

        # Google Trends
        for item in fetch_google_trends(geo):
            cat = categorize(item['topic'])
            rows.append([country, 'Google Trends', cat, item['topic'],
                         item['source'], item['volume'],
                         estimate_competition(item['topic']), '', '', today])

        # Google News
        for item in fetch_google_news(geo):
            cat = categorize(item['topic'])
            rows.append([country, 'Google News', cat, item['topic'],
                         item['source'], item['volume'],
                         estimate_competition(item['topic']), '', '', today])

        # Reddit (multiple subreddits)
        for sub in subreddits[country]:
            for item in fetch_reddit(sub):
                cat = categorize(item['topic'])
                rows.append([country, f'Reddit/{sub}', cat, item['topic'],
                             item['source'], item['volume'],
                             estimate_competition(item['topic']), '', '', today])

        # YouTube trending
        for item in fetch_piped_trending(geo):
            cat = categorize(item['topic'])
            rows.append([country, 'YouTube', cat, item['topic'],
                         item['source'], item['volume'],
                         estimate_competition(item['topic']), '', '', today])

        # Hacker News (only USA to avoid duplicates)
        if country == 'USA':
            for item in fetch_hackernews():
                cat = categorize(item['topic'])
                rows.append([country, 'Hacker News', cat, item['topic'],
                             item['source'], item['volume'],
                             estimate_competition(item['topic']), '', '', today])

        # Duplicate সরানো
        seen = set()
        unique_rows = []
        for r in rows:
            key = r[3].lower()
            if key not in seen:
                seen.add(key)
                unique_rows.append(r)

        if unique_rows:
            ws.append_rows(unique_rows, value_input_option='USER_ENTERED')
        print(f'{country}: {len(unique_rows)} rows added')

        # ক্যাটাগরি ভিত্তিক কাউন্ট প্রিন্ট
        from collections import Counter
        cats = Counter([r[2] for r in unique_rows])
        print(f'  Categories: {dict(cats)}')

if __name__ == '__main__':
    main()
