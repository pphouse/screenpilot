#!/usr/bin/env python3
"""
lisa_copilot.py — Human-Agent コパイロット制御サーバー
=====================================================
同じ画面 (DISPLAY :99) でエージェントと人間が共存。
- エージェントはオートパイロットでタスクを実行
- 認証や問題が起きたら自動で一時停止 → 人間がVNCで操作
- 人間が「再開」ボタンを押したらエージェント復帰

Usage:
    python3 examples/lisa_copilot.py
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, request, render_template_string

# ============================================================================
# 設定
# ============================================================================

JST = timezone(timedelta(hours=9))
STATE_DIR = Path(__file__).parent
PAUSE_FILE = STATE_DIR / ".copilot_paused"
LOG_FILE = "/tmp/lisa_copilot.log"
BOT_LOG = "/tmp/lisa_growth.log"
LLM_STREAM_FILE = Path("/tmp/lisa_llm_stream.jsonl")

# ============================================================================
# Flask アプリ
# ============================================================================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# グローバル状態
copilot_state = {
    "paused": False,
    "pause_reason": "",
    "agent_status": "idle",
    "last_task": "",
    "log_lines": [],
}


def is_paused():
    return PAUSE_FILE.exists()


def set_paused(reason="manual"):
    PAUSE_FILE.write_text(reason)
    copilot_state["paused"] = True
    copilot_state["pause_reason"] = reason
    add_log(f"⏸ 一時停止: {reason}")


def set_resumed():
    PAUSE_FILE.unlink(missing_ok=True)
    copilot_state["paused"] = False
    copilot_state["pause_reason"] = ""
    add_log("▶ 再開")


def add_log(msg):
    now = datetime.now(JST).strftime("%H:%M:%S")
    line = f"[{now}] {msg}"
    copilot_state["log_lines"].append(line)
    # 最新100行のみ保持
    copilot_state["log_lines"] = copilot_state["log_lines"][-100:]


# ============================================================================
# HTML テンプレート
# ============================================================================

COPILOT_HTML = r"""
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>lisa copilot</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0d1117; color: #c9d1d9; font-family: -apple-system, 'Segoe UI', sans-serif; }

  .layout {
    display: grid;
    grid-template-columns: 1fr 400px;
    grid-template-rows: 48px 1fr;
    height: 100vh;
    gap: 0;
  }

  /* Header */
  .header {
    grid-column: 1 / -1;
    background: #161b22;
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 16px;
  }
  .header h1 { font-size: 16px; font-weight: 600; }
  .status-badge {
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }
  .status-running { background: #238636; color: #fff; }
  .status-paused { background: #d29922; color: #000; }
  .status-idle { background: #484f58; color: #c9d1d9; }

  /* VNC Panel */
  .vnc-panel {
    background: #000;
    position: relative;
    overflow: hidden;
  }
  .vnc-panel iframe {
    width: 100%;
    height: 100%;
    border: none;
  }

  /* Control Panel */
  .control-panel {
    background: #161b22;
    border-left: 1px solid #30363d;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .controls {
    padding: 16px;
    border-bottom: 1px solid #30363d;
  }
  .controls h2 { font-size: 14px; margin-bottom: 12px; color: #8b949e; }

  .btn-group { display: flex; gap: 8px; margin-bottom: 12px; }
  .btn {
    flex: 1;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn:hover { filter: brightness(1.1); }
  .btn:active { transform: scale(0.97); }
  .btn-pause { background: #d29922; color: #000; }
  .btn-resume { background: #238636; color: #fff; }
  .btn-task { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }
  .btn-task:hover { background: #30363d; }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .pause-reason {
    background: #0d1117;
    border: 1px solid #d29922;
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 12px;
    font-size: 13px;
    color: #d29922;
    display: none;
  }
  .pause-reason.active { display: block; }

  .task-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin-bottom: 8px;
  }

  /* Tabs */
  .tab-bar {
    display: flex;
    border-bottom: 1px solid #30363d;
    background: #161b22;
  }
  .tab-btn {
    flex: 1;
    padding: 8px 12px;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #8b949e;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  .tab-btn:hover { color: #c9d1d9; }
  .tab-btn.active {
    color: #58a6ff;
    border-bottom-color: #58a6ff;
  }
  .tab-content {
    display: none;
    flex: 1;
    overflow-y: auto;
    padding: 8px 16px;
  }
  .tab-content.active { display: block; }

  /* Log */
  .log-line {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 11px;
    line-height: 1.6;
    color: #8b949e;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .log-line.info { color: #58a6ff; }
  .log-line.warn { color: #d29922; }
  .log-line.error { color: #f85149; }
  .log-line.success { color: #3fb950; }

  /* LLM思考 */
  .llm-block {
    margin-bottom: 12px;
    border-radius: 6px;
    overflow: hidden;
  }
  .llm-context {
    background: #1c2333;
    border-left: 3px solid #58a6ff;
    padding: 8px 12px;
    font-size: 12px;
    color: #58a6ff;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .llm-reasoning {
    background: #1a1e2a;
    border-left: 3px solid #a371f7;
    padding: 8px 12px;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 11px;
    line-height: 1.5;
    color: #a371f7;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .llm-content {
    background: #162312;
    border-left: 3px solid #3fb950;
    padding: 8px 12px;
    font-size: 13px;
    line-height: 1.5;
    color: #3fb950;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .llm-status {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 11px;
    color: #8b949e;
    padding: 4px 0;
  }
  .llm-status.done { color: #3fb950; }
  .llm-status.error { color: #f85149; }
  .llm-cursor {
    display: inline-block;
    width: 2px;
    height: 14px;
    background: #3fb950;
    animation: blink 0.8s infinite;
    vertical-align: text-bottom;
    margin-left: 2px;
  }
  @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
</style>
</head>
<body>

<div class="layout">
  <!-- Header -->
  <div class="header">
    <h1>lisa copilot</h1>
    <span id="statusBadge" class="status-badge status-idle">IDLE</span>
    <span id="agentStatus" style="font-size:13px;color:#8b949e;"></span>
  </div>

  <!-- VNC -->
  <div class="vnc-panel">
    <iframe id="vncFrame" src="/vnc/vnc_lite.html?autoconnect=true&path=websockify&resize=scale&reconnect=true&reconnect_delay=1000"></iframe>
  </div>

  <!-- Control Panel -->
  <div class="control-panel">
    <div class="controls">
      <h2>CONTROL</h2>

      <div class="btn-group">
        <button id="btnPause" class="btn btn-pause" onclick="doPause()">⏸ 一時停止</button>
        <button id="btnResume" class="btn btn-resume" onclick="doResume()" disabled>▶ 再開</button>
      </div>

      <div id="pauseReason" class="pause-reason"></div>

      <h2>TASKS</h2>
      <div class="task-grid">
        <button class="btn btn-task" onclick="runTask('x_reply_viral')">💬 バズリプ</button>
        <button class="btn btn-task" onclick="runTask('x_tweet')">📝 ツイート</button>
        <button class="btn btn-task" onclick="runTask('x_like')">❤️ いいね</button>
        <button class="btn btn-task" onclick="runTask('x_follow')">👤 フォロー</button>
        <button class="btn btn-task" onclick="runTask('x_reply_lonely')">💬 寂しがり</button>
        <button class="btn btn-task" onclick="runTask('x_patrol')">🛡️ パトロール</button>
        <button class="btn btn-task" onclick="runTask('x_quote_viral')">🔄 引用RT</button>
        <button class="btn btn-task" onclick="runTask('room_like')">🏠 ROOM</button>
      </div>
    </div>

    <!-- Tab bar -->
    <div class="tab-bar">
      <button class="tab-btn active" onclick="switchTab('log')">📋 LOG</button>
      <button class="tab-btn" onclick="switchTab('llm')">🧠 LLM思考</button>
    </div>

    <!-- Log tab -->
    <div id="tabLog" class="tab-content active">
      <div id="logContainer"></div>
    </div>

    <!-- LLM思考 tab -->
    <div id="tabLlm" class="tab-content">
      <div id="llmContainer"></div>
    </div>
  </div>
</div>

<script>
// ── Tab switching ──
function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  if (tab === 'log') {
    document.querySelectorAll('.tab-btn')[0].classList.add('active');
    document.getElementById('tabLog').classList.add('active');
  } else {
    document.querySelectorAll('.tab-btn')[1].classList.add('active');
    document.getElementById('tabLlm').classList.add('active');
  }
}

// ── API helper ──
function api(method, path, body) {
  return fetch(path, {
    method: method,
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined
  }).then(r => {
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) return {};
    return r.json();
  });
}

function doPause() {
  api('POST', '/api/pause', {reason: '手動で一時停止'});
}

function doResume() {
  api('POST', '/api/resume');
}

function runTask(task) {
  api('POST', '/api/run_task', {task: task});
}

// ── Poll status (LOG tab) ──
function poll() {
  api('GET', '/api/status').then(data => {
    const badge = document.getElementById('statusBadge');
    const agentEl = document.getElementById('agentStatus');

    if (data.paused) {
      badge.className = 'status-badge status-paused';
      badge.textContent = 'PAUSED';
      document.getElementById('btnPause').disabled = true;
      document.getElementById('btnResume').disabled = false;
    } else if (data.agent_status !== 'idle') {
      badge.className = 'status-badge status-running';
      badge.textContent = 'RUNNING';
      document.getElementById('btnPause').disabled = false;
      document.getElementById('btnResume').disabled = true;
    } else {
      badge.className = 'status-badge status-idle';
      badge.textContent = 'IDLE';
      document.getElementById('btnPause').disabled = false;
      document.getElementById('btnResume').disabled = true;
    }

    agentEl.textContent = data.agent_status !== 'idle' ? data.agent_status : '';

    const pr = document.getElementById('pauseReason');
    if (data.paused && data.pause_reason) {
      pr.textContent = '⚠️ ' + data.pause_reason;
      pr.classList.add('active');
    } else {
      pr.classList.remove('active');
    }

    const container = document.getElementById('logContainer');
    container.innerHTML = data.log_lines.slice(-50).map(line => {
      let cls = 'log-line';
      if (line.includes('成功') || line.includes('▶')) cls += ' success';
      else if (line.includes('失敗') || line.includes('エラー')) cls += ' error';
      else if (line.includes('⏸') || line.includes('WARNING')) cls += ' warn';
      else if (line.includes('INFO')) cls += ' info';
      return `<div class="${cls}">${line}</div>`;
    }).join('');
    container.scrollTop = container.scrollHeight;
  }).catch(() => {});
}

setInterval(poll, 2000);
poll();

// ── LLM思考 ポーリング ──
const llmContainer = document.getElementById('llmContainer');
const llmTab = document.getElementById('tabLlm');
let currentBlock = null;
let reasoningEl = null;
let contentEl = null;
let llmOffset = 0;

function scrollLlm() {
  llmTab.scrollTop = llmTab.scrollHeight;
}

function pollLlm() {
  fetch('/api/llm_events?offset=' + llmOffset)
    .then(r => {
      const ct = r.headers.get('content-type') || '';
      if (!ct.includes('application/json')) return null;
      return r.json();
    })
    .then(data => {
      if (!data) return;
      if (data.events && data.events.length > 0) {
        data.events.forEach(ev => handleLlmEvent(ev));
      }
      llmOffset = data.offset || llmOffset;
    })
    .catch(e => { console.log('LLM poll error:', e); });
}

function handleLlmEvent(ev) {
  const type = ev.type;
  const data = ev.data;
  const ts = ev.ts || '';

  switch(type) {
    case 'context':
      currentBlock = document.createElement('div');
      currentBlock.className = 'llm-block';

      const ctxEl = document.createElement('div');
      ctxEl.className = 'llm-context';
      ctxEl.textContent = `[${ts}] ${data}`;
      currentBlock.appendChild(ctxEl);

      reasoningEl = null;
      contentEl = null;
      llmContainer.appendChild(currentBlock);
      scrollLlm();
      break;

    case 'prompt':
    case 'thinking':
      if (currentBlock) {
        const st = document.createElement('div');
        st.className = 'llm-status';
        st.textContent = `[${ts}] ${data}`;
        currentBlock.appendChild(st);
        scrollLlm();
      }
      break;

    case 'reasoning':
      if (currentBlock && !reasoningEl) {
        reasoningEl = document.createElement('div');
        reasoningEl.className = 'llm-reasoning';
        const label = document.createElement('div');
        label.style.cssText = 'font-weight:600;margin-bottom:4px;font-size:12px;color:#a371f7;';
        label.textContent = '💭 思考過程';
        reasoningEl.appendChild(label);
        currentBlock.appendChild(reasoningEl);
      }
      if (reasoningEl) {
        const cursor = reasoningEl.querySelector('.llm-cursor');
        if (cursor) cursor.remove();
        reasoningEl.appendChild(document.createTextNode(data));
        const c = document.createElement('span');
        c.className = 'llm-cursor';
        reasoningEl.appendChild(c);
        scrollLlm();
      }
      break;

    case 'reasoning_done':
      if (reasoningEl) {
        const cursor = reasoningEl.querySelector('.llm-cursor');
        if (cursor) cursor.remove();
      }
      if (currentBlock) {
        const st = document.createElement('div');
        st.className = 'llm-status';
        st.textContent = `[${ts}] ${data}`;
        currentBlock.appendChild(st);
      }
      break;

    case 'content_token':
      if (currentBlock && !contentEl) {
        contentEl = document.createElement('div');
        contentEl.className = 'llm-content';
        const label = document.createElement('div');
        label.style.cssText = 'font-weight:600;margin-bottom:4px;font-size:12px;color:#3fb950;';
        label.textContent = '✏️ 生成テキスト';
        contentEl.appendChild(label);
        currentBlock.appendChild(contentEl);
      }
      if (contentEl) {
        const cursor = contentEl.querySelector('.llm-cursor');
        if (cursor) cursor.remove();
        contentEl.appendChild(document.createTextNode(data));
        const c = document.createElement('span');
        c.className = 'llm-cursor';
        contentEl.appendChild(c);
        scrollLlm();
      }
      break;

    case 'done':
      if (contentEl) {
        const cursor = contentEl.querySelector('.llm-cursor');
        if (cursor) cursor.remove();
      }
      if (currentBlock) {
        const st = document.createElement('div');
        st.className = 'llm-status done';
        st.textContent = `[${ts}] ${data}`;
        currentBlock.appendChild(st);
        scrollLlm();
      }
      currentBlock = null;
      reasoningEl = null;
      contentEl = null;
      break;

    case 'error':
      if (currentBlock) {
        const st = document.createElement('div');
        st.className = 'llm-status error';
        st.textContent = `[${ts}] ${data}`;
        currentBlock.appendChild(st);
      }
      break;
  }
}

// 500msごとにポーリング
setInterval(pollLlm, 500);
pollLlm();
</script>
</body>
</html>
"""


# ============================================================================
# API エンドポイント
# ============================================================================

@app.route("/")
def index():
    return render_template_string(COPILOT_HTML)


@app.route("/api/status")
def api_status():
    # bot ログの最新行を取得
    try:
        with open(BOT_LOG) as f:
            lines = f.readlines()
        recent = [l.strip() for l in lines[-30:] if l.strip()]
        # agent_status を最新のログから推測
        for line in reversed(recent):
            if "タスク開始" in line:
                task_name = line.split("タスク開始: ")[-1].strip()
                copilot_state["agent_status"] = f"実行中: {task_name}"
                break
            elif "タスク完了" in line:
                copilot_state["agent_status"] = "idle"
                break
        # ログ行を追加 (重複回避)
        for line in recent:
            if line not in copilot_state["log_lines"][-30:]:
                copilot_state["log_lines"].append(line)
        copilot_state["log_lines"] = copilot_state["log_lines"][-100:]
    except FileNotFoundError:
        pass

    copilot_state["paused"] = is_paused()
    if copilot_state["paused"]:
        try:
            copilot_state["pause_reason"] = PAUSE_FILE.read_text()
        except Exception:
            pass

    return jsonify(copilot_state)


@app.route("/api/pause", methods=["POST"])
def api_pause():
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "手動で一時停止")
    set_paused(reason)
    return jsonify({"ok": True, "paused": True})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    set_resumed()
    return jsonify({"ok": True, "paused": False})


@app.route("/api/run_task", methods=["POST"])
def api_run_task():
    data = request.get_json(silent=True) or {}
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "no task"}), 400

    count_map = {
        "x_reply_viral": 2,
        "x_reply_lonely": 3,
        "x_patrol": 3,
        "x_tweet": 1,
        "x_like": 5,
        "x_follow": 3,
        "x_quote_viral": 1,
        "room_like": 5,
        "room_collect": 1,
    }
    count = count_map.get(task, 1)

    add_log(f"🚀 タスク実行開始: {task} (count={count})")
    copilot_state["agent_status"] = f"実行中: {task}"

    def run():
        try:
            cmd = [
                sys.executable,
                str(STATE_DIR / "lisa_growth_bot.py"),
                "--task", task,
                "--count", str(count),
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(STATE_DIR),
            )
            for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    copilot_state["log_lines"].append(text)
                    copilot_state["log_lines"] = copilot_state["log_lines"][-100:]
                    # 認証・CAPTCHAなど問題検知 → 自動一時停止
                    if any(kw in text for kw in [
                        "ログイン失敗", "CAPTCHA", "captcha", "認証",
                        "suspended", "locked", "verify",
                    ]):
                        set_paused(f"🔐 認証が必要: {text[:80]}")
            proc.wait()
            add_log(f"✅ タスク完了: {task}")
        except Exception as e:
            add_log(f"❌ タスクエラー: {task} — {e}")
        finally:
            copilot_state["agent_status"] = "idle"

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "task": task})


# ============================================================================
# LLM ストリーム SSE
# ============================================================================

@app.route("/api/llm_events")
def api_llm_events():
    """ポーリング: /tmp/lisa_llm_stream.jsonl から offset 以降の行を返す"""
    offset = request.args.get("offset", 0, type=int)

    if not LLM_STREAM_FILE.exists():
        return jsonify({"events": [], "offset": 0})

    try:
        with open(LLM_STREAM_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return jsonify({"events": [], "offset": offset})

    events = []
    for line in lines[offset:]:
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return jsonify({"events": events, "offset": len(lines)})


@app.route("/api/llm_clear", methods=["POST"])
def api_llm_clear():
    """LLMストリームファイルをクリア"""
    LLM_STREAM_FILE.write_text("")
    return jsonify({"ok": True})


# ============================================================================
# メイン
# ============================================================================

if __name__ == "__main__":
    # 初期状態クリア
    PAUSE_FILE.unlink(missing_ok=True)
    add_log("🤖 lisa copilot 起動")

    print("lisa copilot 起動")
    print("  コントロールパネル: http://localhost:5000")
    print("  ngrok経由: https://<ngrok-url>/")
    app.run(host="0.0.0.0", port=5000, debug=False)
