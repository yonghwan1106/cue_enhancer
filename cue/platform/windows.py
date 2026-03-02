"""Windows environment implementation using ctypes and UIAutomation."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import time
from io import BytesIO
from typing import Any

from PIL import Image

from cue.platform.base import EnvironmentAbstraction
from cue.types import AccessibilityNode, AccessibilityTree

# ─── ctypes constants ──────────────────────────────────────

# SendInput INPUT types
_INPUT_KEYBOARD = 1
_INPUT_MOUSE = 0

# MOUSEEVENTF flags
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSEEVENTF_ABSOLUTE = 0x8000

# KEYEVENTF flags
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

# Clipboard formats
_CF_UNICODETEXT = 13

# GetSystemMetrics indices
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1

# Key name -> display string (mirrors LinuxEnvironment._translate_key output style)
# These are the canonical CUE key names mapped to Windows-friendly string tokens.
_KEY_NAME_MAP: dict[str, str] = {
    "Return": "Return",
    "Enter": "Return",
    "Tab": "Tab",
    "Escape": "Escape",
    "Backspace": "BackSpace",
    "Delete": "Delete",
    "Space": "space",
    "Up": "Up",
    "Down": "Down",
    "Left": "Left",
    "Right": "Right",
    "Home": "Home",
    "End": "End",
    "Page_Up": "Prior",
    "Page_Down": "Next",
    "Insert": "Insert",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
    "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
    "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "super": "super",
    "win": "super",
}

# Separate VK code table used only for SendInput operations
_VK_CODE_MAP: dict[str, int] = {
    "Return": 0x0D, "Enter": 0x0D,
    "Tab": 0x09,
    "Escape": 0x1B,
    "Backspace": 0x08, "BackSpace": 0x08,
    "Delete": 0x2E,
    "Space": 0x20, "space": 0x20,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "Home": 0x24, "End": 0x23,
    "Page_Up": 0x21, "Prior": 0x21,
    "Page_Down": 0x22, "Next": 0x22,
    "Insert": 0x2D,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "super": 0x5B, "win": 0x5B,
}

# ─── ctypes structures ──────────────────────────────────────


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("_input", _INPUT_UNION),
    ]


# ─── Environment implementation ─────────────────────────────


class WindowsEnvironment(EnvironmentAbstraction):
    """Windows desktop environment using ctypes (user32/gdi32) and UIAutomation.

    Screenshot: ctypes GetDC/BitBlt with PIL.ImageGrab fallback.
    Input: ctypes SendInput (keyboard + mouse).
    Accessibility: comtypes IUIAutomation with graceful degradation.
    Clipboard: ctypes OpenClipboard / GetClipboardData.
    """

    # ── Screenshot ──────────────────────────────────────────

    async def take_screenshot(self, width: int = 1024, height: int = 768) -> Image.Image:
        img = await asyncio.get_event_loop().run_in_executor(None, self._capture_screen)
        if img.size != (width, height):
            img = img.resize((width, height), Image.LANCZOS)
        return img

    def _capture_screen(self) -> Image.Image:
        """Capture screen via GDI BitBlt; fall back to PIL.ImageGrab."""
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            screen_w = user32.GetSystemMetrics(_SM_CXSCREEN)
            screen_h = user32.GetSystemMetrics(_SM_CYSCREEN)

            hdesktop = user32.GetDesktopWindow()
            hdc = user32.GetWindowDC(hdesktop)
            hdc_mem = gdi32.CreateCompatibleDC(hdc)
            hbmp = gdi32.CreateCompatibleBitmap(hdc, screen_w, screen_h)
            gdi32.SelectObject(hdc_mem, hbmp)
            gdi32.BitBlt(hdc_mem, 0, 0, screen_w, screen_h, hdc, 0, 0, 0x00CC0020)  # SRCCOPY

            bmp_info_header = (ctypes.c_byte * 40)(
                40, 0, 0, 0,       # biSize
                screen_w & 0xFF, (screen_w >> 8) & 0xFF, (screen_w >> 16) & 0xFF, (screen_w >> 24) & 0xFF,
                screen_h & 0xFF, (screen_h >> 8) & 0xFF, (screen_h >> 16) & 0xFF, (screen_h >> 24) & 0xFF,
                1, 0,              # biPlanes
                24, 0,             # biBitCount (24 bpp)
                0, 0, 0, 0,        # biCompression = BI_RGB
                0, 0, 0, 0,        # biSizeImage
                0, 0, 0, 0,        # biXPelsPerMeter
                0, 0, 0, 0,        # biYPelsPerMeter
                0, 0, 0, 0,        # biClrUsed
                0, 0, 0, 0,        # biClrImportant
            )
            stride = ((screen_w * 3 + 3) & ~3)
            buf = (ctypes.c_byte * (stride * screen_h))()
            gdi32.GetDIBits(hdc_mem, hbmp, 0, screen_h, buf, bmp_info_header, 0)

            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hdesktop, hdc)

            img = Image.frombuffer(
                "RGB", (screen_w, screen_h),
                bytes(buf), "raw", "BGR", stride, -1
            )
            return img
        except Exception:
            # Fallback: PIL.ImageGrab (requires pillow with Windows support)
            from PIL import ImageGrab
            return ImageGrab.grab()

    # ── Accessibility tree ──────────────────────────────────

    async def get_a11y_tree(self) -> AccessibilityTree:
        try:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=comtypes.gen.UIAutomationClient.IUIAutomation,
            )
            focused = uia.GetFocusedElement()
            root_node = self._traverse_uia(uia, focused, depth=0)
            window_info = await self.get_active_window_info()
            return AccessibilityTree(
                root=root_node, app_name=window_info.get("app_name", "")
            )
        except Exception:
            # comtypes not available or UIAutomation error — return empty tree
            return AccessibilityTree(root=None, app_name="")

    def _traverse_uia(self, uia: Any, element: Any, depth: int, max_depth: int = 15) -> AccessibilityNode:
        """Recursively traverse a UIAutomation element into AccessibilityNode."""
        if depth > max_depth:
            return AccessibilityNode(depth=depth)
        try:
            role = str(element.CurrentControlType)
            name = element.CurrentName or ""
            rect = element.CurrentBoundingRectangle
            bbox = (rect.left, rect.top, rect.right, rect.bottom)

            states: list[str] = []
            try:
                if element.CurrentIsEnabled:
                    states.append("enabled")
                if element.CurrentIsKeyboardFocusable:
                    states.append("focusable")
            except Exception:
                pass

            children: list[AccessibilityNode] = []
            try:
                condition = uia.CreateTrueCondition()
                child_array = element.FindAll(
                    2,  # TreeScope_Children
                    condition,
                )
                for i in range(child_array.Length):
                    child = child_array.GetElement(i)
                    children.append(self._traverse_uia(uia, child, depth + 1, max_depth))
            except Exception:
                pass

            return AccessibilityNode(
                id=f"{role}_{name}_{depth}",
                role=role,
                name=name,
                bbox=bbox,
                states=states,
                children=children,
                depth=depth,
            )
        except Exception:
            return AccessibilityNode(depth=depth)

    # ── Keyboard input ──────────────────────────────────────

    async def send_keys(self, text: str) -> None:
        """Type text character by character using SendInput with KEYEVENTF_UNICODE."""
        await asyncio.get_event_loop().run_in_executor(None, self._send_unicode_text, text)

    def _send_unicode_text(self, text: str) -> None:
        inputs: list[_INPUT] = []
        for ch in text:
            scan = ord(ch)
            # Key down
            ki_down = _KEYBDINPUT(
                wVk=0,
                wScan=scan,
                dwFlags=_KEYEVENTF_UNICODE,
                time=0,
                dwExtraInfo=None,
            )
            inp_down = _INPUT(type=_INPUT_KEYBOARD, _input=_INPUT_UNION(ki=ki_down))
            inputs.append(inp_down)
            # Key up
            ki_up = _KEYBDINPUT(
                wVk=0,
                wScan=scan,
                dwFlags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=None,
            )
            inp_up = _INPUT(type=_INPUT_KEYBOARD, _input=_INPUT_UNION(ki=ki_up))
            inputs.append(inp_up)

        self._send_input_batch(inputs)

    async def send_key(self, key: str) -> None:
        """Send a single key or modifier combo like 'ctrl+s'."""
        await asyncio.get_event_loop().run_in_executor(None, self._send_key_sync, key)

    def _send_key_sync(self, key: str) -> None:
        if "+" in key:
            parts = [p.strip() for p in key.split("+")]
        else:
            parts = [key.strip()]

        vk_codes = [self._vk_for_key(p) for p in parts]

        # Press all keys in sequence
        inputs: list[_INPUT] = []
        for vk in vk_codes:
            ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
            inputs.append(_INPUT(type=_INPUT_KEYBOARD, _input=_INPUT_UNION(ki=ki)))
        # Release in reverse
        for vk in reversed(vk_codes):
            ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
            inputs.append(_INPUT(type=_INPUT_KEYBOARD, _input=_INPUT_UNION(ki=ki)))

        self._send_input_batch(inputs)

    # ── Mouse input ─────────────────────────────────────────

    async def click(
        self, x: int, y: int, button: str = "left", click_count: int = 1
    ) -> None:
        await asyncio.get_event_loop().run_in_executor(
            None, self._click_sync, x, y, button, click_count
        )

    def _click_sync(self, x: int, y: int, button: str, click_count: int) -> None:
        ctypes.windll.user32.SetCursorPos(x, y)
        down_flag, up_flag = _button_flags(button)
        for _ in range(click_count):
            ctypes.windll.user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.02)
            ctypes.windll.user32.mouse_event(up_flag, 0, 0, 0, 0)
            if click_count > 1:
                time.sleep(0.05)

    async def mouse_move(self, x: int, y: int) -> None:
        ctypes.windll.user32.SetCursorPos(x, y)

    async def mouse_down(self, x: int, y: int, button: str = "left") -> None:
        ctypes.windll.user32.SetCursorPos(x, y)
        down_flag, _ = _button_flags(button)
        ctypes.windll.user32.mouse_event(down_flag, 0, 0, 0, 0)

    async def mouse_up(self, x: int, y: int, button: str = "left") -> None:
        ctypes.windll.user32.SetCursorPos(x, y)
        _, up_flag = _button_flags(button)
        ctypes.windll.user32.mouse_event(up_flag, 0, 0, 0, 0)

    async def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> None:
        ctypes.windll.user32.SetCursorPos(x, y)
        if delta_y != 0:
            # WHEEL_DELTA = 120 per notch; positive = scroll up
            wheel_amount = delta_y * 120
            ctypes.windll.user32.mouse_event(
                _MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_int(wheel_amount).value, 0
            )
        # Horizontal scroll (MOUSEEVENTF_HWHEEL = 0x1000) if needed
        if delta_x != 0:
            hwheel_amount = delta_x * 120
            ctypes.windll.user32.mouse_event(
                0x1000, 0, 0, ctypes.c_int(hwheel_amount).value, 0
            )

    # ── Clipboard ───────────────────────────────────────────

    async def get_clipboard(self) -> str:
        try:
            if not ctypes.windll.user32.OpenClipboard(None):
                return ""
            h_data = ctypes.windll.user32.GetClipboardData(_CF_UNICODETEXT)
            if not h_data:
                ctypes.windll.user32.CloseClipboard()
                return ""
            ptr = ctypes.windll.kernel32.GlobalLock(h_data)
            if not ptr:
                ctypes.windll.user32.CloseClipboard()
                return ""
            text = ctypes.wstring_at(ptr)
            ctypes.windll.kernel32.GlobalUnlock(h_data)
            ctypes.windll.user32.CloseClipboard()
            return text
        except Exception:
            return ""

    async def set_clipboard(self, text: str) -> None:
        try:
            encoded = (text + "\x00").encode("utf-16-le")
            h_mem = ctypes.windll.kernel32.GlobalAlloc(0x0042, len(encoded))  # GMEM_MOVEABLE
            if not h_mem:
                return
            ptr = ctypes.windll.kernel32.GlobalLock(h_mem)
            ctypes.memmove(ptr, encoded, len(encoded))
            ctypes.windll.kernel32.GlobalUnlock(h_mem)

            if not ctypes.windll.user32.OpenClipboard(None):
                ctypes.windll.kernel32.GlobalFree(h_mem)
                return
            ctypes.windll.user32.EmptyClipboard()
            ctypes.windll.user32.SetClipboardData(_CF_UNICODETEXT, h_mem)
            ctypes.windll.user32.CloseClipboard()
        except Exception:
            pass

    # ── Window info ─────────────────────────────────────────

    async def get_active_window_info(self) -> dict[str, str]:
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()

            # Window title
            length = user32.GetWindowTextLengthW(hwnd) + 1
            title_buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, title_buf, length)
            title = title_buf.value

            # Class name (serves as app_name proxy)
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            app_name = class_buf.value

            return {"app_name": app_name, "title": title}
        except Exception:
            return {"app_name": "", "title": ""}

    async def get_screen_size(self) -> tuple[int, int]:
        try:
            user32 = ctypes.windll.user32
            w = user32.GetSystemMetrics(_SM_CXSCREEN)
            h = user32.GetSystemMetrics(_SM_CYSCREEN)
            return w, h
        except Exception:
            return 1920, 1080

    # ─── Internal helpers ───────────────────────────────────

    def _translate_key(self, key: str) -> str:
        """Translate common key names to canonical CUE string tokens.

        Modifier combos like 'ctrl+s' are handled by splitting on '+' and
        translating each part, then rejoining with '+'.
        """
        if "+" in key:
            parts = key.split("+")
            translated = [_KEY_NAME_MAP.get(p.strip(), p.strip()) for p in parts]
            return "+".join(translated)
        return _KEY_NAME_MAP.get(key, key)

    def _vk_for_key(self, key: str) -> int:
        """Return the Windows virtual key code for a (already-translated or raw) key name."""
        if key in _VK_CODE_MAP:
            return _VK_CODE_MAP[key]
        if len(key) == 1:
            vk = ctypes.windll.user32.VkKeyScanW(ord(key)) & 0xFF
            return vk if vk != 0xFF else 0
        return 0

    def _send_input_batch(self, inputs: list[_INPUT]) -> None:
        """Send a batch of INPUT structures via SendInput."""
        if not inputs:
            return
        arr = (_INPUT * len(inputs))(*inputs)
        ctypes.windll.user32.SendInput(
            len(inputs), arr, ctypes.sizeof(_INPUT)
        )


# ─── Module-level helpers ───────────────────────────────────

def _button_flags(button: str) -> tuple[int, int]:
    """Return (down_flag, up_flag) for a mouse button name."""
    mapping = {
        "left": (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP),
        "right": (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP),
        "middle": (_MOUSEEVENTF_MIDDLEDOWN, _MOUSEEVENTF_MIDDLEUP),
    }
    return mapping.get(button, (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP))
