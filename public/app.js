import { createExtraction } from "/extraction.js";

const form = document.querySelector("#extract-form");
const statusEl = document.querySelector("#status");
const resultsEl = document.querySelector("#results");
const countEl = document.querySelector("#count");
const searchEl = document.querySelector("#search");
const copyAllButton = document.querySelector("#copy-all");
const storageKey = "instabrief-web-items";

let savedItems = loadItems();
render();

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(form));
  const extraction = createExtraction(payload);

  if (!extraction.items.length) {
    setStatus("No supported Instagram media URLs found.");
    return;
  }

  savedItems = [...extraction.items, ...savedItems].slice(0, 50);
  saveItems(savedItems);
  setStatus(`Saved ${extraction.items.length} summary item${extraction.items.length === 1 ? "" : "s"}.`);
  render();
});

searchEl.addEventListener("input", render);

copyAllButton.addEventListener("click", async () => {
  const markdown = filteredItems().map((item) => item.markdown).join("\n\n---\n\n");
  if (!markdown) {
    setStatus("Nothing to copy yet.");
    return;
  }
  await copyMarkdown(markdown, "Markdown copied.");
});

function render() {
  const items = filteredItems();
  countEl.textContent = `${savedItems.length} saved`;

  if (!items.length) {
    resultsEl.className = "results empty";
    resultsEl.textContent = savedItems.length ? "No saved summaries match that search." : "No summaries yet.";
    return;
  }

  resultsEl.className = "results";
  resultsEl.replaceChildren(...items.map(renderItem));
}

function renderItem(item) {
  const article = document.createElement("article");
  article.className = "result-card";

  const title = document.createElement("h3");
  title.textContent = `${item.type.toUpperCase()} · ${item.summary.hook || "Untitled summary"}`;

  const url = document.createElement("a");
  url.href = item.url;
  url.textContent = item.url;
  url.target = "_blank";
  url.rel = "noreferrer";

  const takeaways = document.createElement("ul");
  for (const takeaway of item.summary.takeaways) {
    const li = document.createElement("li");
    li.textContent = takeaway;
    takeaways.append(li);
  }

  const tags = document.createElement("p");
  tags.className = "tags";
  tags.textContent = item.tags.map((tag) => `#${tag}`).join(" ");

  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "secondary small";
  copyButton.textContent = "Copy note";
  copyButton.addEventListener("click", async () => {
    await copyMarkdown(item.markdown, "Summary note copied.");
  });

  const downloadButton = document.createElement("button");
  downloadButton.type = "button";
  downloadButton.className = "secondary small";
  downloadButton.textContent = "Download .md";
  downloadButton.addEventListener("click", () => {
    downloadMarkdown(item);
    setStatus("Markdown download started.");
  });

  const buttonRow = document.createElement("div");
  buttonRow.className = "card-actions";
  buttonRow.append(copyButton, downloadButton);

  article.append(title, url, takeaways, tags, buttonRow);
  return article;
}

function filteredItems() {
  const query = searchEl.value.trim().toLowerCase();
  if (!query) {
    return savedItems;
  }
  return savedItems.filter((item) => JSON.stringify(item).toLowerCase().includes(query));
}

function loadItems() {
  try {
    return JSON.parse(localStorage.getItem(storageKey) || "[]");
  } catch {
    return [];
  }
}

function saveItems(items) {
  localStorage.setItem(storageKey, JSON.stringify(items));
}

function setStatus(message) {
  statusEl.textContent = message;
}

async function copyMarkdown(markdown, successMessage) {
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error("Clipboard API is unavailable.");
    }
    await navigator.clipboard.writeText(markdown);
    setStatus(successMessage);
  } catch {
    setStatus("Clipboard copy is unavailable in this browser. Use Download .md instead.");
  }
}

function downloadMarkdown(item) {
  const blob = new Blob([item.markdown], { type: "text/markdown;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = item.filename || "instagram-summary.md";
  link.click();
  URL.revokeObjectURL(link.href);
}
