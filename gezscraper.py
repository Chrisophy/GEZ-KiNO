import os
import re
import json
import time
import threading
import unicodedata
import requests

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from functools import lru_cache

TMDB_API_KEY = os.environ.get(
    "TMDB_API_KEY",
    "60b3801a9e76b5706ee2a432f06423e6"
)

MEDIATHEK_URL = "https://mediathekviewweb.de/api/query"
TMDB_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w342"

OUTPUT_FILE = "movies.json"
PLACEHOLDER = "placeholder.png"

MIN_DURATION = 4680
MAX_RESULTS_PER_QUERY = 2000
MAX_WORKERS = 6
REQUEST_TIMEOUT = 15
TMDB_LANGUAGE = "de-DE"

QUERIES = [
    "Spielfilm",
    "Spielfilme",
    "Spielfilm-Highlights",
    "Filme",
    "Kino - Filme",
    "Filme in der ARD",
]

GENRES_MAP = {
    28: "Action",
    12: "Abenteuer",
    16: "Animation",
    35: "Komödie",
    80: "Krimi",
    99: "Doku",
    18: "Drama",
    10751: "Familie",
    14: "Fantasy",
    36: "Historie",
    27: "Horror",
    10402: "Musik",
    9648: "Mystery",
    10749: "Romanze",
    878: "Sci-Fi",
    10770: "TV-Film",
    53: "Thriller",
    10752: "Krieg",
    37: "Western",
}

print_lock = threading.Lock()
tmdb_lock = threading.Lock()
processed_count = 0


# ---------------------------------------------------------
# HTTP
# ---------------------------------------------------------

_thread_local = threading.local()


def get_session():
    """Eigene Session je Thread."""
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "GEZ-KiNO/2.0",
            "Accept": "application/json",
        })
        _thread_local.session = session
    return _thread_local.session


def request_json(url, params=None, method="GET", payload=None,
                 retries=3, timeout=REQUEST_TIMEOUT):
    """HTTP-Anfrage mit begrenzten Wiederholungen."""
    session = get_session()

    for attempt in range(retries):
        try:
            if method == "POST":
                response = session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "text/plain"},
                    timeout=timeout,
                )
            else:
                response = session.get(
                    url,
                    params=params,
                    timeout=timeout,
                )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = min(float(retry_after), 20)
                except (TypeError, ValueError):
                    delay = min(2 ** (attempt + 1), 10)

                time.sleep(delay)
                continue

            if response.status_code >= 500:
                time.sleep(min(2 ** attempt, 5))
                continue

            if response.status_code != 200:
                return {}

            return response.json()

        except (requests.RequestException, ValueError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 5))

    return {}


# ---------------------------------------------------------
# Titel und Jahr
# ---------------------------------------------------------

def normalize_title(title):
    if not title:
        return ""

    text = unicodedata.normalize("NFKD", str(title).lower())
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.replace("&", " und ")
    text = text.replace("ß", "ss")
    text = re.sub(r"\bder\b", "der", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def extract_year(value):
    """Erkennt ein plausibles Produktionsjahr."""
    if value is None:
        return ""

    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value))
    if not match:
        return ""

    year = int(match.group(1))
    current_year = datetime.now().year

    if 1900 <= year <= current_year + 1:
        return str(year)

    return ""


