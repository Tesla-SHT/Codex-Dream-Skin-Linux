# Codex Dream Skin · Linux 版

<p align="center">
  <strong>给 ChatGPT / Codex 桌面端换一张会呼吸的脸。</strong><br>
  Linux 安装与维护分支 · 本机 CDP 注入 · 不修改官方安装包
</p>

<p align="center">
  <a href="./README.en.md">English</a> ·
  <a href="./docs/install-linux.md">完整安装文档</a> ·
  <a href="./LINUX-FIX-NOTES.md">修复与改动记录</a>
</p>

<p align="center">
  <a href="https://github.com/Tesla-SHT/Codex-Dream-Skin-Linux/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Tesla-SHT/Codex-Dream-Skin-Linux/actions/workflows/ci.yml/badge.svg"></a>
</p>

> **非 OpenAI 官方产品。** 本工具不修改 `.deb`、`app.asar` 或任何官方文件，
> 只在本机回环地址上通过 Chrome DevTools Protocol 注入 CSS 与少量渲染逻辑。

---

## 这是什么

Codex Dream Skin 用一套外部主题给官方桌面端换配色、面板质感和背景图。本仓库是
**面向 Linux 的维护分支**，基于上游 [Fei-Away/Codex-Dream-Skin](https://github.com/Fei-Away/Codex-Dream-Skin)
PR #410 快照（`22d54c7`），并修复了新版客户端上的严重回归、补齐了 Linux 缺失的图形设置界面。

### 相对上游的改动

| 改动 | 说明 |
| --- | --- |
| **修复对话黑屏** | ChatGPT `26.1013.40934` 把 `data-app-shell-main-content-top-fade` 放到整个对话容器上，旧选择器把它当装饰遮罩隐藏，导致正文和输入框消失。现限定为 `:empty` 装饰节点 |
| **修复验证误判** | 新版会保留隐藏的旧页面缓存，验证器改取第一个**可见**节点，不再把隐藏首页误判为当前页 |
| **图形设置面板** | 原生 Tkinter 中文面板：皮肤启停、背景图开关、透明度滑块（带预览），拖动即保存并热更新 |
| **静态壁纸独立开关** | `dreamskin wallpaper on/off/toggle`，只隐藏图片、保留配色和布局 |
| **透明度可调** | `wallpaper.json` 增加 `opacity`，首页、对话页、宽屏背景统一生效；旧的仅 `enabled` 偏好按 50% 兼容读取 |
| **桌面入口** | 应用菜单新增「Dream Skin 壁纸设置」，无需开终端 |

详细根因、修复方式和验证证据见 [LINUX-FIX-NOTES.md](./LINUX-FIX-NOTES.md)。

---

## 系统要求

- **Linux x64**，X11 或 Wayland（Wayland 异常时可强制 `--renderer x11`）
- **官方 ChatGPT / Codex 桌面端**（deb、AppImage 或独立二进制）
- **Node.js ≥ 22**（deb 会自动拉取依赖）
- **Python 3 + tkinter**（仅图形面板需要：`sudo apt install python3-tk`）
- 已至少启动过一次 ChatGPT，使 `~/.codex/config.toml` 存在

---

## 安装

### 方式一：从源码安装（推荐，无需 root 改系统）

```bash
# 0) 关键前置：刷新 apt 索引，让官方源元数据包含你当前安装的版本
sudo apt update

# 1) 完全退出 ChatGPT（托盘也要退），否则安装会拒绝改写 config.toml
pkill -f '/usr/lib/chatgpt/ChatGPT' || true

# 2) 获取代码并安装到 ~/.local/share/codex-dream-skin
git clone https://github.com/Tesla-SHT/Codex-Dream-Skin-Linux.git
cd Codex-Dream-Skin-Linux
bash linux/scripts/install-dream-skin-linux.sh

# 3) 启动 ChatGPT 并应用皮肤
dreamskin start
```

安装器会创建：

- `~/.local/bin/dreamskin` —— 命令行入口
- `~/.local/share/applications/codex-dream-skin.desktop` —— 应用菜单「Dream Skin」
- `~/.local/share/applications/codex-dream-skin-settings.desktop` —— 应用菜单「Dream Skin 壁纸设置」

### 方式二：构建并安装 deb

```bash
bash linux/scripts/build-deb.sh --version 1.5.18
sudo apt install ./release/codex-dream-skin_1.5.18_amd64.deb
```

### 方式三：便携 tar.gz（解压即用，不写系统目录）

```bash
bash linux/scripts/build-tarball.sh
tar -xzf release/CodexDreamSkin-v1.5.18-linux-amd64.tar.gz
cd CodexDreamSkin-v1.5.18-linux-amd64 && ./install.sh
```

安装完成后，`dreamskin --help` 不可用也没关系，直接运行 `dreamskin` 会进入终端菜单。

---

## 日常使用

```bash
dreamskin start              # 启动 ChatGPT 并应用当前主题
dreamskin settings           # 打开图形设置面板（同义：dreamskin gui）
dreamskin wallpaper off      # 只隐藏背景图，保留配色与布局
dreamskin wallpaper on
dreamskin wallpaper opacity 50   # 图片不透明度 50%（= 透明度 50%）
dreamskin theme list         # 已保存主题
dreamskin theme apply <id>   # 切换主题
dreamskin import --file ~/Downloads/xxx.zip
dreamskin pause              # 临时关闭皮肤（不退出 ChatGPT）
dreamskin restore            # 一键恢复官方外观
dreamskin status             # 查看状态
```

终端菜单里按 `S` 也能打开图形面板，按 `W` 切换壁纸。

### 图形设置面板

- **暂停 / 启用皮肤**：暂停会移除整套皮肤；启用会保留壁纸偏好。
- **显示背景图**：只控制静态图片，主题配色、布局、文字都保留。
- **图片透明度 0–100%**：0 为完整显示，100 为图片不可见；默认 50%。拖动时预览即时变化，松手约 0.35 秒后自动保存并刷新当前窗口。
- 关闭面板**不会**退出 ChatGPT；关闭前会等待最后一次保存完成。

偏好保存在 `~/.local/state/codex-dream-skin/wallpaper.json`，与主题包分离，换主题不会丢。

---

## 需要注意什么

1. **安装前必须完全退出 ChatGPT。** 安装器要改写 `~/.codex/config.toml`，运行中改写会被拒绝。
2. **先 `sudo apt update`。** 安装器会校验「当前安装版本是否出现在官方 APT 元数据里」，索引过期会报
   `The installed Codex version is not available from the official OpenAI repository.`，这是安全校验，不是 bug。
3. **会重启 ChatGPT 的调试端口。** `dreamskin start` 用 `--remote-debugging-port` 启动客户端（默认 9335/9341），仅绑定 `127.0.0.1`。若你所在环境不允许本地调试端口，皮肤无法工作。
4. **升级官方客户端可能再次失效。** 官方改动 DOM 结构后，选择器需要更新；遇到黑屏或布局错乱请先看
   [LINUX-FIX-NOTES.md](./LINUX-FIX-NOTES.md) 与 `dreamskin status --deep`。
5. **不要在容器 / CI / 沙箱里安装或验证。** 这些环境常常看不到 `/var/lib/dpkg`、`/run/user` 或没有显示服务，会误报「找不到官方应用」或「验证失败」。
6. **Wayland 下如遇花屏或输入异常**，用 `dreamskin start --renderer x11` 强制 X11。
7. **主题素材版权自负。** 仓库只随附 `preset-gothic-void-crusade` 一套原创预设；导入第三方主题前请确认你有使用权。本仓库不接受可识别真人肖像素材。
8. **恢复官方外观**：`dreamskin restore`。它会把配置和外观还原，不会卸载 ChatGPT。

### 常见问题速查

| 现象 | 处理 |
| --- | --- |
| 双击 Codex 图标打开没有皮肤 | 皮肤依赖本机调试端口，普通启动不会带；请用 `dreamskin start`（菜单 1）启动。可把 Dream Skin 固定到任务栏当启动器 |
| 点菜单 1 后终端窗口一闪就没了 | 多半是 Codex 已在运行、且不是带端口的实例。菜单会询问是否重启；直接命令行启动请加 `--restart-existing` |
| 首页正常、点开对话黑屏 | 本仓库已修复；确认用的是本仓库资产并重新 `dreamskin start` |
| 皮肤在但背景图几乎看不见 | 检查是不是把透明度调得太高：`dreamskin wallpaper opacity 50`，或在设置面板点「恢复 50%」 |
| `找不到官方应用` / 版本校验失败 | `sudo apt update`，确认 `dpkg -l chatgpt` 有记录 |
| 面板打不开或提示缺 tkinter | `sudo apt install python3-tk` |
| `ChatGPT is already running without ... CDP endpoint` | 先完全退出 ChatGPT，或加 `--restart-existing` |
| 皮肤没生效但进程在 | `dreamskin status --deep`；必要时 `dreamskin pause` 后重新 `start` |

---

## 卸载

```bash
dreamskin restore                      # 先恢复官方外观
rm -rf ~/.local/share/codex-dream-skin
rm -rf ~/.local/state/codex-dream-skin
rm -f  ~/.local/bin/dreamskin
rm -f  ~/.local/share/applications/codex-dream-skin*.desktop
```

deb 安装的用户改用 `sudo apt remove codex-dream-skin`。

---

## 目录结构

```
linux/        Linux 引擎、安装器、CLI、图形面板、预设与测试
runtime/      共享的 CSS / 注入器源码（改动后用 tools/sync-runtime-assets.mjs 生成 linux/assets）
tools/        选择器契约、资产同步、运行时测试
docs/         安装与设计文档
.github/      CI（语法检查、资产一致性、完整测试）
```

> 本仓库只保留 Linux 实现。上游的 macOS / Windows 目录已移除，避免携带与 Linux 无关的
> 平台代码和素材；需要跨平台版本请使用上游仓库。

开发与提交前自检：

```bash
node tools/sync-runtime-assets.mjs --check
bash linux/tests/run-tests.sh
```

---

## 来源与许可

- 上游项目：[Fei-Away/Codex-Dream-Skin](https://github.com/Fei-Away/Codex-Dream-Skin)（MIT）
- 本分支基线：上游 PR #410 快照 `22d54c7`
- 本分支维护：[Tesla-SHT](https://github.com/Tesla-SHT)
- 许可证：[MIT](./LICENSE)，原始版权声明保留

本项目与 OpenAI 无隶属或背书关系。ChatGPT、Codex 及相关标识归其各自权利人所有。
