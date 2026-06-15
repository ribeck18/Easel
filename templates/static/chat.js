const chatTitle = document.getElementById('chat-title');
const textarea = document.getElementById('msg-input');
const messagesArea = document.getElementById('messages-area');
const sendBtn = document.getElementById('send-btn');
const sidebarList = document.querySelector('.sidebar-list');
const newBtn = document.querySelector('.btn-new');
const attachBtn = document.querySelector('.attach-btn');
const fileInput = document.getElementById('file-input');
const attachmentChips = document.getElementById('attachment-chips');
const sidebarSearch = document.querySelector('.sidebar-search-input');

let currentChatId = null;
let pendingAttachments = [];
// Recall tools are bookkeeping and hidden from the transcript. The `memory` write tool
// is intentionally NOT here, so the user sees what was remembered. Keep in sync with
// HIDDEN_MEMORY_TOOLS in services/chat.py.
const MEMORY_TOOL_NAMES = new Set([
  'search_memory',
  'read_wiki_note',
  'search_chat_history',
  'read_chat_history',
]);

async function loadChatList(autoSelectLatest = false) {
  try {
    const res = await fetch('/api/chat-list');
    const chats = await res.json();
    sidebarList.innerHTML = '';
    for (const chat of chats) {
      addChatItem(chat.id, chat.name);
    }
    filterChatList();
    if (autoSelectLatest && chats.length > 0) {
      const last = chats[chats.length - 1];
      const item = sidebarList.querySelector(`[data-chat="${last.id}"]`);
      if (item) selectChat(last.id, last.name, item);
    }
  } catch (err) {
    console.error('Failed to load chat list:', err);
  }
}

function addChatItem(id, name) {
  const item = document.createElement('div');
  item.className = 'chat-item';
  item.dataset.chat = id;
  item.innerHTML = `<span class="chat-item-name">${esc(name)}</span>`;
  item.addEventListener('click', () => selectChat(id, name, item));
  sidebarList.appendChild(item);
  return item;
}

// Client-side filter of the conversation list by name (no backend route).
function filterChatList() {
  if (!sidebarSearch) return;
  const raw = sidebarSearch.value.trim();
  const query = raw.toLowerCase();
  let visible = 0;
  sidebarList.querySelectorAll('.chat-item').forEach(item => {
    const nameEl = item.querySelector('.chat-item-name');
    const text = nameEl ? nameEl.textContent.toLowerCase() : '';
    const matches = !query || text.indexOf(query) > -1;
    item.style.display = matches ? '' : 'none';
    if (matches) visible++;
  });
  // Show a hint only while searching with nothing matched.
  let empty = sidebarList.querySelector('.sidebar-empty');
  if (query && visible === 0) {
    if (!empty) {
      empty = document.createElement('div');
      empty.className = 'sidebar-empty';
      sidebarList.appendChild(empty);
    }
    empty.textContent = `No conversations match “${raw}”`;
  } else if (empty) {
    empty.remove();
  }
}

if (sidebarSearch) {
  sidebarSearch.addEventListener('input', filterChatList);
}

async function selectChat(id, name, item) {
  if (currentChatId !== null && currentChatId !== id && messagesArea.children.length > 0) {
    markChatLeft(currentChatId);
  }
  document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
  item.classList.add('active');
  chatTitle.textContent = name;
  currentChatId = id;
  messagesArea.innerHTML = '';

  try {
    const res = await fetch(`/api/chat-history?current_chat_id=${id}`);
    const history = await res.json();
    for (const item of history) {
      if (item.type === 'tool') {
        if (item.tool_name === 'read_skill') {
          appendSkillChip(item.arguments);
        } else {
          appendToolBlock(item.tool_name, item.arguments, item.result, null);
        }
      } else {
        appendMessage(item.role, item.content, formatTime(item.time));
      }
    }
    messagesArea.scrollTop = messagesArea.scrollHeight;
  } catch (err) {
    console.error('Failed to load chat history:', err);
  }
}

newBtn.addEventListener('click', async () => {
  try {
    if (currentChatId !== null && messagesArea.children.length > 0) {
      markChatLeft(currentChatId);
    }
    const res = await fetch('/api/chat/session', { method: 'POST' });
    const data = await res.json();
    const newId = data.chat_session_id;
    await loadChatList();
    const newItem = sidebarList.querySelector(`[data-chat="${newId}"]`);
    if (newItem) {
      selectChat(newId, newItem.querySelector('.chat-item-name').textContent, newItem);
    }
  } catch (err) {
    console.error('Failed to create new chat:', err);
  }
});

textarea.addEventListener('input', () => {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 160) + 'px';
});

