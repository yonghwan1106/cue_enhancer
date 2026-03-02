"""Live CUE Agent test on Xvfb with xterm."""
import asyncio
import os
import sys
import time

# Ensure DISPLAY is set
os.environ["DISPLAY"] = ":99"

sys.path.insert(0, "/opt/cue_enhancer")

from dotenv import load_dotenv
load_dotenv("/opt/cue_enhancer/.env")

TIME_FMT = "%Y-%m-%d %H:%M:%S"


async def test_screenshot_and_grounding():
    """Test 1: Take screenshot and run grounding on live Xvfb."""
    from cue.platform.linux import LinuxEnvironment

    env = LinuxEnvironment()
    print("=== Test 1: Screenshot + Platform ===")

    # Take screenshot
    img = await env.take_screenshot(1920, 1080)
    img.save("/tmp/cue_live_test.png")
    print(f"  Screenshot: {img.size} saved to /tmp/cue_live_test.png")

    # Get active window info
    info = await env.get_active_window_info()
    print(f"  Active window: {info}")

    # Get screen size
    size = await env.get_screen_size()
    print(f"  Screen size: {size}")

    # Try a11y tree
    try:
        tree = await env.get_a11y_tree()
        print(f"  A11y tree: root={tree.root is not None}, app={tree.app_name}")
    except Exception as e:
        print(f"  A11y tree: unavailable ({e})")

    print("  PASSED\n")
    return img


async def test_xdotool_actions():
    """Test 2: Execute keyboard/mouse actions via xdotool."""
    from cue.platform.linux import LinuxEnvironment

    env = LinuxEnvironment()
    print("=== Test 2: xdotool Actions ===")

    # Click on xterm window area
    await env.click(300, 300, button="left", click_count=1)
    await asyncio.sleep(0.5)
    print("  Clicked at (300, 300)")

    # Type some text
    await env.send_keys("echo 'Hello from CUE Agent!'")
    await asyncio.sleep(0.3)
    print("  Typed: echo 'Hello from CUE Agent!'")

    # Press Enter
    await env.send_key("Return")
    await asyncio.sleep(1)
    print("  Pressed Enter")

    # Take after screenshot
    img = await env.take_screenshot(1920, 1080)
    img.save("/tmp/cue_after_action.png")
    print("  After screenshot saved")

    # Verify clipboard round-trip
    await env.set_clipboard("CUE test clipboard")
    clip = await env.get_clipboard()
    assert clip.strip() == "CUE test clipboard", f"Clipboard mismatch: {clip!r}"
    print("  Clipboard round-trip: OK")

    print("  PASSED\n")


async def test_grounding_on_live():
    """Test 3: Run grounding enhancer on live screenshot."""
    from cue.platform.linux import LinuxEnvironment
    from cue.grounding.visual import OpenCVGrounder
    from cue.grounding.enhancer import GroundingEnhancer
    from cue.config import GroundingConfig

    env = LinuxEnvironment()
    img = await env.take_screenshot(1920, 1080)

    print("=== Test 3: Grounding on Live Screenshot ===")

    # OpenCV grounding
    visual = OpenCVGrounder()
    visual_elements = await visual.detect(img)
    print(f"  OpenCV detected: {len(visual_elements)} visual elements")

    # Full grounding enhancer
    config = GroundingConfig(level="basic")
    enhancer = GroundingEnhancer(config)
    result = await enhancer.enhance(img, "type a command in the terminal")
    print(f"  Grounding result: {len(result.elements)} merged elements")
    if result.element_description:
        desc_preview = result.element_description[:200]
        print(f"  Description preview: {desc_preview}...")

    print("  PASSED\n")


async def test_safety_gate():
    """Test 4: Safety gate with real actions."""
    from cue.safety.gate import SafetyGate
    from cue.types import Action

    print("=== Test 4: Safety Gate (Live) ===")
    gate = SafetyGate()
    gate.start_episode()

    safe_action = Action(type="left_click", coordinate=(100, 100))
    result = gate.check_with_permission(safe_action)
    print(f"  Click action: {result.level.value} -- {result.reason}")

    dangerous = Action(type="key", text="rm -rf /")
    result = gate.check_with_permission(dangerous)
    print(f"  Dangerous action: {result.level.value} -- {result.reason}")

    emergency = gate.check_emergency(safe_action)
    print(f"  Emergency check: {emergency.level.value}")

    print("  PASSED\n")


async def main():
    separator = "=" * 60
    print(separator)
    print("CUE Agent Live Integration Test")
    print("Time: " + time.strftime(TIME_FMT))
    print("DISPLAY: " + str(os.environ.get("DISPLAY")))
    api_status = "set" if os.environ.get("ANTHROPIC_API_KEY") else "MISSING"
    print("API Key: " + api_status)
    print(separator + "\n")

    t0 = time.monotonic()

    await test_screenshot_and_grounding()
    await test_xdotool_actions()
    await test_grounding_on_live()
    await test_safety_gate()

    elapsed = time.monotonic() - t0
    print(separator)
    print(f"All tests PASSED in {elapsed:.1f}s")
    print(separator)


if __name__ == "__main__":
    asyncio.run(main())
