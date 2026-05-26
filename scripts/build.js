import { access, copyFile } from "node:fs/promises";

const requiredFiles = [
  "public/index.html",
  "public/app.js",
  "public/client-session.js",
  "public/routing.js",
  "public/styles.css",
  "src/extraction.js",
  "netlify/functions/extract.js"
];

await Promise.all(requiredFiles.map((file) => access(file)));
await copyFile("src/extraction.js", "public/extraction.js");
