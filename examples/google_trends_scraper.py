"""Google Trends Scraper via Selenium GUI automation.

Scrapes the "急上昇中" (Trending) page which has relaxed rate limits,
unlike the "調べる" (Explore) endpoint that gets 429-blocked quickly.

Usage:
    python examples/google_trends_scraper.py [--geo JP] [--pages 5] [--explore "keyword"]
"""
import os, sys, time, csv, re, random, argparse
from datetime import datetime
from pathlib import Path

os.environ.setdefault('DISPLAY', ':99')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import pandas as pd

OUTPUT_DIR = Path("recordings/google_trends")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def create_driver():
    options = Options()
    options.binary_location = '/usr/bin/google-chrome-stable'
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--no-first-run')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    prefs = {"download.default_directory": str(OUTPUT_DIR.resolve())}
    options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=options)


def dismiss_cookie_banner(driver):
    try:
        ok_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, '//button[text()="OK"]'))
        )
        ok_btn.click()
        time.sleep(1)
        print("  Cookie banner dismissed")
    except:
        pass


def parse_trending_page(driver):
    """Parse trending items from current page DOM."""
    body_text = driver.find_element(By.TAG_NAME, 'body').text
    lines = body_text.split('\n')

    items = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect search volume pattern: "5万+", "1,000+", "500+"
        if i + 1 < len(lines) and re.match(r'^[\d,]+万?\+$', lines[i].strip()):
            # Previous line is the keyword, current line is volume
            keyword = lines[i - 1].strip() if i > 0 else ""
            volume_str = lines[i].strip()

            # Parse volume
            volume = parse_volume(volume_str)

            # Next lines: growth%, time_ago
            growth = ""
            time_ago = ""
            related = []

            j = i + 1
            while j < len(lines) and j < i + 8:
                l = lines[j].strip()
                if '%' in l and 'arrow' not in l:
                    growth = l
                elif '時間前' in l or '分前' in l or '日前' in l:
                    time_ago = l
                elif l.startswith('+') and '件' in l:
                    pass  # "+N件" marker
                elif l in ('有効', 'trending_up', 'arrow_upward', 'timelapse', 'info'):
                    pass  # UI markers
                elif l and not l.startswith('期間') and l not in ('検索ボリューム', '発生日時', 'トレンドの内訳'):
                    if len(l) > 1 and not re.match(r'^[\d,]+万?\+$', l) and '%' not in l:
                        related.append(l)
                j += 1

            if keyword and keyword not in ('検索ボリューム', 'search', 'トレンド', '24 時間以内'):
                items.append({
                    'keyword': keyword,
                    'volume': volume,
                    'volume_str': volume_str,
                    'growth': growth,
                    'time_ago': time_ago,
                    'related_keywords': '; '.join(related[:5]),
                })
        i += 1

    return items


def parse_volume(vol_str):
    """Parse volume string like '5万+' -> 50000, '1,000+' -> 1000."""
    vol_str = vol_str.replace('+', '').replace(',', '').strip()
    if '万' in vol_str:
        return int(float(vol_str.replace('万', '')) * 10000)
    return int(vol_str) if vol_str.isdigit() else 0


def scrape_trending(driver, geo="JP", pages=5):
    """Scrape multiple pages of trending data."""
    url = f'https://trends.google.com/trending?geo={geo}&hl=ja'
    print(f"Navigating to {url}")
    driver.get(url)
    time.sleep(5)
    dismiss_cookie_banner(driver)

    all_items = []

    for page in range(pages):
        print(f"\n--- Page {page + 1} ---")
        time.sleep(2)

        items = parse_trending_page(driver)
        # Deduplicate within page
        new_keywords = {item['keyword'] for item in all_items}
        new_items = [item for item in items if item['keyword'] not in new_keywords]
        all_items.extend(new_items)
        print(f"  Found {len(new_items)} new items (total: {len(all_items)})")

        if page < pages - 1:
            # Click "Next page" button using JS to bypass overlay
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="次のページに移動"]')
                if not next_btn.is_enabled():
                    print("  No more pages")
                    break
                driver.execute_script("arguments[0].click()", next_btn)
                time.sleep(random.uniform(3, 5))
            except Exception as e:
                print(f"  Pagination failed: {e}")
                break

    return all_items


