# -*- coding: utf-8 -*-
import json
import requests
import feedparser
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CATEGORIES = {
    "Top-News": "https://www.bild.de/feed/alles.xml",
    "Politik": "https://www.bild.de/rss-feeds/rss-16725492,feed=politik.bild.html",
    "News": "https://www.bild.de/rss-feeds/rss-16725492,feed=news.bild.html",
    "Sport": "https://www.bild.de/rss-feeds/rss-16725492,feed=sport.bild.html",
    "Unterhaltung": "https://www.bild.de/rss-feeds/rss-16725492,feed=unterhaltung.bild.html",
    "Lifestyle": "https://www.bild.de/rss-feeds/rss-16725492,feed=lifestyle.bild.html",
    "Auto": "https://www.bild.de/rss-feeds/rss-16725492,feed=auto.bild.html",
    "Ratgeber": "https://www.bild.de/rss-feeds/rss-16725492,feed=ratgeber.bild.html",
}

def get_article_text(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(response.text, "html.parser")
        article_text = []
        selectors = [
            'article p', '.article-body p', '.txt p', 
            '.post-content p', '[data-key="article"] p'
        ]
        for selector in selectors:
            paragraphs = soup.select(selector)
            if paragraphs:
                for p in paragraphs:
                    text = p.get_text(" ", strip=True)
                    if len(text) > 40 and "In App öffnen" not in text:
                        article_text.append(text)
                if article_text:
                    break
        
        if not article_text:
            return "Volltext konnte nicht automatisch geladen werden. Bitte nutze den Link unten, um direkt zu BILD.de zu gelangen."
            
        cleaned = []
        for line in article_text:
            if line not in cleaned:
                cleaned.append(line)
        return "\n\n".join(cleaned)
    except Exception as e:
        return f"Fehler beim Scrapen des Volltextes: {str(e)}"

def build_news_json():
    compiled_news = []
    seen_links = set()
    
    print("Starte Aggregation der BILD-RSS-Feeds...")
    
    for category_name, feed_url in CATEGORIES.items():
        print(f"Verarbeite Kategorie: {category_name}")
        feed = feedparser.parse(feed_url)
        
        # Um die Actions-Laufzeit flach zu halten, limitieren wir auf max 15 frische Artikel pro Kategorie
        for entry in feed.entries[:15]:
            link = entry.get("link", "")
            if not link or link in seen_links:
                continue
                
            title = entry.get("title", "Ohne Titel")
            summary = entry.get("summary", "")
            
            # Volltext über deinen Kodi-Scraper holen
            print(f" -> Scrape Text für: {title[:40]}...")
            full_text = get_article_text(link)
            
            # Struktur exakt an index.html Render-Pipeline anpassen
            article_node = {
                "title": title,
                "plot": summary if summary else "Keine Kurzbeschreibung verfügbar.",
                "text": full_text,
                "video_url": link,  # Zweckentfremdet als eindeutige ID / Link
                "thumb": "https://www.bild.de/favicon.ico", # Uniformes Icon für Stabilität
                "rating": "BILD",
                "channel": "BILD",
                "year": "Heute",
                "genres_list": [category_name],
                "category": category_name
            }
            
            compiled_news.append(article_node)
            seen_links.add(link)
            
    # Als news.json speichern
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(compiled_news, f, ensure_ascii=False, indent=2)
    print("Zusammenfassung erfolgreich! news.json wurde geschrieben.")

if __name__ == '__main__':
    build_news_json()
