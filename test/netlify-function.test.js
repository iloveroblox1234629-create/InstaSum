import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { handler } from "../netlify/functions/extract.js";

describe("extract function", () => {
  it("rejects non-POST requests", async () => {
    const response = await handler({ httpMethod: "GET" });

    assert.equal(response.statusCode, 405);
    assert.deepEqual(JSON.parse(response.body), { error: "Use POST." });
  });

  it("rejects invalid JSON payloads", async () => {
    const response = await handler({ httpMethod: "POST", body: "{" });

    assert.equal(response.statusCode, 400);
    assert.match(JSON.parse(response.body).error, /JSON|Expected/i);
  });

  it("returns extraction items for valid POST requests", async () => {
    const response = await handler({
      httpMethod: "POST",
      body: JSON.stringify({
        rawUrls: "https://www.instagram.com/reel/ABC/?igsh=tracker",
        extractRemote: false,
        caption: "AI note workflow",
        transcript: "Export the result to Markdown.",
        visualText: "Hook: organize saved Reels."
      })
    });

    const body = JSON.parse(response.body);
    assert.equal(response.statusCode, 200);
    assert.equal(body.items.length, 1);
    assert.equal(body.items[0].url, "https://www.instagram.com/reel/ABC/");
    assert.match(body.items[0].markdown, /## Hook/);
  });

  it("uses the default remote extraction path called by the browser", async () => {
    const response = await handler({
      httpMethod: "POST",
      body: JSON.stringify({
        rawUrls: "https://www.instagram.com/reel/ABC/?igsh=tracker"
      })
    }, {
      fetchPage: async () => `
        <meta property="og:title" content="Creator on Instagram: &quot;Remote hook&quot;">
        <meta property="og:description" content="10 likes, 1 comments - Creator on May 25, 2026: &quot;Remote caption extracted.&quot;">
      `
    });

    const body = JSON.parse(response.body);
    assert.equal(response.statusCode, 200);
    assert.equal(body.items[0].extraction.ok, true);
    assert.match(body.items[0].markdown, /Remote caption extracted/);
  });
});
