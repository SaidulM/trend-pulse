import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from xml.etree import ElementTree as ET

COUNTRIES = {'India': 'IN', 'USA': 'US', 'UK': 'GB'}

CATEGORIES = {
    'AI': ['ai ', ' ai', 'artificial intelligence', 'chatgpt', 'gemini', 'machine learning', 'openai', 'llm'],
    'Tech': ['tech', 'software', 'app ', 'gadget', 'iphone', 'android', 'computer', 'laptop', 'samsung'],
    'Business': ['business', 'startup', 'stock', 'market', 'economy', 'finance', 'crypto', 'bitcoin'],
    'Islamic': ['islam', 'muslim', 'quran', 'hadith', 'ramadan', 'prayer', 'hajj', 'umrah'],
    'Health': ['health', 'covid', 'vaccine', 'fitness', 'diet', 'medicine', 'hospital', 'cancer'],
    'World News': ['war', 'conflict', 'election', 'protest', 'crisis', 'attack', 'ukraine', 'gaza', 'israel'],
    'Best Products': ['best', 'top ', 'review', 'buy', 'deal', 'offer', 'sale', 'cheap']
}

def categorize(topic):
    t = ' ' + topic.lower() + ' '
    for cat, kws in CATEGORIES.items():
        if any(kw in t for kw in kws):
            return cat
    return 'General'

def fetch_google_trends(geo):
    url = f'https://trends.google.com/trending/rss?geo={geo}'
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            if title:
                items.append({'topic': title, 'source': link, 'date': pub})
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
        for item in root.findall('.//item')[:15]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            if title:
                items.append({'topic': title, 'source': link, 'date': pub})
        return items
    except Exception as e:
        print(f'Google News {geo}: {e}')
        return []

def fetch_reddit(sub):
    url = f'https://www.reddit.com/r/{sub}/hot.json?limit=15'
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
                'date': datetime.utcfromtimestamp(d.get('created_utc', 0)).isoformat()
            })
        return items
    except Exception as e:
        print(f'Reddit {sub}: {e}')
        return []

def fetch_hackernews():
    try:
        r = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=30)
        ids = r.json()[:10]
        items = []
        for i in ids:
            d = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{i}.json', timeout=15).json()
            items.append({
                'topic': d.get('title', ''),
                'source': d.get('url') or f"https://news.ycombinator.com/item?id={i}",
                'date': datetime.utcfromtimestamp(d.get('time', 0)).isoformat()
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
    subreddits = {'India': 'india', 'USA': 'all', 'UK': 'unitedkingdom'}

    for country, geo in COUNTRIES.items():
        ws = ss.worksheet(country)
        rows = []

        for item in fetch_google_trends(geo):
            rows.append([country, 'Google Trends', categorize(item['topic']),
                         item['topic'], item['source'], '', '', '', '', today])

        for item in fetch_google_news(geo):
            rows.append([country, 'Google News', categorize(item['topic']),
                         item['topic'], item['source'], '', '', '', '', today])

        for item in fetch_reddit(subreddits[country]):
            rows.append([country, 'Reddit', categorize(item['topic']),
                         item['topic'], item['source'], '', '', '', '', today])

        if country == 'USA':
            for item in fetch_hackernews():
                rows.append([country, 'Hacker News', categorize(item['topic']),
                             item['topic'], item['source'], '', '', '', '', today])

        if rows:
            ws.append_rows(rows, value_input_option='USER_ENTERED')
        print(f'{country}: {len(rows)} rows added')

if __name__ == '__main__':
    main()