def clean_title(title):
    """
    Entfernt Senderzusätze und ein am Ende angehängtes Jahr.
    Das Produktionsjahr wird separat zurückgegeben.
    """
    if not title:
        return "", ""

    original = str(title).strip()
    year = ""

    # Nur ein am Titelende stehendes Jahr verwenden.
    year_match = re.search(
        r"\s*[\(\[]?(19\d{2}|20\d{2})[\)\]]?\s*$",
        original,
    )

    if year_match:
        year = extract_year(year_match.group(1))
        original = original[:year_match.start()].strip()

    clean = original

    clean = re.sub(
        r"^(?:Spielfilm|Spiellfilm)\s*:\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    )

    # Bekannte redaktionelle Zusätze am Ende abschneiden.
    markers = [
        r"\s*[-–—,]\s*Spielfilm\b.*$",
        r"\s*[-–—,]\s*Spiellfilm\b.*$",
        r"\s*[-–—,]\s*Spielfilm-Highlights\b.*$",
        r"\s*[-–—,]\s*(?:Video|Präsentiert)\s*:.*$",
        r"\s*[-–—,]\s*(?:Kurzfilm|Heimatfilm)\b.*$",
        r"\s*[-–—,]\s*(?:Fernsehfilm)\b.*$",
        r"\s*,\s*(?:Österreich|Deutschland|Schweiz|Belgien|Frankreich|"
        r"Spanien|Niederlande|Irland|Luxemburg|Italien|USA|Kosovo|"
        r"Großbritannien|Tschechische Republik|Norwegen|BRD|Dänemark|"
        r"Australien|Schweden)\s*$",
    ]

    for marker in markers:
        clean = re.sub(marker, "", clean, flags=re.IGNORECASE)

    clean = clean.replace("«", "").replace("»", "")
    clean = re.sub(r"\s+", " ", clean)
    clean = clean.strip(" \t,.-_–—")

    return clean, year


def score_title(source, candidate):
    """Titelähnlichkeit von 0 bis 100."""
    src = normalize_title(source)
    cand = normalize_title(candidate)

    if not src or not cand:
        return 0.0

    if src == cand:
        return 100.0

    # Bei Titeln wie Phoenix niemals einen langen Zusatztitel
    # allein aufgrund eines einzigen gemeinsamen Wortes bevorzugen.
    src_words = set(src.split())
    cand_words = set(cand.split())

    overlap = len(src_words & cand_words)
    if not overlap:
        return 0.0

    source_coverage = overlap / max(len(src_words), 1)
    candidate_coverage = overlap / max(len(cand_words), 1)

    sequence = SequenceMatcher(None, src, cand).ratio()

    score = (
        source_coverage * 45
        + candidate_coverage * 25
        + sequence * 30
    )

    if src in cand_words and len(src_words) == 1:
        # Ein einzelnes Wort darf nicht automatisch einen
        # Film mit längerem, abweichendem Titel matchen.
        if len(cand_words) > 1:
            score = min(score, 48.0)

    return min(score, 100.0)


# ---------------------------------------------------------
# MediathekViewWeb-Metadaten
# ---------------------------------------------------------

def get_upload_timestamp(item):
    value = item.get("timestamp", 0)

    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return 0

    # MVW liefert normalerweise Unix-Zeitstempel in Sekunden.
    # Millisekunden vorsichtig normalisieren.
    if value > 100000000000:
        value /= 1000

    return int(value) if value > 0 else 0


def format_upload_date(timestamp):
    if not timestamp:
        return ""

    try:
        return datetime.fromtimestamp(
            timestamp, timezone.utc
        ).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return ""


def get_description(item):
    value = item.get("description", "")
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def get_duration(item):
    try:
        return max(0, int(float(item.get("duration", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def select_video_urls(item):
    """
    Priorität:
      1. HD
      2. Standardqualität / SD
      3. LQ

    Die erste verfügbare URL wird für Stream und Download verwendet.
    """
    candidates = [
        ("HD", item.get("url_video_hd", "")),
        ("SD", item.get("url_video", "")),
        ("LQ", item.get("url_video_low", "")),
    ]

    valid = []
    seen = set()

    for quality, url in candidates:
        if not isinstance(url, str):
            continue

        url = url.strip()

        if not url.startswith(("https://", "http://")):
            continue

        if url in seen:
            continue

        seen.add(url)
        valid.append((quality, url))

    if not valid:
        return "", "", "N/A"

    quality, selected_url = valid[0]

    # Download und Stream verwenden exakt dieselbe Qualitätsstufe.
    return selected_url, selected_url, quality


def is_excluded(title, channel):
    title_lower = title.lower()
    channel_lower = channel.lower()

    if any(x in channel_lower for x in ("kika", "zdf-tivi")):
        return True

    if "tivi" in title_lower:
        return True

    exclusions = [
        r"audiodeskription",
        r"audio description",
        r"ad version",
        r"hörfilm",
        r"deskription",
        r"barrierefrei",
        r"\(englisch\)",
        r"\(zho\)",
        r"\(originalversion mit untertitel\)",
        r"\(mit untertitel\)",
        r"\(originalversion\)",
    ]

    if any(re.search(pattern, title_lower) for pattern in exclusions):
        return True

    if re.search(
        r"\b(folge|staffel|episode|ep\.)\b",
        title_lower,
    ):
        return True

    if re.search(r"\(\d+(?:\s*[/\-]\s*\d+)?\)", title):
        return True

    if re.search(r"\b\d{1,2}/\d{1,2}\b", title):
        return True

    return False


def fetch_mediathek_movies():
    """Sammelt Filme und entfernt Dubletten."""
    by_url = {}
    print("Starte MediathekViewWeb-Abfrage...")

    for query in QUERIES:
        payload = {
            "queries": [
                {
                    "fields": ["topic"],
                    "query": query,
                }
            ],
            "size": MAX_RESULTS_PER_QUERY,
            "sortBy": "timestamp",
            "sortOrder": "desc",
        }

        data = request_json(
            MEDIATHEK_URL,
            method="POST",
            payload=payload,
        )

        results = data.get("result", {}).get("results", [])

        if not results:
            with print_lock:
                print("Keine Ergebnisse für:", query)
            continue

        for item in results:
            raw_title = str(item.get("title", "") or "").strip()
            channel = str(item.get("channel", "") or "").strip()

            if not raw_title or is_excluded(raw_title, channel):
                continue

            duration = get_duration(item)
            if duration < MIN_DURATION:
                continue

            stream_url, download_url, quality = select_video_urls(item)

            if not stream_url:
                continue

            clean_name, title_year = clean_title(raw_title)

            if not clean_name or normalize_title(clean_name) == "no":
                continue

            description = get_description(item)

            # Das Jahr aus dem Titel ist ein Hinweis auf das
            # Produktionsjahr, nicht auf das Upload-Datum.
            production_year = title_year or ""

            timestamp = get_upload_timestamp(item)
            upload_date = format_upload_date(timestamp)

            entry = {
                "title": clean_name,
                "search": clean_name,
                "year": production_year,
                "production_year": production_year,

                "video_url": stream_url,
                "stream_url": stream_url,
                "download_url": download_url,
                "quality": quality,

                "plot": description or "Keine Beschreibung verfügbar.",
                "mediathek_desc": description,
                "duration": duration,
                "duration_seconds": duration,

                "director": "",
                "actors": [],
                "rating": "N/A",
                "thumb": PLACEHOLDER,
                "genres_list": ["Sonstige"],

                "channel": channel,
                "timestamp": timestamp,
                "upload_date": upload_date,
                "isNew": False,
            }

            # URL-Dubletten vermeiden; bei Wiederholung den
            # vollständigeren Datensatz behalten.
            previous = by_url.get(stream_url)

            if previous is None:
                by_url[stream_url] = entry
            else:
                if len(description) > len(previous["mediathek_desc"]):
                    previous["mediathek_desc"] = description
                    previous["plot"] = description

                if not previous.get("production_year") and production_year:
                    previous["production_year"] = production_year
                    previous["year"] = production_year

    movies = list(by_url.values())

    # Gleiche Titel können bei unterschiedlichen Sendern oder
    # Ausstrahlungen vorkommen. Nicht allein nach Titel deduplizieren.
    movies.sort(
        key=lambda movie: movie.get("timestamp", 0),
        reverse=True,
    )

    # Neue Filme ausschließlich anhand des Upload-Zeitstempels.
    newest_urls = {
        movie["video_url"] for movie in movies[:100]
    }

    for movie in movies:
        movie["isNew"] = movie["video_url"] in newest_urls

    return movies


# ---------------------------------------------------------
# TMDB-Suche und Matching
# ---------------------------------------------------------

@lru_cache(maxsize=4096)
def search_tmdb_cached(media_type, query, year):
    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
        "language": TMDB_LANGUAGE,
        "include_adult": "false",
    }

    if year:
        params["year" if media_type == "movie" else "first_air_date_year"] = year

    data = request_json(
        f"{TMDB_URL}/search/{media_type}",
        params=params,
    )

    return data.get("results", [])


def tokenize_description(text):
    if not text:
        return set()

    normalized = normalize_title(text)
    stopwords = {
        "und", "oder", "aber", "eine", "einer", "eines", "einem",
        "einen", "der", "die", "das", "den", "dem", "des", "ein",
        "im", "in", "am", "an", "auf", "aus", "mit", "von", "vom",
        "zum", "zur", "bei", "nach", "vor", "ueber", "unter", "ist",
        "sind", "war", "wird", "werden", "sich", "sein", "ihre",
        "seine", "ihren", "seinen", "als", "auch", "nicht", "noch",
        "nur", "doch", "dann", "wenn", "wie", "was", "wer", "mehr",
        "man", "kann", "koennen", "haben", "hat", "hatte", "einem",
    }

    return {
        word for word in normalized.split()
        if len(word) >= 4 and word not in stopwords
    }


def description_similarity(source_description, candidate_overview):
    source_words = tokenize_description(source_description)
    candidate_words = tokenize_description(candidate_overview)

    if not source_words or not candidate_words:
        return 0.0

    overlap = len(source_words & candidate_words)
    if not overlap:
        return 0.0

    # Jaccard verhindert, dass kurze generische Treffer zu stark wirken.
    union = len(source_words | candidate_words)
    return overlap / max(union, 1)


def candidate_score(movie, candidate, media_type):
    title_key = "name" if media_type == "tv" else "title"
    original_key = "original_name" if media_type == "tv" else "original_title"
    date_key = "first_air_date" if media_type == "tv" else "release_date"

    source_title = movie.get("search") or movie.get("title", "")
    source_year = (
        movie.get("production_year")
        or extract_year(movie.get("year", ""))
    )

    candidate_title = candidate.get(title_key, "")
    original_title = candidate.get(original_key, "")

    title_score = max(
        score_title(source_title, candidate_title),
        score_title(source_title, original_title),
    )

    candidate_date = candidate.get(date_key, "")
    candidate_year = candidate_date[:4] if candidate_date else ""

    # Ein gutes Titelmatch bleibt nötig. Das Jahr ist ein starkes
    # Zusatzkriterium, aber allein kein ausreichender Treffer.
    year_adjustment = 0

    if source_year and candidate_year:
        if source_year == candidate_year:
            year_adjustment = 18
        else:
            year_adjustment = -28

    desc_score = description_similarity(
        movie.get("mediathek_desc", ""),
        candidate.get("overview", ""),
    )

    # Beschreibung ist ein Hilfssignal, kein Ersatz für den Titel.
    description_adjustment = min(desc_score * 15, 8)

    total = title_score + year_adjustment + description_adjustment

    return total, title_score, candidate_year


def choose_best_result(results, movie, media_type):
    if not results:
        return None

    ranked = []

    for candidate in results:
        total, title_score, candidate_year = candidate_score(
            movie,
            candidate,
            media_type,
        )

        ranked.append((
            total,
            title_score,
            candidate_year,
            candidate,
        ))

    ranked.sort(key=lambda item: item[0], reverse=True)

    for total, title_score, candidate_year, candidate in ranked:
        # Bei kurzen oder generischen Titeln besonders streng sein.
        source_words = normalize_title(
            movie.get("search", "")
        ).split()

        minimum_title_score = 70 if len(source_words) <= 1 else 58

        if title_score < minimum_title_score:
            continue

        # Ein klarer Jahreskonflikt ist nur mit sehr starkem
        # Titelmatch akzeptabel.
        source_year = (
            movie.get("production_year")
            or extract_year(movie.get("year", ""))
        )

        if (
            source_year
            and candidate_year
            and source_year != candidate_year
            and title_score < 88
        ):
            continue

        if total >= 66:
            return candidate

    return None


def find_tmdb_match(movie):
    title = movie.get("search") or movie.get("title", "")
    year = (
        movie.get("production_year")
        or extract_year(movie.get("year", ""))
    )

    if not title:
        return None, ""

    # Erst Film mit Produktionsjahr, danach ohne Jahr suchen.
    movie_results = search_tmdb_cached("movie", title, year)

    match = choose_best_result(movie_results, movie, "movie")
    if match:
        return match, "movie"

    if year:
        movie_results = search_tmdb_cached("movie", title, "")
        match = choose_best_result(movie_results, movie, "movie")
        if match:
            return match, "movie"

    # Serien-/TV-Fallback nur bei fehlendem Spielfilm-Treffer.
    tv_results = search_tmdb_cached("tv", title, year)
    match = choose_best_result(tv_results, movie, "tv")
    if match:
        return match, "tv"

    if year:
        tv_results = search_tmdb_cached("tv", title, "")
        match = choose_best_result(tv_results, movie, "tv")
        if match:
            return match, "tv"

    return None, ""


# ---------------------------------------------------------
# TMDB-Details
# ---------------------------------------------------------

def get_tmdb_details(media_type, tmdb_id):
    params = {
        "api_key": TMDB_API_KEY,
        "language": TMDB_LANGUAGE,
        "append_to_response": "credits",
    }

    return request_json(
        f"{TMDB_URL}/{media_type}/{tmdb_id}",
        params=params,
    )


def hydrate_movie(movie):
    global processed_count

    try:
        tmdb, media_type = find_tmdb_match(movie)

        if not tmdb:
            movie["plot"] = (
                movie.get("mediathek_desc")
                or "Keine Beschreibung verfügbar."
            )
            movie["rating"] = "N/A"
            movie["thumb"] = PLACEHOLDER
            movie["tmdb_id"] = None
            movie["tmdb_media_type"] = ""
            return movie

        details = get_tmdb_details(media_type, tmdb["id"])

        # Bei einem temporären API-Fehler Suchdaten weiterverwenden.
        if not details:
            details = tmdb

        overview = (
            details.get("overview")
            or tmdb.get("overview")
            or movie.get("mediathek_desc")
            or "Keine Beschreibung verfügbar."
        )

        movie["plot"] = overview
        movie["tmdb_id"] = tmdb.get("id")
        movie["tmdb_media_type"] = media_type

        vote_avg = details.get("vote_average", tmdb.get("vote_average"))

        try:
            movie["rating"] = (
                f"{float(vote_avg):.1f}"
                if vote_avg is not None and float(vote_avg) > 0
                else "N/A"
            )
        except (ValueError, TypeError):
            movie["rating"] = "N/A"

        poster = details.get("poster_path") or tmdb.get("poster_path")
        movie["thumb"] = (
            f"{TMDB_IMAGE_URL}{poster}"
            if poster
            else PLACEHOLDER
        )

        credits = details.get("credits", {})
        crew = credits.get("crew", [])
        cast = credits.get("cast", [])

        director = next(
            (
                person.get("name", "")
                for person in crew
                if person.get("job") == "Director"
            ),
            "",
        )

        # Executive Producer nur als Ersatz verwenden, wenn kein
        # Regisseur eingetragen ist.
        if not director:
            director = next(
                (
                    person.get("name", "")
                    for person in crew
                    if person.get("job") == "Executive Producer"
                ),
                "",
            )

        movie["director"] = director
        movie["actors"] = [
            person["name"]
            for person in cast[:3]
            if person.get("name")
        ]

        date_str = (
            details.get("release_date")
            or details.get("first_air_date")
            or tmdb.get("release_date")
            or tmdb.get("first_air_date")
            or ""
        )

        tmdb_year = date_str[:4] if date_str else ""

        # Ein bereits aus dem Titel extrahiertes Produktionsjahr
        # wird nicht durch das Upload-Datum überschrieben.
        if not movie.get("production_year") and tmdb_year:
            movie["production_year"] = tmdb_year
            movie["year"] = tmdb_year

        genre_ids = details.get("genres")

        if isinstance(genre_ids, list) and genre_ids:
            genres = [
                genre.get("name", "")
                for genre in genre_ids
                if genre.get("name")
            ]
        else:
            genres = [
                GENRES_MAP[genre_id]
                for genre_id in tmdb.get("genre_ids", [])
                if genre_id in GENRES_MAP
            ]

        # Anime-Kennzeichnung nicht pauschal entfernen:
        # Genre-IDs bleiben erhalten, da Animation auch Spielfilme
        # umfassen kann.
        movie["genres_list"] = genres or ["Sonstige"]

    except Exception as exc:
        with print_lock:
            print(
                f"Fehler bei TMDB für "
                f"{movie.get('search', movie.get('title', ''))}: {exc}"
            )

        movie["plot"] = (
            movie.get("mediathek_desc")
            or "Keine Beschreibung verfügbar."
        )
        movie["rating"] = "N/A"
        movie["thumb"] = PLACEHOLDER
        movie.setdefault("genres_list", ["Sonstige"])

    finally:
        with print_lock:
            processed_count += 1

            if processed_count % 50 == 0:
                print(
                    f"Fortschritt: {processed_count} Filme verarbeitet..."
                )

    return movie


# ---------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------

def main():
    global processed_count
    processed_count = 0

    movies = fetch_mediathek_movies()

    # Upload-Zeitstempel steuert nur Sortierung und isNew.
    movies.sort(
        key=lambda movie: movie.get("timestamp", 0),
        reverse=True,
    )

    newest_urls = {
        movie["video_url"] for movie in movies[:100]
    }

    for movie in movies:
        movie["isNew"] = movie["video_url"] in newest_urls

    # Für die TMDB-Verarbeitung alphabetisch sortieren.
    movies.sort(
        key=lambda movie: normalize_title(movie.get("title", ""))
    )

    print(
        f"{len(movies)} Filme gefunden. "
        f"Starte optimierte TMDB-Zuordnung..."
    )

    hydrated_movies = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(hydrate_movie, movie): movie
            for movie in movies
        }

        for future in as_completed(futures):
            try:
                hydrated_movies.append(future.result())
            except Exception as exc:
                movie = futures[future]
                with print_lock:
                    print(
                        f"Verarbeitungsfehler für "
                        f"{movie.get('title', '')}: {exc}"
                    )

                movie["plot"] = (
                    movie.get("mediathek_desc")
                    or "Keine Beschreibung verfügbar."
                )
                movie["rating"] = "N/A"
                movie["thumb"] = PLACEHOLDER
                hydrated_movies.append(movie)

    hydrated_movies.sort(
        key=lambda movie: normalize_title(movie.get("title", ""))
    )

    output_dir = os.path.dirname(os.path.abspath(OUTPUT_FILE))
    os.makedirs(output_dir, exist_ok=True)

    temp_file = OUTPUT_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            hydrated_movies,
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(temp_file, OUTPUT_FILE)

    print(f"Fertig! {OUTPUT_FILE} erfolgreich gespeichert.")
    print(f"Filme insgesamt: {len(hydrated_movies)}")

    quality_counts = {"HD": 0, "SD": 0, "LQ": 0, "N/A": 0}

    for movie in hydrated_movies:
        quality = movie.get("quality", "N/A")
        quality_counts[quality] = quality_counts.get(quality, 0) + 1

    print(
        "Qualitätsverteilung: "
        + ", ".join(
            f"{quality}: {count}"
            for quality, count in quality_counts.items()
        )
    )


if __name__ == "__main__":
    main()
