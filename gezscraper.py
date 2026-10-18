import os
import json
import time 
import requests
import urllib.parse
from datetime import datetime

TMDB_API_KEY = '60b3801a9e76b5706ee2a432f06423e6'
MEDIATHEK_URL = 'https://mediathekviewweb.de/api/query'

GENRES_MAP = {
    28: 'Action', 12: 'Abenteuer', 16: 'Animation', 35: 'Komödie', 80: 'Krimi', 99: 'Doku',
    18: 'Drama', 10751: 'Familie', 14: 'Fantasy', 36: 'Historie', 27: 'Horror', 10402: 'Musik', 
    9648: 'Mystery', 10749: 'Romanze', 878: 'Sci-Fi', 10770: 'TV-Film', 53: 'Thriller', 
    10752: 'Krieg', 37: 'Western'
}

QUERIES = ['Spielfilm', 'Spielfilme', 'Spielfilm-Highlights', 'Filme', 'Kino - Filme', 'Filme in der ARD']

def clean_title(title):
    import re
    year_match = re.search(r'(\d{4})', title)
    year = year_match.group(1) if year_match else 'None'
    
    clean = title
    markers = [
        ' - Spielfilm', ' – Spielfilm', ' - Spiellfilm', ' – Spiellfilm', ', Spielfilm', 
        ' Österreich', ', Deutschland', ', Schweiz', ', Belgien', ', Frankreich', ', Spanien',
        ', Niederlande', ', Irland', ', Luxemburg', ', Italien', ', USA', ', Kosovo', 
        ', Großbritannien', ', Tschechische Republik', ', Norwegen', ', BRD', ', Dänemark', 
        ', Australien', ', Schweden', ', Video:', ', Präsentiert:', ', Kurzfilm', ' Fernsehfilm', 
        ' Heimatfilm', ' - Thriller', ' - Drama', '«', '»'
    ]

    for marker in markers:
        clean = clean.split(marker)[0]

    clean = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', clean, flags=re.IGNORECASE)
    clean = clean.replace('–', '-').replace('—', '-')
    clean = re.sub(r'\(.*?\)', '', clean)
    clean = clean.strip(r' \t,.\-_–—»')

    return clean, year

def normalize_title(title):
    import unicodedata
    if not title:
        return ''
    t = title.lower()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = t.replace('&', ' und ')
    import re
    t = re.sub(r'[^a-z0-9]+', ' ', t).strip()
    t = re.sub(r'\s+', ' ', t)
    return t

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
        return 35  

    score = src_cov * 55 + cand_cov * 25
    if cand.startswith(src + ' ') or cand.endswith(' ' + src):
        score = max(score, 45)
    if src.startswith(cand + ' ') or src.endswith(' ' + cand):
        score = max(score, 45)
    return score

def choose_best_result(results, movie, media_type):
    if not results:
        return None
    source_title = movie['search']
    source_year = str(movie['year']) if movie['year'] not in ['None', 'LIVE'] else ''
    m_desc = movie['mediathek_desc'].lower()

    scored = []
    for cand in results:
        cand_title = cand.get('name' if media_type == 'tv' else 'title', '')
        cand_orig = cand.get('original_name' if media_type == 'tv' else 'original_title', '')
        
        title_score = max(score_title(source_title, cand_title), score_title(source_title, cand_orig))
        score = title_score

        if title_score < 30:
            continue  

        date = cand.get('first_air_date' if media_type == 'tv' else 'release_date', '')
        cand_year = date[:4] if date else ''
        
        if source_year and cand_year:
            year_diff = abs(int(source_year) - int(cand_year))
            if year_diff == 0:
                score += 25
            elif year_diff == 1:
                score += 10
            else:
                score -= 50  

        overview = cand.get('overview', '').lower()
        if m_desc and overview and title_score >= 40:
            words = [w for w in overview.split() if len(w) > 5]
            matches = sum(1 for w in words if w in m_desc)
            score += min(matches * 0.3, 8)

        scored.append((cand, score))

    if not scored:
        return None

    scored.sort(key=lambda x: x[1], reverse=True)
    best = scored[0]
    
    if best[1] < 50:
        return None
        
    return best[0]


