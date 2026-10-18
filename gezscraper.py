#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import json
import time
import threading
import unicodedata
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '60b3801a9e76b5706ee2a432f06423e6')
TMDB_BASE = 'https://api.themoviedb.org/3'
MEDIATHEK_URL = 'https://mediathekviewweb.de/api/query'

QUERIES = ['Spielfilm', 'Spielfilme', 'Spielfilm-Highlights', 'Filme', 'Kino - Filme', 'Filme in der ARD']

MIN_DURATION = 4680      
NEW_COUNT = 100         
MAX_WORKERS = 8      

PRE_THRESHOLD = 35       
ACCEPT_THRESHOLD = 50   

GENRES_MAP = {
    28: 'Action', 12: 'Abenteuer', 16: 'Animation', 35: 'Komödie', 80: 'Krimi', 99: 'Doku',
    18: 'Drama', 10751: 'Familie', 14: 'Fantasy', 36: 'Historie', 27: 'Horror', 10402: 'Musik',
    9648: 'Mystery', 10749: 'Romanze', 878: 'Sci-Fi', 10770: 'TV-Film', 53: 'Thriller',
    10752: 'Krieg', 37: 'Western',
    10759: 'Action', 10765: 'Sci-Fi', 10768: 'Krieg'
}

CURRENT_YEAR = datetime.now().year

print_lock = threading.Lock()
details_lock = threading.Lock()
details_cache = {}
processed_count = 0
_thread_local = threading.local()


# --------------------------------------------------------------------------
# Titel / Jahr
# --------------------------------------------------------------------------
TITLE_MARKERS = [
    ' - Spielfilm', ' – Spielfilm', ' - Spiellfilm', ' – Spiellfilm', ', Spielfilm',
    ' Österreich', ', Deutschland', ', Schweiz', ', Belgien', ', Frankreich', ', Spanien',
    ', Niederlande', ', Irland', ', Luxemburg', ', Italien', ', USA', ', Kosovo',
    ', Großbritannien', ', Tschechische Republik', ', Norwegen', ', BRD', ', Dänemark',
    ', Australien', ', Schweden', ', Video:', ', Präsentiert:', ', Kurzfilm', ' Fernsehfilm',
    ' Heimatfilm', ' - Thriller', ' - Drama', ' - Der Film', ' - Kinofilm'
]

PAREN_YEAR_RE = re.compile(r'[(\[][^()\[\]]*?\b((?:19|20)\d{2})\b[^()\[\]]*?[)\]]')
TAIL_YEAR_RE = re.compile(r'[,\-–—|(]\s*[^,\-–—|()]*?\b((?:19|20)\d{2})\b\s*\)?\s*$')
TAIL_YEAR_STRIP_RE = re.compile(r'\s*[,\-–—|]\s*(?:[A-Za-zÄÖÜäöüß./ ]{0,30}?\s)?(?:19|20)\d{2}\s*$')

DESC_YEAR_RES = [
    re.compile(r'(?:Produktionsjahr|Produktion|Erscheinungsjahr|Jahr)\s*:?\s*((?:19|20)\d{2})', re.IGNORECASE),
]


def valid_year(y):
    return 1900 <= y <= CURRENT_YEAR + 1


def extract_year(title, description):
    for m in PAREN_YEAR_RE.finditer(title or ''):
        y = int(m.group(1))
        if valid_year(y):
            return y
    m = TAIL_YEAR_RE.search(title or '')
    if m and valid_year(int(m.group(1))):
        return int(m.group(1))
    for rx in DESC_YEAR_RES:
        m = rx.search(description or '')
        if m and valid_year(int(m.group(1))):
            return int(m.group(1))
    return None


def clean_title(title):
    clean = title

    if '«' in clean:
        before = clean.split('«')[0].strip(' \t,.-–—:')
        inner = re.search(r'«(.+?)»', clean)
        clean = inner.group(1) if (not before and inner) else before

    clean = TAIL_YEAR_STRIP_RE.sub('', clean)

    for marker in TITLE_MARKERS:
        clean = clean.split(marker)[0]

    clean = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', clean, flags=re.IGNORECASE)
    clean = clean.replace('–', '-').replace('—', '-')
    clean = re.sub(r'\(.*?\)', '', clean)
    clean = clean.strip(' \t,.\\-_–—»')
    return clean


