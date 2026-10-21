# Codex Dream Skin — Linux 修复记录（PR #410 基础上的本地修复）

本仓库是 [Fei-Away/Codex-Dream-Skin](https://github.com/Fei-Away/Codex-Dream-Skin) PR #410 源码
（提交 `22d54c7d1f3c0214472d82caa4052036ded2b2ba`）加上一个**本地修复提交**的完整副本。

- 修复分支：`fix/linux-261013-thread-black-screen`
- 修复提交：`d1c375d` — `fix(renderer): stop hiding the conversation container and prefer visible cached workspaces`
- 已推送到 fork：<https://github.com/Tesla-SHT/Codex-Dream-Skin/tree/fix/linux-261013-thread-black-screen>

## 它解决了什么问题

在 ChatGPT 桌面版 **26.1013.40934**（Ubuntu 22.04.5 / X11）上，PR #410 原版皮肤会出现：
**首页正常，点开任意对话后主区域整块黑屏（正文、表格、输入框全部消失）。**

根因有两层：

1. **对话容器被误判为“顶部渐变”并隐藏。**
   新版把 `data-app-shell-main-content-top-fade="visible|hidden"` 放在了包含整个对话
   正文和输入框的容器上，用属性值控制原生渐变的显隐；旧皮肤把任何带这个属性的节点
   都当作装饰渐变，套了 `display: none !important`，于是整块对话一起消失。

2. **验证器读取了缓存隐藏页。**
   新版会在 DOM 里保留导航过的旧工作区（隐藏状态）。Linux 验证器和路由检测只取
   `document.querySelector` 的第一个匹配，经常拿到隐藏的首页，得出“主区域零尺寸 /
   当前在首页”的错误结论。

## 修复内容（`d1c375d`）

| 文件 | 改动 |
|---|---|
| `tools/selectors.json` | `main-content-top-fade` 属性回退分支限定为 `[data-app-shell-main-content-top-fade]:empty`；保留 `.app-shell-main-content-top-fade` 类和 `_MainContentTopFade_` 模块两个真装饰分支 |
| `runtime/renderer-inject.js` | 路由检测 `selectorHit` 排除处于 `display:none` / `contentVisibility:hidden` 祖先中的节点（注意：不能直接用节点自身 `checkVisibility`，因为皮肤本身就会隐藏 home-icon，会形成反馈循环） |
| `linux/scripts/injector.mjs` | `verifySession` 对 shell/composer/sidebar/generic 部件改为 `visibleNode()`——在全部匹配中选第一个**可见**节点，而不是文档序第一个 |
| `tools/renderer-runtime.test.mjs` | 增加 CSS 契约断言（禁止裸的 `[data-app-shell-main-content-top-fade]` 隐藏规则）+ 隐藏缓存首页必须判为 thread 的回归 |
| `linux/tests/cached-workspace.test.mjs` | 新增：可见 thread + 隐藏缓存首页 → 验证通过；全部隐藏 → 验证必须失败 |
| `linux|macos|windows/assets/*` | 由 `tools/sync-runtime-assets.mjs` 重新生成的三端同步资产 |

## 在本机复现 / 验证的方法

```bash
# 1. 跑完整 Linux 测试（需要 Node >= 22）
NODE="$(command -v node)" bash linux/tests/run-tests.sh
# 期望最后一行：linux tests passed

# 2. 部署到用户安装目录（官方 deb 的 ChatGPT，无需 sudo）
bash linux/scripts/install-dream-skin-linux.sh --no-launch

# 3. 启动并验证
dreamskin start
dreamskin status            # 普通 status 不探测 CDP，cdp=false 是正常的
bash ~/.local/share/codex-dream-skin/scripts/status-dream-skin-linux.sh --deep
bash ~/.local/share/codex-dream-skin/scripts/verify-dream-skin-linux.sh
```

验证环境：Ubuntu 22.04.5 / GNOME X11 / ChatGPT 26.1013.40934（官方 deb，来源与
`dpkg -V` 完整性校验均通过）。验证结果：`linux tests passed`；home 与 thread 路由
独立 verify 全部 `pass: true`；`--remove` 清理干净；重启后再次验证通过。

## 已知环境坑（与本仓库无关，但会干扰安装/验证）

- **安装器要求“已安装版本出现在官方 APT 元数据里”**。如果本机 apt 列表还没刷新到
  你装的这个版本，安装会以
  `The installed Codex version is not available from the official OpenAI repository.`
  退出 1。先 `sudo apt update`（或把 ChatGPT 升到源里已有的版本）即可。
- **不要用 sandbox/隔离环境跑测试或安装**：测试会因 Node 无法调用 `/bin/bash` 失败；
  安装脚本读不到 `/var/lib/dpkg` 时会误报“找不到官方应用”。
- **会话进程保活**：从一次性执行环境（CI、agent 沙盒）里启动 ChatGPT，进程会随会话
  结束被回收。用 `systemd-run --user ...` 或正常桌面启动即可。

## 上游反馈

修复已整理为可直接提交的分支。给上游提 issue/PR 时可直接引用：
`fix/linux-261013-thread-black-screen`（`d1c375d`），复现版本 26.1013.40934，
症状“home 正常、thread 黑屏”，根因与修复见上。

## 本机背景偏好：50%（2026-10-21）

使用 `gpt-luna-dragongirl` 主题时，按用户偏好将 ambient / banner 对话背景层不透明度从 `.78`（浅色 `.72`）调为 `.5`；通用主区回退层也设为 `.5`。首页大图在背景图上叠加 50% 主题底色，使图片贡献为 50%，文字和控件保持完全不透明。

规范源为 `runtime/dream-skin.css`，三端 CSS 通过 `tools/sync-runtime-assets.mjs` 生成；本机安装目录的 `assets/dream-skin.css` 已同步，重启应用保留。此前临时插入的 `dream-skin-art-opacity-user` 已移除。此项是本 fork 的本地显示偏好，独立于黑屏兼容性修复；修改核心 CSS 会同时影响其他主题的上述背景模式，full / off 模式继续沿用原行为。

验收：渲染测试、生成资产一致性、真实对话 `--verify` 通过；运行时确认对话背景层 `opacity=0.5`，首页背景为 50% 主题底色叠层且容器 `opacity=1`。

## Linux 图形设置面板（2026-10-21）

在应用菜单搜索 **Dream Skin 壁纸设置**，或运行：

```bash
dreamskin settings     # 同义命令：dreamskin gui
```

- **暂停 / 启用皮肤**：复用原有皮肤会话管理。暂停去掉整套皮肤；启用保留壁纸偏好。面板不强制重启正在运行的 ChatGPT；未开启换肤连接时，按提示先正常关闭 ChatGPT，再启用。
- **显示背景图**：只控制静态图片，保留主题配色、布局和文字；不影响独立的动画背景设置。
- **图片透明度 0–100%**：0% 完整显示，100% 图片不可见；默认 50%。拖动时预览即时变化，停止拖动约 350ms 后自动保存并刷新当前活动皮肤；快速拖动合并请求，关闭窗口等待最后一次保存。
- **恢复 50%**：恢复透明度，保持背景开关原值。关闭设置窗口不退出 ChatGPT。

设置窗口使用 Python 3 标准库 Tkinter，无 pip 依赖；Debian/Ubuntu 缺少组件时安装 `python3-tk`。deb 的推荐依赖与新设置启动器、用户安装器均已接入。原终端菜单保留，按 `S` 也可打开面板。

命令行仍可使用：

```bash
dreamskin wallpaper off          # 只隐藏图片
dreamskin wallpaper on           # 显示图片，保留已设透明度
dreamskin wallpaper toggle
dreamskin wallpaper opacity 50   # 图片不透明度50%，即透明度50%
dreamskin wallpaper opacity 25   # 图片不透明度25%，即透明度75%
dreamskin wallpaper status --json
```

本机偏好保存在 `${XDG_STATE_HOME:-$HOME/.local/state}/codex-dream-skin/wallpaper.json`，`opacity` 为 0–1 不透明度，独立于主题 ZIP。旧版只有 `enabled` 的偏好会按 0.5 兼容读取。暂停/离线时修改只保存，不会意外恢复皮肤；下次启用生效。full、ambient、首页和宽屏背景均消费同一透明度变量，正文和按钮不降低透明度。

源码入口：`linux/scripts/settings-panel.py`、`settings-panel-linux.sh`、`wallpaper-linux.sh`、`wallpaper-settings.mjs`；运行时在 `runtime/renderer-inject.js` 设变量，在 `runtime/dream-skin.css` 消费，再同步三端资产。测试包括旧偏好迁移、边界值、暂停状态、线程请求合并、保存失败、PPM预览和真实桌面窗口的滑块/关闭流程。

## 便捷开关：只隐藏图片或暂停整套皮肤

```bash
# 仅隐藏静态图片，保留 Luna 配色、布局和输入框
 dreamskin wallpaper off
# 重新显示图片，继续使用 50% 效果
 dreamskin wallpaper on
# 一键切换 / 查看已保存的偏好
 dreamskin wallpaper toggle
 dreamskin wallpaper status
# 不带参数打开菜单，按 W 切换壁纸
 dreamskin
# 暂停整套换肤，保留当前应用窗口
 dreamskin pause
# 重新开启换肤；若未运行应用，会启动应用
 dreamskin start
# 完整恢复原外观和原配色配置，会重启应用
 dreamskin restore
```

静态图片开关保存在 `$XDG_STATE_HOME/codex-dream-skin/wallpaper.json`（未设置 `XDG_STATE_HOME` 时为 `~/.local/state/codex-dream-skin/wallpaper.json`），不修改主题包或删除图片。偏好跨重启和切换主题保留；暂停时只保存偏好，不自动恢复换肤。动画背景独立由 `dreamskin animation off|on` 控制。

热切换通过本机已保存端口连接 `app://` 页面，验证 ChatGPT 页面标记、当前皮肤启用状态和主题 ID 后才应用；不依赖 dpkg/APT 数据库，不唤醒暂停的皮肤。实际关闭/开启验证分别确认无图片绘制层 / 图片层 `opacity=.5`，两次配色值和可见编辑器一致。新增偏好、CLI、文件监听、渲染清理及暂停保护测试通过。完整 Linux 测试在当前隔离执行环境中有四项被 `/dev/fd` 不可访问或临时空间不足阻塞；详见本地测试日志，未将其记录为全部通过。
