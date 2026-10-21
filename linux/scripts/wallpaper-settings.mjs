import fs from "node:fs/promises";
import { constants } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { ensureAnimationStateRoot } from "./animation-settings.mjs";

export const DEFAULT_WALLPAPER_SETTINGS = Object.freeze({ schemaVersion: 1, enabled: true, opacity: 0.5 });

export function validateWallpaperSettings(value) {
  if (!value || Array.isArray(value) || value.schemaVersion !== 1 || typeof value.enabled !== "boolean"
      || Object.keys(value).some(key => !["schemaVersion", "enabled", "opacity"].includes(key))) {
    throw new Error("Invalid wallpaper settings");
  }
  // Older preferences contain only enabled. Keep their setting and migrate at read time.
  const opacity = value.opacity === undefined ? DEFAULT_WALLPAPER_SETTINGS.opacity : value.opacity;
  if (typeof opacity !== "number" || !Number.isFinite(opacity) || opacity < 0 || opacity > 1) {
    throw new Error("Wallpaper opacity must be between 0 and 1");
  }
  return { schemaVersion: 1, enabled: value.enabled, opacity: Math.round(opacity * 100) / 100 };
}

export async function readWallpaperSettings(filename) {
  let handle;
  try {
    handle = await fs.open(filename, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size < 1 || stat.size > 4096) throw new Error("Invalid wallpaper preference file");
    const buffer = Buffer.alloc(4097);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    const after = await handle.stat();
    if (bytesRead !== stat.size || after.size !== stat.size || after.mtimeMs !== stat.mtimeMs) {
      throw new Error("Wallpaper settings changed while reading");
    }
    return validateWallpaperSettings(JSON.parse(buffer.subarray(0, bytesRead).toString("utf8")));
  } catch (error) {
    if (!handle && error.code === "ENOENT") return { ...DEFAULT_WALLPAPER_SETTINGS };
    throw error;
  } finally { await handle?.close(); }
}

export async function saveWallpaperSettings(stateRoot, value) {
  const settings = validateWallpaperSettings(value);
  const directory = await ensureAnimationStateRoot(stateRoot);
  const filename = path.join(directory, "wallpaper.json");
  const stat = await fs.lstat(filename).catch(error => { if (error.code === "ENOENT") return null; throw error; });
  if (stat && (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1)) throw new Error("Refusing linked wallpaper preferences");
  const temporary = path.join(directory, `.wallpaper-${randomUUID()}.tmp`);
  try {
    await fs.writeFile(temporary, `${JSON.stringify(settings, null, 2)}\n`, { mode: 0o600, flag: "wx" });
    await fs.rename(temporary, filename);
  } finally { await fs.rm(temporary, { force: true }); }
  return settings;
}

async function main(argv) {
  const json = argv.includes("--json");
  const [flag, stateRoot, command = "status", ...args] = argv.filter(arg => arg !== "--json");
  if (flag !== "--state-root" || !stateRoot || !["status", "on", "off", "toggle", "opacity", "check-root"].includes(command)
      || args.length !== (command === "opacity" ? 1 : 0)) {
    throw new Error("Usage: dreamskin wallpaper on|off|toggle|status|opacity <0..100> [--json]");
  }
  if (command === "check-root") { await ensureAnimationStateRoot(stateRoot); return; }
  const settings = await readWallpaperSettings(path.join(path.resolve(stateRoot), "wallpaper.json"));
  if (command === "opacity") {
    if (!/^(?:100|[0-9]{1,2})$/.test(args[0])) throw new Error("Opacity must be an integer from 0 to 100");
    settings.opacity = Number(args[0]) / 100;
  } else if (command !== "status") {
    settings.enabled = command === "toggle" ? !settings.enabled : command === "on";
  }
  if (command !== "status") await saveWallpaperSettings(stateRoot, settings);
  if (json) console.log(JSON.stringify(settings));
  else console.log(`静态壁纸：${settings.enabled ? "开启" : "关闭"}；图片不透明度 ${Math.round(settings.opacity * 100)}%；主题配色和布局保留。`);
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
}
