"""Live CUE Agent test with real Claude API on Xvfb."""
import asyncio
import logging
import os
import sys
import time

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/opt/cue_enhancer")

from dotenv import load_dotenv
load_dotenv("/opt/cue_enhancer/.env")

# Enable detailed logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

TIME_FMT = "%H:%M:%S"


async def main():
    from cue.config import CUEConfig, AgentConfig
    from cue.agent import CUEAgent

    print("=" * 60)
    print("CUE Agent LIVE Test (Claude API)")
    print("Time: " + time.strftime(TIME_FMT))
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("API Key: " + api_key[:8] + "..." if api_key else "API Key: MISSING")
    print("=" * 60)

    # Configure for minimal test: 5 steps max, 60s timeout
    config = CUEConfig.load()
    config.agent.max_steps = 10
    config.agent.timeout_seconds = 60
    config.agent.screenshot_width = 1920
    config.agent.screenshot_height = 1080
    config.agent.model = "claude-sonnet-4-6"

    agent = CUEAgent(config)

    print("\nStarting agent with task: 'Type ls in the terminal and press Enter'")
    print("-" * 60)

    t0 = time.monotonic()
    try:
        result = await agent.run("Type 'ls' in the terminal window and press Enter")
        elapsed = time.monotonic() - t0
        print("-" * 60)
        print("Result:")
        print("  success: " + str(result.success))
        print("  steps: " + str(result.steps_taken))
        print("  time: " + str(round(elapsed, 1)) + "s")
        if result.error:
            print("  error: " + str(result.error))
        print("=" * 60)
    except Exception as e:
        elapsed = time.monotonic() - t0
        print("-" * 60)
        print("EXCEPTION after " + str(round(elapsed, 1)) + "s:")
        import traceback
        traceback.print_exc()
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
