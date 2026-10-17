
const CACHE_TTL = 60 * 60 * 24 * 7;
const ALLOWED_ORIGINS = [
  "https://chrisophy.github.io",
  "http://localhost"
];

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.includes(origin)
      ? origin
      : ALLOWED_ORIGINS[0],
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=3600",
    "Content-Type": "application/json; charset=utf-8"
  };
}

function json(data, origin, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: corsHeaders(origin)
  });
}

function decodeHtml(value = "") {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#x([0-9a-f]+);/gi, (_, h) =>
      String.fromCodePoint(parseInt(h, 16))
    )
    .replace(/&#(\d+);/g, (_, n) =>
      String.fromCodePoint(parseInt(n, 10))
    )
    .trim();
}

function getMeta(html, key, attribute = "property") {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(
    `<meta\\b(?=[^>]*\\b${attribute}\\s*=\\s*["']${escaped}["'])[^>]*>`,
    "i"
  );
  const tag = html.match(pattern)?.[0] || "";
  const content = tag.match(/\bcontent\s*=\s*["']([^"']*)["']/i);
  return content ? decodeHtml(content[1]) : "";
}

function cleanText(value) {
  return decodeHtml(String(value || ""))
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalize(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9äöüß]+/g, " ")
    .trim();
}

function findFilmUrls(html, title) {
  const found = new Set();
  const re = /(?:https?:\/\/www\.zdf\.de)?(\/filme\/[^"'?#\s<>]+)/gi;
  let match;

  while ((match = re.exec(html)) !== null) {
    const path = decodeHtml(match[1]);
    if (path.length > 10) {
      found.add("https://www.zdf.de" + path);
    }
  }

  const target = normalize(title);
  return [...found]
    .map(url => {
      const slug = normalize(url.split("/").pop().replace(/-\d+$/, ""));
      const words = target.split(" ").filter(w => w.length > 2);
      const score = words.reduce((sum, word) =>
        sum + (slug.includes(word) ? 1 : 0), 0);
      return { url, score };
    })
    .sort((a, b) => b.score - a.score)
    .filter(item => item.score > 0)
    .slice(0, 5)
    .map(item => item.url);
}

function findJsonLd(html) {
  const matches = html.matchAll(
    /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi
  );

  for (const match of matches) {
    try {
      const parsed = JSON.parse(match[1]);
      const queue = Array.isArray(parsed) ? [...parsed] : [parsed];

      while (queue.length) {
        const item = queue.shift();
        if (!item || typeof item !== "object") continue;
        if (Array.isArray(item)) {
          queue.push(...item);
          continue;
        }

        if (
          item["@type"] &&
          /movie|creativework|tvfilm/i.test(
            Array.isArray(item["@type"])
              ? item["@type"].join(" ")
              : item["@type"]
          )
        ) {
          return item;
        }

        if (item["@graph"]) queue.push(...item["@graph"]);
      }
    } catch (_) {}
  }

  return {};
}

function namesFrom(value) {
  if (!value) return [];
  const list = Array.isArray(value) ? value : [value];
  return list
    .map(item => typeof item === "string" ? item : item?.name)
    .filter(Boolean)
    .slice(0, 10);
}

async function fetchPage(url) {
  const response = await fetch(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 (compatible; GEZ-KiNO/1.0)",
      "Accept": "text/html,application/xhtml+xml",
      "Accept-Language": "de-DE,de;q=0.9"
    },
    redirect: "follow"
  });

  if (!response.ok) {
    throw new Error(`ZDF antwortete mit HTTP ${response.status}`);
  }

  return {
    url: response.url,
    html: await response.text()
  };
}

async function getDetails(title) {
  const searchUrl =
    "https://www.zdf.de/suche?q=" + encodeURIComponent(title);

  const search = await fetchPage(searchUrl);
  const urls = findFilmUrls(search.html, title);

  // Nur echte ZDF-Filmseiten öffnen, keine beliebigen URLs.
  for (const url of urls) {
    try {
      const page = await fetchPage(url);
      const html = page.html;
      const ld = findJsonLd(html);

      const ogTitle = getMeta(html, "og:title");
      const description =
        getMeta(html, "og:description") ||
        getMeta(html, "description", "name") ||
        cleanText(ld.description);

      const image =
        getMeta(html, "og:image") ||
        cleanText(ld.image?.url || ld.image);

      const date = ld.datePublished || ld.dateCreated || "";
      const yearMatch = String(date).match(/\b(19\d{2}|20\d{2})\b/);

      const director = namesFrom(ld.director);
      const actors = namesFrom(ld.actor || ld.actors);
      const genres = namesFrom(ld.genre);

      // Wenn die Suche einen völlig unpassenden Treffer lieferte,
      // diesen nicht als Ergebnis zurückgeben.
      const pageTitle = normalize(ogTitle || ld.name || "");
      const wantedWords = normalize(title)
        .split(" ")
        .filter(word => word.length > 2);

      const matchedWords = wantedWords.filter(word =>
        pageTitle.includes(word)
      ).length;

      if (wantedWords.length && matchedWords === 0) continue;

      return {
        found: true,
        title: cleanText(ogTitle || ld.name || title),
        url: page.url,
        thumb: image.startsWith("https://") ? image : "",
        plot: cleanText(description),
        year: yearMatch ? yearMatch[1] : "",
        director: director[0] || "",
        actors,
        genres,
        rating: ld.aggregateRating?.ratingValue
          ? String(ld.aggregateRating.ratingValue)
          : ""
      };
    } catch (_) {
      // Ein nicht erreichbarer Treffer soll die Suche nicht abbrechen.
    }
  }

  return { found: false, title };
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(origin)
      });
    }

    const requestUrl = new URL(request.url);

    if (request.method !== "GET") {
      return json({ error: "Nur GET wird unterstützt." }, origin, 405);
    }

    if (requestUrl.pathname !== "/" && requestUrl.pathname !== "/zdf") {
      return json({ error: "Unbekannter Endpunkt." }, origin, 404);
    }

    if (origin && !ALLOWED_ORIGINS.includes(origin)) {
      return json({ error: "Origin nicht erlaubt." }, origin, 403);
    }

    const title = (requestUrl.searchParams.get("title") || "").trim();

    if (!title || title.length > 180) {
      return json({ error: "Bitte einen gültigen Filmtitel angeben." }, origin, 400);
    }

    const cache = caches.default;
    const cacheUrl = new URL(request.url);
    cacheUrl.searchParams.set("title", normalize(title));

    const cacheKey = new Request(cacheUrl.toString(), { method: "GET" });
    const cached = await cache.match(cacheKey);

    if (cached) {
      const data = await cached.json();
      return json(data, origin);
    }

    try {
      const data = await getDetails(title);

      const cacheResponse = new Response(JSON.stringify(data), {
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": `public, max-age=${CACHE_TTL}`
        }
      });

      ctx.waitUntil(cache.put(cacheKey, cacheResponse));
      return json(data, origin);
    } catch (error) {
      return json({
        found: false,
        error: "ZDF konnte momentan nicht abgefragt werden."
      }, origin, 502);
    }
  }
};
