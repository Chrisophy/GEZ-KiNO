import json
import re
import requests

# Offizielle MediathekViewWeb API (kostenlos & ohne Token)
MVW_API_URL = 'https://mediathekviewweb.de/api/query'


def parse_duration_to_seconds(val):
  """Wandelt verschiedene Duration-Formate (Int, Float, String, ISO-8601) sicher in Sekunden um."""
  if val is None:
    return 0

  if isinstance(val, (int, float)):
    return float(val)

  if isinstance(val, str):
    val = val.strip()
    if val.isdigit():
      return float(val)

    # Fallback für ISO-8601 Strings (z.B. PT1H30M)
    match_h = re.search(r'(\d+)H', val)
    match_m = re.search(r'(\d+)M', val)
    match_s = re.search(r'(\d+)S', val)

    hours = int(match_h.group(1)) if match_h else 0
    minutes = int(match_m.group(1)) if match_m else 0
    seconds = int(match_s.group(1)) if match_s else 0

    if hours > 0 or minutes > 0 or seconds > 0:
      return (hours * 3600) + (minutes * 60) + seconds

  return 0


def fetch_all_films():
  print(
      'Frage MediathekViewWeb-API ab (Mit automatischer Paginierung für >1000'
      ' Einträge)...'
  )

  all_results = []
  offset = 0
  batch_size = 1000  # Maximal erlaubter Wert pro Anfrage

  while True:
    payload = {
        'queries': [{
            'fields': ['title', 'topic'],
            'query': 'Film',
        }],
        'sortBy': 'duration',
        'sortOrder': 'desc',
        'size': batch_size,
        'offset': offset,
    }

    try:
      response = requests.post(
          MVW_API_URL,
          data=json.dumps(payload),
          headers={'Content-Type': 'text/plain'},
          timeout=25,
      )

      if response.status_code == 200:
        data = response.json()
        results = data.get('result', {}).get('results', [])

        if not results:
          break

        all_results.extend(results)
        print(
            f'   -> Batch ab Offset {offset} geladen: {len(results)} Einträge'
            f' (Gesamt bisher: {len(all_results)})'
        )

        if len(results) < batch_size:
          break

        offset += batch_size
      else:
        print(f'   -> Fehler bei Offset {offset}: {response.text[:300]}')
        break

    except Exception as e:
      print(f'   -> Exception bei Offset {offset}: {e}')
      break

  print(
      f'   -> Fertig! Insgesamt {len(all_results)} Roh-Einträge von der API'
      ' geladen.'
  )
  return all_results


def main():
  raw_items = fetch_all_films()

  if not raw_items:
    print('\n[!] Keine Einträge gefunden.')
    return

  print('\nVerarbeite und filtere alle Filme ab 78 Minuten...\n')
  print('-' * 60)

  films_data = []
  count = 0

  for item in raw_items:
    duration_secs = parse_duration_to_seconds(item.get('duration', 0))
    duration_mins = round(duration_secs / 60)

    # Filter: Nur Filme ab 78 Minuten (>= 4680 Sekunden)
    if duration_mins >= 78:
      count += 1
      title = item.get('title', 'Unbekannter Titel')
      topic = item.get('topic', '')
      channel = item.get('channel', 'Unbekannt')
      description = item.get('description', '')
      date = item.get('date', '')

      # URLs & Streams
      url_web = item.get('url_website', '')
      url_stream = item.get(
          'url_video', item.get('url', item.get('url_video_hd', ''))
      )
      url_stream_hd = item.get('url_video_hd', '')
      url_stream_low = item.get('url_video_low', '')

      # Poster / Thumbnail
      poster_url = (
          item.get('thumbnail_url')
          or item.get('image_url')
          or item.get('poster_url')
          or ''
      )

      full_title = f'{topic} - {title}' if topic else title

      # Strukturiertes Dictionary für JSON
      film_entry = {
          'id': item.get('id'),
          'channel': channel,
          'topic': topic,
          'title': title,
          'full_title': full_title,
          'duration_minutes': duration_mins,
          'duration_seconds': duration_secs,
          'date': date,
          'description': description,
          'url_website': url_web,
          'url_stream': url_stream,
          'url_stream_hd': url_stream_hd,
          'url_stream_low': url_stream_low,
          'url_poster': poster_url,
      }

      films_data.append(film_entry)

  # Export als zdfm.json
  filename = 'zdfm.json'
  with open(filename, 'w', encoding='utf-8') as f:
    json.dump(films_data, f, ensure_ascii=False, indent=2)

  print(
      f'\nFertig! Insgesamt {len(films_data)} Filme (ab 78 Minuten) erfolgreich'
      f' in "{filename}" gespeichert.'
  )


if __name__ == '__main__':
  main()
