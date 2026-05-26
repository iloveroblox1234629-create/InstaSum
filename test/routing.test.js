import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { currentView } from "../public/routing.js";

describe("currentView", () => {
  it("routes the root site to the homepage", () => {
    assert.equal(currentView({ hostname: "kaleidoscopic-flan-89e32b.netlify.app", pathname: "/" }), "home");
  });

  it("routes path-based extraction and library pages", () => {
    assert.equal(currentView({ hostname: "kaleidoscopic-flan-89e32b.netlify.app", pathname: "/extract" }), "extract");
    assert.equal(currentView({ hostname: "kaleidoscopic-flan-89e32b.netlify.app", pathname: "/library" }), "library");
  });

  it("routes configured extraction and library subdomains", () => {
    assert.equal(currentView({ hostname: "extract.example.com", pathname: "/" }), "extract");
    assert.equal(currentView({ hostname: "library.example.com", pathname: "/" }), "library");
  });
});
