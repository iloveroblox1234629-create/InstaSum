import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildExtractionPayload,
  clearInstagramSession,
  clearPrivateAccessFields,
  fillPrivateAccessFields,
  readSavedInstagramSession,
  saveInstagramSession,
  syncPrivateAccessFields,
  tokenStorageKey
} from "../public/client-session.js";

describe("buildExtractionPayload", () => {
  it("keeps private tokens only when the private session toggle is enabled", () => {
    const payload = buildExtractionPayload([
      ["rawUrls", "https://www.instagram.com/reel/PRIVATE/"],
      ["usePrivateSession", "on"],
      ["rememberInstagramSession", "on"],
      ["instagramSessionId", "session-token"],
      ["instagramCsrfToken", "csrf-token"],
      ["instagramUserId", "12345"]
    ], true);

    assert.deepEqual(payload, {
      rawUrls: "https://www.instagram.com/reel/PRIVATE/",
      instagramSessionId: "session-token",
      instagramCsrfToken: "csrf-token",
      instagramUserId: "12345"
    });
  });

  it("omits private tokens when the private session toggle is disabled", () => {
    const payload = buildExtractionPayload([
      ["rawUrls", "https://www.instagram.com/reel/PUBLIC/"],
      ["instagramSessionId", "session-token"],
      ["instagramCsrfToken", "csrf-token"],
      ["instagramUserId", "12345"]
    ], false);

    assert.deepEqual(payload, {
      rawUrls: "https://www.instagram.com/reel/PUBLIC/"
    });
  });
});

describe("private access field helpers", () => {
  it("clears, disables, and resets private session fields after request completion", () => {
    const toggle = { checked: true };
    const fields = [
      { value: "session-token", disabled: false },
      { value: "csrf-token", disabled: false },
      { value: "12345", disabled: false }
    ];

    clearPrivateAccessFields(toggle, fields);

    assert.equal(toggle.checked, false);
    assert.deepEqual(fields.map((field) => field.value), ["", "", ""]);
    assert.deepEqual(fields.map((field) => field.disabled), [true, true, true]);
  });

  it("enables token fields only while the private session toggle is active", () => {
    const toggle = { checked: true };
    const fields = [{ value: "session-token", disabled: true }];

    syncPrivateAccessFields(toggle, fields);
    assert.equal(fields[0].disabled, false);

    toggle.checked = false;
    syncPrivateAccessFields(toggle, fields);
    assert.equal(fields[0].disabled, true);
    assert.equal(fields[0].value, "");
  });

  it("fills private session fields from saved browser storage", () => {
    const toggle = { checked: false };
    const fields = [
      { name: "instagramSessionId", value: "", disabled: true },
      { name: "instagramCsrfToken", value: "", disabled: true },
      { name: "instagramUserId", value: "", disabled: true }
    ];

    fillPrivateAccessFields(toggle, fields, {
      instagramSessionId: "session-token",
      instagramCsrfToken: "csrf-token",
      instagramUserId: "12345"
    });

    assert.equal(toggle.checked, true);
    assert.deepEqual(fields.map((field) => field.value), ["session-token", "csrf-token", "12345"]);
    assert.deepEqual(fields.map((field) => field.disabled), [false, false, false]);
  });
});

describe("Instagram session browser storage", () => {
  it("persists and reads Instagram cookies from local storage", () => {
    const storage = createMemoryStorage();

    saveInstagramSession({
      instagramSessionId: "session-token",
      instagramCsrfToken: "csrf-token",
      instagramUserId: "12345"
    }, storage);

    assert.equal(storage.getItem(tokenStorageKey).includes("session-token"), true);
    assert.deepEqual(readSavedInstagramSession(storage), {
      instagramSessionId: "session-token",
      instagramCsrfToken: "csrf-token",
      instagramUserId: "12345"
    });
  });

  it("clears saved Instagram cookies from local storage", () => {
    const storage = createMemoryStorage();
    storage.setItem(tokenStorageKey, JSON.stringify({ instagramSessionId: "session-token" }));

    clearInstagramSession(storage);

    assert.equal(storage.getItem(tokenStorageKey), null);
  });
});

function createMemoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    }
  };
}
