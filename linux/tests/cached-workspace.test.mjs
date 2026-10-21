import assert from "node:assert/strict";
import fs from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";
import { verifySession } from "../scripts/injector.mjs";

const contract = JSON.parse(await fs.readFile(new URL("../assets/selectors.json", import.meta.url), "utf8"));
const selector = key => contract.selectors.find(entry => entry.key === key).selector;

function fixture({ visibleThread = true } = {}) {
  const sheet = {};
  function node(visible) {
    return {
      isConnected: true,
      classList: [],
      children: [],
      firstElementChild: null,
      querySelector: () => null,
      querySelectorAll: () => [],
      closest: () => null,
      getBoundingClientRect: () => ({ x: 0, y: 0, width: visible ? 800 : 0, height: visible ? 600 : 0 }),
      checkVisibility: () => visible,
    };
  }
  const cached = node(false), active = node(visibleThread), sidebar = node(true);
  const map = new Map([
    [selector("home-icon"), [cached]],
    [selector("home-route"), [cached]],
    [selector("shell-main"), [cached, active]],
    [selector("composer-chrome"), [cached, active]],
    [selector("left-panel"), [sidebar]],
    ['[data-ds-part="main"], [data-ds-part="home"]', [cached, active]],
    ['[data-ds-part="composer"]', [cached, active]],
  ]);
  const document = {
    visibilityState: "visible",
    documentElement: {
      getAttribute: name => name === "data-dream-skin" ? "active" : null,
      scrollWidth: 1280, clientWidth: 1280, scrollHeight: 800, clientHeight: 800,
    },
    adoptedStyleSheets: [sheet],
    querySelectorAll: s => map.get(s) || [],
    querySelector: s => (map.get(s) || [])[0] || null,
    getElementById: () => null,
  };
  const context = {
    document, innerWidth: 1280, innerHeight: 800,
    getComputedStyle: () => ({ display: "flex", visibility: "visible", opacity: "1", contentVisibility: "visible" }),
    window: { __CODEX_DREAM_SKIN_STATE__: {
      styleMode: "adopted", styleSheet: sheet, version: "1.5.18", themeId: "fixture", revision: "fixture",
      scope: { baseState: "thread", level: "L1", missingL1: [] },
    } },
  };
  return {
    target: { id: "fixture" },
    evaluate: async expression => vm.runInNewContext(expression, context),
    send: async () => { throw Object.assign(new Error("Browser window not found"), { cdpCode: -32000 }); },
  };
}

test("verification selects the visible thread after a cached hidden home", async () => {
  const result = await verifySession(fixture(), "fixture", "fixture");
  assert.equal(result.homePresent, false);
  assert.equal(result.homeRoute, false);
  assert.equal(result.shell.visible, true);
  assert.equal(result.composer.visible, true);
  assert.equal(result.checks.structurePass, true);
});

test("verification still fails when every thread surface is hidden", async () => {
  const result = await verifySession(fixture({ visibleThread: false }), "fixture", "fixture");
  assert.equal(result.checks.structurePass, false);
  assert.equal(result.pass, false);
});
