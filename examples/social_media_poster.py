#!/usr/bin/env python3
"""
ScreenPilot Social Media Poster
================================
Uses ScreenPilot's browser automation to post marketing content
to various social media platforms.

Prerequisites:
    - Display (Xvfb or real)
    - Google Chrome with logged-in sessions for target platforms
    - OR: API keys for programmatic posting

Usage:
    # Post to Hacker News (requires logged-in Chrome session)
    python examples/social_media_poster.py --platform hn

    # Post to Reddit
    python examples/social_media_poster.py --platform reddit

    # Post to Twitter/X
    python examples/social_media_poster.py --platform twitter

    # All platforms (dry run)
    python examples/social_media_poster.py --all --dry-run

    # API-based posting (no browser needed)
    python examples/social_media_poster.py --platform twitter --api
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass

if not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":99"


@dataclass
class Post:
    """A social media post."""
    title: str
    url: str
    body: str
    tags: list[str]


# Marketing content
POSTS = {
    "hn": Post(
        title="Show HN: ScreenPilot – AI desktop automation using vision + LLM (replaces brittle RPA)",
        url="https://github.com/pphouse/screenpilot",
        body="",  # HN Show posts are link-only
        tags=[],
    ),
    "reddit_python": Post(
        title="ScreenPilot: Open-source AI desktop automation using vision + LLM – replaces brittle RPA selectors",
        url="https://github.com/pphouse/screenpilot",
        body=(
            "Built an open-source tool that uses screenshot analysis + LLM to automate "
            "any desktop application. No CSS selectors, no XPath — just describe what you "
            "want in natural language.\n\n"
            "Key features:\n"
            "- Vision-based UI understanding (Claude, GPT-4, or any LiteLLM model)\n"
            "- Set-of-Mark prompting for precise element grounding\n"
            "- Self-healing error recovery with escalating strategies\n"
            "- Task scheduling, execution reports, Python SDK\n"
            "- Workflow recording and replay with adaptation\n\n"
            "pip install screenpilot\n\n"
            "Would love feedback from the community!"
        ),
        tags=["python", "automation", "ai", "rpa"],
    ),
    "reddit_ml": Post(
        title="ScreenPilot: Using vision LLMs for self-healing desktop automation (Set-of-Mark prompting + hierarchical planning)",
        url="https://github.com/pphouse/screenpilot",
        body=(
            "We built an open-source desktop automation agent that uses LLM vision APIs "
            "to understand screens and execute tasks described in natural language.\n\n"
            "Technical approach:\n"
            "- Set-of-Mark (SoM) prompting: overlays numbered markers on screenshots for element grounding\n"
            "- Hierarchical planning: high-level strategy decomposition + step execution\n"
            "- Task Memory Tree: structured memory for coherent long-horizon execution\n"
            "- Self-healing error recovery: retry → relocate → scroll → dismiss → LLM recovery\n\n"
            "Works with Claude, GPT-4o, or any LiteLLM-compatible model.\n\n"
            "GitHub: https://github.com/pphouse/screenpilot"
        ),
        tags=["computer-vision", "llm", "agents", "automation"],
    ),
    "twitter_en": Post(
        title="",
        url="https://github.com/pphouse/screenpilot",
        body=(
            "Introducing ScreenPilot — AI desktop automation using vision + LLM\n\n"
            "No CSS selectors. No XPath. Just describe what you want:\n\n"
            '$ screenpilot run "Open Chrome and search for Python tutorials"\n\n'
            "- Vision-based (Claude, GPT-4)\n"
            "- Self-healing\n"
            "- Open source\n\n"
            "pip install screenpilot\n"
            "https://github.com/pphouse/screenpilot"
        ),
        tags=["AI", "RPA", "Python", "OpenSource", "Automation"],
    ),
    "twitter_jp": Post(
        title="",
        url="https://github.com/pphouse/screenpilot",
        body=(
            "ScreenPilot をリリースしました\n\n"
            "AIビジョン+LLMでデスクトップ操作を自動化するOSSツールです。\n\n"
            "従来のRPA: CSSセレクタが壊れる → 修正の繰り返し\n"
            "ScreenPilot: 画面を見て理解 → 自然言語で指示するだけ\n\n"
            "pip install screenpilot\n"
            "https://github.com/pphouse/screenpilot"
        ),
        tags=["AI", "RPA", "Python", "自動化"],
    ),
    "linkedin": Post(
        title="Introducing ScreenPilot: AI-Powered Desktop Automation",
        url="https://github.com/pphouse/screenpilot",
        body=(
            "Excited to announce ScreenPilot — an open-source alternative to traditional RPA "
            "that uses AI vision to automate any desktop application.\n\n"
            "The Problem:\n"
            "Traditional RPA tools rely on CSS selectors and XPath that break every time the "
            "UI updates. Enterprises spend $50K+/year on licenses, plus developer time for "
            "constant maintenance.\n\n"
            "Our Approach:\n"
            "ScreenPilot uses screenshot analysis + LLM to understand any screen like a human. "
            "Describe tasks in plain English — no coding required. When the UI changes, "
            "ScreenPilot adapts automatically.\n\n"
            "Features:\n"
            "• Multi-LLM support (Claude, GPT-4, any LiteLLM model)\n"
            "• Task scheduling & execution reports\n"
            "• Python SDK & REST API\n"
            "• Self-healing error recovery\n"
            "• Apache 2.0 — free forever\n\n"
            "Try it: pip install screenpilot\n"
            "GitHub: https://github.com/pphouse/screenpilot\n\n"
            "#AI #RPA #Automation #OpenSource #Python"
        ),
        tags=["AI", "RPA", "Automation", "OpenSource", "Python"],
    ),
}


def post_to_hn(post: Post, dry_run: bool = False):
    """Post to Hacker News using browser automation."""
    import pyautogui
    import mss
    from mss.tools import to_png

    pyautogui.FAILSAFE = False

    print(f"  Title: {post.title}")
    print(f"  URL: {post.url}")

    if dry_run:
        print("  [DRY RUN] Would navigate to news.ycombinator.com/submit")
        return

    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)
    pyautogui.typewrite("https://news.ycombinator.com/submit", interval=0.02)
    pyautogui.press("enter")
    time.sleep(5)

    # Fill title field
    pyautogui.click(140, 184)  # Title input (approximate)
    time.sleep(0.3)
    pyautogui.typewrite(post.title, interval=0.01)

    # Fill URL field
    pyautogui.click(140, 210)  # URL input
    time.sleep(0.3)
    pyautogui.typewrite(post.url, interval=0.01)

    # Screenshot before submitting
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])
        to_png(shot.rgb, shot.size, output="/tmp/hn_pre_submit.png")

    print("  [READY] Form filled. Review screenshot at /tmp/hn_pre_submit.png")
    print("  [NOTE] Submit manually or pass --submit flag")


def post_to_reddit(post: Post, subreddit: str, dry_run: bool = False):
    """Post to Reddit using browser automation."""
    import pyautogui

    pyautogui.FAILSAFE = False

    print(f"  Subreddit: r/{subreddit}")
    print(f"  Title: {post.title}")

    if dry_run:
        print(f"  [DRY RUN] Would navigate to reddit.com/r/{subreddit}/submit")
        return

    url = f"https://www.reddit.com/r/{subreddit}/submit"
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)
    pyautogui.typewrite(url, interval=0.02)
    pyautogui.press("enter")
    time.sleep(5)
    print("  [READY] Navigate to Reddit submit page")


def post_to_twitter(post: Post, dry_run: bool = False):
    """Post to Twitter/X using browser automation."""
    import pyautogui

    pyautogui.FAILSAFE = False

    print(f"  Content: {post.body[:80]}...")

    if dry_run:
        print("  [DRY RUN] Would navigate to twitter.com/compose/tweet")
        return

    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)
    pyautogui.typewrite("https://twitter.com/compose/tweet", interval=0.02)
    pyautogui.press("enter")
    time.sleep(5)
    print("  [READY] Navigate to Twitter compose")


def post_via_api(platform: str, post: Post, dry_run: bool = False):
    """Post using platform APIs (requires API keys in env)."""
    if platform == "twitter":
        api_key = os.environ.get("TWITTER_API_KEY")
        if not api_key:
            print("  [ERROR] TWITTER_API_KEY not set")
            return
        if dry_run:
            print("  [DRY RUN] Would post via Twitter API v2")
            return
        # Twitter API v2 posting would go here
        print("  [TODO] Twitter API v2 integration")

    elif platform == "reddit":
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        if not client_id:
            print("  [ERROR] REDDIT_CLIENT_ID not set")
            return
        if dry_run:
            print("  [DRY RUN] Would post via Reddit API")
            return
        print("  [TODO] Reddit API integration")

    else:
        print(f"  [ERROR] API posting not supported for {platform}")


def main():
    parser = argparse.ArgumentParser(description="ScreenPilot Social Media Poster")
    parser.add_argument("--platform", choices=["hn", "reddit", "twitter", "linkedin", "all"],
                        help="Target platform")
    parser.add_argument("--all", action="store_true", help="Post to all platforms")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--api", action="store_true", help="Use API instead of browser")
    parser.add_argument("--lang", choices=["en", "jp"], default="en", help="Language")
    args = parser.parse_args()

    platforms = ["hn", "reddit", "twitter", "linkedin"] if args.all or args.platform == "all" else [args.platform]

    if not platforms or platforms == [None]:
        parser.print_help()
        return

    print("=" * 60)
    print("ScreenPilot Social Media Poster")
    print(f"Platforms: {', '.join(platforms)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'API' if args.api else 'BROWSER'}")
    print("=" * 60)

    for platform in platforms:
        print(f"\n--- {platform.upper()} ---\n")

        if platform == "hn":
            post = POSTS["hn"]
            if args.api:
                post_via_api("hn", post, args.dry_run)
            else:
                post_to_hn(post, args.dry_run)

        elif platform == "reddit":
            for key in ["reddit_python", "reddit_ml"]:
                post = POSTS[key]
                sub = "Python" if "python" in key else "MachineLearning"
                print(f"  >> r/{sub}")
                if args.api:
                    post_via_api("reddit", post, args.dry_run)
                else:
                    post_to_reddit(post, sub, args.dry_run)

        elif platform == "twitter":
            key = f"twitter_{args.lang}"
            post = POSTS.get(key, POSTS["twitter_en"])
            if args.api:
                post_via_api("twitter", post, args.dry_run)
            else:
                post_to_twitter(post, args.dry_run)

        elif platform == "linkedin":
            post = POSTS["linkedin"]
            if args.api:
                post_via_api("linkedin", post, args.dry_run)
            else:
                print(f"  Content: {post.body[:80]}...")
                if args.dry_run:
                    print("  [DRY RUN] Would navigate to linkedin.com")
                else:
                    print("  [READY] LinkedIn browser automation")

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
