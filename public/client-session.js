export const tokenStorageKey = "instabrief-instagram-session";

export function buildExtractionPayload(formData, usePrivateSession) {
  const payload = Object.fromEntries(formData);
  if (!usePrivateSession) {
    delete payload.instagramSessionId;
    delete payload.instagramCsrfToken;
    delete payload.instagramUserId;
  }
  delete payload.usePrivateSession;
  delete payload.rememberInstagramSession;
  return payload;
}

export function readSavedInstagramSession(storage = globalThis.localStorage) {
  try {
    const saved = JSON.parse(storage.getItem(tokenStorageKey) || "{}");
    return normalizeSavedSession(saved);
  } catch {
    return {};
  }
}

export function saveInstagramSession(session, storage = globalThis.localStorage) {
  const normalized = normalizeSavedSession(session);
  if (!hasSessionValues(normalized)) {
    storage.removeItem(tokenStorageKey);
    return {};
  }
  storage.setItem(tokenStorageKey, JSON.stringify(normalized));
  return normalized;
}

export function clearInstagramSession(storage = globalThis.localStorage) {
  storage.removeItem(tokenStorageKey);
}

export function fillPrivateAccessFields(privateSessionToggle, privateTokenFields, session = {}) {
  const normalized = normalizeSavedSession(session);
  privateSessionToggle.checked = hasSessionValues(normalized);
  syncPrivateAccessFields(privateSessionToggle, privateTokenFields);
  for (const field of privateTokenFields) {
    field.value = normalized[field.name] || "";
  }
}

export function syncPrivateAccessFields(privateSessionToggle, privateTokenFields) {
  const isEnabled = privateSessionToggle.checked;
  for (const field of privateTokenFields) {
    field.disabled = !isEnabled;
    if (!isEnabled) {
      field.value = "";
    }
  }
}

export function clearPrivateAccessFields(privateSessionToggle, privateTokenFields) {
  for (const field of privateTokenFields) {
    field.value = "";
  }
  privateSessionToggle.checked = false;
  syncPrivateAccessFields(privateSessionToggle, privateTokenFields);
}

function normalizeSavedSession(session) {
  if (!session || typeof session !== "object" || Array.isArray(session)) {
    return {};
  }
  return {
    instagramSessionId: typeof session.instagramSessionId === "string" ? session.instagramSessionId : "",
    instagramCsrfToken: typeof session.instagramCsrfToken === "string" ? session.instagramCsrfToken : "",
    instagramUserId: typeof session.instagramUserId === "string" ? session.instagramUserId : ""
  };
}

function hasSessionValues(session) {
  return Boolean(session.instagramSessionId || session.instagramCsrfToken || session.instagramUserId);
}
