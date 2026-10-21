#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
settings-panel.py 的无 GUI 单元测试。

仅通过 importlib 加载产品模块并实例化 WallpaperClient / 调用纯函数，
绝不创建 Tk 窗口、不触碰真实设置目录、不启动后端或 ChatGPT。

覆盖：
  - WallpaperClient 请求合并（worker 阻塞期间多次更新 desired，放行后
    最终串行保存最新值，不并发重复派发）；
  - 失败不会假记 applied，也不重试；
  - 关闭路径的纯逻辑“需要保存”判定 + 在途请求期间 _dispatch 安全（不并发）；
  - parse_status_json 对 malformed 输入一律返回 None；
  - PPM 极值 alpha=0/1 合成；
  - 透明度与 image opacity 转换边界。

同步方式：用 threading.Event（带 timeout）等待 worker，绝不 sleep 轮询。
"""

import importlib.util
import os
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCT = os.path.normpath(os.path.join(HERE, "..", "scripts", "settings-panel.py"))

_spec = importlib.util.spec_from_file_location("dreamskin_settings_panel", PRODUCT)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

WallpaperClient = _module.WallpaperClient
parse_status_json = _module.parse_status_json
composite_ppm = _module.composite_ppm
solid_ppm = _module.solid_ppm
fallback_ppm = _module.fallback_ppm
transparency_to_image_opacity_pct = _module.transparency_to_image_opacity_pct
settings_opacity_to_transparency = _module.settings_opacity_to_transparency

GOOD_STATUS = ('{"settings":{"schemaVersion":1,"enabled":true,"opacity":0.5},'
               '"applied":true,"session":"active","message":"ok"}')


class FakeScheduler:
    """最小 after/cancel 实现：记录唯一待发 dispatch，advance() 手动触发。"""

    def __init__(self):
        self._token = 0
        self.pending = None  # (token, fn)

    def schedule(self, ms, f):
        self._token += 1
        self.pending = (self._token, f)
        return self._token

    def cancel(self, token):
        if self.pending is not None and self.pending[0] == token:
            self.pending = None

    def advance(self):
        if self.pending is not None:
            _, f = self.pending
            self.pending = None
            f()


class BlockingRunner:
    """runner 在被调用后阻塞，直到测试调用 release_now()；记录每次调用。"""

    def __init__(self, status=GOOD_STATUS, rc=0):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()   # 每次调用返回后置位
        self.status = status
        self.rc = rc

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        self.started.set()
        self.release.wait(timeout=15)
        self.done.set()
        return self.rc, self.status, ""

    def release_now(self):
        self.release.set()


def make_client(runner):
    fs = FakeScheduler()
    results = []
    result_event = threading.Event()

    def on_result(r):
        results.append(r)
        result_event.set()  # 在 worker 内 applied 已写入之后才调用，故可据此同步

    client = WallpaperClient(runner=runner, scheduler=fs.schedule,
                             scheduler_cancel=fs.cancel, on_result=on_result)
    return client, fs, results, result_event


def wait_results(results, event, n, timeout):
    """事件驱动等待：直到收到 n 个 on_result（不 sleep 轮询）。"""
    end = time.time() + timeout
    while len(results) < n:
        remaining = end - time.time()
        if remaining <= 0:
            return False
        event.wait(remaining)
        event.clear()
    return True


class TestWallpaperClientMerge(unittest.TestCase):
    """worker 阻塞期间 desired 多次更新 -> 放行后最终保存最新值，串行。"""

    def test_merge_saves_latest_serialized(self):
        runner = BlockingRunner()
        client, fs, results, result_event = make_client(runner)
        client.set_applied(True, 50)
        client.update(transparency=10)   # 待发
        client.update(transparency=20)   # 取消上一条，覆盖
        fs.advance()                     # 触发 dispatch -> worker1 启动并阻塞
        self.assertTrue(runner.started.wait(timeout=5))

        # worker 阻塞期间继续更新（不立即派发，仅改 desired）
        client.update(transparency=30)
        client.update(transparency=40)

        runner.release_now()             # 放行 worker1

        # 等待两次派发（含合并重派发）的 on_result，applied 已落定
        self.assertTrue(wait_results(results, result_event, 2, timeout=5))

        # 第一次应用了 worker1 启动时读到的值(20 -> opacity 80)，
        # 随后合并重派发应用了最新值(40 -> opacity 60)。
        self.assertEqual(runner.calls, [
            ["opacity", "80", "--json"],
            ["opacity", "60", "--json"],
        ])
        # The pending debounce still belongs to the UI thread; consume it as Tk would.
        client.wait_inflight(timeout=5)
        fs.advance()
        # 最终状态：最新 desired 已被 applied，且无在途/待发
        self.assertEqual(client.desired_transparency, 40)
        self.assertEqual(client.applied_transparency, 40)
        client.wait_inflight(timeout=5)
        self.assertTrue(client.is_idle())

    def test_dispatch_while_inflight_is_noop_close_safe(self):
        """模拟关闭时若已有在途请求，_dispatch 不应并发重复派发。"""
        runner = BlockingRunner()
        client, fs, results, result_event = make_client(runner)
        client.set_applied(True, 50)
        client.update(transparency=10)
        fs.advance()
        self.assertTrue(runner.started.wait(timeout=5))

        n = len(runner.calls)
        client._dispatch()               # 关闭路径会调用；in-flight 下应为安全空操作
        self.assertEqual(len(runner.calls), n)   # 没有新的并发 runner 调用

        runner.release_now()
        self.assertTrue(wait_results(results, result_event, 1, timeout=5))
        # 在途 worker 自身会保存最新 desired
        self.assertEqual(client.applied_transparency, 10)
        self.assertEqual(client.desired_transparency, 10)


class TestFailureNotApplied(unittest.TestCase):
    def test_failure_keeps_applied_and_no_retry(self):
        runner = BlockingRunner(rc=1, status="")  # 后端失败
        client, fs, results, result_event = make_client(runner)
        client.set_applied(True, 50)
        client.update(transparency=10)
        fs.advance()
        runner.release_now()             # 让阻塞的 runner 返回失败
        self.assertTrue(wait_results(results, result_event, 1, timeout=5))

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        # 失败绝不应假记 applied
        self.assertEqual(client.applied_transparency, 50)
        self.assertEqual(client.desired_transparency, 10)
        # 失败后不重试（无第二次后端调用）
        self.assertEqual(len(runner.calls), 1)
        client.wait_inflight(timeout=5)
        self.assertTrue(client.is_idle())


class TestPartialSave(unittest.TestCase):
    def test_successful_toggle_is_remembered_after_opacity_failure(self):
        calls = []
        def runner(args, timeout):
            calls.append(args[0])
            return (1, "", "opacity failed") if args[0] == "opacity" else (0, GOOD_STATUS, "")
        client, scheduler, results, event = make_client(runner)
        client.update(enabled=False, transparency=70)
        scheduler.advance()
        client.wait_inflight(5)
        self.assertEqual(calls, ["off", "opacity"])
        self.assertFalse(client.applied_enabled)
        self.assertEqual(client.applied_transparency, 50)
        client.update(enabled=True, transparency=50)
        scheduler.advance()
        client.wait_inflight(5)
        self.assertEqual(calls[-1], "on")
        self.assertTrue(client.applied_enabled)


class TestCloseNeedSavePredicate(unittest.TestCase):
    """关闭“需要保存”判定是纯逻辑：desired != applied 时需保存。"""

    def test_need_save_predicate(self):
        runner = BlockingRunner()
        client, fs, _, _ = make_client(runner)
        client.set_applied(True, 50)
        # 已同步：无需保存
        need = (client.desired_enabled != client.applied_enabled) or \
               (client.desired_transparency != client.applied_transparency)
        self.assertFalse(need)
        # 有未决改动：需要保存
        client.update(transparency=80)
        need = (client.desired_enabled != client.applied_enabled) or \
               (client.desired_transparency != client.applied_transparency)
        self.assertTrue(need)
        # 应用后再次同步
        client.set_applied(client.desired_enabled, client.desired_transparency)
        need = (client.desired_enabled != client.applied_enabled) or \
               (client.desired_transparency != client.applied_transparency)
        self.assertFalse(need)


class TestParseStatusJson(unittest.TestCase):
    def test_valid(self):
        s = parse_status_json('{"settings":{"enabled":false,"opacity":0.25},'
                              '"applied":true,"session":"paused","message":"m"}')
        self.assertIsNotNone(s)
        self.assertFalse(s["enabled"])
        self.assertEqual(s["opacity"], 0.25)
        self.assertTrue(s["applied"])
        self.assertEqual(s["session"], "paused")

    def test_malformed_returns_none(self):
        cases = [
            "",                       # 空
            None,                     # None
            "not json",               # 非 JSON
            "[1,2,3]",                # 非 dict
            '{"settings":"bad"}',     # settings 非 dict
            '{"settings":{"opacity":"abc"}}',  # opacity 非数值
        ]
        for c in cases:
            self.assertIsNone(parse_status_json(c), msg="case=%r" % (c,))

    def test_missing_or_invalid_settings_do_not_overwrite_ui(self):
        for value in ['{"settings":null}', '{}', '{"settings":{"enabled":"false"}}',
                      '{"settings":{"enabled":true,"opacity":1.1}}',
                      '{"settings":{"enabled":true,"opacity":NaN}}']:
            self.assertIsNone(parse_status_json(value))


class TestPpmExtremes(unittest.TestCase):
    def test_composite_alpha_zero_and_one(self):
        rgb = [(10, 20, 30)]
        bg = (200, 100, 50)
        # alpha=0 -> 完全显示图片（纯 rgb）
        p0 = composite_ppm(1, 1, rgb, bg, 0.0)
        self.assertEqual(p0, b"P6\n1 1\n255\n" + bytes((10, 20, 30)))
        # alpha=1 -> 完全显示背景（纯 bg）
        p1 = composite_ppm(1, 1, rgb, bg, 1.0)
        self.assertEqual(p1, b"P6\n1 1\n255\n" + bytes((200, 100, 50)))

    def test_solid_and_fallback_structure(self):
        s = solid_ppm(2, 3, (1, 2, 3))
        self.assertTrue(s.startswith(b"P6\n2 3\n255\n"))
        self.assertEqual(len(s) - len(b"P6\n2 3\n255\n"), 2 * 3 * 3)
        f = fallback_ppm(4, 2)
        self.assertTrue(f.startswith(b"P6\n4 2\n255\n"))
        self.assertEqual(len(f) - len(b"P6\n4 2\n255\n"), 4 * 2 * 3)


class TestTransparencyConversion(unittest.TestCase):
    def test_to_image_opacity_edges(self):
        self.assertEqual(transparency_to_image_opacity_pct(0), 100)
        self.assertEqual(transparency_to_image_opacity_pct(50), 50)
        self.assertEqual(transparency_to_image_opacity_pct(100), 0)
        self.assertEqual(transparency_to_image_opacity_pct(150), 0)   # clamp
        self.assertEqual(transparency_to_image_opacity_pct(-10), 100) # clamp

    def test_from_settings_opacity_edges(self):
        self.assertEqual(settings_opacity_to_transparency(0.0), 100)
        self.assertEqual(settings_opacity_to_transparency(1.0), 0)
        self.assertEqual(settings_opacity_to_transparency(0.5), 50)
        self.assertEqual(settings_opacity_to_transparency(2.0), 0)     # clamp
        self.assertEqual(settings_opacity_to_transparency(-1.0), 100)  # clamp
        self.assertEqual(settings_opacity_to_transparency("bad"), 50)  # 默认 0.5


if __name__ == "__main__":
    unittest.main(verbosity=2)
