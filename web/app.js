'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const state = {user: null, overview: null, page: 'overview', conversations: [], current: null, messages: [], busy: false, filter: '', chunkDocument: null};
const titles = {overview: '知识概览', chat: '知识问答', documents: '文档知识库', users: '成员与权限', audit: '操作记录'};
const statusNames = {queued: '等待解析', parsing: '解析中', parsed: '已解析 · 待向量化', indexing: '向量生成中', ready: '可检索', error: '解析失败'};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const admin = () => state.user?.role === 'admin';
const number = n => Number(n || 0).toLocaleString('zh-CN');
const date = value => new Date(value).toLocaleDateString('zh-CN', {month: '2-digit', day: '2-digit', year: 'numeric'});
const badge = (status, label) => `<span class="badge ${escape(status)}">${escape(label || statusNames[status] || status)}</span>`;

function toast(message, error = false) {
  const node = document.createElement('div'); node.className = `toast${error ? ' error' : ''}`; node.textContent = message;
  $('#toasts').append(node); setTimeout(() => node.remove(), 6500);
}

async function api(path, options = {}) {
  const headers = {...options.headers};
  if (options.body && !(options.body instanceof FormData)) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  let response;
  try { response = await fetch(`/api${path}`, {...options, headers, credentials: 'same-origin'}); }
  catch (_) { throw new Error('无法连接服务，请确认服务仍在运行。'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') showLogin();
    const detail = typeof data.detail === 'string' ? data.detail : (Array.isArray(data.detail) ? '输入格式不符合要求，请检查字段长度和格式。' : `请求失败（${response.status}）`);
    const error = new Error(detail); error.data = data; error.status = response.status; throw error;
  }
  return data;
}

function showLogin() {
  state.user = null; state.current = null; state.messages = []; state.busy = false; state.overview = null;
  $('#app-view').hidden = true; $('#login-view').hidden = false;
  if ($('#modal').open) $('#modal').close();
}

async function enter(user) {
  state.user = user; $('#login-view').hidden = true; $('#app-view').hidden = false;
  $('#account-name').textContent = user.username; $('#account-avatar').textContent = user.username.slice(0, 1).toUpperCase();
  $('#account-role').textContent = admin() ? '管理员' : '只读成员';
  document.querySelectorAll('.admin-only').forEach(node => { node.hidden = !admin(); });
  await refreshOverview(); await route();
}

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('button', event.target); button.disabled = true; $('#login-error').textContent = '';
  try { const user = await api('/auth/login', {method: 'POST', body: {username: $('#username').value.trim(), password: $('#password').value}}); $('#password').value = ''; await enter(user); }
  catch (error) { $('#login-error').textContent = error.message; }
  finally { button.disabled = false; }
});

async function refreshOverview() {
  const result = await api('/overview'); state.overview = result; $('#nav-doc-count').textContent = result.counts.documents; return result;
}

