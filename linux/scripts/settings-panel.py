#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dream Skin 设置面板（原生 Tkinter，Linux，暗色，中文）。

只读取 state.json / theme/theme.json / theme/background.png（只读），
所有写操作通过现有 bash/Node 后端（wallpaper-linux.sh）完成。
import 本模块不会创建任何 Tk 窗口；只有 SettingsPanel.__init__ 调 tk.Tk()。
"""

import argparse
import json
import os
import queue
import sys
import threading
import subprocess

import tkinter as tk  # 仅导入，不创建窗口

# ---------------------------------------------------------------------------
# 颜色
# ---------------------------------------------------------------------------
BG = "#15171c"
CARD = "#20232b"
ACCENT = "#b9a1ff"
TEXT = "#f0f0f4"
TEXT_DIM = "#9aa0ad"
BTN = "#2a2e39"
BTN_ACTIVE = "#3a3450"
OK_COLOR = "#9ad0a0"
ERR_COLOR = "#e08a8a"
LINE = "#2c3038"

BG_RGB = (0x15, 0x17, 0x1c)
CARD_RGB = (0x20, 0x23, 0x2b)

BASH = "/bin/bash"
DEBOUNCE_MS = 350
POLL_MS = 50
PREVIEW_W, PREVIEW_H = 170, 100

# ---------------------------------------------------------------------------
# 纯函数：输入转换与解析（无 Tk 依赖，--self-test 验证）
# ---------------------------------------------------------------------------

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def transparency_to_image_opacity_pct(transparency):
    """滑块透明度 0..100 -> 后端 image opacity 百分比 (100 - 透明度)。"""
    return 100 - clamp(int(round(transparency)), 0, 100)


def settings_opacity_to_transparency(opacity):
    try:
        o = float(opacity)
    except (TypeError, ValueError):
        o = 0.5
    o = clamp(o, 0.0, 1.0)
    return clamp(int(round((1.0 - o) * 100)), 0, 100)


def parse_status_json(text):
    if not text:
        return None
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        settings = data.get("settings")
        if not isinstance(settings, dict) or type(settings.get("enabled")) is not bool:
            return None
        opacity = settings.get("opacity", 0.5)
        if type(opacity) not in (float, int) or not 0 <= opacity <= 1:
            return None
        return {
            "enabled": settings["enabled"],
            "opacity": float(opacity),
            "applied": bool(data.get("applied", False)),
            "session": str(data.get("session", "")),
            "message": str(data.get("message", "")),
        }
    except Exception:
        # 任意字段（如 malformed schema / 非数值 opacity）都返回 None
        return None


def hex_to_rgb(s):
    s = (s or "").strip()
    if s.startswith("#"):
        s = s[1:]
        if len(s) >= 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    if s.startswith("rgb("):
        try:
            p = s[4:-1].split(",")
            return (int(p[0]), int(p[1]), int(p[2]))
        except Exception:
            return (0, 0, 0)
    return (0, 0, 0)


# ---------------------------------------------------------------------------
# PPM 生成（纯标准库，无 Pillow）：将 base RGB 按透明度与背景混合
# ---------------------------------------------------------------------------

def composite_ppm(w, h, rgb, bg, alpha):
    head = b"P6\n%d %d\n255\n" % (w, h)
    inv = 1.0 - alpha
    buf = bytearray()
    for (r, g, b) in rgb:
        buf += bytes((
            int(r * inv + bg[0] * alpha),
            int(g * inv + bg[1] * alpha),
            int(b * inv + bg[2] * alpha),
        ))
    return head + bytes(buf)


def solid_ppm(w, h, rgb):
    head = b"P6\n%d %d\n255\n" % (w, h)
    row = bytes(rgb) * w
    return head + row * h


def fallback_ppm(w, h):
    """无背景图时的退色彩预览：上深下浅的渐变块。"""
    head = b"P6\n%d %d\n255\n" % (w, h)
    buf = bytearray()
    for y in range(h):
        t = y / max(1, h - 1)
        c = (int(CARD_RGB[0] * (1 - t) + 0x5a * t),
             int(CARD_RGB[1] * (1 - t) + 0x4a * t),
             int(CARD_RGB[2] * (1 - t) + 0x8c * t))
        buf += bytes(c) * w
    return head + bytes(buf)


# ---------------------------------------------------------------------------
# 后端客户端：串行 + 合并未发送请求；仅把结果投递到队列，绝不调用 Tk
# ---------------------------------------------------------------------------

class WallpaperClient:
    def __init__(self, runner, scheduler, scheduler_cancel, on_result):
        self.runner = runner
        self.scheduler = scheduler
        self.scheduler_cancel = scheduler_cancel
        self.on_result = on_result
        self.desired_enabled = True
        self.desired_transparency = 50
        self.applied_enabled = True
        self.applied_transparency = 50
        self.inflight = False
        self._thread = None
        self._timer = None
        self._lock = threading.Lock()

    def is_idle(self):
        with self._lock:
            return (not self.inflight) and (self._timer is None) and not (self._thread and self._thread.is_alive())

    def set_applied(self, enabled, transparency):
        self.desired_enabled = bool(enabled)
        self.applied_enabled = bool(enabled)
        self.desired_transparency = int(transparency)
        self.applied_transparency = int(transparency)

    def update(self, enabled=None, transparency=None):
        if enabled is not None:
            self.desired_enabled = bool(enabled)
        if transparency is not None:
            self.desired_transparency = clamp(int(round(transparency)), 0, 100)
        self._schedule()

    def _schedule(self):
        if self._timer is not None:
            try:
                self.scheduler_cancel(self._timer)
            except Exception:
                pass
        self._timer = self.scheduler(DEBOUNCE_MS, self._dispatch)

    def cancel_pending(self):
        if self._timer is not None:
            try:
                self.scheduler_cancel(self._timer)
            except Exception:
                pass
            self._timer = None

    def _dispatch(self):
        with self._lock:
            if self.inflight:
                return
            self._timer = None
            self.inflight = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _commands_for(self, tgt_en, tgt_tr, ap_en, ap_tr):
        cmds = []
        if tgt_en != ap_en:
            cmds.append(["on" if tgt_en else "off", "--json"])
        if tgt_tr != ap_tr:
            cmds.append(["opacity", str(transparency_to_image_opacity_pct(tgt_tr)), "--json"])
        return cmds

    def _worker(self):
        # Keep inflight true through result publication and any coalesced saves.
        try:
            self._save_pending()
        finally:
            with self._lock:
                self.inflight = False

    def _save_pending(self):
        with self._lock:
            tgt_en, tgt_tr = self.desired_enabled, self.desired_transparency
            ap_en, ap_tr = self.applied_enabled, self.applied_transparency
        cmds = self._commands_for(tgt_en, tgt_tr, ap_en, ap_tr)
        result = {"ok": True, "message": "", "settings": None, "error": None}
        ok_all = True
        if cmds:
            for c in cmds:
                rc, out, err = self.runner(c, 30)
                parsed = parse_status_json(out)
                if rc != 0 or parsed is None:
                    ok_all = False
                    result["ok"] = False
                    result["error"] = (err or out or "后端返回异常").strip()[-400:]
                    break
                result["settings"] = parsed
                result["message"] = parsed.get("message", "")
                # Each command commits independently; preserve successful partial saves.
                with self._lock:
                    if c[0] in ("on", "off"):
                        self.applied_enabled = tgt_en
                    elif c[0] == "opacity":
                        self.applied_transparency = tgt_tr
            with self._lock:
                if ok_all:
                    self.applied_enabled, self.applied_transparency = tgt_en, tgt_tr
            self.on_result(result)
        # 合并：期间又有新改动则再派发一次（失败不再重试，避免死循环）
        if not cmds or ok_all:
            with self._lock:
                more = (self.desired_enabled != self.applied_enabled) or \
                       (self.desired_transparency != self.applied_transparency)
            if more:
                self._save_pending()

    def wait_inflight(self, timeout=30):
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)


# ---------------------------------------------------------------------------
# 设置面板
# ---------------------------------------------------------------------------

class SettingsPanel:
    def __init__(self, root, state_root, wallpaper_script, start_script, pause_script):
        self.root = root
        # Remote X11 sessions can report ~30 DPI, making point-sized text unreadable.
        if float(root.tk.call("tk", "scaling")) < 1.0:
            root.tk.call("tk", "scaling", 96 / 72)
        self.state_root = state_root
        self.wallpaper_script = wallpaper_script
        self.start_script = start_script
        self.pause_script = pause_script
        self.theme_path = os.path.join(state_root, "theme", "theme.json")
        self.state_path = os.path.join(state_root, "state.json")
        self.preview_path = os.path.join(state_root, "theme", "background.png")

        self._env = dict(os.environ)
        self._env["XDG_STATE_HOME"] = os.path.dirname(state_root)

        self._loading = False
        self._busy = False
        self._closing = False
        self._alive = True
        self._last_save_failed = False
        self._edit_revision = 0
        self._current_session = ""
        self._transparency = 50
        self._base_rgb = None
        self._base_w = self._base_h = 0
        self._disp_img = None

        self._queue = queue.Queue()

        self.client = WallpaperClient(
            runner=self._run_wallpaper,
            scheduler=lambda ms, f: self.root.after(ms, f),
            scheduler_cancel=self.root.after_cancel,
            on_result=lambda r: self._enqueue(self._apply_save_result, r),
        )

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_poll()
        self.root.after(50, self.refresh_status)

    # ----- 后端调用（主线程构造，子线程执行）-----
    def _run_wallpaper(self, args, timeout=30):
        return self._run_script(self.wallpaper_script, args, timeout)

    def _run_script(self, script, args, timeout=30):
        cmd = [BASH, script] + list(args)
        try:
            proc = subprocess.run(cmd, env=self._env, capture_output=True,
                                  text=True, timeout=timeout)
            if proc.returncode != 0 and proc.stdout.strip() == "":
                return proc.returncode, proc.stdout, (proc.stderr or "命令返回非零状态").strip()[-400:]
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return None, "", "后端命令超时（%d 秒）" % timeout
        except Exception as e:
            return None, "", "无法运行 %s：%s" % (os.path.basename(script), e)

    def _run_control(self, script, args, timeout=120):
        cmd = [BASH, script] + list(args)
        try:
            proc = subprocess.run(cmd, env=self._env, capture_output=True,
                                  text=True, timeout=timeout)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return None, "", "控制命令超时（%d 秒）" % timeout
        except Exception as e:
            return None, "", "无法运行 %s：%s" % (os.path.basename(script), e)

    # ----- 队列：子线程只投递，主线程轮询执行 -----
    def _enqueue(self, fn, *args):
        self._queue.put((fn, args))

    def _start_poll(self):
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _poll(self):
        if not self._alive:
            return
        try:
            while True:
                fn, args = self._queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        if self._closing:
            idle = self.client.is_idle() and self.client._timer is None
            if idle and not self._busy and not self._last_save_failed:
                self._alive = False
                try:
                    self.root.destroy()
                except Exception:
                    pass
                return
            # 保存失败：取消关闭、恢复 UI、允许重试（不静默销毁）
            if self._last_save_failed and idle and not self._busy:
                self._closing = False
                self._last_save_failed = False
                self._set_controls_enabled("normal")
                self._set_message("保存失败，请调整后重试。", ERR_COLOR)
        self._poll_id = self.root.after(POLL_MS, self._poll)

    # ----- UI 构建（可滚动，确保内容完整可见）-----
    def _build_ui(self):
        self.root.title("Dream Skin 设置")
        self.root.geometry("680x780")
        try:
            self.root.minsize(620, 680)
        except Exception:
            pass
        self.root.configure(bg=BG)

        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=8)
        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vscroll = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vscroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        self._body = tk.Frame(self._canvas, bg=BG)
        self._win = self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>",
                        lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # 滚轮：Windows/macOS 用 MouseWheel，Linux 用 Button-4/5
        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self._canvas.bind_all("<Button-4>",
                              lambda e: self._canvas.yview_scroll(-1, "units"))
        self._canvas.bind_all("<Button-5>",
                              lambda e: self._canvas.yview_scroll(1, "units"))

        self._build_header(self._body)
        self._build_skin_card(self._body)
        self._build_bg_card(self._body)
        self._build_refresh_card(self._body)
        self._build_message(self._body)

    def _build_header(self, parent):
        f = tk.Frame(parent, bg=BG, padx=10, pady=6)
        f.pack(fill="x")
        tk.Label(f, text="主题", bg=BG, fg=TEXT_DIM, font=("Sans", 10)).pack(anchor="w")
        self.theme_var = tk.StringVar(value="—")
        tk.Label(f, textvariable=self.theme_var, bg=BG, fg=TEXT,
                 font=("Sans", 15, "bold")).pack(anchor="w", pady=(0, 6))
        self.status_pill = tk.Canvas(f, width=130, height=22, bg=BG, highlightthickness=0)
        self.status_pill.create_oval(2, 4, 16, 18, fill=TEXT_DIM, tags="dot")
        self.status_pill.create_text(24, 11, anchor="w", text="未知", fill=TEXT_DIM,
                                     font=("Sans", 10), tags="txt")
        self.status_pill.pack(anchor="w")

    def _build_skin_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(14, 0))
        self.skin_card = card
        self._section_title(card, "皮肤")
        self.skin_status_var = tk.StringVar(value="未知")
        tk.Label(card, textvariable=self.skin_status_var, bg=CARD, fg=TEXT_DIM,
                 font=("Sans", 11)).pack(anchor="w", padx=14, pady=(0, 12))
        self.toggle_btn = self._button(card, "启用皮肤", self._on_toggle_skin)
        self.toggle_btn.pack(anchor="w", padx=14, pady=(0, 14))

    def _build_bg_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(14, 0))
        self.bg_card = card
        self._section_title(card, "背景")
        self.show_bg_var = tk.BooleanVar(value=True)
        self.show_bg_cb = tk.Checkbutton(
            card, text="显示背景图（保留主题配色）", variable=self.show_bg_var,
            bg=CARD, fg=TEXT, selectcolor=CARD, activebackground=CARD,
            activeforeground=ACCENT, relief="flat", command=self._on_show_bg,
            font=("Sans", 11))
        self.show_bg_cb.pack(anchor="w", padx=14, pady=(4, 10))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=14)
        tk.Label(row, text="图片透明度", bg=CARD, fg=TEXT_DIM, font=("Sans", 10)).pack(side="left")
        self.pct_var = tk.StringVar(value="50%")
        tk.Label(row, textvariable=self.pct_var, bg=CARD, fg=ACCENT,
                 font=("Sans", 11, "bold")).pack(side="right")

        self.scale = tk.Scale(card, from_=0, to=100, orient="horizontal", resolution=1,
                              showvalue=0, bg=CARD, fg=TEXT, troughcolor="#16181d",
                              activebackground=ACCENT, highlightthickness=0, relief="flat",
                              command=self._on_scale)
        self.scale.set(50)
        self.scale.pack(fill="x", padx=14, pady=(2, 6))

        prev_row = tk.Frame(card, bg=CARD)
        prev_row.pack(fill="x", padx=14, pady=(4, 14))
        self.preview = tk.Canvas(prev_row, width=PREVIEW_W, height=PREVIEW_H, bg=BG,
                                 highlightthickness=1, highlightbackground=LINE)
        self.preview.pack(side="left")
        self._cache_base()
        self.render_preview()
        right = tk.Frame(prev_row, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        tk.Label(right, text="0 = 完全显示，100 = 隐藏图片（仍启用）",
                 bg=CARD, fg=TEXT_DIM, font=("Sans", 9)).pack(anchor="w", pady=(0, 10))
        self.reset_btn = self._button(right, "恢复 50%", self._on_reset)
        self.reset_btn.pack(anchor="w")

    def _build_refresh_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=(14, 0))
        self.refresh_card = card
        self.refresh_btn = self._button(card, "刷新状态", self._on_refresh)
        self.refresh_btn.pack(anchor="w", padx=14, pady=12)

    def _build_message(self, parent):
        self.msg_var = tk.StringVar(value="")
        self.msg_label = tk.Label(parent, textvariable=self.msg_var, bg=BG, fg=TEXT_DIM,
                                  font=("Sans", 10), anchor="w", wraplength=620,
                                  justify="left")
        self.msg_label.pack(fill="x", padx=12, pady=(12, 4))

    # ----- 小组件助手 -----
    def _on_canvas_configure(self, event):
        try:
            self._canvas.itemconfigure(self._win, width=self._canvas.winfo_width())
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        except Exception:
            pass

    def _card(self, parent):
        return tk.Frame(parent, bg=CARD, padx=0, pady=8,
                        highlightthickness=1, highlightbackground=LINE)

    def _section_title(self, parent, text):
        tk.Label(parent, text=text, bg=CARD, fg=ACCENT,
                 font=("Sans", 11, "bold")).pack(anchor="w", padx=14, pady=(8, 4))

    def _button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=BTN, fg=TEXT,
                         activebackground=BTN_ACTIVE, activeforeground=ACCENT,
                         relief="flat", highlightthickness=0, font=("Sans", 11),
                         padx=14, pady=6, cursor="hand2")

    # ----- 控件回调（主线程）-----
    def _on_scale(self, value):
        try:
            t = int(float(value))
        except ValueError:
            return
        self._transparency = t
        self.pct_var.set("%d%%" % t)
        self.render_preview()
        if self._loading:
            return
        self._edit_revision += 1
        self.client.update(transparency=t)

    def _on_show_bg(self):
        if self._loading:
            return
        self.render_preview()
        self._edit_revision += 1
        self.client.update(enabled=self.show_bg_var.get())

    def _on_reset(self):
        self._loading = True
        self.scale.set(50)
        self._transparency = 50
        self.pct_var.set("50%")
        self.render_preview()
        self._loading = False
        self._edit_revision += 1
        self.client.update(transparency=50)

    def _on_refresh(self):
        self.refresh_status(show_message=True)

    def _on_toggle_skin(self):
        if self._busy or self._closing:
            return
        session = self._current_session
        if session == "active":
            script, label = self.pause_script, "正在暂停皮肤…"
        else:
            script, label = self.start_script, "正在启用皮肤…"
        self._busy = True
        self._set_message(label, ACCENT)
        self.toggle_btn.configure(state="disabled")
        threading.Thread(target=self._toggle_worker, args=(script,), daemon=True).start()

    def _toggle_worker(self, script):
        rc, out, err = self._run_control(script, [], timeout=120)
        msg = (out or err or "").strip()[-400:]
        self._enqueue(self._toggle_done, rc == 0, msg)

    def _toggle_done(self, ok, msg):
        self._busy = False
        self.toggle_btn.configure(state="normal")
        if not ok:
            self._set_message(msg or "操作未完成", ERR_COLOR)
        self.refresh_status(show_message=ok)

    # ----- 保存结果（经队列在主线程执行，仅更新消息）-----
    def _apply_save_result(self, result):
        if result.get("ok"):
            self._last_save_failed = False
            self._set_message(result.get("message") or "已保存", OK_COLOR)
        else:
            self._last_save_failed = True
            self._set_message(result.get("error") or "保存失败", ERR_COLOR)

    # ----- 状态加载/刷新：后端调用在后台线程，UI 更新经队列 -----
    def refresh_status(self, show_message=True):
        if show_message:
            self._set_message("刷新中…", TEXT_DIM)
        threading.Thread(target=self._refresh_worker, args=(show_message, self._edit_revision),
                         daemon=True).start()

    def _refresh_worker(self, show_message, revision):
        theme = self._read_json(self.theme_path)
        state = self._read_json(self.state_path)
        theme_name = "—"
        if isinstance(theme, dict):
            theme_name = theme.get("name") or theme.get("id") or "—"
        session = ""
        if isinstance(state, dict):
            session = str(state.get("session", "") or "")
        rc, out, err = self._run_wallpaper(["status", "--json"], timeout=15)
        parsed = parse_status_json(out)
        status = {
            "theme_name": theme_name, "session": session, "edit_revision": revision, "valid": parsed is not None,
            "enabled": True, "transparency": 50,
            "message": "", "applied": False,
        }
        if parsed is None:
            status["message"] = "离线：未能连接后端（%s）" % (err.strip()[-200:] or "无输出")
        else:
            status["enabled"] = parsed["enabled"]
            status["transparency"] = settings_opacity_to_transparency(parsed["opacity"])
            status["message"] = parsed.get("message", "")
            status["applied"] = parsed.get("applied", False)
        self._enqueue(self._apply_status, status, show_message)

    def _apply_status(self, status, show_message):
        self._current_session = status.get("session", "")
        self.theme_var.set(status.get("theme_name", "—"))
        self._update_skin_status(self._current_session)
        self._update_status_pill(self._current_session)
        if show_message and status.get("message"):
            self._set_message(status["message"],
                              OK_COLOR if status.get("applied") else TEXT_DIM)
        # 仅在“无在途且无本地未决改动（desired==applied）”时同步控件，
        # 避免覆盖用户正在拖动或刚保存（尚未被本次刷新读取到）的值。
        if status.get("valid") and status.get("edit_revision") == self._edit_revision and self.client.is_idle() and \
           self.client.desired_enabled == self.client.applied_enabled and \
           self.client.desired_transparency == self.client.applied_transparency:
            enabled = status["enabled"]
            transparency = status["transparency"]
            self._loading = True
            self.show_bg_var.set(enabled)
            self.scale.set(transparency)
            self._transparency = transparency
            self.pct_var.set("%d%%" % transparency)
            self.render_preview()
            self._loading = False
            self.client.set_applied(enabled, transparency)

    def _update_skin_status(self, session):
        labels = {
            "active": "皮肤运行中", "paused": "皮肤已暂停", "applying": "正在应用…",
            "pausing": "正在暂停…", "stale": "状态异常（请刷新）", "off": "皮肤未启用",
            "": "皮肤未启用",
        }
        self.skin_status_var.set(labels.get(session, "未知"))

    def _update_status_pill(self, session):
        color = {
            "active": OK_COLOR, "applying": ACCENT, "pausing": ACCENT,
            "paused": "#d9b36b", "stale": ERR_COLOR, "off": TEXT_DIM, "": TEXT_DIM,
        }.get(session, TEXT_DIM)
        self.status_pill.itemconfig("dot", fill=color)
        self.status_pill.itemconfig("txt", text=self._session_short(session), fill=color)

    def _session_short(self, session):
        return {
            "active": "运行中", "paused": "已暂停", "applying": "应用中",
            "pausing": "暂停中", "stale": "异常", "off": "未启用", "": "未启用",
        }.get(session, "未知")

    # ----- 预览：PPM 合成（缓存 base RGB，拖动只复合小图）-----
    def _cache_base(self):
        self._base_rgb = None
        self._base_w = self._base_h = 0
        if not os.path.isfile(self.preview_path):
            return
        try:
            img = tk.PhotoImage(file=self.preview_path)
            bw, bh = img.width(), img.height()
            f = max(bw // PREVIEW_W, bh // PREVIEW_H, 1)
            if f > 1:
                img = img.subsample(f)
            w, h = img.width(), img.height()
            rgb = []
            for y in range(h):
                for x in range(w):
                    c = img.get(x, y)
                    if isinstance(c, (tuple, list)):   # Tk 9.x 返回 (r,g,b)
                        rgb.append((int(c[0]), int(c[1]), int(c[2])))
                    else:                              # Tk 8.6 返回 "#rrggbb"
                        rgb.append(hex_to_rgb(c))
            self._base_rgb, self._base_w, self._base_h = rgb, w, h
        except Exception:
            self._base_rgb = None

    def render_preview(self):
        cv = self.preview
        cv.delete("all")
        w, h = PREVIEW_W, PREVIEW_H
        if not self.show_bg_var.get():
            ppm = solid_ppm(w, h, BG_RGB)            # 背景图关闭 -> 纯色
        elif self._base_rgb is not None:
            ppm = composite_ppm(self._base_w, self._base_h, self._base_rgb,
                                BG_RGB, self._transparency / 100.0)
            w, h = self._base_w, self._base_h
        else:
            ppm = fallback_ppm(PREVIEW_W, PREVIEW_H)  # 退色彩预览
        try:
            self._disp_img = tk.PhotoImage(data=ppm)
        except Exception:
            self._disp_img = tk.PhotoImage(data=solid_ppm(PREVIEW_W, PREVIEW_H, CARD_RGB))
        cv.create_image((PREVIEW_W - w) // 2, (PREVIEW_H - h) // 2,
                        image=self._disp_img, anchor="nw")

    # ----- 关闭：禁用 UI 并异步等待最后请求完成再销毁 -----
    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        self._set_controls_enabled("disabled")
        self.client.cancel_pending()           # 清掉待发计时器
        with self.client._lock:
            need = (self.client.desired_enabled != self.client.applied_enabled) or \
                   (self.client.desired_transparency != self.client.applied_transparency)
        if need:
            self.client._dispatch()            # 保证最后的 desired 目标被保存
        # _poll 在空闲（无在途/无计时器/非 busy/未失败）时销毁窗口

    def _set_controls_enabled(self, state):
        for w in (self.scale, self.show_bg_cb, self.toggle_btn,
                  self.reset_btn, self.refresh_btn):
            try:
                w.configure(state=state)
            except Exception:
                pass

    # ----- 消息 / 工具 -----
    def _set_message(self, text, color):
        self.msg_var.set(text or "")
        self.msg_label.configure(fg=color)

    def _read_json(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def resolve_state_root(args):
    if args.state_root:
        return os.path.abspath(args.state_root)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return os.path.join(xdg, "codex-dream-skin")
    return os.path.expanduser("~/.local/state/codex-dream-skin")


def main():
    parser = argparse.ArgumentParser(description="Dream Skin 设置面板")
    parser.add_argument("--state-root", default=None,
                        help="状态目录（codex-dream-skin），用于 demo/test")
    parser.add_argument("--self-test", action="store_true",
                        help="无显示环境下的输入转换与合并验证")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    state_root = resolve_state_root(args)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(script_dir):
        sys.stderr.write("错误：脚本目录不存在：%s\n" % script_dir)
        return 2
    wallpaper_script = os.environ.get("DREAMSKIN_WALLPAPER_SCRIPT") or \
        os.path.join(script_dir, "wallpaper-linux.sh")
    start_script = os.path.join(script_dir, "start-dream-skin-linux.sh")
    pause_script = os.path.join(script_dir, "pause-dream-skin-linux.sh")
    if not os.path.isfile(wallpaper_script):
        sys.stderr.write("错误：未找到后端脚本：%s\n" % wallpaper_script)
        return 2

    root = tk.Tk(className="DreamSkinSettings")
    SettingsPanel(root, state_root, wallpaper_script, start_script, pause_script)
    root.mainloop()
    return 0


# ---------------------------------------------------------------------------
# 无界面自测：验证输入转换与请求合并（不创建 Tk 窗口）
# ---------------------------------------------------------------------------

def run_self_test():
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)

    check("t50", transparency_to_image_opacity_pct(50) == 50)
    check("t0", transparency_to_image_opacity_pct(0) == 100)
    check("t100", transparency_to_image_opacity_pct(100) == 0)
    check("o05", settings_opacity_to_transparency(0.5) == 50)
    check("o1", settings_opacity_to_transparency(1.0) == 0)
    check("o0", settings_opacity_to_transparency(0.0) == 100)
    s = parse_status_json('{"settings":{"schemaVersion":1,"enabled":true,'
                          '"opacity":0.25},"applied":true,"session":"active","message":"ok"}')
    check("parse", bool(s) and s["opacity"] == 0.25 and s["enabled"] is True)
    check("parsebad", parse_status_json("not json") is None)

    calls = []

    class FakeScheduler:
        def __init__(self):
            self.pending = None

        def schedule(self, ms, f):
            self.pending = f
            return id(f)

        def cancel(self, token):
            self.pending = None

        def advance(self):
            if self.pending:
                f = self.pending
                self.pending = None
                f()

    def runner(args, timeout):
        calls.append(list(args))
        return 0, '{"settings":{"schemaVersion":1,"enabled":true,"opacity":0.5},' \
                  '"applied":true,"session":"active","message":""}', ""

    fs = FakeScheduler()
    client = WallpaperClient(runner=runner, scheduler=fs.schedule,
                             scheduler_cancel=fs.cancel, on_result=lambda r: None)
    client.set_applied(True, 50)
    client.update(transparency=10)
    client.update(transparency=20)
    fs.advance(); client.wait_inflight(5); fs.advance(); client.wait_inflight(5)
    check("merge1", len(calls) == 1 and calls[0] == ["opacity", "80", "--json"])

    calls.clear()
    client.set_applied(True, 50)
    client.update(enabled=False, transparency=100)
    fs.advance(); client.wait_inflight(5); fs.advance(); client.wait_inflight(5)
    check("merge2", len(calls) == 2 and calls[0] == ["off", "--json"]
          and calls[1] == ["opacity", "0", "--json"])

    if fails:
        sys.stderr.write("SELF-TEST FAILED: %s\n" % ", ".join(fails))
        return 1
    sys.stdout.write("SELF-TEST OK (conversions + request merge verified)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
