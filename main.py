import os
import json
import re
import requests
import gspread
from urllib.parse import quote
from google.oauth2.service_account import Credentials
from datetime import datetime
from xml.etree import ElementTree as ET

TIMEOUT = 15
LIMIT_PER_CATEGORY = 15

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
           'Description', 'Source Name', 'Search Volume', 'Competition',
           'Published Date', 'Fetched At']


def log(msg):
    print(msg, flush=True)


def fetch_google_news_search(query):
    url = f'https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en'
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:20]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            desc = (item.findtext('description') or '').strip()
            src_el = item.find('source')
            src_name = src_el.text if src_el is not None else ''
            desc = re.sub(r'<[^>]+>', '', desc)[:300]
            if title:
                items.append({
                    'topic': title, 'source': link, 'description': desc,
                    'source_name': src_name, 'date': pub, 'platform': 'Google News'
                })
        return items
    except Exception as e:
        log(f'    [Google News: {query}] ERROR: {e}')
        return []


def fetch_hackernews_search(keyword):
    try:
        url = f'https://hn.algolia.com/api/v1/search?query={quote(keyword)}&tags=story&hitsPerPage=15'
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        items = []
        for hit in r.json().get('hits', []):
            items.append({
                'topic': hit.get('title', ''),
                'source': hit.get('url') or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                'description': (hit.get('story_text') or '')[:300],
                'source_name': 'Hacker News',
                'date': hit.get('created_at', ''),
                'platform': 'Hacker News'
            })
        return items
    except Exception as e:
        log(f'    [HN: {keyword}] ERROR: {e}')
        return []


def fetch_devto(tag):
    try:
        r = requests.get(f'https://dev.to/api/articles?tag={tag}&per_page=15', timeout=TIMEOUT)
        r.raise_for_status()
        items = []
        for a in r.json():
            items.append({
                'topic': a.get('title', ''),
                'source': a.get('url', ''),
                'description': (a.get('description') or '')[:300],
                'source_name': 'Dev.to',
                'date': a.get('published_at', ''),
                'platform': 'Dev.to'
            })
        return items
    except Exception as e:
        log(f'    [Dev.to: {tag}] ERROR: {e}')
        return []


def fetch_rss(url, name):
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall('.//item')[:15]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            desc = (item.findtext('description') or '').strip()
            desc = re.sub(r'<[^>]+>', '', desc)[:300]
            if title:
                items.append({
                    'topic': title, 'source': link, 'description': desc,
                    'source_name': name, 'date': pub, 'platform': name
                })
        return items
    except Exception as e:
        log(f'    [{name}] ERROR: {e}')
        return []


def fetch_coingecko():
    try:
        r = requests.get('https://api.coingecko.com/api/v3/search/trending', timeout=TIMEOUT)
        r.raise_for_status()
        items = []
        for c in r.json().get('coins', [])[:10]:
            coin = c.get('item', {})
            items.append({
                'topic': f"{coin.get('name')} ({coin.get('symbol')}) trending",
                'source': f"https://www.coingecko.com/en/coins/{coin.get('id')}",
                'description': f"Market cap rank: {coin.get('market_cap_rank', 'N/A')}",
                'source_name': 'CoinGecko', 'date': '', 'platform': 'CoinGecko'
            })
        return items
    except Exception as e:
        log(f'    [CoinGecko] ERROR: {e}')
        return []


# ─── Category Collectors ───

def collect_ai():
    log('  [AI]')
    items = []
    for q in CATEGORY_QUERIES['AI']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_devto('ai'))
    items.extend(fetch_devto('machinelearning'))
    items.extend(fetch_hackernews_search('AI'))
    items.extend(fetch_hackernews_search('ChatGPT'))
    return items


def collect_tech():
    log('  [Tech]')
    items = []
    for q in CATEGORY_QUERIES['Tech']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_devto('programming'))
    items.extend(fetch_hackernews_search('programming'))
    items.extend(fetch_rss('https://techcrunch.com/feed/', 'TechCrunch'))
    items.extend(fetch_rss('https://www.theverge.com/rss/index.xml', 'The Verge'))
    return items


def collect_business():
    log('  [Business]')
    items = []
    for q in CATEGORY_QUERIES['Business']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_coingecko())
    items.extend(fetch_rss('https://feeds.a.dj.com/rss/RSSMarketsMain.xml', 'WSJ Markets'))
    return items


def collect_islamic():
    log('  [Islamic]')
    items = []
    for q in CATEGORY_QUERIES['Islamic']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_rss('https://aboutislam.net/feed/', 'About Islam'))
    return items


def collect_health():
    log('  [Health]')
    items = []
    for q in CATEGORY_QUERIES['Health']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_rss('https://www.medicalnewstoday.com/rss', 'Medical News Today'))
    items.extend(fetch_rss('https://feeds.webmd.com/rss/rss.aspx?RSSSource=RSS_PUBLIC', 'WebMD'))
    return items


def collect_world_news():
    log('  [World News]')
    items = []
    for q in CATEGORY_QUERIES['World News']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_rss('http://feeds.bbci.co.uk/news/world/rss.xml', 'BBC World'))
    items.extend(fetch_rss('https://www.aljazeera.com/xml/rss/all.xml', 'Al Jazeera'))
    items.extend(fetch_rss('https://feeds.npr.org/1004/rss.xml', 'NPR World'))
    return items


def collect_best_products():
    log('  [Best Products]')
    items = []
    for q in CATEGORY_QUERIES['Best Products']:
        items.extend(fetch_google_news_search(q))
    items.extend(fetch_rss('https://slickdeals.net/newsearch.php?searchin=first&rss=1', 'Slickdeals'))
    return items


COLLECTORS = {
    'AI': collect_ai,
    'Tech': collect_tech,
    'Business': collect_business,
    'Islamic': collect_islamic,
    'Health': collect_health,
    'World News': collect_world_news,
    'Best Products': collect_best_products,
}


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


def get_or_create_sheet(ss, name):
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=2000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
        log(f'  [Sheets] Created tab: {name}')
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


def estimate_competition(topic):
    words = len(topic.split())
    if words <= 3:
        return 'High'
    elif words <= 6:
        return 'Medium'
    return 'Low'


def main():
    log('▶ Starting')
    client = get_client()
    ss = client.open('Trend Data')
    log('▶ Sheet opened')

    today = datetime.utcnow().strftime('%Y-%m-%d %H:%M')

    for category, collector in COLLECTORS.items():
        log(f'▶ Category: {category}')
        try:
            items = dedupe(collector())
        except Exception as e:
            log(f'  Collector error: {e}')
            items = []
        log(f'  Unique items: {len(items)}')

        ws = get_or_create_sheet(ss, category)

        rows = []
        for it in items[:LIMIT_PER_CATEGORY]:
            rows.append([
                'USA',
                it.get('platform', ''),
                category,
                it.get('topic', ''),
                it.get('source', ''),
                it.get('description', ''),
                it.get('source_name', ''),
                it.get('volume', ''),
                estimate_competition(it.get('topic', '')),
                it.get('date', ''),
                today
            ])

        if rows:
            ws.append_rows(rows, value_input_option='USER_ENTERED')
            log(f'  ✅ {category}: {len(rows)} rows added')
        else:
            log(f'  ⚠ {category}: no rows')

    log('▶ Done')


if __name__ == '__main__':
    main()