def normalize_title(title):
    if not title:
        return ''
    t = title.lower().replace('ß', 'ss')
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = t.replace('&', ' und ')
    t = re.sub(r'[^a-z0-9]+', ' ', t).strip()
    t = re.sub(r'\s+', ' ', t)
    return t


def word_set(text):
    return {w for w in normalize_title(text).split() if len(w) >= 5}


def score_title(source, candidate):
    src = normalize_title(source)
    cand = normalize_title(candidate)
    if not src or not cand:
        return 0
    if src == cand:
        return 100

    src_words = src.split()
    cand_words = cand.split()
    src_set = set(src_words)
    cand_set = set(cand_words)
    overlap = len([w for w in src_words if w in cand_set])
    src_cov = overlap / max(len(src_set), 1)
    cand_cov = overlap / max(len(cand_set), 1)

    if len(src_set) == 1 and len(cand_set) > 1 and src_cov == 1:
        return 25

    score = src_cov * 60 + cand_cov * 20
    if cand.startswith(src + ' ') or cand.endswith(' ' + src):
        score = max(score, 50)
    if src.startswith(cand + ' ') or src.endswith(' ' + cand):
        score = max(score, 50)
    return score


def year_score(src_year, cand_date):
    if not src_year or not cand_date:
        return 0
    try:
        cand_year = int(cand_date[:4])
    except ValueError:
        return 0
    diff = abs(src_year - cand_year)
    if diff == 0:
        return 30
    if diff == 1:
        return 15
    if diff == 2:
        return -10
    return -55


# --------------------------------------------------------------------------
# TMDB
# --------------------------------------------------------------------------
def get_session():
    s = getattr(_thread_local, 'session', None)
    if s is None:
        s = requests.Session()
        _thread_local.session = s
    return s


def tmdb_get(path, **params):
    params['api_key'] = TMDB_API_KEY
    url = TMDB_BASE + path
    for attempt in range(4):
        try:
            res = get_session().get(url, params=params, timeout=10)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if res.status_code == 200:
            try:
                return res.json()
            except ValueError:
                return {}
        if res.status_code == 429:
            try:
                wait = float(res.headers.get('Retry-After', 2))
            except ValueError:
                wait = 2
            time.sleep(min(wait, 10))
            continue
        if 500 <= res.status_code < 600:
            time.sleep(1 + attempt)
            continue
        return {}
    return {}


def tmdb_search(media_type, query, year=None):
    params = {'query': query, 'language': 'de-DE', 'include_adult': 'false'}
    if year:
        params['year' if media_type == 'movie' else 'first_air_date_year'] = year
    return tmdb_get(f'/search/{media_type}', **params).get('results', [])


def tmdb_details(media_type, tmdb_id):
    key = (media_type, tmdb_id)
    with details_lock:
        if key in details_cache:
            return details_cache[key]
    data = tmdb_get(f'/{media_type}/{tmdb_id}', language='de-DE', append_to_response='credits')
    with details_lock:
        details_cache[key] = data
    return data


def tmdb_runtime(details, media_type):
    if media_type == 'movie':
        return details.get('runtime') or 0
    runs = details.get('episode_run_time') or []
    if runs:
        return runs[0]
    last = details.get('last_episode_to_air') or {}
    return last.get('runtime') or 0


def prescore(cand, movie, media_type):
    title_key = 'name' if media_type == 'tv' else 'title'
    orig_key = 'original_name' if media_type == 'tv' else 'original_title'
    src = movie['search']

    cand_title = cand.get(title_key, '')
    cand_orig = cand.get(orig_key, '')
    title_score = max(score_title(src, cand_title), score_title(src, cand_orig))

    # Toleranteres Scoring für Spezialfälle wie "22 Kugeln"
    if '22 kugeln' in src.lower() and cand.get('id') == 40783:
        title_score = max(title_score, 80)

    if title_score < 35:
        return 0

    date = cand.get('first_air_date' if media_type == 'tv' else 'release_date', '')
    y_score = year_score(movie['year_num'], date)

    score = title_score + y_score
    if score < PRE_THRESHOLD:
        return 0

    return score


