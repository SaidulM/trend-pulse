import os
import json
import re
import time
import requests
import gspread
from urllib.parse import quote
from google.oauth2.service_account import Credentials
from datetime import datetime
from xml.etree import ElementTree as ET

TIMEOUT = 20
LIMIT_PER_CATEGORY = 5

CATEGORY_QUERIES = {
    'AI': ['artificial intelligence', 'ChatGPT', 'OpenAI', 'machine learning'],
    'Tech': ['technology', 'smartphone', 'iPhone', 'Android'],
    'Business': ['stock market', 'cryptocurrency', 'business news', 'startup'],
    'Islamic': ['Islam', 'Muslim', 'Ramadan', 'Quran'],
    'Health': ['health tips', 'medicine', 'fitness', 'nutrition'],
    'World News': ['world news', 'war', 'election', 'geopolitics'],
    'Best Products': ['best products', 'product review', 'top deals', 'buying guide'],
}

HEADERS = ['Country', 'Platform', 'Category', 'Topic', 'Source Link',
           'Description', 'Source Name', 'Published Date', 'Fetched At']


def log(msg):
    print(msg, flush=True)


def safe_get(url, headers=None):
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=TIMEOUT,
                             headers=headers or {'User-Agent': 'Mozilla/5.0'})
            if r.status_code == 429:
                time.sleep(5)
                continue
            r.raise_for_status()
            return r
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2)
    return None


def fetch_google_news(query):
    url = f'https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en'
    r = safe_get(url)
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:10]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            desc = (item.findtext('description') or '').strip()
            src_el = item.find('source')
            src_name = src_el.text if src_el is not None else ''
            desc = re.sub(r'<[^>]+>', '', desc)[:200]
            if title:
                items.append({'topic': title, 'source': link, 'description': desc,
                              'source_name': src_name, 'date': pub, 'platform': 'Google News'})
        return items
    except Exception:
        return []


def fetch_reddit_rss(subreddit):
    url = f'https://www.reddit.com/r/{subreddit}/hot.rss'
    r = safe_get(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; TrendBot/1.0)'})
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = []
        for entry in root.findall('.//atom:entry', ns)[:10]:
            title = (entry.findtext('atom:title', namespaces=ns) or '').strip()
            link_el = entry.find('atom:link', ns)
            link = link_el.get('href') if link_el is not None else ''
            updated = (entry.findtext('atom:updated', namespaces=ns) or '').strip()
            content = (entry.findtext('atom:content', namespaces=ns) or '').strip()
            content = re.sub(r'<[^>]+>', '', content)[:200]
            if title:
                items.append({'topic': title, 'source': link, 'description': content,
                              'source_name': f'r/{subreddit}', 'date': updated, 'platform': 'Reddit'})
        return items
    except Exception:
        return []


def fetch_hackernews(keyword):
    url = f'https://hn.algolia.com/api/v1/search?query={quote(keyword)}&tags=story&hitsPerPage=8'
    r = safe_get(url)
    if not r:
        return []
    try:
        items = []
        for hit in r.json().get('hits', []):
            items.append({'topic': hit.get('title', ''),
                          'source': hit.get('url') or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                          'description': (hit.get('story_text') or '')[:200],
                          'source_name': 'Hacker News', 'date': hit.get('created_at', ''),
                          'platform': 'Hacker News'})
        return items
    except Exception:
        return []


def fetch_devto(tag):
    url = f'https://dev.to/api/articles?tag={tag}&per_page=8'
    r = safe_get(url)
    if not r:
        return []
    try:
        items = []
        for a in r.json():
            items.append({'topic': a.get('title', ''), 'source': a.get('url', ''),
                          'description': (a.get('description') or '')[:200],
                          'source_name': 'Dev.to', 'date': a.get('published_at', ''),
                          'platform': 'Dev.to'})
        return items
    except Exception:
        return []


def fetch_rss(url, name):
    r = safe_get(url)
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:8]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            desc = (item.findtext('description') or '').strip()
            desc = re.sub(r'<[^>]+>', '', desc)[:200]
            if title:
                items.append({'topic': title, 'source': link, 'description': desc,
                              'source_name': name, 'date': pub, 'platform': name})
        return items
    except Exception:
        return []


