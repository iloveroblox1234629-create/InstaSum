import { createExtraction } from "../../src/extraction.js";

export async function handler(event) {
  if (event.httpMethod !== "POST") {
    return response(405, { error: "Use POST." });
  }

  try {
    const payload = JSON.parse(event.body || "{}");
    return response(200, createExtraction(payload));
  } catch (error) {
    return response(400, { error: error instanceof Error ? error.message : "Invalid request." });
  }
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