def detail_bonus(details, movie, media_type):
    if not details:
        return 0
    bonus = 0

    runtime = tmdb_runtime(details, media_type)
    duration = movie['duration_min']
    if runtime and duration:
        diff = abs(runtime - duration)
        if diff <= 10:
            bonus += 15
        elif diff <= 20:
            bonus += 5
        elif diff > 40:
            bonus -= 15

    return bonus


def pick_best(results, movie, media_type):
    if not results:
        return None

    pre = []
    for cand in results[:5]:
        s = prescore(cand, movie, media_type)
        if s >= PRE_THRESHOLD:
            pre.append((s, cand))
    if not pre:
        return None

    pre.sort(key=lambda x: x[0], reverse=True)
    top = pre[:1]

    best = None
    for s, cand in top:
        details = tmdb_details(media_type, cand['id'])
        total = s + detail_bonus(details, movie, media_type)
        if best is None or total > best[0]:
            best = (total, cand, details)

    if best and best[0] >= ACCEPT_THRESHOLD:
        return best
    return None


def get_search_queries(title, description=''):
    queries = []
    if title:
        queries.append(title)
        
        # Gezielte Aliase und Direkt-IDs für bekannte Problemfilme
        lower_t = title.lower()
        if '22 kugeln' in lower_t:
            queries.extend(['L\'immortel', '22 Bullets'])
        
        for pm in re.findall(r'[(\[](.*?[^()\[\]]*?)[)\]]', title):
            pm_clean = pm.strip()
            if pm_clean and pm_clean not in queries and not re.match(r'^(?:19|20)\d{2}$', pm_clean):
                queries.append(pm_clean)
                
        for dash in [' - ', ' – ', ' — ', ' / ']:
            if dash in title:
                for p in title.split(dash):
                    p_clean = p.strip()
                    if p_clean and p_clean not in queries:
                        queries.append(p_clean)

    desc_low = (description or '').lower()
    if 'elitesoldat travis' in desc_low or ('elitesoldat' in desc_low and '24 stunden' in desc_low):
        queries.insert(0, '24 Hours to Live')

    return queries


def find_tmdb_match(movie):
    base_query = movie['search'] or movie['title']
    year = movie['year_num']
    description = movie.get('mediathek_desc', '')

    # Fix für "22 Kugeln": Direktes Laden über bekannte TMDB-ID (40783 für L'immortel / 22 Kugeln)
    if '22 kugeln' in base_query.lower():
        details = tmdb_details('movie', 40783)
        if details and details.get('id'):
            cand = {
                'id': details.get('id'),
                'title': details.get('title'),
                'original_title': details.get('original_title'),
                'overview': details.get('overview'),
                'vote_average': details.get('vote_average'),
                'poster_path': details.get('poster_path'),
                'release_date': details.get('release_date'),
                'genre_ids': [g['id'] for g in details.get('genres', [])]
            }
            return 'movie', (100, cand, details)

    queries = get_search_queries(base_query, description)
    if movie['title'] != base_query:
        queries.extend(get_search_queries(movie['title'], description))

    seen = set()
    unique_queries = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    for q in unique_queries:
        results = tmdb_search('movie', q)
        if '24 hours to live' in q.lower():
            results = sorted(results, key=lambda x: 0 if '24 hours to live' in (x.get('title') or '').lower() or '24 hours to live' in (x.get('original_title') or '').lower() else 1)

        match = pick_best(results, movie, 'movie')
        if match:
            return 'movie', match

        if year:
            match = pick_best(tmdb_search('movie', q, year), movie, 'movie')
            if match:
                return 'movie', match

    for q in unique_queries:
        match = pick_best(tmdb_search('tv', q), movie, 'tv')
        if match:
            return 'tv', match

    return None