def main():
    existing_cache = {}
    if os.path.exists('movies.json'):
        try:
            with open('movies.json', 'r', encoding='utf-8') as f:
                old_movies = json.load(f)
                for m in old_movies:
                    if m.get('video_url'):
                        # Nur übernehmen, wenn es ein echter TMDB-Treffer ist (kein Platzhalter)
                        if m.get('thumb') and 'placeholder.png' not in m.get('thumb'):
                            m['processed'] = True
                        else:
                            # Fehlerhafte/Platzhalter-Einträge zurücksetzen, damit sie neu geprüft werden
                            m['processed'] = False
                        existing_cache[m['video_url']] = m
            print(f"Lese Cache: {len(existing_cache)} Filme aus movies.json geladen.")
        except Exception as e:
            print(f"Konnte bestehende movies.json nicht laden: {e}")

    seen_urls = set()
    seen_titles = set()
    temp_results = []

    print("Starte Mediathek-Abfrage...")
    for q in QUERIES:
        payload = {
            "queries": [{"fields": ["topic"], "query": q}],
            "size": 2000,
            "sortBy": "timestamp",
            "sortOrder": "desc"
        }
        try:
            res = requests.post(MEDIATHEK_URL, json=payload, headers={'Content-Type': 'application/json'})

            data = res.json()
            results = data.get('result', {}).get('results', [])
            for m in results:
                url = m.get('url_video', '')
                title = m.get('title', '')
                channel = m.get('channel', '')
                if not url or not title:
                    continue
                chan_low = channel.lower()
                if 'kika' in chan_low or 'zdf-tivi' in chan_low or 'tivi' in title.lower():
                    continue
                import re
                if re.search(r'audiodeskription|audio description|ad version|hörfilm|deskription|barrierefrei', title.lower()):
                    continue
                if any(x in title for x in ['(Englisch)', '(zho)', '(Originalversion mit Untertitel)', '(mit Untertitel)', '(Originalversion)']):
                    continue
                if re.search(r'\b(folge|staffel|episode|ep\.|teil)\b', title, re.IGNORECASE):
                    continue
                if re.search(r'\(\d+(\s*[\/\-]\s*\d+)?\)', title):
                    continue
                if re.search(r'\b\d{1,2}\/\d{1,2}\b', title):
                    continue
                if url in seen_urls:
                    continue

                clean_name, year = clean_title(title)
                if not clean_name:
                    continue
                norm_title = clean_name.lower().strip()
                if norm_title == 'nö' or norm_title in seen_titles:
                    continue
                if m.get('duration', 0) < 4680:
                    continue

                seen_urls.add(url)
                seen_titles.add(norm_title)

                temp_results.append({
                    "title": clean_name,
                    "search": clean_name,
                    "year": year,
                    "duration_min": m.get('duration', 0) // 60,  
                    "video_url": url,
                    "plot": m.get('description', 'Keine Beschreibung verfügbar.'),
                    "mediathek_desc": m.get('description', ''),
                    "director": "",
                    "actors": [],
                    "rating": "N/A",
                    "thumb": "placeholder.png",
                    "genres_list": ["Sonstige"],
                    "channel": channel,
                    "timestamp": m.get('timestamp', 0),
                    "isNew": False,
                    "processed": False
                })
        except Exception as e:
            print(f"Fehler bei Query {q}: {e}")

    temp_results.sort(key=lambda x: x['timestamp'], reverse=True)
    newest_urls = {m['video_url'] for m in temp_results[:100]}
    for m in temp_results:
        if m['video_url'] in newest_urls:
            m['isNew'] = True

    all_movies = sorted(temp_results, key=lambda x: x['title'])
    print(f"{len(all_movies)} Filme gefunden. Starte TMDB-Hydrierung...")

    for i, movie in enumerate(all_movies):
        url = movie['video_url']

        if url in existing_cache and existing_cache[url].get('processed', False):
            cached = existing_cache[url]
            movie.update({
                "plot": cached.get("plot"),
                "rating": cached.get("rating"),
                "thumb": cached.get("thumb"),
                "director": cached.get("director"),
                "actors": cached.get("actors"),
                "genres_list": cached.get("genres_list"),
                "year": cached.get("year"),
                "processed": True
            })
            continue

        try:
            query = urllib.parse.quote(movie['search'] or movie['title'])
            movie_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&language=de-DE&include_adult=false"

            res = requests.get(movie_url)
            data = res.json()
            tmdb = choose_best_result(data.get('results', []), movie, 'movie')
            is_tv = False

            if not tmdb:
                tv_url = f"https://api.themoviedb.org/3/search/tv?api_key={TMDB_API_KEY}&query={query}&language=de-DE&include_adult=false"
                tv_res = requests.get(tv_url)
                if tv_res.status_code == 200:
                    tmdb = choose_best_result(tv_res.json().get('results', []), movie, 'tv')
                    is_tv = bool(tmdb)

            d_data = {}
            if tmdb:
                media_type = 'tv' if is_tv else 'movie'
                credits_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb['id']}?api_key={TMDB_API_KEY}&language=de-DE&append_to_response=credits"
                d_res = requests.get(credits_url)
                
                d_data = d_res.json() if d_res.status_code == 200 else {}

                tmdb_runtime = d_data.get('runtime', 0)
                if not tmdb_runtime and is_tv and d_data.get('episode_run_time'):
                    tmdb_runtime = d_data['episode_run_time'][0]

                mediathek_runtime = movie.get('duration_min', 0)

                if tmdb_runtime > 0 and mediathek_runtime > 0:
                    # Toleranz auf 12 Minuten erhöht (berücksichtigt PAL-Speedup & TV-Kürzungen)
                    if abs(tmdb_runtime - mediathek_runtime) > 12:
                        tmdb = None

            if tmdb:
                genre_ids = tmdb.get('genre_ids', [])
                if 16 in genre_ids:
                    lower_title = movie['title'].lower()
                    lower_overview = tmdb.get('overview', '').lower()
                    real_keywords = ['tatort', 'polizeiruf', 'in aller freundschaft', 'rosenheim-cops', 'krimi', 'fernsehfilm', 'kommissar', 'drama', 'spielfilm']
                    if any(kw in lower_title or kw in lower_overview or kw in movie['mediathek_desc'].lower() for kw in real_keywords):
                        genre_ids = [gid for gid in genre_ids if gid != 16]

                movie['plot'] = tmdb.get('overview') or movie['mediathek_desc'] or 'Keine Beschreibung verfügbar.'
                vote_avg = tmdb.get('vote_average')
                movie['rating'] = f"{vote_avg:.1f}" if vote_avg else 'N/A'
                poster = tmdb.get('poster_path')
                movie['thumb'] = f"https://image.tmdb.org/t/p/w342{poster}" if poster else 'placeholder.png'

                credits = d_data.get('credits', {})
                director = next((c['name'] for c in credits.get('crew', []) if c.get('job') in ['Director', 'Executive Producer']), '')
                movie['director'] = director
                movie['actors'] = [a['name'] for a in credits.get('cast', [])[:3]]

                date_str = tmdb.get('release_date') or tmdb.get('first_air_date')
                if date_str and movie['year'] == 'None':
                    movie['year'] = date_str.split('-')[0]

                if genre_ids:
                    movie['genres_list'] = [GENRES_MAP[gid] for gid in genre_ids if gid in GENRES_MAP]
                    if not movie['genres_list']:
                        movie['genres_list'] = ['Sonstige']
            else:
                movie['plot'] = movie['mediathek_desc'] or 'Keine Beschreibung verfügbar.'
                movie['rating'] = 'N/A'
                movie['thumb'] = 'placeholder.png'

            movie['processed'] = True

        except Exception as e:
            print(f"Fehler bei TMDB für {movie['search']}: {e}")

        time.sleep(0.15)

        if (i + 1) % 50 == 0:
            print(f"Fortschritt: {i + 1}/{len(all_movies)} verarbeitet... (Zwischenspeicherung)")
            with open('movies.json', 'w', encoding='utf-8') as f:
                json.dump(all_movies, f, ensure_ascii=False, indent=2)

    with open('movies.json', 'w', encoding='utf-8') as f:
        json.dump(all_movies, f, ensure_ascii=False, indent=2)
    print("Fertig! movies.json erfolgreich vollständig gespeichert.")

if __name__ == '__main__':
    main()