def scrape_explore(driver, keyword, geo="JP", timeframe="today 3-m"):
    """Carefully try the Explore page for interest over time.

    Returns interest-over-time data if successful, None if rate-limited.
    """
    # Map timeframe to URL parameter
    tf_map = {
        "today 1-m": "today%201-m",
        "today 3-m": "today%203-m",
        "today 12-m": "today%2012-m",
        "past 5 years": "today%205-y",
    }
    tf_param = tf_map.get(timeframe, "today%203-m")

    from urllib.parse import quote
    encoded_kw = quote(keyword)
    url = f'https://trends.google.com/trends/explore?q={encoded_kw}&geo={geo}&hl=ja&date={tf_param}'

    print(f"  Explore: {keyword} ({timeframe})")
    driver.get(url)
    time.sleep(random.uniform(6, 10))

    # Check for 429
    if '429' in driver.title or 'Too Many' in driver.title:
        print("  ⚠ 429 Rate Limited! Waiting 60s...")
        time.sleep(60)
        driver.get(url)
        time.sleep(random.uniform(8, 12))
        if '429' in driver.title:
            print("  ✗ Still rate limited. Skipping.")
            return None

    # Try to extract interest-over-time data
    driver.save_screenshot(str(OUTPUT_DIR / f"explore_{keyword[:20]}.png"))

    # Get page text
    try:
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        if '429' in body_text[:100] or 'Too Many' in body_text[:100]:
            print("  ✗ Rate limited (body check)")
            return None

        # Extract related queries section
        related = []
        if '関連キーワード' in body_text or '関連トピック' in body_text:
            lines = body_text.split('\n')
            in_related = False
            for line in lines:
                if '関連キーワード' in line or '関連トピック' in line:
                    in_related = True
                    continue
                if in_related and line.strip():
                    if line.strip() in ('急激増加', '人気', '注目', ''):
                        continue
                    if re.match(r'^\d+$', line.strip()):
                        continue
                    related.append(line.strip())
                    if len(related) >= 10:
                        break

        return {
            'keyword': keyword,
            'related_queries': related,
            'screenshot': f"explore_{keyword[:20]}.png",
            'page_text_length': len(body_text),
        }
    except Exception as e:
        print(f"  Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Google Trends Scraper")
    parser.add_argument('--geo', default='JP', help='Country code (default: JP)')
    parser.add_argument('--pages', type=int, default=5, help='Pages of trending to scrape')
    parser.add_argument('--explore', nargs='*', help='Keywords for explore (careful - rate limited)')
    args = parser.parse_args()

    driver = create_driver()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        # Phase 1: Trending data (safe, no rate limit)
        print("=" * 60)
        print("Phase 1: Scraping Trending (急上昇中)")
        print("=" * 60)
        trending = scrape_trending(driver, geo=args.geo, pages=args.pages)

        if trending:
            csv_path = OUTPUT_DIR / f"trending_{args.geo}_{timestamp}.csv"
            df = pd.DataFrame(trending)
            df['geo'] = args.geo
            df['scraped_at'] = datetime.now().isoformat()
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"\n✓ Saved {len(df)} trending items to {csv_path}")
            print(df[['keyword', 'volume', 'growth', 'time_ago']].head(10).to_string())

        # Phase 2: Explore (careful, rate limited)
        if args.explore:
            print("\n" + "=" * 60)
            print("Phase 2: Explore (調べる) - CAREFUL, rate limited")
            print("=" * 60)

            explore_results = []
            for kw in args.explore:
                result = scrape_explore(driver, kw, geo=args.geo)
                if result:
                    explore_results.append(result)
                    print(f"  ✓ {kw}: {len(result.get('related_queries', []))} related queries")
                else:
                    print(f"  ✗ {kw}: rate limited or failed")

                # Long delay between explore requests
                if kw != args.explore[-1]:
                    delay = random.uniform(45, 75)
                    print(f"  Waiting {delay:.0f}s before next explore...")
                    time.sleep(delay)

            if explore_results:
                json_path = OUTPUT_DIR / f"explore_{args.geo}_{timestamp}.json"
                import json
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(explore_results, f, ensure_ascii=False, indent=2)
                print(f"\n✓ Saved explore results to {json_path}")

    finally:
        driver.quit()

    print(f"\nAll output in: {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
