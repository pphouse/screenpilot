# ScreenPilot

[![GitHub Release](https://img.shields.io/github/v/release/pphouse/screenpilot)](https://github.com/pphouse/screenpilot/releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-156%20passing-brightgreen.svg)](tests/)

**AI-powered desktop automation using vision + LLM. A smarter alternative to traditional RPA.**

> **[Landing Page](https://pphouse.github.io/screenpilot/)** | **[Release Notes](https://github.com/pphouse/screenpilot/releases)** | **[Discussions](https://github.com/pphouse/screenpilot/discussions)**

ScreenPilot uses screenshot analysis and large language models to automate any desktop application — no brittle CSS selectors, no XPath, no accessibility APIs required. Just describe what you want to do in plain English.

## Why ScreenPilot?

Traditional RPA tools (UiPath, Automation Anywhere, etc.) rely on fragile UI selectors that break when applications update. ScreenPilot takes a fundamentally different approach:

| Feature | Traditional RPA | ScreenPilot |
|---------|----------------|-------------|
| Element Finding | CSS/XPath selectors | Vision-based (screenshots + LLM) |
| Resilience | Breaks on UI changes | Adapts automatically |
| Setup Complexity | Days of scripting | Minutes of natural language |
| Application Support | Needs connectors | Works with any application |
| Maintenance | High (selector updates) | Low (vision adapts) |

## Key Features

- **Natural Language Tasks**: Describe tasks in plain English — "Open Chrome and search for Python tutorials"
- **Vision-Based UI Understanding**: Uses LLM vision APIs to understand any screen, any application
- **Set-of-Mark (SoM) Prompting**: Overlays numbered markers on screenshots for precise element grounding
- **Hierarchical Planning**: Two-level task decomposition (high-level strategy + step execution) for complex workflows
- **Task Memory Tree**: Structured memory for coherent long-horizon task execution
- **Multi-LLM Support**: Works with Anthropic Claude, OpenAI GPT-4, or any LiteLLM-compatible model
- **Workflow Templates**: Pre-built templates for common business tasks (form filling, data extraction, etc.)
- **Workflow Recording**: Record human workflows, replay them intelligently with vision-based adaptation
- **Error Recovery & Self-Healing**: Automatic retry with escalating strategies (relocate, scroll, dismiss dialogs, LLM recovery)
- **Task Scheduling**: Cron-like scheduling for unattended automation (daily, weekly, interval, cron expression)
- **Execution Reports**: JSON and HTML reports with KPIs for business stakeholders
- **Python SDK**: Clean programmatic client for integration into existing applications and CI/CD pipelines
- **REST API + Web Dashboard**: Real-time monitoring, live screenshots, template browser via WebSocket
- **Cross-Platform**: Works on Linux, macOS, and Windows
- **Safety First**: Failsafe mode, action logging, confirmation for destructive actions

## Quick Start

### Installation

```bash
pip install screenpilot
```

Or from source:

```bash
git clone https://github.com/pphouse/screenpilot.git
cd screenpilot
pip install -e .
```

### Set up your API key

```bash
# For Anthropic Claude (default)
export ANTHROPIC_API_KEY=your-key-here

# For OpenAI
export OPENAI_API_KEY=your-key-here
```

### Run a task

```bash
# Natural language automation
screenpilot run "Open the file manager and create a new folder called 'Reports'"

# Take and analyze a screenshot
screenpilot screenshot

# Find a specific UI element
screenpilot find "the search bar"

# Start the API server
screenpilot serve --port 8420
```

### Record and replay workflows

```bash
# Record a workflow (Ctrl+C to stop)
screenpilot record "login-flow" -d "Login to the application"

# Replay with vision-based adaptation
screenpilot replay ~/.screenpilot/recordings/login-flow/workflow.json

# Replay at 2x speed without adaptation
screenpilot replay workflow.json --speed 2.0 --exact
```

## Python API

```python
from screenpilot import ScreenPilotAgent
from screenpilot.config import ScreenPilotConfig, LLMConfig

# Configure
config = ScreenPilotConfig(
    llm=LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
    )
)

# Create agent and run
agent = ScreenPilotAgent(config)
result = agent.run("Open Chrome and navigate to github.com")

print(f"Success: {result.success}")
print(f"Steps: {result.num_steps}")
print(f"Time: {result.total_time:.1f}s")
```

### REST API

```bash
# Start server
screenpilot serve

# Take screenshot
curl -X POST http://localhost:8420/screenshot

# Run a task
curl -X POST http://localhost:8420/task \
  -H "Content-Type: application/json" \
  -d '{"goal": "Open calculator and compute 42 * 17"}'

# Find element
curl -X POST http://localhost:8420/find \
  -H "Content-Type: application/json" \
  -d '{"target": "the save button"}'

# Execute single action
curl -X POST http://localhost:8420/action \
  -H "Content-Type: application/json" \
  -d '{"action_type": "click", "x": 500, "y": 300}'
```

### Python SDK

```bash
pip install screenpilot[sdk]
```

```python
from screenpilot.sdk import ScreenPilotClient

client = ScreenPilotClient("http://localhost:8420")

# Run a task and wait for completion
task = client.run_task("Open Chrome and search for 'hello'")
task.wait(timeout=120)
print(f"Success: {task.success}, Steps: {task.current_step}")

# Direct actions
client.click(500, 300)
client.type_text("Hello World")
client.press_key("enter")
client.find_and_click("the search button")

# Use workflow templates
templates = client.list_templates()
task = client.run_template("web_form_fill", {
    "url": "https://example.com/form",
    "form_data": "name=John, email=john@example.com",
})
```

### Task Scheduling

```python
from screenpilot.scheduler import TaskScheduler, ScheduledTask

scheduler = TaskScheduler(persist_path="~/.screenpilot/schedules.json")

# Run daily at 9 AM
scheduler.add(ScheduledTask(
    id="daily_report",
    name="Generate Daily Report",
    goal="Open Excel, generate sales report, save as PDF",
    schedule_type="daily",
    time_of_day="09:00",
))

# Run every 2 hours
scheduler.add(ScheduledTask(
    id="health_check",
    name="App Health Check",
    goal="Open monitoring dashboard, check all services are green",
    schedule_type="interval",
    interval_seconds=7200,
))

scheduler.start()
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    ScreenPilot Agent                      │
│                                                           │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │  Screen   │  │  Hierarchical│  │    Action          │   │
│  │ Capture   │─▶│  Planner +   │─▶│   Executor         │   │
│  │  (mss)    │  │  Task Memory │  │  (pyautogui)       │   │
│  └──────────┘  └──────────────┘  └───────────────────┘   │
│       │              │                    │               │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │  Vision   │  │  SoM     │  │  Error Recovery       │   │
│  │ Analyzer  │  │ Prompting│  │  & Self-Healing       │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│       │              │                    │               │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ Workflow  │  │ Template │  │  Scheduler + Reports  │   │
│  │ Recorder  │  │ Registry │  │  + REST API + SDK     │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**Core Loop:**
1. Capture screenshot of current screen
2. Send screenshot + goal to LLM planner
3. LLM analyzes screen and determines next action
4. Execute action (click, type, scroll, etc.)
5. Capture new screenshot and repeat until done

## Configuration

Create `~/.screenpilot/config.json`:

```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "temperature": 0.0
  },
  "capture": {
    "monitor": 0,
    "max_width": 1920,
    "max_height": 1080
  },
  "executor": {
    "click_delay": 0.1,
    "type_delay": 0.02,
    "safe_mode": true
  },
  "recorder": {
    "save_dir": "~/.screenpilot/recordings"
  },
  "verbose": false
}
```

## Use Cases

### Business Process Automation
Automate repetitive tasks across any desktop application — data entry, form filling, report generation, file management.

### QA Testing
Create visual test scripts that adapt to UI changes. No more brittle selectors breaking your test suite.

### Legacy System Integration
Bridge modern systems with legacy applications that lack APIs. ScreenPilot can interact with any GUI.

### Customer Support
Build automated workflows for common support tasks across multiple applications.

## Safety

- **Failsafe**: Move mouse to any screen corner to immediately abort
- **Safe Mode**: Confirm before destructive actions (delete, close, etc.)
- **Action Logging**: Complete audit trail of all executed actions
- **Max Steps**: Configurable step limit prevents runaway automation

## Development

```bash
git clone https://github.com/pphouse/screenpilot.git
cd screenpilot
pip install -e ".[dev]"
pytest
```

## License

Apache License 2.0
