import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildExtractionPayload, clearPrivateAccessFields, syncPrivateAccessFields } from "../public/client-session.js";

describe("buildExtractionPayload", () => {
  it("keeps private tokens only when the private session toggle is enabled", () => {
    const payload = buildExtractionPayload([
      ["rawUrls", "https://www.instagram.com/reel/PRIVATE/"],
      ["usePrivateSession", "on"],
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
});