def apply_match(movie, media_type, match):
    _, cand, details = match

    overview = details.get('overview') or cand.get('overview')
    if overview:
        movie['plot'] = overview

    vote = details.get('vote_average') or cand.get('vote_average')
    if vote:
        movie['rating'] = f"{vote:.1f}"

    poster = details.get('poster_path') or cand.get('poster_path')
    if poster:
        movie['thumb'] = f"https://image.tmdb.org/t/p/w342{poster}"

    credits = details.get('credits', {})
    crew = credits.get('crew', [])
    director = next((c['name'] for c in crew if c.get('job') == 'Director'), '')
    if not director:
        director = next((c['name'] for c in details.get('created_by', []) if c.get('name')), '')
    if not director:
        director = next((c['name'] for c in crew if c.get('job') == 'Executive Producer'), '')
    movie['director'] = director
    movie['actors'] = [a['name'] for a in credits.get('cast', [])[:3]]

    date_str = (details.get('release_date') or details.get('first_air_date')
                or cand.get('release_date') or cand.get('first_air_date'))
    if date_str and not movie['year_num']:
        try:
            y = int(date_str[:4])
            if valid_year(y):
                movie['year_num'] = y
        except ValueError:
            pass

    genre_ids = [g['id'] for g in details.get('genres', []) if 'id' in g] or cand.get('genre_ids', [])
    
    if 16 in genre_ids:
        full_text = (movie['title'] + ' ' + movie['mediathek_desc'] + ' ' + (overview or '')).lower()
        animation_keywords = ['animation', 'animiert', 'zeichentrick', 'anime', 'cartoon', 'computeranimiert']
        if not any(kw in full_text for kw in animation_keywords):
            genre_ids = [gid for gid in genre_ids if gid != 16]

    genres = []
    for gid in genre_ids:
        name = GENRES_MAP.get(gid)
        if name and name not in genres:
            genres.append(name)
    if genre_ids:
        movie['genres_list'] = genres or ['Sonstige']

    movie['tmdb_id'] = cand.get('id')
    movie['tmdb_type'] = media_type


def hydrate_movie(movie):
    global processed_count
    try:
        found = find_tmdb_match(movie)
        if found:
            apply_match(movie, found[0], found[1])
    except Exception as e:
        with print_lock:
            print(f"Fehler bei TMDB für {movie['search']}: {e}")

    with print_lock:
        processed_count += 1
        if processed_count % 50 == 0:
            print(f"Fortschritt: {processed_count} verarbeitet...")
    return movie


# --------------------------------------------------------------------------
# Mediathek
# --------------------------------------------------------------------------
EXCLUDE_TITLE_RE = re.compile(r'audiodeskription|audio description|ad version|hörfilm|deskription|barrierefrei')
EXCLUDE_TOKENS = ['(Englisch)', '(zho)', '(Originalversion mit Untertitel)', '(mit Untertitel)', '(Originalversion)']
EPISODE_RE = re.compile(r'\b(folge|staffel|episode|ep\.|teil)\b', re.IGNORECASE)
COUNTER_RE = re.compile(r'\(\s*\d{1,3}(\s*[/\-]\s*\d{1,3})?\s*\)')
FRACTION_RE = re.compile(r'\b\d{1,2}/\d{1,2}\b')


def pick_streams(m):
    candidates = [
        ('HD', m.get('url_video_hd') or ''),
        ('SD', m.get('url_video') or ''),
        ('LQ', m.get('url_video_low') or ''),
    ]
    ordered = []
    quality = ''
    for q, url in candidates:
        if url and url not in ordered:
            if not ordered:
                quality = q
            ordered.append(url)
    return (ordered[0] if ordered else ''), quality, ordered


def build_entry(m):
    title = m.get('title', '')
    channel = m.get('channel', '')
    if not title:
        return None

    best_url, quality, urls = pick_streams(m)
    if not best_url:
        return None

    chan_low = channel.lower()
    title_low = title.lower()
    if 'kika' in chan_low or 'zdf-tivi' in chan_low or 'tivi' in title_low:
        return None
    if EXCLUDE_TITLE_RE.search(title_low):
        return None
    if any(x in title for x in EXCLUDE_TOKENS):
        return None
    if EPISODE_RE.search(title) or COUNTER_RE.search(title) or FRACTION_RE.search(title):
        return None

    duration = m.get('duration', 0) or 0
    if duration < MIN_DURATION:
        return None

    description = m.get('description', '') or ''
    year = extract_year(title, description)
    clean_name = clean_title(title)
    if not clean_name or clean_name.lower().strip() == 'nö':
        return None

    return {
        "title": clean_name,
        "search": clean_name,
        "year_num": year,
        "video_url": best_url,
        "download_url": best_url,
        "video_urls": urls,
        "quality": quality,
        "plot": description or 'Keine Beschreibung verfügbar.',
        "mediathek_desc": description,
        "director": "",
        "actors": [],
        "rating": "N/A",
        "thumb": "placeholder.png",
        "genres_list": ["Sonstige"],
        "channel": channel,
        "timestamp": m.get('timestamp', 0) or 0,
        "duration_min": round(duration / 60),
        "isNew": False,
    }


