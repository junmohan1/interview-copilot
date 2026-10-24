let pin = '';
let ws;
let chatHistory = [];
let currentSessionId = null;
let streamingEl = null;
let currentStrategies = null;
let currentEditingFile = "";
let activeAnswers = {}; 

async function init() {
  try {
    const res = await fetch('/api/pin');
    const data = await res.json();
    pin = data.pin;
    document.getElementById('pinDisplay').textContent = 'PIN: ' + pin;
  } catch (e) {
    console.error('获取 PIN 失败', e);
  }
  await loadSources();
  await loadStrategies(); // 初始化加载策略卡
  connect();
}

function connect() {
  const url = `ws://${location.host}/ws?role=desktop&pin=${pin}`;
  ws = new WebSocket(url);
  ws.onopen = () => {
    console.log('[WS] 已连接');
    ws.send(JSON.stringify({ type: 'list_history' }));
  };
  ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 2000);
}

function handleMessage(data) {
  switch (data.type) {
    // ======== 多面板面试相关 ========
    case 'new_question':
      createNewAnswerBlock(data.task_id, data.text, data.strategy);
      break;
    case 'thinking_chunk':
      if (activeAnswers[data.task_id]) {
        updateThinking(activeAnswers[data.task_id], data.text);
      }
      break;
    case 'answer_chunk':
      if (activeAnswers[data.task_id]) {
        updateAnswer(activeAnswers[data.task_id], data.text);
      }
      break;
    case 'answer_done':
      if (activeAnswers[data.task_id]) {
        const t = activeAnswers[data.task_id];
        t._done = true;
        if (t._timeout) clearTimeout(t._timeout);
        finalizeAnswer(t);
      }
      break;
    case 'answer_cancelled':
      if (activeAnswers[data.task_id]) {
        const t = activeAnswers[data.task_id];
        t._done = true;
        if (t._timeout) clearTimeout(t._timeout);
        t.answerEl.textContent = '⛔ 已取消（并发过多）';
        t.answerEl.style.color = '#c00';
      }
      break;
    case 'answer_error':
      if (activeAnswers[data.task_id]) {
        const t = activeAnswers[data.task_id];
        t._done = true;
        if (t._timeout) clearTimeout(t._timeout);
        updateAnswer(t, '⚠ ' + data.message);
      }
      break;

    // ======== 中间聊天区讨论相关 ========
    case 'discuss_thinking_chunk': {
      if (!streamingEl) break;
      const bubble = streamingEl.querySelector('.bubble');
      let thinkBlock = bubble.querySelector('.thinking-block');
      if (!thinkBlock) {
        thinkBlock = document.createElement('div');
        thinkBlock.className = 'thinking-block';
        thinkBlock.innerHTML = `
          <div class="thinking-header" onclick="this.parentElement.classList.toggle('collapsed')">
            <span>🧠 思考过程（点击折叠/展开）</span>
            <span class="arrow">▼</span>
          </div>
          <div class="thinking-body"></div>
        `;
        bubble.insertBefore(thinkBlock, bubble.firstChild);
      }
      thinkBlock.querySelector('.thinking-body').textContent = data.text;
      thinkBlock.querySelector('.thinking-body').scrollTop = 999999;
      document.getElementById('chatMessages').scrollTop = 999999;
      break;
    }
    case 'discuss_chunk': {
      if (!streamingEl) break;
      const bubble = streamingEl.querySelector('.bubble');
      let contentEl = bubble.querySelector('.content-text');
      if (!contentEl) {
        contentEl = document.createElement('div');
        contentEl.className = 'content-text';
        bubble.appendChild(contentEl);
      }
      contentEl.textContent = data.text;
      document.getElementById('chatMessages').scrollTop = 999999;
      break;
    }
    case 'discuss_done':
      finalizeStreamingBubble();
      break;
    case 'discuss_error':
      if (streamingEl) {
        streamingEl.querySelector('.bubble').textContent = '⚠ ' + data.message;
      }
      finalizeStreamingBubble();
      break;

    // ======== 其他状态 ========
    case 'my_speech':
      appendTranscript(data.text.includes('[面试官]') || data.text.includes('[识别]') ? 'interviewer' : 'me', data.text);
      break;
    case 'history_list':
      renderHistoryList(data.sessions);
      break;
    case 'history_loaded':
      renderChatHistory(data.messages);
      break;
    case 'kb_updated':
      loadSources();
      break;
    case 'strategy_updated':
      loadStrategies();
      break;
    case 'pregenerate_started': {
      const btn = document.getElementById('warmupBtn');
      if (btn) { btn.textContent = '预热中...'; btn.disabled = true; }
      break;
    }
    case 'pregenerate_done': {
      const btn2 = document.getElementById('warmupBtn');
      if (btn2) {
        btn2.textContent = data.status === 'success' ? '✅ 预热成功' : '❌ 预热失败';
        setTimeout(() => { btn2.textContent = '⚡ 预热面试缓存'; btn2.disabled = false; }, 3000);
      }
      break;
    }
  }
}

