# Codex Dream Skin · Linux Edition

<p align="center">
  <a href="./README.md">中文</a> · <strong>English</strong>
</p>

External themes for the official ChatGPT / Codex desktop app on Linux.
Themes are injected over a **loopback-only** Chrome DevTools Protocol connection —
no official file, `.deb`, or `app.asar` is modified.

> Not an OpenAI product. Not affiliated with or endorsed by OpenAI.

This is a Linux-focused maintenance fork based on upstream
[Fei-Away/Codex-Dream-Skin](https://github.com/Fei-Away/Codex-Dream-Skin) PR #410 (`22d54c7`).

## What this fork changes

- **Fixes the blank conversation screen** on ChatGPT `26.1013.40934` — the old skin hid the
  container that carries the whole thread because it matched a top-fade attribute.
- **Fixes false verification failures** caused by cached hidden routes in the new renderer.
- **Adds a native settings panel** (Tkinter): skin on/off, wallpaper on/off, transparency slider.
- **Adds a persistent wallpaper toggle** and a per-device `opacity` preference (legacy files
  without `opacity` are read as 50%).
- **Adds desktop entries** for the app and the settings panel.

See [LINUX-FIX-NOTES.md](./LINUX-FIX-NOTES.md) (Chinese) for root cause and verification details.

## Requirements

- Linux x64, X11 or Wayland
- Official ChatGPT / Codex desktop app (deb, AppImage, or binary)
- Node.js ≥ 22
- Python 3 + tkinter for the GUI (`sudo apt install python3-tk`)

## Install

```bash
sudo apt update                 # required: the installer checks the official APT metadata
pkill -f '/usr/lib/chatgpt/ChatGPT' || true   # fully quit ChatGPT first

git clone https://github.com/Tesla-SHT/Codex-Dream-Skin-Linux.git
cd Codex-Dream-Skin-Linux
bash linux/scripts/install-dream-skin-linux.sh
dreamskin start
```

Optional deb build:

```bash
bash linux/scripts/build-deb.sh --version 1.5.18
sudo apt install ./release/codex-dream-skin_1.5.18_amd64.deb
```

## Usage

```bash
dreamskin start                 # launch ChatGPT with the active theme
dreamskin settings              # graphical settings panel
dreamskin wallpaper off         # hide the artwork only, keep colors and layout
dreamskin wallpaper opacity 50  # image opacity 50%
dreamskin theme list            # saved themes
dreamskin pause                 # temporarily remove the skin
dreamskin restore               # restore the official appearance
```

## Notes

1. **Quit ChatGPT before installing.** The installer rewrites `~/.codex/config.toml`.
2. **Run `sudo apt update` first.** A stale index produces
   `The installed Codex version is not available from the official OpenAI repository.`
3. The skin launches ChatGPT with a **loopback-only** debugging port (9335/9341).
4. A client update can change the DOM again; re-check selectors if the layout breaks.
5. **Do not install or verify inside containers / CI / sandboxes** — they often cannot see
   `/var/lib/dpkg`, `/run/user`, or a display server.
6. On Wayland, use `dreamskin start --renderer x11` if rendering misbehaves.
7. Only `preset-gothic-void-crusade` ships in this repository. You are responsible for the
   rights of any theme you import; identifiable real-person portraits are not accepted.

Uninstall:

```bash
dreamskin restore
rm -rf ~/.local/share/codex-dream-skin ~/.local/state/codex-dream-skin
rm -f ~/.local/bin/dreamskin ~/.local/share/applications/codex-dream-skin*.desktop
```

## License

MIT — see [LICENSE](./LICENSE). Upstream copyright notices are preserved.
