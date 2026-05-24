const INSTAGRAM_MEDIA_URL_RE = /https?:\/\/(?:www\.)?instagram\.com\/(?:reel|reels|p|tv)\/[A-Za-z0-9_.-]+\/?(?:\?[^)\]\s"'<>]*)?/gi;
const STOP_WORDS = new Set([
  "about",
  "after",
  "again",
  "also",
  "and",
  "are",
  "but",
  "for",
  "from",
  "has",
  "have",
  "into",
  "later",
  "that",
  "the",
  "this",
  "then",
  "they",
  "with",
  "your"
]);

export function extractInstagramUrls(text = "") {
  const urls = text.match(INSTAGRAM_MEDIA_URL_RE) ?? [];
  const seen = new Set();
  const normalized = [];

  for (const url of urls) {
    const cleaned = normalizeInstagramUrl(url);
    if (!seen.has(cleaned)) {
      seen.add(cleaned);
      normalized.push(cleaned);
    }
  }

  return normalized;
}

export function classifyInstagramUrl(url) {
  const pathname = safeUrl(url)?.pathname ?? "";
  if (pathname.startsWith("/reel/") || pathname.startsWith("/reels/")) {
    return "reel";
  }
  if (pathname.startsWith("/p/")) {
    return "post";
  }
  if (pathname.startsWith("/tv/")) {
    return "video";
  }
  return "unsupported";
}

export function createExtraction({ rawUrls = "", role = "researcher", caption = "", transcript = "", visualText = "" } = {}) {
  const urls = extractInstagramUrls(rawUrls);
  const summary = summarizeInputs({ role, caption, transcript, visualText });
  const tags = createTags([caption, transcript, visualText].join(" "));

  return {
    items: urls.map((url) => {
      const type = classifyInstagramUrl(url);
      return {
        url,
        type,
        role,
        summary,
        tags,
        filename: createMarkdownFilename({ type, summary }),
        markdown: buildMarkdown({ url, type, role, summary, tags })
      };
    })
  };
}

export function summarizeInputs({ role = "researcher", caption = "", transcript = "", visualText = "" } = {}) {
  const captionSentences = splitSentences(caption);
  const transcriptSentences = splitSentences(transcript);
  const visualSentences = splitSentences(visualText);
  const allSentences = [...captionSentences, ...transcriptSentences, ...visualSentences];

  return {
    hook: chooseHook([...visualSentences, ...captionSentences, ...transcriptSentences]),
    takeaways: chooseTakeaways(allSentences),
    visualContext: visualSentences.slice(0, 3),
    actions: chooseActions(allSentences),
    creatorNotes: buildRoleNotes(role, allSentences)
  };
}

export function buildMarkdown({ url, type, role, summary, tags }) {
  const titleType = type === "reel" ? "Reel" : type === "post" ? "Post" : "Video";
  return [
    `# Instagram ${titleType} Summary`,
    "",
    `- URL: ${url}`,
    `- Type: ${type}`,
    `- Role: ${role}`,
    `- Tags: ${tags.join(", ") || "untagged"}`,
    "",
    "## Hook",
    summary.hook || "No hook detected yet.",
    "",
    "## Takeaways",
    formatList(summary.takeaways),
    "",
    "## Visual Context",
    formatList(summary.visualContext),
    "",
    "## Actions",
    formatList(summary.actions),
    "",
    "## Creator Notes",
    formatList(summary.creatorNotes)
  ].join("\n");
}

export function createMarkdownFilename({ type, summary }) {
  const hook = summary?.hook || "instagram-summary";
  const slug = `${type || "instagram"}-${hook}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `${slug || "instagram-summary"}.md`;
}

function normalizeInstagramUrl(value) {
  const parsed = safeUrl(value);
  if (!parsed) {
    return value;
  }
  parsed.searchParams.delete("igsh");
  return parsed.toString();
}

function safeUrl(value) {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function splitSentences(text) {
  return text
    .split(/[\n.!?]+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function chooseHook(sentences) {
  return sentences.find((sentence) => /hook|start|secret|nobody|steal|mistake|why|how/i.test(sentence)) ?? sentences[0] ?? "";
}

function chooseTakeaways(sentences) {
  const useful = sentences.filter((sentence) => sentence.length > 12);
  return (useful.length ? useful : sentences).slice(0, 5);
}

function chooseActions(sentences) {
  const actions = sentences.filter((sentence) => /save|try|use|export|add|paste|start|write|share/i.test(sentence));
  return (actions.length ? actions : ["Review the source Reel before publishing or citing the summary."]).slice(0, 4);
}

function buildRoleNotes(role, sentences) {
  const roleNotes = {
    creator: ["Identify the hook pattern, CTA, and reusable content structure."],
    marketer: ["Map this Reel to campaign angle, audience pain, proof, and CTA."],
    researcher: ["Capture claims, tools mentioned, open questions, and source context."],
    student: ["Turn takeaways into study notes, flashcards, or follow-up questions."],
    casual: ["Keep the TL;DR short and save only the useful next action."]
  };
  const notes = roleNotes[role] ?? roleNotes.researcher;
  const pattern = sentences.find((sentence) => /hook|CTA|step|pattern|template|framework/i.test(sentence));
  return pattern ? [...notes, `Detected pattern: ${pattern}`] : notes;
}

function createTags(text) {
  const words = text
    .toLowerCase()
    .match(/[a-z0-9]{2,}/g) ?? [];
  const counts = new Map();
  for (const word of words) {
    if (!STOP_WORDS.has(word)) {
      counts.set(word, (counts.get(word) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([word]) => word);
}

function formatList(items) {
  if (!items.length) {
    return "- Not provided.";
  }
  return items.map((item) => `- ${item}`).join("\n");
}
