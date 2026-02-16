#!/usr/bin/env python3
"""
ScreenPilot + Playwright Demo with Video Recording
====================================================
Uses Playwright's built-in video recording to capture a browser automation demo.
This creates an MP4 video showing ScreenPilot navigating GitHub.
"""

import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT_DIR = Path("recordings")
OUTPUT_DIR.mkdir(exist_ok=True)


async def main():
    print("=" * 60)
    print("ScreenPilot + Playwright Demo (with video recording)")
    print("=" * 60)
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )

        # Create context with video recording
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(OUTPUT_DIR),
            record_video_size={"width": 1280, "height": 720},
        )

        page = await context.new_page()

        start = time.time()

        # --- Step 1: Navigate to GitHub repo ---
        print("Step 1: Navigating to GitHub repo...")
        await page.goto("https://github.com/pphouse/screenpilot")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUTPUT_DIR / "01_repo.png"))
        print("  -> Repository page loaded")

        # --- Step 2: Check the repo description ---
        print("Step 2: Reading repo description...")
        desc = await page.locator(".f4.my-3").text_content()
        print(f"  -> Description: {desc.strip()[:80]}...")
        await asyncio.sleep(1)

        # --- Step 3: Click on Issues tab ---
        print("Step 3: Clicking Issues tab...")
        await page.goto("https://github.com/pphouse/screenpilot/issues")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUTPUT_DIR / "02_issues.png"))
        print("  -> Issues page loaded")
        await asyncio.sleep(1)

        # --- Step 4: Click on the demo issue ---
        print("Step 4: Clicking on demo issue...")
        await page.click("[data-hovercard-type='issue'], a:has-text('self-marketing')")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUTPUT_DIR / "03_issue_detail.png"))
        print("  -> Issue detail loaded")
        await asyncio.sleep(1)

        # --- Step 5: Go back and check Discussions ---
        print("Step 5: Navigating to Discussions...")
        await page.goto("https://github.com/pphouse/screenpilot/discussions")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUTPUT_DIR / "04_discussions.png"))
        print("  -> Discussions page loaded")
        await asyncio.sleep(1)

        # --- Step 6: Navigate to landing page ---
        print("Step 6: Navigating to landing page...")
        await page.goto("https://pphouse.github.io/screenpilot/")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUTPUT_DIR / "05_landing.png"))
        print("  -> Landing page loaded")
        await asyncio.sleep(2)

        # --- Step 7: Scroll through landing page ---
        print("Step 7: Scrolling through landing page...")
        for i, scroll_y in enumerate([500, 1000, 1500, 2500, 3500]):
            await page.evaluate(f"window.scrollTo(0, {scroll_y})")
            await asyncio.sleep(0.8)
            await page.screenshot(path=str(OUTPUT_DIR / f"06_landing_scroll_{i}.png"))
        print("  -> Landing page scrolled through")

        # --- Step 8: Navigate to releases ---
        print("Step 8: Checking releases...")
        await page.goto("https://github.com/pphouse/screenpilot/releases")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)
        await page.screenshot(path=str(OUTPUT_DIR / "07_releases.png"))
        print("  -> Releases page loaded")
        await asyncio.sleep(1)

        # --- Step 9: Scroll release notes ---
        print("Step 9: Scrolling release notes...")
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(1)
        await page.screenshot(path=str(OUTPUT_DIR / "08_release_detail.png"))
        print("  -> Release notes scrolled")

        elapsed = time.time() - start

        # Close and save video
        await context.close()
        await browser.close()

    # Find the recorded video
    videos = list(OUTPUT_DIR.glob("*.webm"))
    if videos:
        video_path = videos[0]
        print(f"\n{'=' * 60}")
        print(f"Completed in {elapsed:.1f}s")
        print(f"Video saved: {video_path}")
        print(f"Screenshots: {OUTPUT_DIR}/*.png")
        print(f"{'=' * 60}")

        # Convert to MP4 with ffmpeg if available
        import shutil
        if shutil.which("ffmpeg"):
            mp4_path = OUTPUT_DIR / "screenpilot_demo.mp4"
            import subprocess
            subprocess.run([
                "ffmpeg", "-y", "-i", str(video_path),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                str(mp4_path)
            ], capture_output=True)
            if mp4_path.exists():
                print(f"MP4 converted: {mp4_path} ({mp4_path.stat().st_size / 1024:.0f} KB)")
    else:
        print(f"\nCompleted in {elapsed:.1f}s (no video found)")
        print(f"Screenshots saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
