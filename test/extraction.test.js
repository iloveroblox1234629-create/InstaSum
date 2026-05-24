import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildMarkdown,
  classifyInstagramUrl,
  createExtraction,
  createMarkdownFilename,
  extractInstagramUrls,
  summarizeInputs
} from "../src/extraction.js";

describe("extractInstagramUrls", () => {
  it("finds Instagram media URLs, removes igsh tracking, and preserves unrelated params", () => {
    const input = [
      "Watch https://www.instagram.com/reel/ABC123/?igsh=tracker&utm_source=share",
      "and https://instagram.com/p/XYZ789/?utm_campaign=keep"
    ].join("\n");

    assert.deepEqual(extractInstagramUrls(input), [
      "https://www.instagram.com/reel/ABC123/?utm_source=share",
      "https://instagram.com/p/XYZ789/?utm_campaign=keep"
    ]);
  });

  it("deduplicates URLs while keeping first-seen order", () => {
    const input = "https://www.instagram.com/reel/ABC/ https://www.instagram.com/reel/ABC/?igsh=again";

    assert.deepEqual(extractInstagramUrls(input), ["https://www.instagram.com/reel/ABC/"]);
  });
});

describe("classifyInstagramUrl", () => {
  it("classifies Reels, posts, TV URLs, and unsupported Instagram pages", () => {
    assert.equal(classifyInstagramUrl("https://www.instagram.com/reel/ABC/"), "reel");
    assert.equal(classifyInstagramUrl("https://www.instagram.com/p/ABC/"), "post");
    assert.equal(classifyInstagramUrl("https://www.instagram.com/tv/ABC/"), "video");
    assert.equal(classifyInstagramUrl("https://www.instagram.com/accounts/login/"), "unsupported");
  });
});

describe("summarizeInputs", () => {
  it("creates role-aware sections from caption, transcript, and visual text", () => {
    const summary = summarizeInputs({
      role: "creator",
      caption: "Steal this retention hook for your next launch. Save it for later.",
      transcript: "Start with the surprising result, then explain the three steps.",
      visualText: "Hook: nobody reads your launch post. Step 1: prove the pain."
    });

    assert.match(summary.hook, /retention hook|nobody reads/i);
    assert.ok(summary.takeaways.some((item) => /surprising result|three steps|prove the pain/i.test(item)));
    assert.ok(summary.creatorNotes.some((item) => /hook|CTA|pattern/i.test(item)));
  });
});

describe("createExtraction", () => {
  it("returns one extraction card per URL with summaries and export metadata", () => {
    const result = createExtraction({
      rawUrls: "https://www.instagram.com/reel/ABC/?igsh=tracker\nhttps://www.instagram.com/p/XYZ/",
      role: "researcher",
      caption: "A reel about AI notes.",
      transcript: "The speaker explains searchable summaries and Markdown export.",
      visualText: "Export: Notion, Obsidian, Sheets"
    });

    assert.equal(result.items.length, 2);
    assert.equal(result.items[0].type, "reel");
    assert.equal(result.items[1].type, "post");
    assert.ok(result.items[0].tags.includes("ai"));
    assert.ok(result.items[0].markdown.includes("## Hook"));
  });
});

describe("buildMarkdown", () => {
  it("includes URL, type, role, hook, visual context, and tags", () => {
    const markdown = buildMarkdown({
      url: "https://www.instagram.com/reel/ABC/",
      type: "reel",
      role: "student",
      summary: {
        hook: "A fast way to capture Reel notes.",
        takeaways: ["Paste the link.", "Add transcript.", "Export Markdown."],
        visualContext: ["Screen text mentions Notion."],
        actions: ["Save to notes."],
        creatorNotes: []
      },
      tags: ["notes", "markdown"]
    });

    assert.match(markdown, /# Instagram Reel Summary/);
    assert.match(markdown, /https:\/\/www\.instagram\.com\/reel\/ABC\//);
    assert.match(markdown, /Screen text mentions Notion/);
    assert.match(markdown, /notes, markdown/);
  });
});

describe("createMarkdownFilename", () => {
  it("uses a readable hook-based filename with the Instagram media type", () => {
    assert.equal(
      createMarkdownFilename({
        type: "reel",
        summary: { hook: "Hook: nobody reads your launch post!" }
      }),
      "reel-hook-nobody-reads-your-launch-post.md"
    );
  });
});
