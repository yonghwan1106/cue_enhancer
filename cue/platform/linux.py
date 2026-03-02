"""Linux environment implementation using Xlib, xdotool, and AT-SPI2."""

from __future__ import annotations

import asyncio
import subprocess
from io import BytesIO

import numpy as np
from PIL import Image

from cue.platform.base import EnvironmentAbstraction
from cue.types import AccessibilityNode, AccessibilityTree


class LinuxEnvironment(EnvironmentAbstraction):
    """Linux desktop environment using X11 tools.

    Dependencies:
    - xdotool: keyboard/mouse automation
    - scrot or import (ImageMagick): screenshot capture
    - xsel: clipboard access
    - AT-SPI2 (gi.repository.Atspi): accessibility tree
    """

    async def take_screenshot(self, width: int = 1024, height: int = 768) -> Image.Image:
        import os
        import tempfile

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="cue_screenshot_")
        os.close(fd)

        try:
            proc = await asyncio.create_subprocess_exec(
                "scrot", "-o", tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

            if proc.returncode != 0:
                # Fallback to import (ImageMagick)
                proc = await asyncio.create_subprocess_exec(
                    "import", "-window", "root", tmp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()

            img = Image.open(tmp_path)
            img.load()  # Force read into memory before deleting temp file
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if img.size != (width, height):
            img = img.resize((width, height), Image.LANCZOS)
        return img

    async def get_a11y_tree(self) -> AccessibilityTree:
        try:
            import gi

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi

            desktop = Atspi.get_desktop(0)
            active_window = self._find_active_window(desktop)

            root_node = AccessibilityNode(id="root", role="desktop")
            if active_window:
                root_node = self._traverse_atspi(active_window, depth=0)

            window_info = await self.get_active_window_info()
            return AccessibilityTree(
                root=root_node, app_name=window_info.get("app_name", "")
            )
        except (ImportError, Exception):
            return AccessibilityTree(root=None, app_name="")

    async def send_keys(self, text: str) -> None:
        await self._run_xdotool("type", "--clearmodifiers", "--delay", "12", text)

    async def send_key(self, key: str) -> None:
        xdotool_key = self._translate_key(key)
        await self._run_xdotool("key", "--clearmodifiers", xdotool_key)

    async def click(
        self, x: int, y: int, button: str = "left", click_count: int = 1
    ) -> None:
        button_num = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
        await self._run_xdotool(
            "mousemove", str(x), str(y),
            "click", "--repeat", str(click_count), button_num,
        )

    async def mouse_move(self, x: int, y: int) -> None:
        await self._run_xdotool("mousemove", str(x), str(y))

    async def mouse_down(self, x: int, y: int, button: str = "left") -> None:
        button_num = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
        await self._run_xdotool(
            "mousemove", str(x), str(y),
            "mousedown", button_num,
        )

    async def mouse_up(self, x: int, y: int, button: str = "left") -> None:
        button_num = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
        await self._run_xdotool(
            "mousemove", str(x), str(y),
            "mouseup", button_num,
        )

    async def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> None:
        await self._run_xdotool("mousemove", str(x), str(y))
        if delta_y > 0:
            for _ in range(abs(delta_y) // 3 or 1):
                await self._run_xdotool("click", "4")  # scroll up
        elif delta_y < 0:
            for _ in range(abs(delta_y) // 3 or 1):
                await self._run_xdotool("click", "5")  # scroll down

    async def get_clipboard(self) -> str:
        proc = await asyncio.create_subprocess_exec(
            "xsel", "--clipboard", "--output",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")

    async def set_clipboard(self, text: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "xsel", "--clipboard", "--input",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=text.encode("utf-8"))

    async def get_active_window_info(self) -> dict[str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "getactivewindow", "getwindowname",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            title = stdout.decode("utf-8", errors="replace").strip()

            proc2 = await asyncio.create_subprocess_exec(
                "xdotool", "getactivewindow", "getwindowclassname",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate()
            app_name = stdout2.decode("utf-8", errors="replace").strip()

            return {"app_name": app_name, "title": title}
        except Exception:
            return {"app_name": "", "title": ""}

    async def get_screen_size(self) -> tuple[int, int]:
        proc = await asyncio.create_subprocess_exec(
            "xdpyinfo",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")
        for line in output.splitlines():
            if "dimensions:" in line:
                # e.g., "  dimensions:    1920x1080 pixels ..."
                parts = line.split()
                idx = parts.index("dimensions:") + 1 if "dimensions:" in parts else -1
                if idx > 0 and idx < len(parts):
                    dims = parts[idx].split("x")
                    return int(dims[0]), int(dims[1])
        return 1920, 1080

    # ─── Internal helpers ──────────────────────────────────

    async def _run_xdotool(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"xdotool failed: {stderr.decode()}")
        return stdout.decode("utf-8", errors="replace")

    def _translate_key(self, key: str) -> str:
        """Translate common key names to xdotool format."""
        translations = {
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
        }
        # Handle modifier combos like "ctrl+s" -> "ctrl+s"
        if "+" in key:
            parts = key.split("+")
            translated = [translations.get(p.strip(), p.strip()) for p in parts]
            return "+".join(translated)
        return translations.get(key, key)

    def _find_active_window(self, desktop):
        """Find the active/focused window in the AT-SPI desktop."""
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app:
                for j in range(app.get_child_count()):
                    win = app.get_child_at_index(j)
                    if win:
                        try:
                            states = win.get_state_set()
                            if states.contains(
                                __import__("gi.repository.Atspi", fromlist=["Atspi"]).StateType.ACTIVE
                            ):
                                return win
                        except Exception:
                            pass
        return None

    def _traverse_atspi(
        self, node, depth: int = 0, max_depth: int = 15
    ) -> AccessibilityNode:
        """Recursively traverse an AT-SPI node into our AccessibilityNode."""
        if depth > max_depth:
            return AccessibilityNode(depth=depth)
        try:
            from gi.repository import Atspi

            role = node.get_role_name() or ""
            name = node.get_name() or ""
            bbox = (0, 0, 0, 0)

            try:
                component = node.query_component()
                if component:
                    ext = component.get_extents(Atspi.CoordType.SCREEN)
                    bbox = (ext.x, ext.y, ext.x + ext.width, ext.y + ext.height)
            except Exception:
                pass

            states: list[str] = []
            try:
                state_set = node.get_state_set()
                for st in Atspi.StateType.__enum_values__.values():
                    if state_set.contains(st):
                        states.append(st.value_nick)
            except Exception:
                pass

            children: list[AccessibilityNode] = []
            for i in range(node.get_child_count()):
                child = node.get_child_at_index(i)
                if child:
                    children.append(self._traverse_atspi(child, depth + 1, max_depth))

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