// ======== 多面板操作逻辑 ========
function createNewAnswerBlock(taskId, question, strategy) {
  const container = document.getElementById('answersContainer');
  const hint = container.querySelector('.hint');
  if (hint) hint.style.display = 'none';

  const panel = document.createElement('div');
  panel.className = 'answer-panel';
  panel.innerHTML = `
    <div class="question-title"></div>
    <div class="strategy-tag ${strategy}">${strategy}</div>
    <div class="thinking-box collapsed" style="display:none">
      <div class="thinking-header" onclick="this.parentElement.classList.toggle('collapsed')">🧠 思考中…</div>
      <div class="thinking-content"></div>
    </div>
    <div class="answer-text" style="color:#888;">等待生成...</div>
  `;
  panel.querySelector('.question-title').textContent = '面试官：' + question;
  container.appendChild(panel);
  container.scrollTop = container.scrollHeight;

  const task = {
    panel: panel,
    thinkEl: panel.querySelector('.thinking-content'),
    thinkBox: panel.querySelector('.thinking-box'),
    answerEl: panel.querySelector('.answer-text'),
    _done: false,
    _timeout: null
  };
  activeAnswers[taskId] = task;

  // 兜底超时：120 秒还没结束就标记超时，避免面板永久卡在“生成中”
  task._timeout = setTimeout(() => {
    if (!task._done) {
      task.answerEl.textContent = '⏱ 生成超时，请重试';
      task.answerEl.style.color = '#c00';
      task._done = true;
    }
  }, 120000);
}

function updateThinking(taskObj, text) {
  taskObj.thinkBox.style.display = 'block';
  taskObj.thinkEl.textContent = text;
}

function updateAnswer(taskObj, text) {
  taskObj.answerEl.textContent = text;
  taskObj.answerEl.style.color = '#333'; 
  // 只有当用户原本就在底部附近（100px 内）时才自动滚动，避免多任务并发时被强行拽到底部
  const container = document.getElementById('answersContainer');
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 100) {
    container.scrollTop = container.scrollHeight;
  }
}

function finalizeAnswer(taskObj) {
  const header = taskObj.thinkBox.querySelector('.thinking-header');
  if (header) header.textContent = '🧠 已完成思考（点击展开）';
}

// ======== 对话与历史 ========
function sendChat() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;

  appendChatMessage('user', text);
  chatHistory.push({ role: 'user', content: text });

  ws.send(JSON.stringify({ type: 'discuss', text: text, history: chatHistory.slice(-10) }));
  input.value = '';
  input.style.height = 'auto';
  streamingEl = appendChatMessage('ai', '', true);
}