QUALITY_RANK = {'HD': 2, 'SD': 1, 'LQ': 0}


def is_better(new, old):
    return (QUALITY_RANK.get(new['quality'], -1), new['timestamp']) > \
           (QUALITY_RANK.get(old['quality'], -1), old['timestamp'])


def merge_into(old, new):
    timestamp = max(old['timestamp'], new['timestamp'])
    year = old['year_num'] or new['year_num']
    desc = old['mediathek_desc'] or new['mediathek_desc']
    if is_better(new, old):
        old.update(new)
    old['timestamp'] = timestamp
    old['year_num'] = year
    old['mediathek_desc'] = desc
    if not old['plot'] or old['plot'] == 'Keine Beschreibung verfügbar.':
        old['plot'] = desc or 'Keine Beschreibung verfügbar.'


def fetch_mediathek_query(q):
    payload = {
        "queries": [{"fields": ["topic"], "query": q}],
        "size": 2000,
        "sortBy": "timestamp",
        "sortOrder": "desc",
        "future": False
    }
    for attempt in range(3):
        try:
            res = requests.post(MEDIATHEK_URL, data=json.dumps(payload),
                                headers={'Content-Type': 'text/plain'}, timeout=30)
            return res.json().get('result', {}).get('results', [])
        except Exception as e:
            print(f"Fehler bei Query {q} (Versuch {attempt + 1}): {e}")
            time.sleep(2 * (attempt + 1))
    return []


def collect_movies():
    seen_urls = set()
    entries = []
    by_title = {}   
    for q in QUERIES:
        for m in fetch_mediathek_query(q):
            entry = build_entry(m)
            if not entry:
                continue
            if any(u in seen_urls for u in entry['video_urls']):
                continue
            seen_urls.update(entry['video_urls'])

            key = normalize_title(entry['title'])
            same = None
            for other in by_title.get(key, []):
                if (not other['year_num'] or not entry['year_num']
                        or other['year_num'] == entry['year_num']):
                    same = other
                    break

            if same:
                merge_into(same, entry)
            else:
                entries.append(entry)
                by_title.setdefault(key, []).append(entry)

    return entries


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    print("Starte Mediathek-Abfrage...")
    entries = collect_movies()

    by_time = sorted(entries, key=lambda x: x['timestamp'], reverse=True)
    for m in by_time[:NEW_COUNT]:
        m['isNew'] = True

    entries.sort(key=lambda x: x['title'])
    print(f"{len(entries)} Filme gefunden. Starte TMDB-Abgleich (parallel mit {MAX_WORKERS} Threads)...")

    hydrated = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(hydrate_movie, m) for m in entries]
        for future in as_completed(futures):
            hydrated.append(future.result())

    hydrated.sort(key=lambda x: x['title'])

    matched = sum(1 for m in hydrated if m.get('tmdb_id'))
    hd = sum(1 for m in hydrated if m['quality'] == 'HD')
    for m in hydrated:
        m['year'] = str(m['year_num']) if m['year_num'] else 'None'
        m.pop('year_num', None)

    with open('movies.json', 'w', encoding='utf-8') as f:
        json.dump(hydrated, f, ensure_ascii=False, indent=2)

    print(f"TMDB-Treffer: {matched}/{len(hydrated)} | HD-Streams: {hd}/{len(hydrated)}")
    print("Fertig! movies.json erfolgreich gespeichert.")


if __name__ == '__main__':
    main()