function heading(title, subtitle, actions = '') {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`;
}

function metricCards() {
  const c = state.overview.counts;
  return `<div class="metric-grid">
    <div class="metric-card"><span class="metric-icon">▤</span><div class="metric-label">知识文档</div><div class="metric-value">${number(c.documents)}</div><div class="metric-caption"><em>${number(c.parsed)} 份</em> 已完成解析</div></div>
    <div class="metric-card"><span class="metric-icon">▥</span><div class="metric-label">知识片段</div><div class="metric-value">${number(c.chunks)}</div><div class="metric-caption">从文档中提取的可追溯内容</div></div>
    <div class="metric-card"><span class="metric-icon">⠿</span><div class="metric-label">有效向量</div><div class="metric-value">${number(c.vectors)}</div><div class="metric-caption">bge-m3 · <em>1024 维</em></div></div>
    <div class="metric-card"><span class="metric-icon">◌</span><div class="metric-label">向量覆盖率</div><div class="metric-value">${c.chunks ? Math.round(c.vectors / c.chunks * 100) : 0}<span class="muted">%</span></div><div class="metric-caption">当前模型下已向量化的片段</div></div>
  </div>`;
}

function empty(title, description, action = '') { return `<div class="empty-state"><div class="empty-glyph">▤</div><h3>${title}</h3><p>${description}</p>${action}</div>`; }

function documentTable(docs, detailed = false) {
  if (!docs.length) return empty(state.filter ? '没有找到匹配的文档' : '知识，从第一份文档开始', state.filter ? '试试其他主题或文件名。' : (admin() ? '上传一份文档，检查解析结果，再建立向量。准备好后，就可以开始有依据的对话。' : '管理员尚未添加文档，稍后再来看看。'), admin() && !state.filter ? '<button class="button primary" data-action="upload">＋ 上传第一份文档</button>' : '');
  return `<div class="table-wrap"><table><thead><tr>${detailed ? '<th>序号</th>' : ''}<th>文档 / 主题</th><th>解析状态</th><th>片段</th><th>向量</th>${detailed ? '<th>添加时间</th>' : ''}<th>操作</th></tr></thead><tbody>${docs.map(doc => {
    const ext = doc.filename.split('.').pop().toLowerCase();
    const processing = ['queued','parsing','indexing'].includes(doc.status);
    return `<tr>${detailed ? `<td class="document-sequence">${state.overview.documents.findIndex(item => item.id === doc.id) + 1}</td>` : ''}<td><div class="document-name"><span class="file-icon ${escape(ext)}">${escape(ext === 'markdown' ? 'MD' : ext.toUpperCase())}</span><div><div class="doc-title" title="${escape(doc.topic)}">${escape(doc.topic)}</div><div class="doc-subtitle" title="${escape(doc.filename)}">${escape(doc.filename)}</div></div></div></td>
      <td>${badge(doc.status)}${doc.error ? `<div class="error-note" title="${escape(doc.error)}">${escape(doc.error)}</div>` : ''}</td><td>${number(doc.chunk_count)}</td><td>${number(doc.vector_count)}</td>${detailed ? `<td class="muted">${date(doc.created_at)}</td>` : ''}
      <td><div class="row-actions"><button class="text-button" data-action="chunks" data-id="${doc.id}">查看片段</button>${detailed && admin() && !processing ? `${doc.chunk_count ? `<button class="text-button" data-action="index" data-id="${doc.id}">${doc.vector_count === doc.chunk_count ? '重建向量' : '建立向量'}</button>` : `<button class="text-button" data-action="parse" data-id="${doc.id}">重试解析</button>`}<button class="text-button" data-action="document-menu" data-id="${doc.id}">更多</button>` : ''}</div></td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function renderOverview() {
  const {counts, documents, models} = state.overview;
  const local = models.embedding.mode === 'local';
  const bgeStatus = local ? (models.embedding.loaded ? '模型已加载' : (models.embedding.runtime_installed ? '运行库已安装 · 待加载' : '待安装本地运行库')) : 'API 模式 · 连接待验证';
  $('#main-content').innerHTML = heading('知识概览', '整理知识，连接信息。你的知识库状态，尽在这里。', `<button class="button" data-action="refresh">↻ 刷新</button>${admin() ? '<button class="button primary" data-action="upload">＋ 上传文档</button>' : ''}`) + metricCards() + `
    <div class="overview-grid"><section class="panel"><div class="panel-heading"><h2>知识文档<small>${number(counts.documents)} 份文档，共享一个知识空间</small></h2><a class="text-button" href="#documents">查看全部 →</a></div>${documentTable(documents.slice(0, 6))}</section>
    <aside class="overview-side"><section class="panel model-panel"><div class="panel-heading"><h2>模型连接</h2>${admin() ? '<button class="text-button" data-action="model-config">配置说明</button>' : ''}</div>
      <div class="model-card"><div class="model-card-head"><span class="model-symbol">≈</span><div><div class="model-name">${escape(models.llm.model)}</div><div class="model-kind">生成模型 · DeepSeek API</div></div></div><div class="model-status ${models.llm.configured ? 'configured' : ''}"><span class="live-dot"></span>${models.llm.configured ? '已配置 · 连接待验证' : '等待配置模型与密钥'}</div></div>
      <div class="model-card"><div class="model-card-head"><span class="model-symbol bge">BGE</span><div><div class="model-name">${escape(models.embedding.model)}</div><div class="model-kind">向量模型 · ${local ? '本地 CPU / 配置设备' : 'Embedding API'}</div></div></div><div class="model-status ${models.embedding.loaded ? 'configured' : ''}"><span class="live-dot"></span>${bgeStatus}</div></div>
      <p class="model-note">连接状态以实际调用为准。解析完成后，建立向量才能用于检索问答。</p></section>
    <section class="panel quick-panel"><h3>让答案回到原文</h3><p>每个回答都应有来源。提问后，点击引用即可查看支撑答案的文档片段。</p><a href="#chat" class="button">开始一次知识问答 <span>↗</span></a></section></aside></div>`;
}

function renderDocuments() {
  const docs = state.overview.documents.filter(d => `${d.filename} ${d.topic}`.toLowerCase().includes(state.filter.toLowerCase()));
  $('#main-content').innerHTML = heading('文档知识库', admin() ? '从原始文档到可检索知识，管理每一个处理环节。' : '浏览共享知识，查看文档主题与原始片段。', `<button class="button" data-action="retrieval-test">◎ 检索测试</button>${admin() ? '<button class="button primary" data-action="upload">＋ 上传文档</button>' : ''}`) +
    (admin() ? `<div id="upload-zone" class="upload-zone"><div class="empty-glyph">↥</div><div><h3>拖拽文档到这里，开始整理知识</h3><p>支持 PDF、TXT、Markdown · 单文件最大 ${state.overview.max_upload_mb} MB · 扫描件请先做 OCR</p></div><button class="button" data-action="upload">选择文件</button></div>` : '') +
    (state.overview.counts.chunks > state.overview.counts.vectors ? '<div class="notice">部分片段尚未建立向量。解析完成后，请由管理员建立向量；修改过的片段也需要重新向量化。</div>' : '') +
    `<section class="panel"><div class="toolbar"><input id="document-filter" class="search-input" placeholder="搜索文档名称或主题…" aria-label="搜索文档" value="${escape(state.filter)}"><span class="muted">${number(docs.length)} 份文档 · 主题可由管理员调整</span></div><div id="document-table">${documentTable(docs, true)}</div></section>`;
  $('#document-filter').addEventListener('input', event => {
    state.filter = event.target.value; const filtered = state.overview.documents.filter(d => `${d.filename} ${d.topic}`.toLowerCase().includes(state.filter.toLowerCase()));
    $('#document-table').innerHTML = documentTable(filtered, true);
  });
  const zone = $('#upload-zone');
  if (zone) {
    zone.addEventListener('dragover', event => { event.preventDefault(); zone.classList.add('dragging'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
    zone.addEventListener('drop', event => { event.preventDefault(); zone.classList.remove('dragging'); uploadFiles(event.dataTransfer.files).catch(e => toast(e.message, true)); });
  }
}

async function renderUsers() {
  const users = await api('/users');
  $('#main-content').innerHTML = heading('成员与权限', '清晰的角色边界，让知识在合适的范围内流动。', '<button class="button primary" data-action="new-user">＋ 添加成员</button>') +
    '<div class="notice info">管理员可以管理用户、文档和知识片段；只读成员可以浏览知识与提问。所有成员共用一个知识库，会话历史按账号隔离。</div>' +
    `<section class="panel"><div class="panel-heading"><h2>空间成员<small>${users.length} 位成员</small></h2></div><div class="table-wrap"><table><thead><tr><th>成员</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${users.map(user => `<tr><td><strong>${escape(user.username)}</strong>${user.id === state.user.id ? ' <span class="muted">（我）</span>' : ''}</td><td>${badge(user.role === 'admin' ? 'ready' : 'parsed', user.role === 'admin' ? '管理员' : '只读成员')}</td><td>${badge(user.active ? 'ready' : 'error', user.active ? '启用' : '已停用')}</td><td class="muted">${date(user.created_at)}</td><td>${user.id === state.user.id ? '<span class="muted">通过左下角修改密码</span>' : `<button class="text-button" data-action="edit-user" data-id="${user.id}" data-username="${escape(user.username)}" data-role="${user.role}" data-active="${user.active}">管理权限</button>`}</td></tr>`).join('')}</tbody></table></div></section>`;
}

async function renderAudit() {
  const rows = await api('/audit'); const names = {login:'登录',change_password:'修改密码',upload_document:'上传文档',edit_topic:'修改主题',delete_document:'删除文档',document_parse:'重新解析',document_index:'建立向量',add_chunk:'新增片段',edit_chunk:'修改片段',delete_chunk:'删除片段',query_knowledge:'知识问答',create_user:'添加成员',update_user:'修改成员',delete_user:'删除成员'};
  $('#main-content').innerHTML = heading('操作记录', '查看最近 100 条操作，了解知识与权限的变更。', '<button class="button" data-action="refresh">↻ 刷新</button>') + `<section class="panel"><div class="table-wrap"><table><thead><tr><th>操作人</th><th>操作</th><th>对象 ID</th><th>时间</th></tr></thead><tbody>${rows.map(row => `<tr><td>${escape(row.username || '已删除用户')}</td><td>${escape(names[row.action] || row.action)}</td><td class="muted"><code>${escape(row.target || '—')}</code></td><td class="muted">${escape(new Date(row.created_at).toLocaleString('zh-CN'))}</td></tr>`).join('')}</tbody></table></div></section>`;
}

async function renderChat() {
  state.conversations = await api('/conversations');
  $('#main-content').innerHTML = heading('知识问答', '让问题找到证据，让答案附上来源。', '<button class="button" data-action="new-chat">＋ 新对话</button>') +
    `<div class="chat-layout"><aside class="panel conversation-panel"><button class="button" data-action="new-chat">＋ 发起新对话</button><h3>最近对话</h3>${state.conversations.length ? state.conversations.map(c => `<div role="button" tabindex="0" class="conversation-item ${state.current === c.id ? 'active' : ''}" data-action="conversation" data-id="${c.id}" title="${escape(c.title)}">${escape(c.title)}</div>`).join('') : '<p class="muted" style-placeholder="none">暂无对话记录</p>'}</aside>
    <section class="panel chat-panel"><div class="chat-header"><span>◎ 知序知识助手</span>${badge('ready', '有限轮次检索 · 引用可追溯')}</div><div id="chat-scroll" class="chat-scroll"></div>
    <form id="chat-form" class="chat-compose"><div class="compose-box"><textarea id="question" aria-label="输入问题" placeholder="向知识库提问，例如：这份制度的适用范围是什么？" maxlength="4000" required></textarea><div class="compose-actions"><select id="chat-scope" aria-label="检索范围"><option value="">全部共享文档</option>${state.overview.documents.filter(d => d.vector_count).map(d => `<option value="${d.id}">${escape(d.topic)}</option>`).join('')}</select><button type="submit" class="button primary" id="send-button" ${state.busy ? 'disabled' : ''}>${state.busy ? '检索中…' : '发送问题 ↑'}</button></div></div><p class="compose-hint">Enter 发送，Shift + Enter 换行 · 回答可能有误，请核对原始资料</p></form></section></div>`;
  paintMessages();
  $('#chat-form').addEventListener('submit', sendQuestion);
  $('#question').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#chat-form').requestSubmit(); } });
}

function paintMessages() {
  const scroll = $('#chat-scroll'); if (!scroll) return;
  if (!state.messages.length && !state.busy) { scroll.innerHTML = `<div class="chat-welcome"><div class="agent-symbol">◎</div><h2>你的知识，值得一个好问题。</h2><p>我会检索已建立向量的文档，<br>并把答案与对应的来源一起交给你。</p><div class="suggestions"><button class="suggestion" data-action="suggest" data-question="这份文档的主要内容是什么？请列出要点并引用依据。">概括文档的主要内容 ↗</button><button class="suggestion" data-action="suggest" data-question="文档中有哪些适用条件和例外？请引用原文。">查找适用条件与例外 ↗</button></div></div>`; return; }
  scroll.innerHTML = state.messages.map((message, index) => {
    const citations = message.citations || [];
    let content = escape(message.role === 'assistant' ? ChatFormat.plainAnswer(message.content) : message.content);
    if (message.role === 'assistant') content = content.replace(/\[(S\d+)\]/g, (match, alias) => citations.some(c => c.id === alias) ? `<button class="inline-citation" data-action="source" data-message="${index}" data-id="${alias}">${alias}</button>` : match);
    return `<article class="message ${message.role === 'user' ? 'user' : 'assistant'} ${message.is_error ? 'error' : ''}"><div class="message-avatar">${message.role === 'user' ? escape(state.user.username.slice(0,1).toUpperCase()) : '知'}</div><div class="message-body"><div class="message-label">${message.role === 'user' ? escape(state.user.username) : '知序知识助手'}</div><div class="message-content">${content}</div>${citations.length ? `<div class="sources">${citations.map(c => `<button class="source-card" data-action="source" data-message="${index}" data-id="${c.id}">${escape(ChatFormat.sourceLabel(c))}</button>`).join('')}</div>` : ''}${message.trace?.length ? `<details class="trace"><summary>${message.trace.length} 次工具调用 · 查看检索过程</summary>${message.trace.map(t => `<p>${t.tool === 'search_knowledge' ? '检索' : '读取前后文'}：${escape(t.query)} → ${t.results} 个片段 · ${number(t.duration_ms)} ms${t.ok ? '' : ' · 未执行'}</p>`).join('')}</details>` : ''}</div></article>`;
  }).join('') + (state.busy ? '<article class="message"><div class="message-avatar">知</div><div class="message-body"><div class="message-label">正在检索并整理证据，请稍候…</div><div class="pending-dots"><i></i><i></i><i></i></div></div></article>' : '');
  scroll.scrollTop = scroll.scrollHeight;
}

async function sendQuestion(event) {
  event.preventDefault(); if (state.busy) return;
  const question = $('#question').value.trim(); if (!question) return;
  const scope = $('#chat-scope').value; const runUser = state.user.id;
  state.messages.push({role: 'user', content: question}); state.busy = true; $('#question').value = ''; $('#send-button').disabled = true; $('#send-button').textContent = '检索中…'; paintMessages();
  try {
    const result = await api('/chat', {method:'POST', body:{question, conversation_id: state.current, document_ids: scope ? [scope] : []}});
    if (state.user?.id !== runUser) return;
    state.current = result.conversation_id; state.messages.push({role:'assistant', content:result.answer, citations:result.citations, trace:result.trace});
  } catch (error) {
    if (state.user?.id !== runUser) return;
    if (error.data?.conversation_id) state.current = error.data.conversation_id;
    state.messages.push({role:'assistant', content:error.message, is_error:true});
  } finally {
    if (state.user?.id === runUser) { state.busy = false; if (state.page === 'chat') await renderChat(); }
  }
}

function openModal(title, subtitle, body) {
  $('#modal-content').innerHTML = `<div class="modal-head"><div><h2 id="modal-title">${escape(title)}</h2>${subtitle ? `<p>${escape(subtitle)}</p>` : ''}</div><button class="close-modal" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-body">${body}</div>`;
  if (!$('#modal').open) $('#modal').showModal();
}
function closeModal() { $('#modal').close(); state.chunkDocument = null; }

function confirmModal(title, description, confirmText, onConfirm) {
  openModal(title, '', `<p>${escape(description)}</p><div class="modal-actions"><button class="button" data-action="close-modal">取消</button><button id="confirm-button" class="button danger">${escape(confirmText)}</button></div>`);
  $('#confirm-button').addEventListener('click', async event => { event.target.disabled = true; try { await onConfirm(); closeModal(); } catch(error) { toast(error.message,true); event.target.disabled = false; } });
}

async function showChunks(documentId) {
  const doc = state.overview.documents.find(d => d.id === documentId); if (!doc) return;
  const chunks = await api(`/documents/${documentId}/chunks`); state.chunkDocument = documentId;
  openModal(doc.topic, `${doc.filename} · ${chunks.length} 个片段 · ${chunks.filter(c => c.has_vector).length} 个有效向量`, `${admin() ? '<p class="muted">编辑或新增片段后，请重新建立向量。重新解析会覆盖手动修改的片段。</p><div class="modal-actions"><button class="button small" data-action="add-chunk">＋ 新增片段</button></div>' : ''}${chunks.length ? chunks.map(c => `<section class="chunk-card"><div class="chunk-head"><span>片段 ${c.ordinal}${c.page ? ` · 第 ${c.page} 页` : ''}${c.section ? ` · ${escape(c.section)}` : ''}</span>${badge(c.has_vector ? 'ready' : 'parsed', c.has_vector ? '已向量化' : '待向量化')}</div><div class="chunk-content" data-chunk-content="${c.id}">${escape(c.content)}</div>${admin() ? `<div class="chunk-actions"><button class="text-button" data-action="edit-chunk" data-id="${c.id}">编辑</button><button class="text-button danger" data-action="delete-chunk" data-id="${c.id}">删除</button></div>` : ''}</section>`).join('') : empty('暂无片段', '文档解析完成后会在这里展示内容。')}`);
}

function editChunk(chunkId) {
  const documentId = state.chunkDocument;
  const content = chunkId ? $(`[data-chunk-content="${chunkId}"]`).textContent : '';
  openModal(chunkId ? '编辑知识片段' : '新增知识片段', '保存后，该片段需要重新建立向量。', `<form id="chunk-form"><label for="chunk-text">片段内容</label><textarea id="chunk-text" rows="12" maxlength="4000" required>${escape(content)}</textarea><div class="modal-field-hint">最多 4000 字符，建议保持一个完整的知识单元。</div><div class="modal-actions"><button type="button" class="button" data-action="close-modal">取消</button><button class="button primary" type="submit">保存片段</button></div></form>`);
  $('#chunk-form').addEventListener('submit', async event => { event.preventDefault(); const button = $('button[type=submit]', event.target); button.disabled = true; try { const value = $('#chunk-text').value.trim(); if (!value) throw new Error('片段内容不能为空。'); await api(chunkId ? `/chunks/${chunkId}` : `/documents/${documentId}/chunks`, {method:chunkId ? 'PATCH' : 'POST', body:{content:value}}); toast('片段已保存，请重新建立向量。'); await refreshOverview(); await showChunks(documentId); if (state.page !== 'chat') renderCurrent(); } catch(error) { toast(error.message,true); button.disabled = false; } });
}

function userForm(target) {
  const editing = Boolean(target); openModal(editing ? `管理 ${target.username}` : '添加空间成员', '用户名为 3～40 位英文字母、数字或 _.@-；密码至少 12 个字符。', `<form id="user-form">${!editing ? '<label for="new-username">用户名</label><input id="new-username" required pattern="[a-zA-Z0-9_.@-]{3,40}" maxlength="40" autocomplete="off">' : ''}<label for="new-role">角色</label><select id="new-role"><option value="reader" ${target?.role !== 'admin' ? 'selected' : ''}>只读成员 · 浏览与问答</option><option value="admin" ${target?.role === 'admin' ? 'selected' : ''}>管理员 · 用户与知识管理</option></select>${editing ? `<label for="new-active">账号状态</label><select id="new-active"><option value="1" ${target.active === '1' ? 'selected' : ''}>启用</option><option value="0" ${target.active === '0' ? 'selected' : ''}>停用</option></select>` : ''}<label for="new-password">${editing ? '重置密码（留空则保留）' : '初始密码'}</label><input id="new-password" type="password" minlength="12" maxlength="256" autocomplete="new-password" ${editing ? '' : 'required'}><div class="modal-field-hint">权限、状态或密码修改后，该成员需要重新登录。</div><div class="modal-actions">${editing ? '<button type="button" class="button danger" id="delete-user-button">删除成员</button>' : ''}<button type="button" class="button" data-action="close-modal">取消</button><button type="submit" class="button primary">${editing ? '保存变更' : '添加成员'}</button></div></form>`);
  $('#user-form').addEventListener('submit', async event => { event.preventDefault(); const button = $('button[type=submit]', event.target); button.disabled = true; try { const body = {role:$('#new-role').value}; const password = $('#new-password').value; if (password) body.password = password; if (editing) body.active = $('#new-active').value === '1'; else body.username = $('#new-username').value; await api(editing ? `/users/${target.id}` : '/users', {method:editing ? 'PATCH':'POST',body}); closeModal(); toast('成员信息已保存。'); await renderUsers(); } catch(error) { toast(error.message,true); button.disabled = false; } });
  if (editing) $('#delete-user-button').addEventListener('click', () => confirmModal('删除成员', `确认删除 ${target.username}？该账号及其个人会话记录将被删除，共享文档会保留。`, '确认删除', async () => { await api(`/users/${target.id}`,{method:'DELETE'}); await renderUsers(); toast('成员已删除。'); }));
}

function accountMenu() {
  openModal('账号设置', `${state.user.username} · ${admin() ? '管理员' : '只读成员'}`, '<form id="password-form"><label for="old-password">当前密码</label><input id="old-password" type="password" autocomplete="current-password" required><label for="change-password">新密码</label><input id="change-password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required><p class="modal-field-hint">新密码至少 12 个字符。修改后，所有已登录的会话将退出。</p><div class="modal-actions"><button type="button" id="logout-button" class="button danger">退出登录</button><button type="submit" class="button primary">修改密码</button></div></form>');
  $('#password-form').addEventListener('submit', async event => { event.preventDefault(); try { await api('/auth/password',{method:'POST',body:{old_password:$('#old-password').value,new_password:$('#change-password').value}}); closeModal(); showLogin(); toast('密码已更新，请重新登录。'); } catch(error) { toast(error.message,true); } });
  $('#logout-button').addEventListener('click', async () => { try { await api('/auth/logout',{method:'POST'}); closeModal(); showLogin(); } catch(error) { toast(error.message,true); } });
}

async function uploadFiles(files) {
  if (!admin()) return;
  for (const file of files) {
    if (file.size > state.overview.max_upload_mb * 1024 * 1024) { toast(`${file.name} 超过文件大小限制。`,true); continue; }
    const body = new FormData(); body.append('file',file);
    try { await api('/documents',{method:'POST',body}); toast(`${file.name} 已上传，正在解析。`); }
    catch(error) { toast(`${file.name}：${error.message}`,true); }
  }
  await refreshOverview(); if (['overview','documents'].includes(state.page)) renderCurrent();
}

function retrievalTest() {
  openModal('检索测试', '只检查召回结果，不调用 DeepSeek；排名分数不代表答案可信度。', '<form id="search-form"><label for="test-query">输入一个真实问题</label><input id="test-query" required maxlength="1000" placeholder="例如：差旅报销需要什么材料？"><div class="modal-actions"><button class="button primary" type="submit">运行检索</button></div></form><div id="search-results"></div>');
  $('#search-form').addEventListener('submit', async event => { event.preventDefault(); const button=$('button',event.target); button.disabled=true; $('#search-results').textContent='正在执行 bge-m3 与关键词混合检索…'; try { const result=await api('/search',{method:'POST',body:{query:$('#test-query').value.trim()}}); $('#search-results').innerHTML=result.results.length ? result.results.map(c=>`<div class="chunk-card"><div class="chunk-head"><span>${escape(c.filename)}${c.page ? ` · 第 ${c.page} 页`:''}</span><span>余弦 ${c.cosine} · RRF ${c.rank_score}</span></div><div class="chunk-content">${escape(c.content)}</div></div>`).join('') : empty('未找到相关片段','尝试更具体的查询，或检查文档是否包含对应信息。'); } catch(error) { $('#search-results').textContent=error.message; } finally { button.disabled=false; } });
}

async function route() {
  if (!state.user) return;
  let page = location.hash.slice(1) || 'overview';
  if (!titles[page] || (!admin() && ['users','audit'].includes(page))) page = 'overview';
  state.page = page; $('#page-breadcrumb').textContent = titles[page];
  document.querySelectorAll('[data-nav]').forEach(node=>node.classList.toggle('active',node.dataset.nav===page));
  await renderCurrent();
}
async function renderCurrent() {
  if (!state.user) return;
  if (state.page === 'overview') renderOverview();
  else if (state.page === 'documents') renderDocuments();
  else if (state.page === 'chat') await renderChat();
  else if (state.page === 'users') await renderUsers();
  else if (state.page === 'audit') await renderAudit();
}

document.addEventListener('click', async event => {
  const node=event.target.closest('[data-action]'); if (!node) return;
  const {action,id}=node.dataset;
  try {
    if (action==='close-modal') closeModal();
    else if (action==='refresh') { await refreshOverview(); await renderCurrent(); toast('已更新。'); }
    else if (action==='upload') { const input=document.createElement('input');input.type='file';input.multiple=true;input.accept='.pdf,.txt,.md,.markdown';input.addEventListener('change',()=>uploadFiles(input.files).catch(e=>toast(e.message,true)));input.click(); }
    else if (action==='chunks') await showChunks(id);
    else if (action==='index' || action==='parse') { if(action==='index') { confirmModal('建立文档向量','将使用配置的 bge-m3 模型生成向量。本地模式首次运行需要下载模型；CPU 处理可能需要较长时间。','开始建立',async()=>{await api(`/documents/${id}/index`,{method:'POST'});await refreshOverview();renderCurrent();toast('已加入向量生成队列。');}); } else { await api(`/documents/${id}/parse`,{method:'POST'});await refreshOverview();renderCurrent(); } }
    else if (action==='document-menu') { const doc=state.overview.documents.find(d=>d.id===id);openModal('管理文档',doc.filename,`<form id="topic-form"><label for="topic-text">文档主题</label><input id="topic-text" value="${escape(doc.topic)}" maxlength="160" required><div class="modal-actions"><button type="button" class="button danger" data-action="delete-document" data-id="${id}">删除文档</button><button type="button" class="button" data-action="reparse-confirm" data-id="${id}">重新解析</button><button type="submit" class="button primary">保存主题</button></div></form>`);$('#topic-form').addEventListener('submit',async e=>{e.preventDefault();try{await api(`/documents/${id}`,{method:'PATCH',body:{topic:$('#topic-text').value.trim()}});closeModal();await refreshOverview();renderCurrent();toast('主题已保存。');}catch(error){toast(error.message,true);}}); }
    else if (action==='delete-document') confirmModal('删除文档','原始文件、全部片段和向量将一起删除。历史回答中的来源快照会保留。确认继续？','删除文档',async()=>{await api(`/documents/${id}`,{method:'DELETE'});await refreshOverview();renderCurrent();toast('文档已删除。');});
    else if (action==='reparse-confirm') confirmModal('重新解析文档','重新解析将覆盖手动编辑的片段，并清除原有向量。之后需要重新建立向量。','重新解析',async()=>{await api(`/documents/${id}/parse`,{method:'POST'});await refreshOverview();renderCurrent();});
    else if (action==='add-chunk') editChunk(null);
    else if (action==='edit-chunk') editChunk(id);
    else if (action==='delete-chunk') { const documentId=state.chunkDocument;confirmModal('删除知识片段','该片段和对应向量会被删除。确认继续？','删除片段',async()=>{await api(`/chunks/${id}`,{method:'DELETE'});await refreshOverview();renderCurrent();toast('片段已删除。');});state.chunkDocument=documentId; }
    else if (action==='new-user') userForm();
    else if (action==='edit-user') userForm(node.dataset);
    else if (action==='retrieval-test') retrievalTest();
    else if (action==='model-config') openModal('配置模型连接','密钥仅保存在服务端，不在网页中展示。','<p>在项目的 <code>.env</code> 中填写 DeepSeek 的 API 地址、密钥和实际模型 ID，然后重启服务。模型须支持工具调用。</p><p>bge-m3 可选择本地运行或 Embedding API。使用本地模式时，先安装 <code>requirements-local-model.txt</code>，再在文档知识库点击「建立向量」。</p><p class="muted">详细步骤见项目 README.md。使用云端生成模型时，问题与检索出的相关片段会发送至你配置的服务商。</p>');
    else if (action==='new-chat') { if(state.busy) return toast('当前对话仍在回答中，请稍候。');state.current=null;state.messages=[];if(state.page!=='chat')location.hash='chat';else await renderChat(); }
    else if (action==='conversation') { if(state.busy)return;const result=await api(`/conversations/${id}`);state.current=id;state.messages=result.messages;await renderChat(); }
    else if (action==='suggest') { $('#question').value=node.dataset.question;$('#question').focus(); }
    else if (action==='source') { const source=state.messages[Number(node.dataset.message)]?.citations?.find(c=>c.id===id);if(source)openModal(ChatFormat.sourceLabel(source),`${source.page ? `第 ${source.page} 页 · `:''}${source.section || source.topic} · 回答时的来源快照`,`<div class="source-detail">${escape(source.content)}</div><p class="muted">此快照保留回答时引用的内容；文档后续更新不会改写历史依据。</p>`); }
  } catch(error) { toast(error.message,true); }
});
document.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.matches('.conversation-item'))event.target.click();});
$('#account-button').addEventListener('click',accountMenu);
window.addEventListener('hashchange',()=>route().catch(e=>toast(e.message,true)));
setInterval(async()=>{if(!state.user||!['overview','documents'].includes(state.page)||$('#modal').open||document.activeElement?.id==='document-filter')return;try{const before=JSON.stringify(state.overview);await refreshOverview();if(before!==JSON.stringify(state.overview))renderCurrent();}catch(_){/* Login expiry is handled by api(); keep the interface responsive. */}},4000);
(async()=>{try{await enter(await api('/auth/me'));}catch(error){showLogin();if(error.status!==401)toast(error.message,true);}})();
