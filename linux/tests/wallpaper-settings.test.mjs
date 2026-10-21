import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import test from "node:test";
import { readWallpaperSettings, saveWallpaperSettings, validateWallpaperSettings } from "../scripts/wallpaper-settings.mjs";
import vm from "node:vm";
import { loadPayload, loadTheme, watchPayloadSources, refreshWallpaperSession } from "../scripts/injector.mjs";

const linuxRoot = fileURLToPath(new URL("../", import.meta.url));
async function fixture(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "dreamskin-wallpaper-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  return directory;
}

test("wallpaper preferences default on, reject bad values and do not follow links", async t => {
  const directory = await fixture(t);
  const filename = path.join(directory, "wallpaper.json");
  assert.deepEqual(await readWallpaperSettings(filename), {schemaVersion:1,enabled:true,opacity:0.5});
  assert.deepEqual(validateWallpaperSettings({schemaVersion:1,enabled:false}), {schemaVersion:1,enabled:false,opacity:0.5});
  for (const opacity of [-0.01, 1.01, NaN, Infinity, "0.5", null]) {
    assert.throws(() => validateWallpaperSettings({schemaVersion:1,enabled:true,opacity}));
  }
  for (const value of [null, [], {}, {schemaVersion:1,enabled:"false"}, {schemaVersion:1,enabled:false,url:"remote"}]) {
    assert.throws(() => validateWallpaperSettings(value));
  }
  await saveWallpaperSettings(directory, {schemaVersion:1,enabled:false});
  assert.equal((await readWallpaperSettings(filename)).enabled, false);
  assert.equal((await fs.stat(filename)).mode & 0o777, 0o600);
  await fs.rename(filename, path.join(directory, "external.json"));
  await fs.symlink(path.join(directory, "external.json"), filename);
  await assert.rejects(readWallpaperSettings(filename));
  await assert.rejects(saveWallpaperSettings(directory, {schemaVersion:1,enabled:true}));
});

test("CLI toggles persist independently without altering a theme or starting ChatGPT", async t => {
  const directory = await fixture(t);
  const stateRoot = path.join(directory, "codex-dream-skin");
  const entry = path.join(linuxRoot, "scripts/dreamskin.sh");
  const env = {...process.env, XDG_STATE_HOME:directory};
  const run = (...args) => execFileSync("/bin/bash", ["-c", 'source "$1" --self-test-source; shift; dispatch wallpaper "$@"', "--", entry, ...args], {env,encoding:"utf8"});
  run("off");
  assert.equal((await readWallpaperSettings(path.join(stateRoot,"wallpaper.json"))).enabled, false);
  run("toggle");
  assert.equal((await readWallpaperSettings(path.join(stateRoot,"wallpaper.json"))).enabled, true);
  run();
  assert.equal((await readWallpaperSettings(path.join(stateRoot,"wallpaper.json"))).enabled, false);
  run("on");
  assert.match(run("status"), /开启/);
  for (const percent of [0, 25, 50, 100]) {
    const result = JSON.parse(run("opacity", String(percent), "--json"));
    assert.equal(result.settings.opacity, percent / 100);
    assert.equal(result.applied, false);
  }
  run("off");
  run("opacity", "35");
  const persisted = JSON.parse(run("status", "--json"));
  assert.equal(persisted.settings.enabled, false);
  assert.equal(persisted.settings.opacity, 0.35);
  for (const bad of ["-1", "101", "NaN", "1.5", "", "1;exit"]) assert.throws(() => run("opacity", bad));
  assert.deepEqual(await fs.readdir(stateRoot), ["wallpaper.json"]);
});

test("payload revision and real file watcher follow wallpaper settings outside theme packs", async t => {
  const directory = await fixture(t);
  const themeDir = path.join(directory,"theme");
  await fs.mkdir(themeDir);
  // Use the built-in theme as content, while exercising a real separate theme directory.
  const builtin = await loadTheme();
  await fs.writeFile(path.join(themeDir,"theme.json"), JSON.stringify(builtin.theme));
  await fs.copyFile(builtin.imagePath, path.join(themeDir,builtin.theme.image));
  const before = await loadPayload(themeDir);
  let resolve;
  const changed = new Promise(r => {resolve=r;});
  const close = watchPayloadSources(themeDir, resolve);
  t.after(close);
  await saveWallpaperSettings(directory,{schemaVersion:1,enabled:false});
  const timeout = setTimeout(() => resolve({timeout:true}),2000);
  const event = await changed;
  clearTimeout(timeout);
  assert.equal(event.timeout, undefined);
  assert.equal(event.wallpaperChanged, true);
  assert.equal(event.animationChanged, false);
  assert.equal(event.staticChanged, false);
  const after = await loadPayload(themeDir);
  assert.notEqual(after.revision,before.revision);
  assert.equal(after.theme.wallpaper.enabled,false);
  assert.equal(after.theme.artKey,before.theme.artKey);
  assert.deepEqual(after.theme.colors,before.theme.colors);
  await saveWallpaperSettings(directory,{schemaVersion:1,enabled:false,opacity:0.23});
  const dimmed = await loadPayload(themeDir);
  assert.notEqual(dimmed.revision,after.revision);
  assert.equal(dimmed.theme.wallpaper.opacity,0.23);
  assert.equal(dimmed.theme.wallpaper.enabled,false);
  assert.equal(dimmed.theme.artKey,before.theme.artKey);
});

test("hot refresh leaves paused or unrelated skins untouched, including hidden windows", async () => {
  const attrs = { "data-dream-skin": "active" };
  const properties = {};
  const context = { window: { __CODEX_DREAM_SKIN_STATE__: { themeId: "luna", revision: "old" } },
    document: { visibilityState: "hidden", documentElement: { getAttribute: key => attrs[key],
      style: { getPropertyValue: key => properties[key] || "" } } } };
  let mutations = 0;
  const loaded = { theme: {id:"luna",wallpaper:{enabled:false}}, revision:"new", payload:"install-wallpaper" };
  const session = { evaluate: async expression => {
    if (expression === loaded.payload) {
      mutations++;
      context.window.__CODEX_DREAM_SKIN_STATE__.revision = "new";
      attrs["data-dream-wallpaper"] = "off";
      properties["--dream-skin-art"] = "none";
      properties["--ds-wallpaper-opacity"] = "0.5";
      return;
    }
    return vm.runInNewContext(expression, context);
  } };
  context.window.__CODEX_DREAM_SKIN_DISABLED__ = true;
  assert.equal((await refreshWallpaperSession(session, loaded)).applied, false);
  context.window.__CODEX_DREAM_SKIN_DISABLED__ = false;
  context.window.__CODEX_DREAM_SKIN_STATE__.themeId = "other";
  assert.equal((await refreshWallpaperSession(session, loaded)).applied, false);
  assert.equal(mutations, 0);
  context.window.__CODEX_DREAM_SKIN_STATE__.themeId = "luna";
  assert.equal((await refreshWallpaperSession(session, loaded)).applied, true);
  assert.equal(mutations, 1);
});
