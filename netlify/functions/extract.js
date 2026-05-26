import { buildMarkdown, createExtraction, extractInstagramUrls } from "../../src/extraction.js";

export async function handler(event, options = {}) {
  if (event.httpMethod !== "POST") {
    return response(405, { error: "Use POST." });
  }

  try {
    const payload = JSON.parse(event.body || "{}");
    const result = payload.extractRemote === false
      ? createExtraction(payload)
      : await createExtractionFromUrls({ ...payload, ...options });
    return response(200, result);
  } catch (error) {
    return response(400, { error: error instanceof Error ? error.message : "Invalid request." });
  }
}

export async function createExtractionFromUrls({
  rawUrls = "",
  role = "researcher",
  caption = "",
  transcript = "",
  visualText = "",
  instagramSessionId = "",
  instagramCsrfToken = "",
  instagramUserId = "",
  fetchPage = defaultFetchPage
} = {}) {
  const urls = extractInstagramUrls(rawUrls).slice(0, 5);
  const auth = {
    sessionId: instagramSessionId,
    csrfToken: instagramCsrfToken,
    userId: instagramUserId
  };
  const items = await Promise.all(urls.map(async (url) => {
    const page = await extractInstagramPage(url, { auth, fetchPage });
    const extractedCaption = page.ok ? page.caption : "";
    const extractedTitle = page.ok ? page.title : "";
    const extractionText = [extractedCaption, caption].filter(Boolean).join("\n");
    const extractionVisualText = [
      extractedTitle ? `Page title: ${extractedTitle}` : "",
      visualText
    ].filter(Boolean).join("\n");
    const result = createExtraction({
      rawUrls: url,
      role,
      caption: extractionText,
      transcript,
      visualText: extractionVisualText
    });
    const item = result.items[0];
    if (item) {
      item.extraction = page;
      item.markdown = buildMarkdown({
        url: item.url,
        type: item.type,
        role: item.role,
        summary: item.summary,
        tags: item.tags,
        extraction: page
      });
      return item;
    }
    return null;
  }));

  return { items: items.filter(Boolean) };
}

export async function extractInstagramPage(url, { auth = {}, fetchPage = defaultFetchPage } = {}) {
  try {
    const headers = createInstagramHeaders(auth);
    const html = await fetchPage(url, { headers });
    const title = readMeta(html, "og:title") || readTitle(html);
    const description = readMeta(html, "og:description") || "";
    const image = readMeta(html, "og:image") || "";
    const caption = cleanInstagramCaption(description || title);

    if (!title && !description) {
      return {
        ok: false,
        source: "instagram-page",
        error: "No public Instagram metadata found. The post may require login, be private, or be blocked from server-side extraction."
      };
    }

    return {
      ok: true,
      source: "instagram-page",
      title,
      caption,
      description,
      image
    };
  } catch (error) {
    return {
      ok: false,
      source: "instagram-page",
      error: sanitizeExtractionError(error)
    };
  }
}

async function defaultFetchPage(url, { headers = createInstagramHeaders({}) } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const page = await fetch(url, {
      headers,
      signal: controller.signal
    });
    if (!page.ok) {
      throw new Error(`Instagram returned HTTP ${page.status}`);
    }
    return page.text();
  } finally {
    clearTimeout(timeout);
  }
}

export function createInstagramHeaders({ sessionId = "", csrfToken = "", userId = "" } = {}) {
  const headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": "Mozilla/5.0 (compatible; InstaBrief/0.1; +https://kaleidoscopic-flan-89e32b.netlify.app)"
  };
  const cookies = [
    cookiePair("sessionid", sessionId),
    cookiePair("csrftoken", csrfToken),
    cookiePair("ds_user_id", userId)
  ].filter(Boolean);
  if (cookies.length) {
    headers.cookie = cookies.join("; ");
  }
  if (csrfToken.trim()) {
    headers["x-csrftoken"] = csrfToken.trim();
  }
  return headers;
}

function cookiePair(name, value) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  assertSafeToken(trimmed);
  return `${name}=${trimmed}`;
}

function assertSafeToken(value) {
  if (/[\r\n;]/.test(value)) {
    throw new Error("Instagram session token contains unsupported characters.");
  }
}

function sanitizeExtractionError(error) {
  const message = error instanceof Error ? error.message : "";
  if (/HTTP\s+(401|403|429)/i.test(message)) {
    return "Instagram rejected the supplied session or rate-limited the request.";
  }
  if (/unsupported characters/i.test(message)) {
    return "Instagram session token contains unsupported characters.";
  }
  return message || "Instagram extraction failed.";
}

function readMeta(html, property) {
  const escaped = property.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const metaPattern = new RegExp(`<meta\\s+[^>]*(?:property|name)\\s*=\\s*["']${escaped}["'][^>]*>`, "i");
  const tag = html.match(metaPattern)?.[0] ?? "";
  return decodeHtml(readAttribute(tag, "content"));
}

function readTitle(html) {
  return decodeHtml(html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? "");
}

function readAttribute(tag, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return tag.match(new RegExp(`${escaped}\\s*=\\s*["']([^"']*)["']`, "i"))?.[1] ?? "";
}

function cleanInstagramCaption(text) {
  return decodeHtml(text)
    .replace(/^[\d,.]+\s+likes?,\s+[\d,.]+\s+comments?\s+-\s+[^:]+:\s*/i, "")
    .replace(/^.*? on Instagram:\s*/i, "")
    .replace(/^["“]|["”]$/g, "")
    .trim();
}

function decodeHtml(value) {
  return value
    .replace(/&quot;/g, "\"")
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .trim();
}

function response(statusCode, body) {
  return {
    statusCode,
    headers: {
      "content-type": "application/json; charset=utf-8"
    },
    body: JSON.stringify(body)
  };
}
