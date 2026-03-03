"""Unit tests for cue.platform — factory function, LinuxEnvironment, WindowsEnvironment."""

from __future__ import annotations

import io
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_png_bytes(width: int = 8, height: int = 8) -> bytes:
    """Return minimal valid PNG bytes for a solid-colour image."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(100, 149, 237)).save(buf, format="PNG")
    return buf.getvalue()


def _make_mock_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Return an AsyncMock that behaves like asyncio.subprocess.Process."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=None)
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ─── TestCreateEnvironment ────────────────────────────────────────────────────


class TestCreateEnvironment:
    """Test create_environment() factory with patched sys.platform."""

    def test_linux_creates_linux_env(self):
        # Patch sys.platform inside the base module's namespace (where it reads it)
        from cue.platform import base as _base
        from cue.platform.linux import LinuxEnvironment

        with patch.object(_base.sys, "platform", "linux"):
            env = _base.create_environment()
        assert isinstance(env, LinuxEnvironment)

    def test_linux_branch_returns_linux_instance(self):
        from cue.platform import base as _base
        from cue.platform.linux import LinuxEnvironment

        with patch.object(_base.sys, "platform", "linux"):
            env = _base.create_environment()
        assert isinstance(env, LinuxEnvironment)

    def test_win32_creates_windows_env(self):
        from cue.platform import base as _base
        from cue.platform.windows import WindowsEnvironment

        with patch.object(_base.sys, "platform", "win32"):
            env = _base.create_environment()
        assert isinstance(env, WindowsEnvironment)

    def test_darwin_raises_not_implemented(self):
        from cue.platform import base as _base

        with patch.object(_base.sys, "platform", "darwin"):
            with pytest.raises(NotImplementedError, match="macOS support"):
                _base.create_environment()

    def test_unsupported_raises_runtime_error(self):
        from cue.platform import base as _base

        with patch.object(_base.sys, "platform", "freebsd"):
            with pytest.raises(RuntimeError, match="Unsupported platform"):
                _base.create_environment()


# ─── TestLinuxEnvironment ─────────────────────────────────────────────────────


class TestLinuxEnvironment:
    """Tests for LinuxEnvironment using mocked subprocess calls."""

    def _env(self):
        from cue.platform.linux import LinuxEnvironment

        return LinuxEnvironment()

    # ── Screenshot ────────────────────────────────────────────────────────────

    async def test_take_screenshot_returns_image(self, tmp_path):
        env = self._env()
        png_bytes = _make_png_bytes(1920, 1080)

        import os
        import tempfile

        real_mkstemp = tempfile.mkstemp

        def fake_mkstemp(suffix="", prefix="", dir=None, text=False):
            # Create a real temp file pre-populated with PNG data and return an
            # open fd so that production code's os.close(fd) succeeds.
            fd, path = real_mkstemp(suffix=suffix, prefix=prefix)
            with open(path, "wb") as f:
                f.write(png_bytes)
            # fd is still open — production code will close it
            return fd, path

        proc_ok = _make_mock_proc(b"", b"", returncode=0)

        with patch("tempfile.mkstemp", side_effect=fake_mkstemp):
            with patch("asyncio.create_subprocess_exec", return_value=proc_ok):
                img = await env.take_screenshot(width=1024, height=768)

        assert isinstance(img, Image.Image)
        assert img.size == (1024, 768)

    async def test_take_screenshot_fallback_to_import(self, tmp_path):
        """When scrot fails (returncode != 0), falls back to 'import'."""
        env = self._env()
        png_bytes = _make_png_bytes(800, 600)

        import tempfile

        real_mkstemp = tempfile.mkstemp

        def fake_mkstemp(suffix="", prefix="", dir=None, text=False):
            fd, path = real_mkstemp(suffix=suffix, prefix=prefix)
            with open(path, "wb") as f:
                f.write(png_bytes)
            return fd, path

        procs = [
            _make_mock_proc(b"", b"scrot error", returncode=1),  # scrot fails
            _make_mock_proc(b"", b"", returncode=0),              # import succeeds
        ]
        proc_iter = iter(procs)

        with patch("tempfile.mkstemp", side_effect=fake_mkstemp):
            with patch("asyncio.create_subprocess_exec", side_effect=lambda *a, **kw: next(proc_iter)):
                img = await env.take_screenshot(width=800, height=600)

        assert isinstance(img, Image.Image)

    # ── Click ─────────────────────────────────────────────────────────────────

    async def test_click_left(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.click(100, 200, button="left", click_count=1)

        args = mock_exec.call_args[0]
        assert args[0] == "xdotool"
        assert "mousemove" in args
        assert "100" in args
        assert "200" in args
        assert "click" in args
        assert "--repeat" in args
        assert "1" in args  # button num for left

    async def test_click_right(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.click(50, 60, button="right")

        args = mock_exec.call_args[0]
        # button number 3 should appear
        assert "3" in args

    async def test_double_click(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.click(10, 20, button="left", click_count=2)

        args = mock_exec.call_args[0]
        assert "--repeat" in args
        idx = list(args).index("--repeat")
        assert args[idx + 1] == "2"

    # ── Keyboard ──────────────────────────────────────────────────────────────

    async def test_send_keys(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.send_keys("hello")

        args = mock_exec.call_args[0]
        assert args[0] == "xdotool"
        assert "type" in args
        assert "--clearmodifiers" in args
        assert "--delay" in args
        assert "hello" in args

    async def test_send_key(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.send_key("Return")

        args = mock_exec.call_args[0]
        assert args[0] == "xdotool"
        assert "key" in args
        assert "--clearmodifiers" in args
        assert "Return" in args

    async def test_send_key_translates_enter(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.send_key("Enter")

        args = mock_exec.call_args[0]
        # "Enter" should translate to "Return" for xdotool
        assert "Return" in args

    # ── Mouse movement ────────────────────────────────────────────────────────

    async def test_mouse_move(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.mouse_move(300, 400)

        args = mock_exec.call_args[0]
        assert args[0] == "xdotool"
        assert "mousemove" in args
        assert "300" in args
        assert "400" in args

    async def test_mouse_down(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.mouse_down(50, 75, button="left")

        args = mock_exec.call_args[0]
        assert "mousedown" in args
        assert "1" in args  # left button

    async def test_mouse_up(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.mouse_up(50, 75, button="right")

        args = mock_exec.call_args[0]
        assert "mouseup" in args
        assert "3" in args  # right button

    # ── Scroll ────────────────────────────────────────────────────────────────

    async def test_scroll_up(self):
        env = self._env()
        calls = []

        async def fake_exec(*args, **kwargs):
            calls.append(args)
            return _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await env.scroll(100, 200, delta_y=3)

        # First call is mousemove; subsequent calls should include "click" "4"
        click_args = [c for c in calls if "click" in c and "4" in c]
        assert len(click_args) >= 1

    async def test_scroll_down(self):
        env = self._env()
        calls = []

        async def fake_exec(*args, **kwargs):
            calls.append(args)
            return _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await env.scroll(100, 200, delta_y=-3)

        click_args = [c for c in calls if "click" in c and "5" in c]
        assert len(click_args) >= 1

    # ── Clipboard ─────────────────────────────────────────────────────────────

    async def test_get_clipboard(self):
        env = self._env()
        proc = _make_mock_proc(stdout=b"clipboard text", stderr=b"", returncode=0)

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await env.get_clipboard()

        args = mock_exec.call_args[0]
        assert args[0] == "xsel"
        assert "--clipboard" in args
        assert "--output" in args
        assert result == "clipboard text"

    async def test_set_clipboard(self):
        env = self._env()
        proc = _make_mock_proc()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await env.set_clipboard("my text")

        args = mock_exec.call_args[0]
        assert args[0] == "xsel"
        assert "--clipboard" in args
        assert "--input" in args
        # Data passed via stdin in communicate()
        communicate_call = proc.communicate.call_args
        assert b"my text" in communicate_call[1].get("input", communicate_call[0][0] if communicate_call[0] else b"")

    # ── Window info ───────────────────────────────────────────────────────────

    async def test_get_active_window_info(self):
        env = self._env()
        proc_title = _make_mock_proc(stdout=b"My Window Title\n")
        proc_class = _make_mock_proc(stdout=b"MyApp\n")

        procs = iter([proc_title, proc_class])

        with patch("asyncio.create_subprocess_exec", side_effect=lambda *a, **kw: next(procs)):
            info = await env.get_active_window_info()

        assert info["title"] == "My Window Title"
        assert info["app_name"] == "MyApp"

    async def test_get_active_window_info_returns_empty_on_error(self):
        env = self._env()

        with patch("asyncio.create_subprocess_exec", side_effect=OSError("xdotool not found")):
            info = await env.get_active_window_info()

        assert info == {"app_name": "", "title": ""}

    # ── Screen size ───────────────────────────────────────────────────────────

    async def test_get_screen_size_parses_xdpyinfo(self):
        env = self._env()
        xdpyinfo_output = (
            b"name of display:    :99\n"
            b"version number:    11.0\n"
            b"vendor string:     The X.Org Foundation\n"
            b"  dimensions:    1920x1080 pixels (508x285 millimeters)\n"
            b"  resolution:    96x96 dots per inch\n"
        )
        proc = _make_mock_proc(stdout=xdpyinfo_output)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            w, h = await env.get_screen_size()

        assert w == 1920
        assert h == 1080

    async def test_get_screen_size_falls_back_to_default(self):
        env = self._env()
        proc = _make_mock_proc(stdout=b"no useful info here\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            w, h = await env.get_screen_size()

        assert (w, h) == (1920, 1080)

    # ── Key translation helper ────────────────────────────────────────────────

    def test_translate_key_known(self):
        from cue.platform.linux import LinuxEnvironment

        env = LinuxEnvironment()
        assert env._translate_key("Enter") == "Return"
        assert env._translate_key("Backspace") == "BackSpace"
        assert env._translate_key("Page_Up") == "Prior"
        assert env._translate_key("Page_Down") == "Next"

    def test_translate_key_modifier_combo(self):
        from cue.platform.linux import LinuxEnvironment

        env = LinuxEnvironment()
        result = env._translate_key("ctrl+s")
        assert result == "ctrl+s"

    def test_translate_key_passthrough_unknown(self):
        from cue.platform.linux import LinuxEnvironment

        env = LinuxEnvironment()
        assert env._translate_key("F5") == "F5"

    # ── a11y tree graceful degradation ───────────────────────────────────────

    async def test_get_a11y_tree_returns_empty_when_gi_unavailable(self):
        env = self._env()

        # Force ImportError for gi
        with patch.dict(sys.modules, {"gi": None}):
            from cue.types import AccessibilityTree

            tree = await env.get_a11y_tree()

        assert isinstance(tree, AccessibilityTree)
        assert tree.root is None
        assert tree.app_name == ""

    # ── xdotool error propagation ─────────────────────────────────────────────

    async def test_run_xdotool_raises_on_nonzero_returncode(self):
        env = self._env()
        proc = _make_mock_proc(stdout=b"", stderr=b"error msg", returncode=1)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(RuntimeError, match="xdotool failed"):
                await env._run_xdotool("badcommand")


# ─── TestWindowsEnvironment ───────────────────────────────────────────────────


class TestWindowsEnvironment:
    """Tests for WindowsEnvironment with ctypes fully mocked."""

    def _make_windll_mock(self):
        """Build a MagicMock that mimics ctypes.windll."""
        windll = MagicMock()
        user32 = windll.user32
        gdi32 = windll.gdi32
        kernel32 = windll.kernel32

        # Screen metrics
        user32.GetSystemMetrics.side_effect = lambda idx: 1920 if idx == 0 else 1080

        # Window handles
        user32.GetForegroundWindow.return_value = 12345
        user32.GetWindowTextLengthW.return_value = 9
        user32.GetWindowTextW.side_effect = lambda hwnd, buf, n: None
        user32.GetClassNameW.side_effect = lambda hwnd, buf, n: None

        # Clipboard
        user32.OpenClipboard.return_value = 1
        user32.GetClipboardData.return_value = 1
        user32.CloseClipboard.return_value = 1
        kernel32.GlobalLock.return_value = 1
        kernel32.GlobalUnlock.return_value = 1

        return windll

    def _env_with_mocked_ctypes(self):
        """Return a WindowsEnvironment with ctypes.windll replaced."""
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        return env

    # ── Screenshot ────────────────────────────────────────────────────────────

    async def test_take_screenshot_returns_pil_image(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        expected_img = Image.new("RGB", (1920, 1080), color=(0, 0, 0))

        with patch.object(env, "_capture_screen", return_value=expected_img):
            img = await env.take_screenshot(width=1024, height=768)

        assert isinstance(img, Image.Image)
        assert img.size == (1024, 768)

    async def test_take_screenshot_no_resize_when_size_matches(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        expected_img = Image.new("RGB", (1024, 768), color=(0, 0, 0))

        with patch.object(env, "_capture_screen", return_value=expected_img):
            img = await env.take_screenshot(width=1024, height=768)

        assert img.size == (1024, 768)

    def test_capture_screen_fallback_to_imagegrab(self):
        """_capture_screen falls back to PIL.ImageGrab when ctypes calls fail."""
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        fake_img = Image.new("RGB", (800, 600))

        # Make ctypes.windll.user32 raise so we hit the except branch
        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetSystemMetrics.side_effect = OSError("no gdi")
            with patch("PIL.ImageGrab.grab", return_value=fake_img):
                img = env._capture_screen()

        assert img is fake_img

    # ── Click ─────────────────────────────────────────────────────────────────

    async def test_click_calls_set_cursor_and_mouse_event(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            mock_windll.user32.mouse_event.return_value = None
            await env.click(100, 200, button="left", click_count=1)

        mock_windll.user32.SetCursorPos.assert_called_once_with(100, 200)
        assert mock_windll.user32.mouse_event.call_count == 2  # down + up

    async def test_click_right_button_uses_correct_flags(self):
        from cue.platform import windows as win_mod
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        captured_flags = []

        def fake_mouse_event(flag, *args):
            captured_flags.append(flag)

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            mock_windll.user32.mouse_event.side_effect = fake_mouse_event
            await env.click(10, 20, button="right", click_count=1)

        # _MOUSEEVENTF_RIGHTDOWN = 0x0008, _MOUSEEVENTF_RIGHTUP = 0x0010
        assert win_mod._MOUSEEVENTF_RIGHTDOWN in captured_flags
        assert win_mod._MOUSEEVENTF_RIGHTUP in captured_flags

    # ── Keyboard ──────────────────────────────────────────────────────────────

    async def test_send_keys_calls_executor(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch.object(env, "_send_unicode_text") as mock_send:
            await env.send_keys("hello")

        mock_send.assert_called_once_with("hello")

    async def test_send_key_calls_executor(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch.object(env, "_send_key_sync") as mock_sync:
            await env.send_key("Return")

        mock_sync.assert_called_once_with("Return")

    def test_translate_key_enter_maps_to_return(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        assert env._translate_key("Enter") == "Return"

    def test_translate_key_modifier_combo(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        result = env._translate_key("ctrl+s")
        # Both parts should be translated (ctrl stays ctrl, s stays s)
        assert "ctrl" in result
        assert "s" in result

    def test_vk_for_key_known(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        assert env._vk_for_key("Return") == 0x0D
        assert env._vk_for_key("Escape") == 0x1B
        assert env._vk_for_key("Tab") == 0x09

    # ── Window info ───────────────────────────────────────────────────────────

    async def test_get_active_window_info_returns_dict(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        import ctypes

        def fake_get_text_w(hwnd, buf, n):
            buf.value = "Test Window"

        def fake_get_class_w(hwnd, buf, n):
            buf.value = "TestClass"

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetForegroundWindow.return_value = 1
            mock_windll.user32.GetWindowTextLengthW.return_value = 11
            mock_windll.user32.GetWindowTextW.side_effect = fake_get_text_w
            mock_windll.user32.GetClassNameW.side_effect = fake_get_class_w
            mock_windll.user32.create_unicode_buffer = ctypes.create_unicode_buffer

            with patch("ctypes.create_unicode_buffer", side_effect=ctypes.create_unicode_buffer):
                info = await env.get_active_window_info()

        assert "app_name" in info
        assert "title" in info

    async def test_get_active_window_info_returns_empty_on_exception(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetForegroundWindow.side_effect = OSError("no user32")
            info = await env.get_active_window_info()

        assert info == {"app_name": "", "title": ""}

    # ── Screen size ───────────────────────────────────────────────────────────

    async def test_get_screen_size_from_metrics(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetSystemMetrics.side_effect = (
                lambda idx: 2560 if idx == 0 else 1440
            )
            w, h = await env.get_screen_size()

        assert w == 2560
        assert h == 1440

    async def test_get_screen_size_fallback_on_exception(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.GetSystemMetrics.side_effect = OSError("fail")
            w, h = await env.get_screen_size()

        assert (w, h) == (1920, 1080)

    # ── Clipboard ─────────────────────────────────────────────────────────────

    async def test_get_clipboard_returns_empty_on_open_failure(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.OpenClipboard.return_value = 0
            result = await env.get_clipboard()

        assert result == ""

    async def test_set_clipboard_silently_returns_on_alloc_failure(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.kernel32.GlobalAlloc.return_value = 0
            # Should not raise
            await env.set_clipboard("test text")

    # ── Scroll ────────────────────────────────────────────────────────────────

    async def test_scroll_vertical_calls_mouse_event(self):
        from cue.platform.windows import WindowsEnvironment, _MOUSEEVENTF_WHEEL

        env = WindowsEnvironment()
        captured = []

        def fake_mouse_event(flag, *args):
            captured.append((flag, args))

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            mock_windll.user32.mouse_event.side_effect = fake_mouse_event
            await env.scroll(100, 200, delta_y=2)

        wheel_calls = [(f, a) for f, a in captured if f == _MOUSEEVENTF_WHEEL]
        assert len(wheel_calls) == 1

    async def test_scroll_no_delta_no_mouse_event(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            mock_windll.user32.mouse_event.return_value = None
            await env.scroll(100, 200, delta_y=0, delta_x=0)

        mock_windll.user32.mouse_event.assert_not_called()

    # ── mouse_move / mouse_down / mouse_up ────────────────────────────────────

    async def test_mouse_move_sets_cursor_pos(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            await env.mouse_move(300, 400)

        mock_windll.user32.SetCursorPos.assert_called_once_with(300, 400)

    async def test_mouse_down_sets_cursor_and_fires_event(self):
        from cue.platform.windows import WindowsEnvironment

        env = WindowsEnvironment()
        captured = []

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            mock_windll.user32.mouse_event.side_effect = lambda f, *a: captured.append(f)
            await env.mouse_down(10, 20, button="left")

        mock_windll.user32.SetCursorPos.assert_called_once_with(10, 20)
        assert len(captured) == 1  # one mouse_event (down only)

    async def test_mouse_up_fires_up_event(self):
        from cue.platform.windows import WindowsEnvironment, _MOUSEEVENTF_LEFTUP

        env = WindowsEnvironment()
        captured = []

        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.SetCursorPos.return_value = 1
            mock_windll.user32.mouse_event.side_effect = lambda f, *a: captured.append(f)
            await env.mouse_up(10, 20, button="left")

        assert _MOUSEEVENTF_LEFTUP in captured
