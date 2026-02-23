#!/usr/bin/env python3
"""
ScreenPilot Autonomous Challenge Loop
========================================
Continuously runs challenges, analyzes failures, retries with improved strategies,
and updates the viewer. Runs until API credits are exhausted.

Usage:
    python examples/auto_challenge_loop.py
    python examples/auto_challenge_loop.py --rounds 5
    python examples/auto_challenge_loop.py --only-new
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

from screenpilot.agent import ScreenPilotAgent, StepResult, TaskResult
from screenpilot.config import ScreenPilotConfig, LLMConfig

RECORDINGS_DIR = Path("recordings/challenges")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# Global provider config — set by main() based on --provider flag
_PROVIDER_CONFIG: ScreenPilotConfig | None = None

# Import shared utilities from challenge_runner
sys.path.insert(0, str(Path(__file__).parent))
from challenge_runner import (
    Challenge, StepLog, start_recording, stop_recording,
    generate_srt, postprocess_video, navigate_chrome, generate_viewer,
)


# ============================================================================
# VIRAL / HIGH-IMPACT CHALLENGES
# ============================================================================

VIRAL_CHALLENGES = [
    # --- インパクト系: 「AIがこんなことできるの!?」 ---
    Challenge(20, "play_wordle", "expert",
              'This is the NYT Wordle game. Type "CRANE" and press Enter to make the first guess, then observe the result',
              "https://www.nytimes.com/games/wordle/index.html", 10,
              "AI plays Wordle - types a guess word"),
    Challenge(21, "use_calculator", "medium",
              'Click the buttons to calculate 42 × 7: click 4, then 2, then ×, then 7, then =',
              "https://www.online-calculator.com/", 15,
              "AI uses an online calculator"),
    Challenge(22, "google_maps_search", "hard",
              'Type "Tokyo Tower" in the search box and press Enter to find it on the map',
              "https://www.google.com/maps", 12,
              "AI searches for Tokyo Tower on Google Maps"),
    Challenge(23, "crypto_price", "medium",
              'Look at the current Bitcoin price displayed on the page and scroll down to see the price chart',
              "https://www.coingecko.com/en/coins/bitcoin", 10,
              "AI checks Bitcoin price and chart on CoinGecko"),
    Challenge(24, "draw_on_canvas", "expert",
              'Click and drag on the white canvas area to draw a simple line or shape',
              "https://kleki.com/", 12,
              "AI draws on a web canvas - creative AI art"),
    Challenge(25, "speed_typing_test", "hard",
              'Click the text area and start typing the displayed text to begin the typing speed test',
              "https://www.typingtest.com/", 12,
              "AI takes a typing speed test"),
    Challenge(26, "chess_first_move", "expert",
              'Make the first chess move by clicking on the e2 pawn (white pawn in front of the king), then clicking e4',
              "https://www.chess.com/play/computer", 15,
              "AI makes opening chess move e2-e4"),
    Challenge(27, "translate_text", "medium",
              'Type "Hello, I am an AI that controls computers by looking at the screen" in the source text box, then change the target language to Japanese',
              "https://translate.google.com/", 15,
              "AI uses Google Translate to translate text"),
    Challenge(28, "amazon_search", "medium",
              'Type "raspberry pi" in the search box and press Enter to search for products',
              "https://www.amazon.com", 12,
              "AI searches for products on Amazon"),
    Challenge(29, "imdb_movie", "medium",
              'Type "Inception" in the search box and press Enter to look up the movie',
              "https://www.imdb.com", 12,
              "AI searches for a movie on IMDB"),
    Challenge(30, "arxiv_paper", "hard",
              'Type "attention is all you need" in the search box and press Enter to find the famous transformer paper',
              "https://arxiv.org", 12,
              "AI searches for the Transformer paper on arXiv"),
    Challenge(31, "spotify_browse", "medium",
              'Scroll down to browse featured playlists and click on any playlist',
              "https://open.spotify.com", 12,
              "AI browses Spotify playlists"),
    Challenge(32, "github_create_issue_comment", "expert",
              'Scroll down to the comment box at the bottom of the issue, click it, and type "This issue was automatically found and commented by ScreenPilot AI agent"',
              "https://github.com/pphouse/screenpilot/issues/2", 15,
              "AI comments on a GitHub issue (read-only since not logged in)"),
    Challenge(33, "news_headline", "easy",
              'Scroll down to see more headlines and click on any news article to read it',
              "https://news.ycombinator.com/newest", 10,
              "AI browses latest HN stories and reads one"),
    Challenge(34, "wolfram_alpha", "hard",
              'Type "integral of x^2 sin(x)" in the input box and press Enter to compute',
              "https://www.wolframalpha.com/", 12,
              "AI solves a calculus problem on Wolfram Alpha"),
    Challenge(35, "github_profile", "medium",
              'Click on the "Repositories" tab to see the list of repositories',
              "https://github.com/pphouse", 10,
              "AI navigates a GitHub user profile"),

    # --- レベル2: フォーム入力・実務系（確定申告への階段） ---
    Challenge(36, "fill_web_form", "hard",
              'Fill out the sample form: type "Taro Yamada" in the Name field, "taro@example.com" in Email, select "Japan" from the Country dropdown, then click Submit',
              "https://www.w3schools.com/html/html_forms.asp", 15,
              "AI fills out a web form with multiple fields"),
    Challenge(37, "tax_calculator", "expert",
              'Enter annual income of 5000000 yen in the income field, click calculate to see the estimated tax. If there are deduction fields, enter 380000 for basic deduction',
              "https://www.nta.go.jp/taxes/shiraberu/shinkoku/kakutei.htm", 20,
              "AI uses Japanese tax calculator - step toward automated tax filing"),
    Challenge(38, "flight_search", "expert",
              'Search for a one-way flight from Tokyo (NRT) to New York (JFK) for next month. Enter the departure city as Tokyo, arrival as New York, select one-way, and click search',
              "https://www.google.com/travel/flights", 20,
              "AI searches for flights - complex multi-field form"),
    Challenge(39, "hotel_booking_search", "expert",
              'Search for a hotel in Kyoto for 2 adults, check-in next Friday, check-out next Saturday. Type "Kyoto" in the destination, set dates, and click search',
              "https://www.booking.com", 20,
              "AI searches for hotels - multi-step booking form"),
    Challenge(40, "currency_converter", "medium",
              'Convert 100 USD to JPY: enter 100 in the amount field, select USD as source currency and JPY as target, then observe the result',
              "https://www.xe.com/currencyconverter/", 12,
              "AI converts currencies - practical financial task"),
    Challenge(41, "stackoverflow_search", "medium",
              'Type "how to read csv file in python" in the search box and press Enter, then click the first result to read the answer',
              "https://stackoverflow.com", 15,
              "AI searches and reads Stack Overflow answers"),
    Challenge(42, "google_sheets_create", "expert",
              'Click on "Blank spreadsheet" to create a new sheet, then type "Income" in cell A1, press Tab, type "Amount" in B1, press Enter, type "Salary" in A2, press Tab, type "5000000" in B2',
              "https://docs.google.com/spreadsheets/", 20,
              "AI creates a spreadsheet and enters data - office automation"),
    Challenge(43, "multi_site_price_compare", "expert",
              'Look at the Bitcoin price shown on the page, remember it, then scroll down to check if there is a 24h change percentage displayed. Report done when you have seen both the price and the percentage change',
              "https://www.coinbase.com/price/bitcoin", 15,
              "AI gathers price data from financial site - data collection task"),
    Challenge(44, "fill_survey_form", "hard",
              'Answer the survey: select your age range, pick your favorite programming language, write a short comment "AI is the future of automation" in the text area, then click Submit',
              "https://www.jotform.com/form-templates/simple-survey-form", 18,
              "AI fills out a survey - complex form with multiple input types"),
    Challenge(45, "job_search", "expert",
              'Type "software engineer" in the job title field, type "Tokyo" in the location field, and click Search or Find Jobs',
              "https://www.indeed.com", 15,
              "AI searches for jobs - practical career task"),

    # --- レベル3: 高難度マルチステップ（確定申告レベルへの階段） ---
    Challenge(50, "flight_sort_cheapest", "expert",
              'Search for one-way flights from Tokyo to New York departing March 15. After results load, click "Price" or sort by price to find the cheapest option, then scroll down to see results.',
              "https://www.google.com/travel/flights", 20,
              "AI searches flights + sorts by price - complex multi-field + sort"),
    Challenge(51, "wikipedia_deep_nav", "expert",
              'Search for "Transformer (deep learning model)" on Wikipedia. After the article loads, scroll down to find the "Architecture" section. Then click the "Attention" link to navigate to the Attention mechanism page.',
              "https://en.wikipedia.org", 20,
              "AI researches a topic: search + read + follow links"),
    Challenge(52, "translate_long_text", "hard",
              'Type "Artificial intelligence agents can now control computers by looking at screenshots and clicking buttons, just like humans do." in the source text box. Then change the target language to Japanese.',
              "https://translate.google.com/", 15,
              "AI translates a full sentence to Japanese"),
    Challenge(53, "github_deep_code_nav", "expert",
              'Navigate into the "screenpilot" folder, then click the "planner" subfolder, then open "planner.py" to view the code. Scroll down to see the system prompt.',
              "https://github.com/pphouse/screenpilot", 20,
              "AI navigates deep into a code repository"),
    Challenge(54, "arxiv_read_abstract", "hard",
              'Search for "attention is all you need", click the first result to open the paper page, then scroll down to read the abstract.',
              "https://arxiv.org", 15,
              "AI finds and reads a research paper on arXiv"),
    Challenge(55, "multi_tab_comparison", "expert",
              'Look at the current Bitcoin price on this page. Note the price, then scroll down to see the 24-hour price change and the 7-day chart. After reviewing, report done.',
              "https://www.coingecko.com/en/coins/bitcoin", 15,
              "AI gathers and reviews financial data from multiple sections"),
    Challenge(56, "form_fill_w3schools", "hard",
              'Scroll down to the "Try it Yourself" section and click the "Try it Yourself" button. In the new page, find the form with First name and Last name fields. Type "Taro" in First name and "Yamada" in Last name, then click Submit.',
              "https://www.w3schools.com/html/html_forms.asp", 20,
              "AI fills out a form on W3Schools - step toward automated form filling"),
    Challenge(57, "chess_play_3_moves", "expert",
              'Play 3 chess moves: First move e2 to e4 (click e2 pawn then e4), wait for the computer to respond, then move d2 to d4 (click d2 pawn then d4), wait again, then move knight from g1 to f3 (click g1 then f3).',
              "https://www.chess.com/play/computer", 25,
              "AI plays 3 chess moves - complex multi-step game interaction"),

    # --- レベル4: 超高難度・実務レベル（確定申告レベル） ---
    Challenge(60, "multi_city_flight", "expert",
              'Search for flights from Tokyo to London. After results appear, change the departure date to April 15 by clicking the date field and selecting it. Then sort by "Best" or look at the first result and note the price and airline.',
              "https://www.google.com/travel/flights", 25,
              "AI searches flights + changes date + reads results"),
    Challenge(61, "zillow_property_search", "expert",
              'Type "San Francisco, CA" in the search box and press Enter. After results load, click "Price" filter and set maximum price to $1,000,000. Then scroll down to see at least 3 listings.',
              "https://www.zillow.com", 25,
              "AI searches properties with price filter - real estate automation"),
    Challenge(62, "linkedin_job_details", "expert",
              'Type "machine learning engineer" in the search box at the top and press Enter. Then click "Jobs" tab to see job listings. Click on the first job result to see details.',
              "https://www.linkedin.com/jobs/", 20,
              "AI searches LinkedIn jobs and reads details"),
    Challenge(63, "github_pr_review", "expert",
              'Click on "Pull requests" tab. Then click on the most recent pull request to open it. Scroll down to see the file changes or comments.',
              "https://github.com/microsoft/vscode", 20,
              "AI navigates GitHub PR review workflow"),
    Challenge(64, "codepen_create", "expert",
              'Click on the HTML editor pane. Clear any existing code and type: <h1>Hello from ScreenPilot</h1><p>This page was created by an AI agent.</p><button onclick="alert(\'AI works!\')">Click me</button>. Then look at the preview pane to verify the output.',
              "https://codepen.io/pen/", 25,
              "AI creates a web page on CodePen - coding automation"),
    Challenge(65, "weather_week_forecast", "expert",
              'Type "Tokyo weather" in the search box and press Enter. After the weather card appears, look for a "7-day forecast" or "10-day" link and click it. Then scroll down to see the full week forecast.',
              "https://www.google.com", 20,
              "AI gets extended weather forecast - multi-step info gathering"),
    Challenge(66, "amazon_compare_prices", "expert",
              'Search for "wireless mouse" on Amazon. After results load, scroll down to see at least 3 products. Click on the first product to see its price and details. Then go back and click the second product to compare.',
              "https://www.amazon.com", 25,
              "AI compares product prices on Amazon - shopping automation"),
    Challenge(67, "github_issue_browse", "expert",
              'Click on "Issues" tab. Then click on "Labels" to see all issue labels. Click on the "bug" label to filter issues by bugs. Then click on the first bug issue to read it.',
              "https://github.com/microsoft/vscode", 20,
              "AI browses GitHub issues by label - developer workflow"),
    Challenge(68, "npm_package_research", "expert",
              'Type "express" in the search box and press Enter. Click on the "express" package (the first result). Scroll down to see the weekly downloads count and the README description.',
              "https://www.npmjs.com", 15,
              "AI researches npm packages - developer workflow"),
    Challenge(69, "multi_step_data_entry", "expert",
              'In the Try-it editor, clear the existing HTML and type a complete form: <form><label>Name:</label><input type="text" value="AI Agent"><br><label>Email:</label><input type="email" value="ai@screenpilot.dev"><br><input type="submit" value="Send"></form>. Then click "Run" to see the result.',
              "https://www.w3schools.com/html/tryit.asp?filename=tryhtml_form_submit", 25,
              "AI writes HTML code and runs it - coding automation"),
    Challenge(70, "youtube_playlist_browse", "expert",
              'Type "lofi hip hop" in the search box and press Enter. After results load, click on a playlist (not a video) from the results. Then scroll down in the playlist to see at least 5 videos listed.',
              "https://www.youtube.com", 20,
              "AI searches and browses YouTube playlists"),
    Challenge(71, "google_scholar_cite", "expert",
              'Type "deep learning" in the search box and press Enter. After results load, click the "Cited by" link under the first result to see papers that cite it.',
              "https://scholar.google.com", 20,
              "AI uses Google Scholar to browse citations - academic workflow"),
    Challenge(72, "trello_style_kanban", "expert",
              'Click on "Add a card" or "+" in the first column. Type "Implement login feature" and press Enter. Then add another card "Write unit tests". Then drag or add a card in the second column "Design database schema".',
              "https://kanban.guide/", 20,
              "AI uses a kanban board - project management"),

    # ================================================================
    # 🎯 確定申告(Tax Filing)スキルツリー
    # ================================================================
    # レベル1: 基本フォーム操作（テキスト入力、ドロップダウン、日付選択）
    Challenge(100, "tax_basic_form_input", "medium",
              'Click the "First name" field and type "太郎". Then click "Last name" and type "山田". Then click the Submit button.',
              "https://www.w3schools.com/html/tryit.asp?filename=tryhtml_form_submit", 15,
              "税務基礎: テキストフィールドへの日本語入力"),
    Challenge(101, "tax_dropdown_select", "medium",
              'Scroll down to find any <select> dropdown example. Click the dropdown and select an option. Then click the Submit or "Try it" button.',
              "https://www.w3schools.com/tags/tryit.asp?filename=tryhtml_select", 15,
              "税務基礎: ドロップダウンメニュー操作"),
    Challenge(102, "tax_radio_checkbox", "medium",
              'Find the radio button and checkbox examples. Select a radio option and check a checkbox. Then click Submit.',
              "https://www.w3schools.com/tags/tryit.asp?filename=tryhtml5_input_type_radio", 15,
              "税務基礎: ラジオボタン・チェックボックス操作"),
    Challenge(103, "tax_date_picker", "hard",
              'Click on the date input field and set the date to 2025-03-15 (March 15, 2025). Then click Submit.',
              "https://www.w3schools.com/tags/tryit.asp?filename=tryhtml5_input_type_date", 15,
              "税務基礎: 日付ピッカー操作"),

    # レベル2: 数値入力・計算検証
    Challenge(110, "tax_income_calc", "hard",
              'Enter "5000000" in the first input field (income). Tab to the next field and enter "480000" (deductions). Look for a calculate button or result area. Report done after entering both values.',
              "https://www.online-calculator.com/", 15,
              "税務計算: 所得と控除の入力"),
    Challenge(111, "tax_currency_calc", "hard",
              'Convert 5000000 JPY to USD. Enter 5000000 in the amount, select JPY as source and USD as target. Read the result and report done.',
              "https://www.xe.com/currencyconverter/", 15,
              "税務参考: 為替計算（外貨所得用）"),
    Challenge(112, "tax_spreadsheet_entry", "expert",
              'Create a new blank spreadsheet. In A1 type "項目", B1 type "金額". A2: "給与所得", B2: "5000000". A3: "基礎控除", B3: "480000". A4: "課税所得", B4: "=B2-B3". Report done after entering all values.',
              "https://docs.google.com/spreadsheets/", 25,
              "税務計算: スプレッドシートで課税所得計算"),

    # レベル3: 日本の税務サイトナビゲーション
    Challenge(120, "tax_nta_navigate", "hard",
              'Find and click on "確定申告書等の作成コーナー" or any link related to tax return filing (確定申告). If you see a button for "作成開始", click it.',
              "https://www.nta.go.jp/taxes/shiraberu/shinkoku/kakutei.htm", 20,
              "国税庁: 確定申告ページナビゲーション"),
    Challenge(121, "tax_nta_etax_start", "expert",
              'Navigate to the e-Tax (確定申告書等作成コーナー). Look for "作成開始" or "新規作成" button. Click it. If asked about browser compatibility or terms, accept/continue.',
              "https://www.keisan.nta.go.jp/kyoutu/ky/sm/top#bsctrl", 25,
              "e-Tax: 確定申告作成開始"),
    Challenge(122, "tax_etax_income_entry", "expert",
              'In the e-Tax form, find the income (所得) section. Enter salary income (給与所得) of 5,000,000 yen. Navigate between form fields using Tab. Look for "次へ" (Next) button and click it.',
              "https://www.keisan.nta.go.jp/kyoutu/ky/sm/top#bsctrl", 30,
              "e-Tax: 所得金額の入力"),
    Challenge(123, "tax_etax_deduction", "expert",
              'In the e-Tax deductions section, find "基礎控除" (basic deduction) and verify it shows 480,000 yen. Look for medical expense deduction (医療費控除) field and enter 100,000. Click 次へ.',
              "https://www.keisan.nta.go.jp/kyoutu/ky/sm/top#bsctrl", 30,
              "e-Tax: 控除額の入力"),
    Challenge(124, "tax_etax_full_flow", "expert",
              'Complete a simplified tax return: 1) Select 所得税 (income tax), 2) Enter salary income 5,000,000, 3) Enter basic deduction, 4) Review the calculated tax amount, 5) Report done with the tax amount visible.',
              "https://www.keisan.nta.go.jp/kyoutu/ky/sm/top#bsctrl", 40,
              "e-Tax: 確定申告フルフロー（簡易版）"),

    # ================================================================
    # 📈 株取引 + ニュース/IR情報取得スキルツリー
    # ================================================================
    # レベル1: 金融情報閲覧
    Challenge(200, "stock_yahoo_price", "medium",
              'Search for "AAPL" (Apple) stock. Read the current price and the daily change percentage. Scroll down to see the chart. Report done.',
              "https://finance.yahoo.com", 15,
              "株式基礎: Yahoo Financeで株価確認"),
    Challenge(201, "stock_yahoo_jp_price", "medium",
              'Search for "7203" (Toyota) or type the ticker in the search box. Read the current stock price in JPY. Report done when you can see the price.',
              "https://finance.yahoo.co.jp/", 15,
              "株式基礎: Yahoo!ファイナンスで日本株確認"),
    Challenge(202, "stock_google_finance", "medium",
              'Search for "NVDA" (NVIDIA) stock. View the current price, daily change, and the price chart. Scroll down to see key statistics. Report done.',
              "https://www.google.com/finance/", 15,
              "株式基礎: Google Financeで株価・チャート閲覧"),
    Challenge(203, "stock_read_chart", "hard",
              'Look at the Bitcoin price chart. Click on "1M" or "1 Month" timeframe button to see the monthly chart. Then click "1Y" for yearly. Report done after seeing both views.',
              "https://www.coingecko.com/en/coins/bitcoin", 15,
              "チャート操作: 時間軸切り替え"),

    # レベル2: ニュース・IR情報取得
    Challenge(210, "news_nikkei_headline", "hard",
              'Scroll down to find financial/market news headlines. Click on the first market-related news article. Read the headline and first paragraph. Report done.',
              "https://www.nikkei.com/", 15,
              "ニュース取得: 日経新聞のマーケットニュース閲覧"),
    Challenge(211, "news_reuters_market", "hard",
              'Click on "Markets" or "Business" section in the navigation. Scroll down to read market headlines. Click on the first market-related article. Report done after seeing the article.',
              "https://www.reuters.com/", 15,
              "ニュース取得: ロイターのマーケットニュース"),
    Challenge(212, "ir_tdnet_browse", "hard",
              'This is the TDnet (適時開示情報閲覧サービス). Look at the latest disclosure filings. Scroll down to see recent IR announcements. Click on any filing to view details. Report done.',
              "https://www.release.tdnet.info/inbs/I_main_00.html", 20,
              "IR情報: TDnetで適時開示情報を閲覧"),
    Challenge(213, "ir_edinet_search", "expert",
              'This is EDINET (金融庁の有価証券報告書検索). Search for "トヨタ" or "Toyota" in the company search. Click on any result to view a filing. Report done after seeing filing details.',
              "https://disclosure.edinet-fsa.go.jp/", 20,
              "IR情報: EDINETで有価証券報告書を検索"),
    Challenge(214, "news_google_finance_news", "medium",
              'Search for "TSLA" (Tesla). Scroll down to the news section below the chart. Read at least 2 news headlines related to Tesla. Report done.',
              "https://www.google.com/finance/", 15,
              "ニュース: Google Financeの個別銘柄ニュース"),

    # レベル3: 証券取引シミュレーション
    Challenge(220, "stock_investopedia_sim", "expert",
              'This is Investopedia stock simulator. Look for a search box or "Trade" button. Search for "AAPL". If you can find a Buy/Trade interface, enter quantity 10 and look for the Buy button (do NOT actually click Buy). Report done when you see the trade form.',
              "https://www.investopedia.com/simulator/", 25,
              "取引シミュ: Investopediaで模擬取引画面操作"),
    Challenge(221, "stock_watchlist_create", "expert",
              'Search for "AAPL" on Yahoo Finance. Find and click the "+ Add to watchlist" or star/bookmark button. Then search for "MSFT" and add it too. Go to "My Portfolio" or "Watchlist" to verify both are listed.',
              "https://finance.yahoo.com", 25,
              "ウォッチリスト: Yahoo Financeで銘柄リスト管理"),
    Challenge(222, "stock_compare_two", "expert",
              'Search for "AAPL" and note the current price and P/E ratio. Then search for "MSFT" and note its price and P/E ratio. In your observation, compare the two. Report done.',
              "https://finance.yahoo.com", 20,
              "銘柄比較: 2銘柄の指標を比較"),
    Challenge(223, "stock_screener_filter", "expert",
              'Find and click on "Screeners" or "Stock Screener". Set filters: Market Cap > 100B, Sector = Technology. Apply the filter and look at the results. Report done after seeing filtered stocks.',
              "https://finance.yahoo.com/screener/", 25,
              "スクリーナー: 条件でフィルタリング"),

    # レベル4: YouTube配信準備
    Challenge(230, "youtube_studio_navigate", "expert",
              'Navigate to YouTube Studio. Look for the "Go Live" or "Create" button. If asked to sign in, report the sign-in page is shown. Report done when you reach the studio or live setup page.',
              "https://studio.youtube.com/", 20,
              "YouTube配信: スタジオ画面ナビゲーション"),
    Challenge(231, "youtube_search_live_stream", "hard",
              'Search for "stock trading live stream" on YouTube. Click on "Live" filter to see only live streams. Click on any currently live stream. Report done.',
              "https://www.youtube.com", 20,
              "YouTube配信参考: ライブ配信の検索・閲覧"),
    Challenge(232, "obs_website_research", "hard",
              'Search for "OBS Studio download" on Google. Click on the official OBS Project website. Find the download button for Linux. Report done when you see the download page.',
              "https://www.google.com", 15,
              "配信準備: OBS Studioの調査"),

    # レベル5: 統合シナリオ（確定申告 + 株取引の実践的フロー）
    Challenge(240, "integrated_stock_news_analysis", "expert",
              'Go to Google Finance. Search for "NVDA". Read the current price and latest news headline. Then navigate to Reuters and search for "NVIDIA". Compare the news. Report done with your analysis in the observation field.',
              "https://www.google.com/finance/", 30,
              "統合: 複数ソースから銘柄情報を収集・分析"),
    Challenge(241, "integrated_tax_prep_research", "expert",
              'Search Google for "確定申告 2025 やり方". Click on the first helpful result (prefer nta.go.jp or official sites). Read the key steps for filing. Then search for "e-Tax 使い方" and read about online filing. Report done.',
              "https://www.google.com", 25,
              "統合: 確定申告の手順をリサーチ"),
    Challenge(242, "integrated_portfolio_tax", "expert",
              'Search for "AAPL" on Yahoo Finance and note the current price. Then go to xe.com and convert that USD price to JPY. Then calculate the approximate Japanese tax on a gain of 100 shares using the online calculator (profit × 20.315%%). Report done with your calculation.',
              "https://finance.yahoo.com", 30,
              "統合: 株式譲渡益の概算税額計算"),

    # =========================================================================
    # X (Twitter) Challenges — SNS操作系
    # =========================================================================

    # --- X ログイン ---
    Challenge(300, "x_login", "medium",
              'Log in to X (Twitter). Click "Sign in" or the login link. '
              'Enter the username/email: lisapyo3274@gmail.com and password: lisalisa3274 . '
              'After logging in, confirm you can see the home timeline. Report done.',
              "https://x.com/login", 15,
              "AIがXにログインする"),

    # --- X 基本操作 ---
    Challenge(301, "x_post_tweet", "hard",
              'You are logged in to X. Click the "Post" or tweet compose button. '
              'Type "Hello from ScreenPilot! This tweet was posted by an AI agent 🤖 #ScreenPilot #AIAgent" '
              'in the compose box. Then click the "Post" button to publish. Report done after the tweet is posted.',
              "https://x.com/home", 15,
              "AIがツイートを投稿する"),

    Challenge(302, "x_search_topic", "medium",
              'Click the Search/Explore icon or the search box. '
              'Type "AI agent computer use" and press Enter. '
              'Look at the search results. Report done after seeing results.',
              "https://x.com/explore", 12,
              "AIがXで検索する"),

    Challenge(303, "x_view_profile", "easy",
              'Navigate to your own profile page. Click on the profile icon or go to the profile section. '
              'Confirm you can see the profile page with username @lisapyo3274. Report done.',
              "https://x.com/lisapyo3274", 10,
              "AIがX自分のプロフィールを確認"),

    Challenge(304, "x_follow_user", "medium",
              'Search for "AnthropicAI" in the search box. '
              'Click on the @AnthropicAI account from the results. '
              'Click the "Follow" button. Report done.',
              "https://x.com/search?q=AnthropicAI&src=typed_query", 12,
              "AIがXでアカウントをフォローする"),

    Challenge(305, "x_like_tweet", "medium",
              'You are on the X home timeline. Scroll down to see tweets. '
              'Find any tweet and click the heart/like button on it. '
              'Confirm the heart turns red/pink (liked). Report done.',
              "https://x.com/home", 10,
              "AIがツイートにいいねする"),

    Challenge(306, "x_reply_tweet", "hard",
              'You are on the X home timeline. Find any tweet and click the reply icon (speech bubble). '
              'Type "Great post! 🤖 - sent by ScreenPilot AI" in the reply box. '
              'Click the Reply button to post. Report done.',
              "https://x.com/home", 15,
              "AIがツイートにリプライする"),

    Challenge(307, "x_retweet", "medium",
              'You are on the X home timeline. Scroll to find a tweet. '
              'Click the retweet/repost icon (the two-arrow icon). '
              'Select "Repost" from the menu. Report done.',
              "https://x.com/home", 10,
              "AIがリツイートする"),

    Challenge(308, "x_send_dm", "hard",
              'Click on the Messages icon (envelope) in the sidebar. '
              'Click "New message" or the compose icon. '
              'Search for and select @AnthropicAI (or type the name). '
              'Type "Hello from ScreenPilot AI agent!" and send the message. Report done.',
              "https://x.com/messages", 15,
              "AIがXでDMを送る"),

    Challenge(309, "x_change_display_name", "hard",
              'Go to your profile page. Click "Edit profile" button. '
              'Change the display name to "Lisa AI 🤖". '
              'Click "Save" to save changes. Report done.',
              "https://x.com/lisapyo3274", 15,
              "AIがXの表示名を変更する"),

    Challenge(310, "x_trending_check", "easy",
              'Go to the Explore page. Look at the trending topics. '
              'Scroll down to see at least 5 trending topics. Report done.',
              "https://x.com/explore/tabs/trending", 10,
              "AIがXのトレンドを確認する"),

    # --- X + Gmail 連携 ---
    Challenge(311, "x_post_with_screenshot", "expert",
              'First go to Yahoo Finance and search for "AAPL". Note the stock price. '
              'Then go to X (x.com/home) using Ctrl+L. '
              'Compose a new tweet: "AAPL stock update: [price you saw] 📈 #stocks #AAPL - posted by ScreenPilot AI". '
              'Post the tweet. Report done.',
              "https://finance.yahoo.com/quote/AAPL/", 20,
              "AIが株価を見てツイートする"),
]


# ============================================================================
# Autonomous improvement loop
# ============================================================================

def analyze_failure(summary: dict) -> str:
    """Analyze why a challenge failed and suggest improvement."""
    steps = summary.get("step_details", [])
    error = summary.get("error", "")

    if not steps:
        return "agent_crash"

    # Check for repeated coordinates
    coords = [s["coords"] for s in steps if s["coords"]]
    if len(coords) >= 3:
        unique = set(coords[-3:])
        if len(unique) == 1:
            return "stuck_same_coords"

    # Check for repeated action types
    actions = [s["action"] for s in steps]
    if len(actions) >= 3 and len(set(actions[-3:])) == 1:
        return "stuck_same_action"

    # Check for bot detection keywords
    reasonings = " ".join(s.get("reasoning", "") for s in steps).lower()
    if any(kw in reasonings for kw in ["captcha", "recaptcha", "bot", "blocked", "forbidden"]):
        return "bot_detected"

    # Check if task was nearly complete (reached target page but didn't say done)
    if len(steps) >= summary.get("steps", 0) and not summary["success"]:
        if any("done" not in s["action"] for s in steps):
            return "completion_detection_fail"

    return "navigation_fail"


def run_single_challenge(challenge: Challenge, speed: float = 3.0, attempt: int = 1) -> dict:
    """Run a single challenge with recording (adapted from challenge_runner)."""
    print(f"\n{'=' * 60}")
    print(f"[Attempt {attempt}] Challenge #{challenge.id}: {challenge.name}")
    print(f"Difficulty: {challenge.difficulty.upper()} | Goal: {challenge.goal}")
    print(f"{'=' * 60}\n")

    suffix = f"_v{attempt}" if attempt > 1 else ""
    output_dir = RECORDINGS_DIR / f"{challenge.id:02d}_{challenge.name}{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_video = output_dir / "recording_raw.mp4"
    srt_path = output_dir / "reasoning.srt"
    final_video = output_dir / "recording.mp4"

    # Navigate
    print(f"  [Setup] → {challenge.setup_url}")
    navigate_chrome(challenge.setup_url)
    time.sleep(2)

    # Record
    recorder = start_recording(raw_video)
    rec_start = time.time()
    time.sleep(1.5)

    # Agent — use global _PROVIDER_CONFIG if set, else default
    config = _PROVIDER_CONFIG or ScreenPilotConfig()
    config.executor.screenshot_after_action = True
    agent = ScreenPilotAgent(config)

    step_logs: list[StepLog] = []
    step_details: list[dict] = []

    def on_step(step: StepResult) -> None:
        ts = time.time() - rec_start
        coords = f"({step.action.x}, {step.action.y})" if step.action.x is not None else ""
        reasoning = step.action.reasoning or ""
        status = "OK" if step.action_result.success else "FAIL"

        step_logs.append(StepLog(
            step.step_number, step.action.action_type.value,
            step.action.target or "", coords, reasoning,
            step.action_result.success, ts,
        ))
        step_details.append({
            "step": step.step_number, "action": step.action.action_type.value,
            "target": step.action.target or "", "coords": coords,
            "reasoning": reasoning[:200], "success": step.action_result.success,
            "timestamp": round(ts, 1),
        })
        print(f"    Step {step.step_number}: {step.action.action_type.value} {coords} [{status}]")

        if step.screenshot_before:
            step.screenshot_before.save(str(output_dir / f"step{step.step_number:02d}_before.png"))
        if step.screenshot_after:
            step.screenshot_after.save(str(output_dir / f"step{step.step_number:02d}_after.png"))

    agent.on_step(on_step)

    start_time = time.time()
    try:
        result = agent.run(challenge.goal, max_steps=challenge.max_steps)
    except Exception as e:
        print(f"    [ERROR] {e}")
        result = TaskResult(goal=challenge.goal, success=False, error=str(e),
                            total_time=time.time() - start_time)

    time.sleep(2)
    stop_recording(recorder)

    # Get cost info from planner
    input_tokens = getattr(agent.planner, "total_input_tokens", 0)
    output_tokens = getattr(agent.planner, "total_output_tokens", 0)
    cost_usd = getattr(agent.planner, "estimated_cost_usd", 0.0)

    # Post-process
    generate_srt(step_logs, srt_path)
    if not postprocess_video(raw_video, srt_path, final_video, speed=speed):
        if raw_video.exists():
            import shutil
            shutil.copy2(raw_video, final_video)

    video_size = final_video.stat().st_size / 1024 if final_video.exists() else 0
    summary = {
        "challenge_id": challenge.id,
        "name": challenge.name + (f" (attempt {attempt})" if attempt > 1 else ""),
        "difficulty": challenge.difficulty,
        "goal": challenge.goal,
        "setup_url": challenge.setup_url,
        "success": result.success,
        "steps": result.num_steps,
        "time": round(result.total_time, 1),
        "error": result.error,
        "video_path": str(final_video),
        "video_size_kb": round(video_size),
        "speed": speed,
        "attempt": attempt,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 4),
        "step_details": step_details,
    }

    status_str = "PASS" if result.success else "FAIL"
    print(f"\n  [{status_str}] {result.num_steps} steps | {result.total_time:.1f}s | Video: {video_size:.0f}KB | Cost: ${cost_usd:.4f}")

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def update_viewer():
    """Regenerate the HTML viewer from all existing summaries."""
    all_results = {}
    for d in sorted(RECORDINGS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text())
            # Use challenge_id + attempt as key to keep all attempts
            key = (data["challenge_id"], data.get("attempt", 1))
            all_results[key] = data
    sorted_results = [all_results[k] for k in sorted(all_results.keys())]
    viewer = generate_viewer(sorted_results, recordings_dir=RECORDINGS_DIR)
    print(f"  Viewer updated: {viewer} ({len(sorted_results)} entries)")

    report_path = RECORDINGS_DIR / "report.json"
    with open(report_path, "w") as f:
        json.dump({"results": sorted_results,
                    "passed": sum(1 for r in sorted_results if r["success"]),
                    "total": len(sorted_results)}, f, indent=2, ensure_ascii=False)


def autonomous_loop(rounds: int = 999, speed: float = 3.0, only_new: bool = False):
    """Main autonomous loop: run → analyze → retry → repeat."""

    # Load existing results to know what's been tried
    existing = {}
    for d in sorted(RECORDINGS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text())
            cid = data["challenge_id"]
            if cid not in existing or data["success"]:
                existing[cid] = data

    all_challenges = VIRAL_CHALLENGES[:]
    # Also include any from challenge_runner not yet tried
    from challenge_runner import CHALLENGES as BASE_CHALLENGES
    all_challenges = BASE_CHALLENGES + VIRAL_CHALLENGES

    round_num = 0
    total_api_calls = 0

    print(f"\n{'#' * 60}")
    print(f"  ScreenPilot Autonomous Challenge Loop")
    print(f"  Max rounds: {rounds} | Speed: {speed}x")
    print(f"  Total challenges available: {len(all_challenges)}")
    print(f"  Already completed: {sum(1 for v in existing.values() if v['success'])}")
    print(f"{'#' * 60}\n")

    while round_num < rounds:
        round_num += 1
        print(f"\n{'━' * 60}")
        print(f"  ROUND {round_num}")
        print(f"{'━' * 60}")

        # Pick challenges to run this round
        # Priority: 1) untried challenges, 2) failed challenges for retry
        untried = [c for c in all_challenges if c.id not in existing]
        failed = [c for c in all_challenges
                  if c.id in existing and not existing[c.id]["success"]
                  and existing[c.id].get("attempt", 1) < 3  # max 3 attempts
                  and analyze_failure(existing[c.id]) != "bot_detected"]  # skip bot-blocked

        if only_new:
            queue = untried
        else:
            # Alternate: 2 new, 1 retry
            queue = []
            u_iter = iter(untried)
            f_iter = iter(failed)
            for _ in range(6):  # up to 6 per round
                try:
                    queue.append(next(u_iter))
                except StopIteration:
                    pass
                try:
                    queue.append(next(u_iter))
                except StopIteration:
                    pass
                try:
                    queue.append(next(f_iter))
                except StopIteration:
                    pass

        if not queue:
            print("  No more challenges to run! All done or max retries reached.")
            break

        # Limit per round
        queue = queue[:6]
        print(f"  Running {len(queue)} challenges this round:")
        for c in queue:
            is_retry = c.id in existing
            tag = f" (retry #{existing[c.id].get('attempt', 1) + 1})" if is_retry else ""
            print(f"    #{c.id} {c.name}{tag} [{c.difficulty}]")

        for challenge in queue:
            attempt = existing.get(challenge.id, {}).get("attempt", 0) + 1

            try:
                summary = run_single_challenge(challenge, speed=speed, attempt=attempt)
                total_api_calls += summary["steps"]

                # Update existing tracker
                existing[challenge.id] = summary

                # Analyze failure
                if not summary["success"]:
                    failure_type = analyze_failure(summary)
                    print(f"  Failure analysis: {failure_type}")

            except Exception as e:
                err_msg = str(e)
                print(f"\n  [FATAL ERROR] {err_msg}")
                if "credit" in err_msg.lower() or "rate" in err_msg.lower() or "quota" in err_msg.lower():
                    print("  API credits likely exhausted. Stopping loop.")
                    update_viewer()
                    return
                if "authentication" in err_msg.lower() or "api_key" in err_msg.lower():
                    print("  API key issue. Stopping loop.")
                    update_viewer()
                    return
                traceback.print_exc()

        # Update viewer after each round
        update_viewer()

        # Stats
        passed = sum(1 for v in existing.values() if v["success"])
        total = len(existing)
        print(f"\n  Round {round_num} complete. Overall: {passed}/{total} passed ({passed/total*100:.0f}%)")
        print(f"  Total API steps so far: {total_api_calls}")

    # Final summary
    update_viewer()
    passed = sum(1 for v in existing.values() if v["success"])
    total = len(existing)
    print(f"\n{'#' * 60}")
    print(f"  LOOP COMPLETE")
    print(f"  Rounds: {round_num} | Passed: {passed}/{total} ({passed/total*100:.0f}%)")
    print(f"  Total API steps: {total_api_calls}")
    print(f"  Viewer: {RECORDINGS_DIR / 'viewer.html'}")
    print(f"{'#' * 60}")


def main():
    parser = argparse.ArgumentParser(description="ScreenPilot Autonomous Challenge Loop")
    parser.add_argument("--rounds", "-r", type=int, default=999,
                        help="Max rounds (default: 999 = until credits run out)")
    parser.add_argument("--speed", "-s", type=float, default=3.0)
    parser.add_argument("--only-new", action="store_true",
                        help="Only run untried challenges, skip retries")
    parser.add_argument("--provider", "-p", default="anthropic",
                        choices=["anthropic", "azure", "gemini", "openai", "vercel", "claude_code"],
                        help="LLM provider (default: anthropic)")
    args = parser.parse_args()

    global _PROVIDER_CONFIG, RECORDINGS_DIR

    if args.provider == "azure":
        llm = LLMConfig(
            provider="azure",
            model="gpt-5",
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "azure-gpt-5"),
            max_tokens=8192,
            temperature=None,
        )
        _PROVIDER_CONFIG = ScreenPilotConfig(llm=llm)
        RECORDINGS_DIR = Path("recordings/azure_gpt5_vision")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Provider: Azure OpenAI GPT-5 (vision)")
    elif args.provider == "gemini":
        llm = LLMConfig(
            provider="gemini",
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            max_tokens=4096,
            temperature=1.0,
        )
        _PROVIDER_CONFIG = ScreenPilotConfig(llm=llm)
        RECORDINGS_DIR = Path(f"recordings/gemini_{llm.model.replace('-', '_')}")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Provider: Google Gemini ({llm.model})")
    elif args.provider == "claude_code":
        cc_model = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
        llm = LLMConfig(
            provider="claude_code",
            model=cc_model,
            max_tokens=4096,
            temperature=0.0,
        )
        _PROVIDER_CONFIG = ScreenPilotConfig(llm=llm)
        RECORDINGS_DIR = Path(f"recordings/claude_code_{cc_model}")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Provider: Claude Code CLI (model={cc_model})")
    elif args.provider == "vercel":
        llm = LLMConfig(
            provider="openai",
            model="anthropic/claude-sonnet-4-5-20250929",
            api_key=os.environ.get("VERCEL_AI_KEY", ""),
            base_url="https://ai-gateway.vercel.sh/v1",
            max_tokens=4096,
            temperature=0.0,
        )
        _PROVIDER_CONFIG = ScreenPilotConfig(llm=llm)
        RECORDINGS_DIR = Path("recordings/vercel_sonnet45")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Provider: Vercel AI Gateway (Claude Sonnet 4.5)")
    elif args.provider == "openai":
        llm = LLMConfig(
            provider="openai",
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            max_tokens=4096,
        )
        _PROVIDER_CONFIG = ScreenPilotConfig(llm=llm)
        RECORDINGS_DIR = Path(f"recordings/openai_{llm.model.replace('-', '_')}")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  Provider: OpenAI ({llm.model})")
    else:
        _PROVIDER_CONFIG = None  # default anthropic
        print(f"  Provider: Anthropic Claude Sonnet 4.5")

    autonomous_loop(rounds=args.rounds, speed=args.speed, only_new=args.only_new)


if __name__ == "__main__":
    main()
