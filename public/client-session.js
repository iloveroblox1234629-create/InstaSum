export function buildExtractionPayload(formData, usePrivateSession) {
  const payload = Object.fromEntries(formData);
  if (!usePrivateSession) {
    delete payload.instagramSessionId;
    delete payload.instagramCsrfToken;
    delete payload.instagramUserId;
  }
  delete payload.usePrivateSession;
  return payload;
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