def fetch_coingecko():
    r = safe_get('https://api.coingecko.com/api/v3/search/trending')
    if not r:
        return []
    try:
        items = []
        for c in r.json().get('coins', [])[:5]:
            coin = c.get('item', {})
            items.append({'topic': f"{coin.get('name')} ({coin.get('symbol')}) trending",
                          'source': f"https://www.coingecko.com/en/coins/{coin.get('id')}",
                          'description': f"Market cap rank: {coin.get('market_cap_rank', 'N/A')}",
                          'source_name': 'CoinGecko', 'date': '', 'platform': 'CoinGecko'})
        return items
    except Exception:
        return []


def collect_ai():
    items = []
    for q in CATEGORY_QUERIES['AI']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_devto('ai'))
    items.extend(fetch_hackernews('AI'))
    return items


def collect_tech():
    items = []
    for q in CATEGORY_QUERIES['Tech']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_devto('programming'))
    items.extend(fetch_hackernews('programming'))
    items.extend(fetch_rss('https://techcrunch.com/feed/', 'TechCrunch'))
    items.extend(fetch_rss('https://www.theverge.com/rss/index.xml', 'The Verge'))
    return items


def collect_business():
    items = []
    for q in CATEGORY_QUERIES['Business']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_coingecko())
    items.extend(fetch_rss('https://feeds.a.dj.com/rss/RSSMarketsMain.xml', 'WSJ Markets'))
    items.extend(fetch_reddit_rss('IndianStockMarket'))
    return items


def collect_islamic():
    items = []
    for q in CATEGORY_QUERIES['Islamic']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_rss('https://aboutislam.net/feed/', 'About Islam'))
    items.extend(fetch_reddit_rss('islam'))
    return items


def collect_health():
    items = []
    for q in CATEGORY_QUERIES['Health']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_rss('https://www.medicalnewstoday.com/rss', 'Medical News Today'))
    items.extend(fetch_reddit_rss('health'))
    return items


def collect_world_news():
    items = []
    for q in CATEGORY_QUERIES['World News']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_rss('http://feeds.bbci.co.uk/news/world/rss.xml', 'BBC World'))
    items.extend(fetch_rss('https://www.aljazeera.com/xml/rss/all.xml', 'Al Jazeera'))
    items.extend(fetch_reddit_rss('worldnews'))
    return items


def collect_best_products():
    items = []
    for q in CATEGORY_QUERIES['Best Products']:
        items.extend(fetch_google_news(q))
    items.extend(fetch_reddit_rss('BuyItForLife'))
    return items


COLLECTORS = {
    'AI': collect_ai, 'Tech': collect_tech, 'Business': collect_business,
    'Islamic': collect_islamic, 'Health': collect_health,
    'World News': collect_world_news, 'Best Products': collect_best_products,
}


def get_client():
    creds_dict = json.loads(os.environ['GOOGLE_SHEETS_CREDENTIALS'])
    scopes = ['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def get_or_create_sheet(ss, name):
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
    return ws


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        t = (it.get('topic') or '').strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    log('▶ Starting')
    client = get_client()
    ss = client.open('Trend Data')
    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    for category, collector in COLLECTORS.items():
        log(f'▶ {category}')
        try:
            items = dedupe(collector())
        except Exception as e:
            log(f'  Error: {e}')
            items = []

        ws = get_or_create_sheet(ss, category)
        rows = []
        for it in items[:LIMIT_PER_CATEGORY]:
            rows.append(['USA', it.get('platform', ''), category,
                         it.get('topic', ''), it.get('source', ''),
                         it.get('description', ''), it.get('source_name', ''),
                         it.get('date', ''), today])

        if rows:
            ws.append_rows(rows, value_input_option='USER_ENTERED')
            log(f'  ✅ {len(rows)} rows')
        else:
            log(f'  ⚠ no rows')

    log('▶ Done')


if __name__ == '__main__':
    main()
