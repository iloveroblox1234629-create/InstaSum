import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createExtractionFromUrls, extractInstagramPage, createInstagramHeaders } from "../netlify/functions/extract.js";

const sampleInstagramHtml = `
  <!doctype html>
  <html>
    <head>
      <title>Creator on Instagram: "Steal this retention hook"</title>
      <meta property="og:title" content="Creator on Instagram: &quot;Steal this retention hook&quot;">
      <meta property="og:description" content="1,204 likes, 30 comments - Creator on January 1, 2026: &quot;Steal this retention hook for your next launch. Save it for later.&quot;">
      <meta property="og:image" content="https://cdn.example.test/reel.jpg">
    </head>
  </html>
`;

const spacedAttributeHtml = `
  <!doctype html>
  <html>
    <head>
      <meta property = "og:title" content = "Creator on Instagram: &quot;Whitespace attributes&quot;">
      <meta property = "og:description" content = "99 likes, 2 comments - Creator on May 25, 2026: &quot;Whitespace metadata still extracts.&quot;">
    </head>
  </html>
`;

describe("extractInstagramPage", () => {
  it("fetches and parses public Instagram page metadata", async () => {
    const page = await extractInstagramPage("https://www.instagram.com/reel/ABC/", {
      fetchPage: async () => sampleInstagramHtml
    });

    assert.equal(page.ok, true);
    assert.equal(page.title, 'Creator on Instagram: "Steal this retention hook"');
    assert.equal(page.caption, "Steal this retention hook for your next launch. Save it for later.");
    assert.equal(page.image, "https://cdn.example.test/reel.jpg");
    assert.equal(page.source, "instagram-page");
  });

  it("returns an explicit extraction failure when Instagram cannot be fetched", async () => {
    const page = await extractInstagramPage("https://www.instagram.com/reel/LOCKED/", {
      fetchPage: async () => {
        throw new Error("HTTP 403");
      }
    });

    assert.equal(page.ok, false);
    assert.equal(page.error, "Instagram rejected the supplied session or rate-limited the request.");
  });

  it("parses metadata when HTML attributes contain spaces around equals signs", async () => {
    const page = await extractInstagramPage("https://www.instagram.com/reel/SPACED/", {
      fetchPage: async () => spacedAttributeHtml
    });

    assert.equal(page.ok, true);
    assert.equal(page.caption, "Whitespace metadata still extracts.");
  });

  it("passes user-provided Instagram tokens as request cookies", async () => {
    let observedHeaders = {};
    const page = await extractInstagramPage("https://www.instagram.com/reel/PRIVATE/", {
      auth: {
        sessionId: "session-token",
        csrfToken: "csrf-token",
        userId: "12345"
      },
      fetchPage: async (_url, options) => {
        observedHeaders = options.headers;
        return sampleInstagramHtml;
      }
    });

    assert.equal(page.ok, true);
    assert.match(observedHeaders.cookie, /sessionid=session-token/);
    assert.match(observedHeaders.cookie, /csrftoken=csrf-token/);
    assert.match(observedHeaders.cookie, /ds_user_id=12345/);
    assert.equal(observedHeaders["x-csrftoken"], "csrf-token");
  });

  it("does not return image URLs from authenticated Instagram fetches", async () => {
    const page = await extractInstagramPage("https://www.instagram.com/reel/PRIVATE/", {
      auth: {
        sessionId: "session-token"
      },
      fetchPage: async () => sampleInstagramHtml
    });

    assert.equal(page.ok, true);
    assert.equal(page.image, "");
  });
});

describe("createInstagramHeaders", () => {
  it("omits cookie headers when tokens are blank", () => {
    const headers = createInstagramHeaders({ sessionId: "", csrfToken: "", userId: "" });

    assert.equal(headers.cookie, undefined);
    assert.equal(headers["x-csrftoken"], undefined);
  });

  it("preserves opaque cookie token values after validation", () => {
    const headers = createInstagramHeaders({ sessionId: "token%3Awith/slash", csrfToken: "csrf/value" });

    assert.match(headers.cookie, /sessionid=token%3Awith\/slash/);
    assert.match(headers.cookie, /csrftoken=csrf\/value/);
  });

  it("rejects token values that cannot be safely sent as cookie headers", () => {
    assert.throws(
      () => createInstagramHeaders({ sessionId: "token;\ninjected=true" }),
      /unsupported characters/
    );
  });
});

describe("createExtractionFromUrls", () => {
  it("creates summaries from fetched Instagram metadata without user-provided transcript", async () => {
    const result = await createExtractionFromUrls({
      rawUrls: "https://www.instagram.com/reel/ABC/?igsh=tracker",
      role: "creator",
      fetchPage: async () => sampleInstagramHtml
    });

    assert.equal(result.items.length, 1);
    assert.equal(result.items[0].url, "https://www.instagram.com/reel/ABC/");
    assert.equal(result.items[0].extraction.ok, true);
    assert.match(result.items[0].summary.hook, /retention hook/i);
    assert.match(result.items[0].markdown, /Extracted Caption/);
  });

  it("forwards private access tokens without storing them in result items", async () => {
    let cookieHeader = "";
    const result = await createExtractionFromUrls({
      rawUrls: "https://www.instagram.com/reel/PRIVATE/",
      instagramSessionId: "session-token",
      instagramCsrfToken: "csrf-token",
      instagramUserId: "12345",
      fetchPage: async (_url, options) => {
        cookieHeader = options.headers.cookie;
        return sampleInstagramHtml;
      }
    });

    assert.match(cookieHeader, /sessionid=session-token/);
    assert.equal(JSON.stringify(result.items).includes("session-token"), false);
    assert.equal(JSON.stringify(result.items).includes("csrf-token"), false);
  });

  it("limits each extraction request to five URLs", async () => {
    let fetches = 0;
    const result = await createExtractionFromUrls({
      rawUrls: [
        "https://www.instagram.com/reel/A/",
        "https://www.instagram.com/reel/B/",
        "https://www.instagram.com/reel/C/",
        "https://www.instagram.com/reel/D/",
        "https://www.instagram.com/reel/E/",
        "https://www.instagram.com/reel/F/"
      ].join("\n"),
      fetchPage: async () => {
        fetches += 1;
        return sampleInstagramHtml;
      }
    });

    assert.equal(result.items.length, 5);
    assert.equal(fetches, 5);
  });

  it("fetches batch URLs concurrently instead of serially", async () => {
    let active = 0;
    let maxActive = 0;
    const result = await createExtractionFromUrls({
      rawUrls: [
        "https://www.instagram.com/reel/A/",
        "https://www.instagram.com/reel/B/",
        "https://www.instagram.com/reel/C/"
      ].join("\n"),
      fetchPage: async () => {
        active += 1;
        maxActive = Math.max(maxActive, active);
        await new Promise((resolve) => setTimeout(resolve, 5));
        active -= 1;
        return sampleInstagramHtml;
      }
    });

    assert.equal(result.items.length, 3);
    assert.ok(maxActive > 1);
  });
});
