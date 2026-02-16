# ScreenPilot Marketing Copy

## Twitter/X Posts

### Launch Post (Japanese)
```
ScreenPilot をオープンソースで公開しました。

AI (Claude/GPT-4) がスクリーンショットを見て、マウスとキーボードを操作する、次世代のPC自動化ツールです。

- CSSセレクタ不要、どんなアプリでも動作
- 自然言語で指示するだけ
- UI変更に自動適応
- エラー自動回復

https://github.com/pphouse/screenpilot

#AI #RPA #自動化 #オープンソース
```

### Launch Post (English)
```
Introducing ScreenPilot - open source AI desktop automation.

It sees the screen like a human, clicks like a human, but never gets tired.

- Natural language task descriptions
- Works with ANY application
- Self-healing error recovery
- No CSS selectors or scripting needed

Replace your $50K/yr RPA licenses with 3 lines of Python.

https://github.com/pphouse/screenpilot

#AI #RPA #OpenSource #Automation
```

### Technical Post
```
Built an open-source alternative to UiPath/Automation Anywhere using:

- Claude/GPT-4 vision for screen understanding
- Set-of-Mark (SoM) prompting for precise element grounding
- Hierarchical task planning with Task Memory Tree
- Self-healing error recovery
- 156 tests, 7.8K lines of Python

The $30B RPA market is ripe for disruption.

github.com/pphouse/screenpilot
```

### Feature Highlight - Scheduling
```
ScreenPilot now supports cron-like task scheduling.

Set up your daily report generation:

$ screenpilot schedule add daily_report \
  "Daily Report" \
  "Open Excel, generate sales report" \
  --type daily --time 09:00

Unattended automation, no $50K license needed.
```

### Feature Highlight - SDK
```
ScreenPilot Python SDK makes desktop automation a first-class API:

from screenpilot.sdk import ScreenPilotClient

client = ScreenPilotClient("http://localhost:8420")
task = client.run_task("Fill out the customer form")
task.wait()

print(f"Done in {task.current_step} steps")

Integrate desktop automation into your CI/CD pipeline.
```

---

## LinkedIn Post (Japanese)

```
【新プロダクト公開】ScreenPilot - AIデスクトップ自動化ツール

RPA市場は300億ドル以上の規模がありますが、従来のRPAツールには根本的な問題があります：

❌ CSSセレクタやXPathに依存 → UIが変わると壊れる
❌ アプリごとにコネクタが必要
❌ スクリプト作成に数日かかる
❌ 維持コストが高い

ScreenPilotは全く異なるアプローチを取ります：

✅ AIがスクリーンショットを「見て」理解する
✅ どんなアプリケーションでも動作
✅ 自然言語で指示するだけ
✅ UIが変わっても自動適応
✅ エラー時は自動回復

技術的には：
- Set-of-Mark (SoM) プロンプティングで精密なUI要素特定
- 階層的タスクプランニングで複雑なワークフローに対応
- タスクメモリツリーで長期タスクを一貫して実行
- Slack/Teams/メール通知対応

オープンソース（Apache 2.0）で、今すぐ無料で使えます。

GitHub: https://github.com/pphouse/screenpilot

#AI #RPA #自動化 #DX #生産性向上 #オープンソース
```

## LinkedIn Post (English)

```
Excited to announce ScreenPilot - an open-source AI-powered desktop automation tool.

The RPA market is worth $30B+, but traditional tools have a fundamental flaw: they rely on brittle UI selectors that break every time an application updates.

ScreenPilot takes a different approach:
- Uses AI vision (Claude, GPT-4) to understand screenshots
- Works with ANY desktop application - no connectors needed
- Describe tasks in plain English - no scripting required
- Self-healing: adapts to UI changes automatically
- Error recovery with escalating strategies

Key technical innovations:
- Set-of-Mark (SoM) prompting for precise element grounding
- Hierarchical task planning with Task Memory Tree
- Multi-channel notifications (Slack, Teams, email)
- Cron-like scheduling for unattended automation
- Python SDK for CI/CD integration

13 modules, 156 tests, 7.8K lines of code. Apache 2.0 licensed.

Check it out: https://github.com/pphouse/screenpilot

#AI #RPA #Automation #OpenSource #Python #ProductLaunch
```

---

## Hacker News Post

```
Title: Show HN: ScreenPilot – AI desktop automation using vision + LLM (open source)

ScreenPilot uses screenshot analysis and LLMs (Claude, GPT-4) to automate any desktop application. Instead of brittle CSS selectors, it literally looks at the screen and figures out what to click.

Key differentiators from traditional RPA:
- Vision-based: works with any application, no connectors
- Natural language: just describe what you want
- Self-healing: adapts to UI changes automatically
- Set-of-Mark prompting for precise element grounding
- Hierarchical planning with task memory for complex workflows

Built with Python. 13 modules, 156 tests. Apache 2.0.

Quick start:
  pip install screenpilot
  screenpilot run "Open Chrome and search for hello world"

GitHub: https://github.com/pphouse/screenpilot
```

---

## Reddit (r/Python, r/MachineLearning)

```
Title: I built an open-source AI desktop automation tool that uses vision instead of CSS selectors

I got frustrated with traditional RPA tools (UiPath, etc.) that break every time a button moves 5 pixels. So I built ScreenPilot - it uses Claude/GPT-4 vision to actually look at screenshots and determine what to click, type, and scroll.

How it works:
1. Takes a screenshot
2. Sends it to an LLM with Set-of-Mark annotations
3. LLM determines the next action (click, type, scroll, etc.)
4. Executes the action
5. Repeats until done

Features:
- Natural language task descriptions
- Works with ANY app (no selectors, no connectors)
- Self-healing error recovery
- Task scheduling (cron-like)
- Workflow recording & replay
- Python SDK + REST API + Web dashboard
- Slack/Teams/email notifications

13 modules, 156 tests, Apache 2.0 licensed.

pip install screenpilot

https://github.com/pphouse/screenpilot
```

---

## Product Hunt Description

```
Tagline: AI desktop automation that sees the screen like a human

Description:
ScreenPilot uses AI vision + LLM to automate any desktop application. No CSS selectors, no XPath, no scripting - just describe what you want in plain English.

Unlike traditional RPA ($50K+ licenses, brittle selectors), ScreenPilot actually looks at the screen and adapts to UI changes automatically.

Key Features:
🔍 Vision-based UI understanding (Claude, GPT-4)
🎯 Set-of-Mark prompting for precise element grounding
🧠 Hierarchical task planning with memory
🔄 Self-healing error recovery
📅 Cron-like task scheduling
📊 Execution reports & analytics
🔌 Plugin system for extensibility
📱 Slack/Teams/email notifications

Open source. Free forever. Apache 2.0.
```