function esc(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function timeNow() {
  return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function formatTime(ms) {
  if (ms == null) return timeNow();
  return new Date(ms).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function appendMessage(role, text, time, tag) {
  const messageEl = document.createElement('div');
  messageEl.className = `message ${role}`;
  // Assistant replies render markdown (sanitized); user text stays literal.
  const bubble = role === 'user'
    ? `<p>${esc(text)}</p>`
    : renderMarkdown(text);
  messageEl.innerHTML = `
    <div class="msg-sender">${role === 'user' ? 'You' : 'Easel'}</div>
    <div class="msg-bubble">${bubble}</div>
    <div class="msg-footer">
      <span>${time}</span>
      ${tag ? `<span class="msg-tag">${tag}</span>` : ''}
    </div>
  `;
  messagesArea.appendChild(messageEl);
}

function appendTypingIndicator() {
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.id = 'typing-indicator';
  el.innerHTML = `
    <div class="msg-sender">Easel</div>
    <div class="msg-bubble">
      <div class="typing-dots">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  messagesArea.appendChild(el);
  messagesArea.scrollTop = messagesArea.scrollHeight;
}

function removeTypingIndicator() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

function appendToolBlock(name, argsStr, result, status) {
  let argsPretty = argsStr || '';
  try { argsPretty = JSON.stringify(JSON.parse(argsStr), null, 2); } catch {}
  const statusTag = status ? `<span class="tool-status ${esc(status)}">${esc(status)}</span>` : '';
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `
    <details class="tool-block">
      <summary class="tool-summary">
        <span class="tool-caret">▸</span>
        <span class="tool-name">${esc(name)}</span>
        ${statusTag}
      </summary>
      <div class="tool-body">
        <div class="tool-section-label">Arguments</div>
        <pre class="tool-pre">${esc(argsPretty)}</pre>
        <div class="tool-section-label">Result</div>
        <pre class="tool-pre">${esc(result || '')}</pre>
      </div>
    </details>
  `;
  messagesArea.appendChild(el);
}

function renderToolActivity(list) {
  for (const a of list || []) {
    if (a.tool_name === 'read_skill') {
      appendSkillChip(a.arguments);
    } else if (!MEMORY_TOOL_NAMES.has(a.tool_name)) {
      appendToolBlock(a.tool_name, a.arguments, a.result, a.status);
    }
  }
}

function appendSkillChip(argsStr) {
  let slug = '';
  try { slug = (JSON.parse(argsStr) || {}).slug || ''; } catch {}
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `<div class="skill-used-chip">✨ Used skill: <strong>${esc(slug)}</strong></div>`;
  messagesArea.appendChild(el);
}

function appendApprovalCard(pending, chatId, time) {
  let args = {};
  try { args = JSON.parse(pending.arguments); } catch {}
  const pathLine = args.path != null
    ? `<div class="approval-path">${esc(String(args.path))}</div>` : '';
  const preview = args.content != null
    ? `<div class="tool-section-label">Content</div><pre class="tool-pre">${esc(String(args.content))}</pre>` : '';
  const el = document.createElement('div');
  el.className = 'message assistant';
  el.innerHTML = `
    <div class="msg-sender">Easel · approval required</div>
    <div class="approval-card">
      <div class="approval-head">Run <strong>${esc(pending.tool_name)}</strong>?</div>
      ${pathLine}
      ${preview}
      <div class="approval-actions">
        <button class="btn-approve">Approve</button>
        <button class="btn-approve-always">Approve & always allow</button>
        <button class="btn-reject">Reject</button>
      </div>
    </div>
    <div class="msg-footer"><span>${time || timeNow()}</span></div>
  `;
  messagesArea.appendChild(el);
  el.querySelector('.btn-approve').addEventListener('click', () => resolveApproval(el, chatId, pending.tool_call_id, 'approve'));
  el.querySelector('.btn-approve-always').addEventListener('click', () => resolveApproval(el, chatId, pending.tool_call_id, 'approve_always'));
  el.querySelector('.btn-reject').addEventListener('click', () => resolveApproval(el, chatId, pending.tool_call_id, 'reject'));
}

async function resolveApproval(cardEl, chatId, toolCallId, decision) {
  cardEl.querySelectorAll('button').forEach(b => { b.disabled = true; });
  cardEl.classList.add('resolved');
  appendTypingIndicator();
  try {
    const response = await fetch('/api/chat/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_session_id: chatId, tool_call_id: toolCallId, decision }),
    });
    removeTypingIndicator();
    if (currentChatId === chatId) {
      if (response.ok) handleTurnResponse(await response.json(), chatId);
      else appendMessage('assistant', 'Something went wrong. Please try again.', timeNow());
      messagesArea.scrollTop = messagesArea.scrollHeight;
    }
  } catch {
    removeTypingIndicator();
    if (currentChatId === chatId) appendMessage('assistant', 'Something went wrong. Please try again.', timeNow());
  }
}

function handleTurnResponse(data, chatId) {
  if (currentChatId !== chatId) return;
  renderToolActivity(data.tool_activity);
  if (data.status === 'awaiting_approval') {
    appendApprovalCard(data.pending, chatId, formatTime(data.time));
    return;
  }
  appendMessage('assistant', data.model_message || '', formatTime(data.time));
  if (data.chat_name) {
    const activeItem = sidebarList.querySelector(`[data-chat="${chatId}"]`);
    if (activeItem) activeItem.querySelector('.chat-item-name').textContent = data.chat_name;
    chatTitle.textContent = data.chat_name;
  }
}

async function sendMessage() {
  const text = textarea.value.trim();
  if ((!text && pendingAttachments.length === 0) || currentChatId === null) return;

  const chatIdAtSend = currentChatId;
  const attachments = pendingAttachments.slice();

  textarea.value = '';
  textarea.style.height = 'auto';
  textarea.disabled = true;
  sendBtn.disabled = true;

  const shown = attachments.length
    ? `${text}${text ? '\n\n' : ''}📎 ${attachments.map(p => p.split('/').pop()).join(', ')}`
    : text;
  appendMessage('user', shown, timeNow());
  clearAttachments();
  appendTypingIndicator();

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_message: text, chat_session_id: chatIdAtSend, attachments }),
    });

    removeTypingIndicator();

    if (currentChatId === chatIdAtSend) {
      if (response.ok) {
        handleTurnResponse(await response.json(), chatIdAtSend);
      } else {
        appendMessage('assistant', 'Something went wrong. Please try again.', timeNow());
      }
      messagesArea.scrollTop = messagesArea.scrollHeight;
    }
  } catch {
    removeTypingIndicator();
    if (currentChatId === chatIdAtSend) {
      appendMessage('assistant', 'Something went wrong. Please try again.', timeNow());
    }
  }

  textarea.disabled = false;
  sendBtn.disabled = false;
  textarea.focus();
}

sendBtn.addEventListener('click', sendMessage);

textarea.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

function renderAttachmentChips() {
  attachmentChips.innerHTML = '';
  pendingAttachments.forEach((path, index) => {
    const chip = document.createElement('span');
    chip.className = 'attachment-chip';
    chip.innerHTML = `<span>${esc(path.split('/').pop())}</span><button type="button" aria-label="Remove">×</button>`;
    chip.querySelector('button').addEventListener('click', () => {
      pendingAttachments.splice(index, 1);
      renderAttachmentChips();
    });
    attachmentChips.appendChild(chip);
  });
}

function clearAttachments() {
  pendingAttachments = [];
  renderAttachmentChips();
}

attachBtn.addEventListener('click', () => {
  if (currentChatId !== null) fileInput.click();
});

fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  fileInput.value = '';
  if (!file || currentChatId === null) return;

  const form = new FormData();
  form.append('chat_session_id', currentChatId);
  form.append('file', file);
  try {
    const res = await fetch('/api/chat/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (data.status === 'ok') {
      pendingAttachments.push(data.path);
      renderAttachmentChips();
    } else {
      appendMessage('assistant', data.message || 'Could not attach that file.', timeNow());
    }
  } catch {
    appendMessage('assistant', 'Could not attach that file.', timeNow());
  }
});

loadChatList(true);

function markChatLeft(chatId) {
  fetch('/api/memory/leave', {
    method: 'POST',
    keepalive: true,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_session_id: chatId }),
  }).catch(function() {});
}

window.addEventListener('pagehide', function() {
  if (currentChatId !== null && messagesArea.children.length > 0) {
    markChatLeft(currentChatId);
  }
});

function pollMemoryEvents() {
  fetch('/api/memory/events?unseen=1')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      const events = data.events || [];
      if (!events.length) return;
      showMemoryToast(events[0].summary);
      fetch('/api/memory/events/seen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: events.map(function(event) { return event.id; }) }),
      });
    })
    .catch(function() {});
}

function showMemoryToast(summary) {
  const toast = document.createElement('div');
  toast.className = 'memory-toast';
  toast.textContent = 'Memory updated: ' + summary;
  document.body.appendChild(toast);
  setTimeout(function() { toast.classList.add('visible'); }, 20);
  setTimeout(function() { toast.remove(); }, 4200);
}

setInterval(pollMemoryEvents, 45000);
pollMemoryEvents();