function appendChatMessage(role, text, isStreaming = false) {
  const container = document.getElementById('chatMessages');
  const welcome = container.querySelector('.welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.innerHTML = `<div class="avatar">${role === 'user' ? '我' : 'AI'}</div><div class="bubble"></div>`;
  div.querySelector('.bubble').textContent = text;
  if (isStreaming) div.dataset.streaming = '1';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function finalizeStreamingBubble() {
  if (streamingEl) {
    delete streamingEl.dataset.streaming;
    const bubble = streamingEl.querySelector('.bubble');
    const contentEl = bubble.querySelector('.content-text');
    const thinkBody = bubble.querySelector('.thinking-body');
    chatHistory.push({
      role: 'assistant',
      content: contentEl ? contentEl.textContent : '',
      thinking: thinkBody ? thinkBody.textContent : ''
    });
    streamingEl = null;
  }
}

function renderChatHistory(messages) {
  const container = document.getElementById('chatMessages');
  const ansContainer = document.getElementById('answersContainer');
  container.innerHTML = '';
  ansContainer.innerHTML = '<div class="hint" style="text-align:center; margin-top:20px;">面试问答将显示在这里...</div>';
  activeAnswers = {};
  chatHistory = [];

  // 兼容老数据：没有 scene 字段时按 role 推断
  const getScene = (m) => {
    if (m.scene) return m.scene;
    return (m.role === 'user' || m.role === 'assistant') ? 'prepare' : 'interview';
  };

  let lastPanelTaskId = null;

  messages.forEach(m => {
    const scene = getScene(m);

    // ===== 准备模式讨论 → 中间聊天区 =====
    if (scene === 'prepare' && (m.role === 'user' || m.role === 'assistant')) {
      const role = m.role === 'user' ? 'user' : 'ai';
      const div = appendChatMessage(role, '');
      const bubble = div.querySelector('.bubble');

      if (m.thinking) {
        const thinkBlock = document.createElement('div');
        thinkBlock.className = 'thinking-block collapsed';
        thinkBlock.innerHTML = `
          <div class="thinking-header" onclick="this.parentElement.classList.toggle('collapsed')">
            <span>🧠 思考过程（点击折叠/展开）</span><span class="arrow">▼</span>
          </div>
          <div class="thinking-body"></div>
        `;
        thinkBlock.querySelector('.thinking-body').textContent = m.thinking;
        bubble.appendChild(thinkBlock);
      }

      const contentEl = document.createElement('div');
      contentEl.className = 'content-text';
      contentEl.textContent = m.content;
      bubble.appendChild(contentEl);

      chatHistory.push({ role: m.role, content: m.content });
      return;
    }

    // ===== 面试模式 → 右侧多面板 =====
    if (scene === 'interview') {
      if (m.role === 'interviewer') {
        const taskId = 'hist_' + Math.random().toString(36).substr(2, 9);
        createNewAnswerBlock(taskId, m.content, 'full');
        const t = activeAnswers[taskId];
        // 历史面板不是实时生成，停掉超时兜底，避免 120s 后被改成“生成超时”
        t._done = true;
        if (t._timeout) clearTimeout(t._timeout);
        t.answerEl.textContent = '（无回答记录）';
        t.answerEl.style.color = '#888';
        lastPanelTaskId = taskId;
      } else if (m.role === 'assistant' && lastPanelTaskId && activeAnswers[lastPanelTaskId]) {
        const t = activeAnswers[lastPanelTaskId];
        t.answerEl.textContent = m.content;
        t.answerEl.style.color = '#333';
        lastPanelTaskId = null; // 一个回答配一个问题，用完清掉
      }
      // m.role === 'me' 的你的发言，历史里先不渲染到右侧面板，避免干扰
      return;
    }
  });
}

function appendTranscript(speaker, text) {
  const container = document.getElementById('liveTranscript');
  const div = document.createElement('div');
  div.className = `transcript-line ${speaker}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function clearTranscript() {
  document.getElementById('liveTranscript').innerHTML = '';
}

// ======== 其他辅助功能 ========
async function loadSources() {
  try {
    const res = await fetch('/api/sources');
    const data = await res.json();
    const list = document.getElementById('fileList');
    list.innerHTML = '';
    if (!data.sources || data.sources.length === 0) {
      list.innerHTML = '<div class="hint">暂无文件</div>';
      return;
    }
    data.sources.forEach(name => {
      const row = document.createElement('div');
      row.className = 'list-row';
      row.innerHTML = `<div class="list-label"></div><button class="list-del">×</button>`;
      row.querySelector('.list-label').textContent = '📄 ' + name;
      row.querySelector('.list-label').title = name;
      row.querySelector('.list-del').onclick = (e) => { e.stopPropagation(); deleteSource(name); };
      list.appendChild(row);
    });
  } catch (e) { console.error(e); }
}

async function deleteSource(name) {
  if (!confirm(`确定删除文件「${name}」及其所有索引片段？`)) return;
  try {
    const res = await fetch(`/api/sources/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.status === 'ok') await loadSources();
    else alert('删除失败: ' + data.message);
  } catch (e) { alert('删除失败: ' + e.message); }
}

function uploadFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.pdf,.docx,.txt,.md,.xlsx';
  input.onchange = async () => {
    for (const file of input.files) {
      const form = new FormData();
      form.append('file', file);
      try {
        const res = await fetch('/upload', { method: 'POST', body: form });
        const data = await res.json();
        if (data.status !== 'ok') alert('上传失败: ' + data.message);
      } catch (e) { alert('上传失败: ' + e.message); }
    }
    loadSources();
  };
  input.click();
}

