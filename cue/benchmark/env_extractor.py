"""Environment state extractor for benchmark success checking."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from typing import Any

from cue.types import BenchmarkTask

logger = logging.getLogger(__name__)


class EnvStateExtractor:
    """Extract environment state from the Linux desktop for benchmark evaluation."""

    def __init__(self, environment=None):
        """
        Args:
            environment: Optional platform.EnvironmentAbstraction instance.
                         If None, creates one via create_environment().
        """
        if environment is not None:
            self._env = environment
        else:
            from cue.platform import create_environment
            self._env = create_environment()

    async def extract(self, task: BenchmarkTask) -> dict[str, Any]:
        """Extract full env_state dict based on the task's success_criteria.type.

        Only extracts what's needed for the specific check type.
        """
        check_type = task.success_criteria.type
        state: dict[str, Any] = {}

        if check_type == "cell_value_check":
            state["cells"] = await self._extract_cells(task)

        elif check_type == "url_check":
            state["active_url"] = await self._extract_active_url()

        elif check_type == "file_content_check":
            state["file_contents"] = await self._extract_file_contents(task)

        elif check_type == "tab_count":
            state["tab_count"] = await self._extract_tab_count()

        elif check_type == "clipboard_check":
            state["clipboard"] = await self._extract_clipboard()

        elif check_type == "screenshot_diff":
            state["screenshot_hash"] = await self._extract_screenshot_hash()
            # initial_screenshot_hash must have been set earlier via extract_initial_screenshot_hash()

        elif check_type == "app_state_check":
            state["app_state"] = await self._extract_app_state(task)

        else:
            logger.warning("Unknown success_criteria.type %r — returning empty state", check_type)

        return state

    async def extract_initial_screenshot_hash(self) -> str:
        """Capture and hash the initial screenshot before task execution."""
        return await self._extract_screenshot_hash()

    # ------------------------------------------------------------------
    # Private extraction methods
    # ------------------------------------------------------------------

    async def _extract_clipboard(self) -> str:
        """Use xsel or xclip to get clipboard contents."""
        # Try xsel first (same tool used by LinuxEnvironment)
        try:
            proc = await asyncio.create_subprocess_exec(
                "xsel", "--clipboard", "--output",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            pass

        # Fallback: xclip
        try:
            proc = await asyncio.create_subprocess_exec(
                "xclip", "-selection", "clipboard", "-o",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            pass

        logger.warning("Neither xsel nor xclip available; clipboard returned empty")
        return ""

    async def _extract_active_url(self) -> str:
        """Use xdotool + window title parsing to extract browser URL.

        Browser titles typically show 'Page Title - Browser Name'.
        For more accurate URL, focuses the address bar via Ctrl+L, then reads clipboard.
        """
        # Step 1: focus address bar and copy URL to clipboard
        try:
            # Save current clipboard so we can restore it later if needed
            original_clipboard = await self._extract_clipboard()

            # Press Ctrl+L to focus address bar (works in Chrome, Firefox)
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            # Short wait for address bar to populate
            await asyncio.sleep(0.3)

            # Select all and copy
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+c",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            await asyncio.sleep(0.2)
            url = await self._extract_clipboard()
            url = url.strip()

            # Press Escape to dismiss, restore focus
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "Escape",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            if url.startswith(("http://", "https://", "ftp://", "file://")):
                return url

        except Exception as exc:
            logger.debug("Ctrl+L URL extraction failed: %s", exc)

        # Fallback: parse window title
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "getactivewindow", "getwindowname",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            title = stdout.decode("utf-8", errors="replace").strip()
            # Title format: "Page Title - Google Chrome" or "Page Title — Mozilla Firefox"
            for sep in (" - Google Chrome", " — Mozilla Firefox", " - Mozilla Firefox",
                        " - Chromium", " - Firefox"):
                if sep in title:
                    # Title may contain the URL if browser is showing the URL in title
                    page_title = title[: title.rfind(sep)]
                    if page_title.startswith(("http://", "https://")):
                        return page_title
                    break
            return title  # Return raw title as best effort
        except Exception as exc:
            logger.warning("Window title URL extraction failed: %s", exc)

        return ""

    async def _extract_tab_count(self) -> int:
        """Use wmctrl or xdotool to count browser windows/tabs."""
        # Attempt 1: wmctrl — count windows belonging to browser processes
        try:
            proc = await asyncio.create_subprocess_exec(
                "wmctrl", "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                lines = stdout.decode("utf-8", errors="replace").splitlines()
                browser_keywords = ("chrome", "chromium", "firefox", "mozilla")
                count = sum(
                    1 for line in lines
                    if any(kw in line.lower() for kw in browser_keywords)
                )
                if count > 0:
                    return count
        except FileNotFoundError:
            pass

        # Attempt 2: xdotool search for browser windows
        try:
            for class_name in ("google-chrome", "chromium", "firefox"):
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "search", "--class", class_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    ids = [l for l in stdout.decode("utf-8").splitlines() if l.strip()]
                    if ids:
                        return len(ids)
        except Exception as exc:
            logger.debug("xdotool tab count failed: %s", exc)

        return 0

    async def _extract_screenshot_hash(self) -> str:
        """Take screenshot and return MD5 hash."""
        try:
            img = await self._env.take_screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            digest = hashlib.md5(buf.getvalue()).hexdigest()
            return digest
        except Exception as exc:
            logger.warning("Screenshot hash extraction failed: %s", exc)
            return ""

    async def _extract_app_state(self, task: BenchmarkTask) -> dict[str, Any]:
        """Extract app-specific state based on task.app.

        Returns dict with keys like 'terminal_open', 'has_open_canvas',
        'current_path_is_home', 'last_output', etc.
        """
        app_state: dict[str, Any] = {}
        app = (task.app or "").lower()

        # Detect open terminal
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--class", "xterm",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            terminal_ids = [l for l in stdout.decode().splitlines() if l.strip()]
            app_state["terminal_open"] = len(terminal_ids) > 0
        except Exception:
            app_state["terminal_open"] = False

        if "writer" in app or "libreoffice" in app:
            # Check if LibreOffice Writer canvas is visible
            try:
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "search", "--class", "soffice",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                ids = [l for l in stdout.decode().splitlines() if l.strip()]
                app_state["has_open_canvas"] = len(ids) > 0
            except Exception:
                app_state["has_open_canvas"] = False

        elif "terminal" in app or "bash" in app or "shell" in app:
            # For terminal tasks: capture last command output via clipboard
            try:
                # Select all visible terminal content
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "key", "--clearmodifiers", "ctrl+shift+a",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                await asyncio.sleep(0.2)
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "key", "--clearmodifiers", "ctrl+shift+c",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                await asyncio.sleep(0.2)
                last_output = await self._extract_clipboard()
                app_state["last_output"] = last_output.strip()
            except Exception:
                app_state["last_output"] = ""

            # Check if current directory is home
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c", "echo $HOME && pwd",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                lines = stdout.decode().strip().splitlines()
                if len(lines) >= 2:
                    home, cwd = lines[0].strip(), lines[1].strip()
                    app_state["current_path_is_home"] = cwd == home
            except Exception:
                app_state["current_path_is_home"] = False

        return app_state

    async def _extract_cells(self, task: BenchmarkTask) -> dict[str, str]:
        """For LibreOffice Calc tasks, read cell values via keyboard + clipboard.

        Navigates to each required cell reference from success_criteria.checks,
        selects it, and copies the value to clipboard.
        """
        cells: dict[str, str] = {}

        # Collect all cell refs needed by the checks
        cell_refs: list[str] = []
        for check in task.success_criteria.checks:
            cell = check.get("cell", "")
            ref = check.get("reference_cell", "")
            if cell:
                cell_refs.append(cell)
            if ref:
                cell_refs.append(ref)

        if not cell_refs:
            return cells

        for cell_ref in cell_refs:
            value = await self._read_calc_cell(cell_ref)
            cells[cell_ref] = value

        return cells

    async def _read_calc_cell(self, cell_ref: str) -> str:
        """Navigate to cell_ref in LibreOffice Calc and return its value via clipboard."""
        try:
            # Use the Name Box (Ctrl+Home then navigate, or directly type in Name Box)
            # Ctrl+G opens Go To dialog in some versions; Ctrl+F5 opens Name Box focus
            # Most reliable: Ctrl+Home, then use Name Box via F5 or clicking name box
            # Simplest reliable approach: press F5 to open Go To dialog
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+Home",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.sleep(0.1)

            # Type cell reference in Name Box using keyboard shortcut
            # Ctrl+G or just clicking the Name Box — use the Name Box shortcut
            # In LibreOffice: the Name Box at top-left can be focused by pressing Ctrl+F5
            # or by the key shortcut that sends focus there
            # Most portable: use the Navigator (F5) -> no, that's different
            # Use: press Escape first, then Ctrl+Home, then navigate by typing in Name Box
            # Actually the most reliable is to use xdotool to type in the Name Box area
            # by pressing Ctrl+F5 which focuses the Name Box in LO Calc
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+F5",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.sleep(0.1)

            # Clear name box and type cell ref
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            proc = await asyncio.create_subprocess_exec(
                "xdotool", "type", "--clearmodifiers", cell_ref,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "Return",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.sleep(0.2)

            # Copy cell value to clipboard
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+c",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.sleep(0.2)

            value = await self._extract_clipboard()
            return value.strip()

        except Exception as exc:
            logger.warning("Failed to read Calc cell %r: %s", cell_ref, exc)
            return ""

    async def _extract_file_contents(self, task: BenchmarkTask) -> dict[str, str]:
        """Read document contents for file_content_check tasks.

        For each file path in success_criteria.checks:
        - If 'current_document': uses Select All + Copy in LibreOffice Writer.
        - Otherwise: reads the file directly from the filesystem.
        """
        file_contents: dict[str, str] = {}

        file_paths: list[str] = []
        for check in task.success_criteria.checks:
            fp = check.get("file", "")
            if fp:
                file_paths.append(fp)

        for fp in file_paths:
            if fp == "current_document":
                content = await self._read_current_document()
            else:
                content = await self._read_file_from_disk(fp)
            file_contents[fp] = content

        return file_contents

    async def _read_current_document(self) -> str:
        """Select all + copy in the active window to get current document text."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.sleep(0.2)

            proc = await asyncio.create_subprocess_exec(
                "xdotool", "key", "--clearmodifiers", "ctrl+c",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await asyncio.sleep(0.3)

            content = await self._extract_clipboard()
            return content
        except Exception as exc:
            logger.warning("Failed to read current document via clipboard: %s", exc)
            return ""

    async def _read_file_from_disk(self, file_path: str) -> str:
        """Read a file from the filesystem and return its text content."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "cat", file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode("utf-8", errors="replace")
            logger.warning("cat %r returned %d: %s", file_path, proc.returncode,
                           stderr.decode("utf-8", errors="replace").strip())
        except Exception as exc:
            logger.warning("Failed to read file %r: %s", file_path, exc)
        return ""