function newSession() { if (ws?.readyState === 1) ws.send(JSON.stringify({ type: 'new_session' })); }
function loadHistory(sessionId) {
  currentSessionId = sessionId;
  if (ws?.readyState === 1) ws.send(JSON.stringify({ type: 'load_history', session_id: sessionId }));
}

function exportInterview() {
  if (!currentSessionId) { alert("当前没有加载历史会话，无法导出。"); return; }
  window.open(`/api/history/${currentSessionId}/export`, '_blank');
}

function renderHistoryList(sessions) {
  const list = document.getElementById('historyList');
  list.innerHTML = '';
  if (!sessions || sessions.length === 0) { list.innerHTML = '<div class="hint">暂无记录</div>'; return; }
  sessions.forEach(s => {
    const row = document.createElement('div');
    row.className = 'list-row';
    row.innerHTML = `<div class="list-label"></div><button class="list-del">×</button>`;
    row.querySelector('.list-label').textContent = `${s.date} ${s.title}`;
    row.querySelector('.list-label').onclick = () => loadHistory(s.id);
    row.querySelector('.list-del').onclick = (e) => { e.stopPropagation(); deleteHistory(s.id); };
    list.appendChild(row);
  });
}

async function deleteHistory(sessionId) {
  if (!confirm('确定删除这条历史记录？')) return;
  try {
    const res = await fetch(`/api/history/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.status !== 'ok') alert('删除失败: ' + data.message);
  } catch (e) { alert('删除失败: ' + e.message); }
}

// ======== 策略卡 ========
async function loadStrategies() {
  try {
    const res = await fetch('/api/strategy');
    currentStrategies = await res.json();
    renderStrategyTree(currentStrategies);
  } catch (e) { console.error(e); }
}

function renderStrategyTree(data) {
  const tree = document.getElementById('strategyTree');
  tree.innerHTML = `
    <div class="strategy-folder">
      <div class="strategy-folder-title">📂 核心规则</div>
      <div class="strategy-item" onclick="openStrategyEditor('parent.md', '父策略')">📄 父策略</div>
      <div class="strategy-item" onclick="openStrategyEditor('style.md', '风格')">📄 回答风格</div>
    </div>
  `;
  for (const [category, name] of [['projects', '项目子卡'], ['topics', '题型子卡']]) {
    const group = document.createElement('div');
    group.className = 'strategy-folder';
    group.innerHTML = `<div class="strategy-folder-title">📂 ${name}</div>`;
    for (const file of Object.keys(data[category] || {})) {
      const item = document.createElement('div');
      item.className = 'strategy-item';
      item.textContent = `📄 ${file}`;
      item.onclick = () => openStrategyEditor(`${category}/${file}.md`, `${name} - ${file}`);
      group.appendChild(item);
    }
    tree.appendChild(group);
  }
}

async function openStrategyEditor(fileRelPath, title) {
  currentEditingFile = fileRelPath;
  let content = "";
  if (fileRelPath === 'parent.md') content = currentStrategies.parent;
  else if (fileRelPath === 'style.md') content = currentStrategies.style;
  else {
    const [cat, filename] = fileRelPath.split('/');
    content = currentStrategies[cat]?.[filename.replace('.md', '')] || "";
  }
  document.getElementById('strategyEditTitle').textContent = "编辑: " + title;
  document.getElementById('strategyEditContent').value = content;
  document.getElementById('strategyEditModal').style.display = 'flex';
}

async function saveStrategy() {
  const content = document.getElementById('strategyEditContent').value;
  try {
    const res = await fetch('/api/strategy/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ file: currentEditingFile, content: content })
    });
    if (res.ok) { alert("保存成功"); document.getElementById('strategyEditModal').style.display = 'none'; loadStrategies(); }
  } catch (e) { alert("保存失败"); }
}

// ======== 设置弹窗 ========
async function openSettings() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    document.getElementById('cfgApiKey').value = cfg.deepseek.api_key || '';
    document.getElementById('cfgBaseUrl').value = cfg.deepseek.base_url || '';
    document.getElementById('cfgInterviewModel').value = cfg.deepseek.interview_model || '';
    document.getElementById('cfgPrepareModel').value = cfg.deepseek.prepare_model || '';
    document.getElementById('cfgThinkingInterview').value = cfg.thinking.interview_default || 'off';
    document.getElementById('cfgThinkingCode').value = cfg.thinking.code_default || 'high';
    document.getElementById('cfgAsrModel').value = cfg.audio.asr_model || 'base';
    document.getElementById('cfgAsrDevice').value = cfg.audio.asr_device || 'cpu';
    document.getElementById('cfgVoiceThreshold').value = cfg.audio.voiceprint_threshold || 0.75;
    document.getElementById('cfgTopK').value = cfg.rag.top_k || 3;
    document.getElementById('cfgPin').value = cfg.server.access_pin || '';
    document.getElementById('cfgBossHotkey').value = cfg.ui?.boss_hotkey || 'ctrl+shift+h';

    const micSelect = document.getElementById('cfgMicDevice');
    const loopSelect = document.getElementById('cfgLoopDevice');
    micSelect.innerHTML = '<option value="">系统默认</option>';
    loopSelect.innerHTML = '<option value="">系统默认</option>';

    try {
      const devRes = await fetch('/api/audio/devices');
      const devData = await devRes.json();
      window.__devices = devData;
      if (devData.mics) devData.mics.forEach(d => micSelect.innerHTML += `<option value="${d.id}">[${d.id}] ${d.name} (${d.hostapi})</option>`);
      if (devData.loops) devData.loops.forEach(d => loopSelect.innerHTML += `<option value="${d.id}">[${d.id}] ${d.name}</option>`);
      
      if (cfg.audio?.mic_device_id != null) micSelect.value = String(cfg.audio.mic_device_id);
      if (cfg.audio?.loop_device_id != null) loopSelect.value = String(cfg.audio.loop_device_id);
    } catch (err) { console.error(err); }
    document.getElementById('settingsModal').style.display = 'flex';
  } catch (e) { alert('加载配置失败: ' + e.message); }
}

function closeSettings() { document.getElementById('settingsModal').style.display = 'none'; }

function deviceNameById(selectId, key) {
  const s = document.getElementById(selectId);
  const id = s.value;
  if (!id || !window.__devices) return null;
  const d = (window.__devices[key] || []).find(x => String(x.id) === String(id));
  return d ? d.name : null;
}

async function saveSettings() {
  const payload = {
    deepseek: {
      api_key: document.getElementById('cfgApiKey').value,
      base_url: document.getElementById('cfgBaseUrl').value,
      interview_model: document.getElementById('cfgInterviewModel').value,
      prepare_model: document.getElementById('cfgPrepareModel').value
    },
    thinking: {
      interview_default: document.getElementById('cfgThinkingInterview').value,
      code_default: document.getElementById('cfgThinkingCode').value
    },
    audio: {
      asr_model: document.getElementById('cfgAsrModel').value,
      asr_device: document.getElementById('cfgAsrDevice').value,
      voiceprint_threshold: parseFloat(document.getElementById('cfgVoiceThreshold').value),
      mic_device_id: document.getElementById('cfgMicDevice').value === "" ? null : parseInt(document.getElementById('cfgMicDevice').value),
      loop_device_id: document.getElementById('cfgLoopDevice').value === "" ? null : parseInt(document.getElementById('cfgLoopDevice').value),
      mic_device_name: deviceNameById('cfgMicDevice', 'mics'),
      loop_device_name: deviceNameById('cfgLoopDevice', 'loops')
    },
    rag: { top_k: parseInt(document.getElementById('cfgTopK').value) },
    server: { access_pin: document.getElementById('cfgPin').value },
    ui: { boss_hotkey: document.getElementById('cfgBossHotkey').value.trim() || 'ctrl+shift+h' }
  };

  try {
    const res = await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
    if (res.ok) {
      await fetch('/api/audio/restart', { method: 'POST' });
      alert('设置已保存。\n注意：老板键修改需重启程序后生效。');
      closeSettings();
    } else { alert('保存失败'); }
  } catch (e) { alert('保存失败: ' + e.message); }
}

// ======== 模式切换与模拟提问 ========
function setMode(mode) {
  document.querySelectorAll('.mode-btn[data-mode]').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  const sidebarLeft = document.querySelector('.sidebar-left');
  const chatArea = document.querySelector('.chat-area');
  const sidebarRight = document.querySelector('.sidebar-right');

  if (mode === 'interview') {
    sidebarLeft.style.display = 'none';
    chatArea.style.display = 'none';
    sidebarRight.style.width = '100%';
  } else {
    sidebarLeft.style.display = '';
    chatArea.style.display = '';
    sidebarRight.style.width = '';
  }
}

function warmupCache() { if (ws?.readyState === 1) ws.send(JSON.stringify({ type: 'pregenerate' })); }
function openSimulateModal() { document.getElementById('simulateModal').style.display = 'flex'; setTimeout(() => document.getElementById('simulateInput').focus(), 100); }
function closeSimulateModal() { document.getElementById('simulateModal').style.display = 'none'; document.getElementById('simulateInput').value = ''; }

function sendSimulate() {
  const text = document.getElementById('simulateInput').value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: 'simulate_interview', text: text }));
  closeSimulateModal();
  setMode('interview');
}

// ======== 音频测试 ========
let mediaRecorder = null;
let audioChunks = [];

async function testAudio(action) {
  if (mediaRecorder && mediaRecorder.state === 'recording') return;
  const btnMap = { asr: document.getElementById('btnTestAsr'), vp_register: document.getElementById('btnTestVpReg'), vp_verify: document.getElementById('btnTestVpVerify') };
  const btn = btnMap[action];
  const originalText = btn.textContent;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    audioChunks = [];
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      btn.textContent = '上传中...';
      const blob = new Blob(audioChunks, { type: 'audio/webm' });
      const form = new FormData();
      form.append('file', blob, 'test.webm');
      const url = action === 'asr' ? '/api/test_asr' : (action === 'vp_register' ? '/api/voiceprint/register' : '/api/voiceprint/verify');
      
      try {
        const res = await fetch(url, { method: 'POST', body: form });
        const data = await res.json();
        if (data.status === 'ok') {
          if (action === 'asr') alert(`识别结果: ${data.text}\n\n音量(RMS): ${data.rms}\n录音时长: ${data.duration}秒`);
          else if (action === 'vp_register') alert('✅ 声纹注册成功！');
          else if (action === 'vp_verify') alert(`相似度: ${data.similarity}\n\n${data.similarity > 0.70 ? '✅ 验证通过。' : '❌ 验证失败。'}`);
        } else alert('失败: ' + data.message);
      } catch (e) { alert('请求失败: ' + e.message); } finally { btn.textContent = originalText; }
    };
    alert(`即将开始录制 8 秒。\n请清晰朗读：“今天天气不错，我正在测试面试辅助软件的音频系统。”`);
    mediaRecorder.start();
    let count = 8;
    btn.textContent = `录音中 8s...`;
    const timer = setInterval(() => {
      count--;
      if (count > 0) btn.textContent = `录音中 ${count}s...`;
      else { clearInterval(timer); mediaRecorder.stop(); }
    }, 1000);
  } catch (e) { alert('无法访问麦克风: ' + e.message); if (btn) btn.textContent = originalText; }
}

async function clearVoiceprint() {
  if (!confirm('确定要清除已保存的声纹吗？')) return;
  try {
    const res = await fetch('/api/voiceprint/clear', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'ok') alert('✅ 声纹已清除，请重新注册。');
    else alert('清除失败: ' + data.message);
  } catch (e) { alert('请求失败: ' + e.message); }
}

// 输入框自动高度
const chatInput = document.getElementById('chatInput');
chatInput.addEventListener('input', function () { this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 120) + 'px'; });
chatInput.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

// ======== 手机端二维码 ========
async function showMobileQR() {
  try {
    const res = await fetch('/api/mobile_url');
    const data = await res.json();
    document.getElementById('mobileURLText').textContent = data.url;

    const qrImg = document.getElementById('qrCodeImage');
    qrImg.src = `/api/qrcode?t=${Date.now()}`;

    document.getElementById('mobileQRModal').style.display = 'flex';
  } catch (e) {
    alert('获取地址失败: ' + e.message);
  }
}

async function copyMobileURL() {
  const text = document.getElementById('mobileURLText').textContent;
  if (!text || !text.startsWith('http')) return;
  try {
    await navigator.clipboard.writeText(text);
    alert('✅ 已复制到剪贴板');
  } catch (e) {
    const range = document.createRange();
    range.selectNode(document.getElementById('mobileURLText'));
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
    document.execCommand('copy');
    alert('✅ 已复制');
  }
}

init();