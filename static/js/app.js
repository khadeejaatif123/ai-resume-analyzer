/* ═══════════════════════════════════════════════════════════════
   RecruitAI — app.js
   Handles: drag-drop upload, polling, role tabs, table rendering
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ── State ──────────────────────────────────────────────────────
let currentRole   = 'all';   // active role key
let allCandidates = [];       // full list (all roles, all statuses)
let pollTimer     = null;
let queueItems    = {};       // candidateId → queue DOM item info

// ── DOM refs (set after DOMContentLoaded) ─────────────────────
let dropZone, fileInput, uploadQueue, queueList;
let candidatesBody, emptyRow, dashboardTitle, exportBtn, statusBar;
let totalCount;

// ── Init ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  dropZone      = document.getElementById('dropZone');
  fileInput     = document.getElementById('fileInput');
  uploadQueue   = document.getElementById('uploadQueue');
  queueList     = document.getElementById('queueList');
  candidatesBody = document.getElementById('candidatesBody');
  emptyRow      = document.getElementById('emptyRow');
  dashboardTitle = document.getElementById('dashboardTitle');
  exportBtn     = document.getElementById('exportBtn');
  statusBar     = document.getElementById('statusBar');
  totalCount    = document.getElementById('totalCount');

  setupDragDrop();
  setupRoleTabs();
  fetchAndRefresh();
  startPolling();

  document.getElementById('clearQueue').addEventListener('click', clearCompleted);
});

// ── Drag & Drop ────────────────────────────────────────────────
function setupDragDrop() {
  dropZone.addEventListener('click', (e) => {
    if (e.target.tagName !== 'LABEL') fileInput.click();
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) uploadFiles(Array.from(fileInput.files));
    fileInput.value = '';
  });

  ['dragenter', 'dragover'].forEach(evt =>
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); })
  );
  ['dragleave', 'drop'].forEach(evt =>
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.remove('drag-over'); })
  );
  dropZone.addEventListener('drop', (e) => {
    const files = Array.from(e.dataTransfer.files);
    if (files.length) uploadFiles(files);
  });
}

// ── File Upload ────────────────────────────────────────────────
async function uploadFiles(files) {
  uploadQueue.style.display = 'block';

  // Batch all at once if >1
  if (files.length > 1) {
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));

    // Add placeholder items first
    files.forEach(f => addQueueItem(null, f.name, 'uploading'));

    try {
      const res  = await fetch('/api/resumes/batch', { method: 'POST', body: formData });
      const data = await res.json();

      // Clear placeholder items for this batch and replace with real ones
      data.forEach(record => {
        if (record.error) return;
        addQueueItem(record.candidate_id, record.filename || record.original_filename, 'queued', record.uploaded_at, record.queue_position);
      });
    } catch (err) {
      console.error('Batch upload failed:', err);
    }
  } else {
    // Single file
    const file     = files[0];
    const tmpId    = 'tmp-' + Date.now();
    const li       = addQueueItem(tmpId, file.name, 'uploading');
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res    = await fetch('/api/resumes', { method: 'POST', body: formData });
      const record = await res.json();
      // Replace temp item
      li.dataset.candidateId = record.candidate_id;
      updateQueueItemStatus(li, 'queued');
      const metaEl = li.querySelector('.queue-item-meta');
      if (metaEl) metaEl.textContent = `Queue #${record.queue_position} · ${fmtTime(record.uploaded_at)}`;
    } catch (err) {
      updateQueueItemStatus(li, 'failed');
    }
  }

  // Refresh table immediately
  fetchAndRefresh();
}

function addQueueItem(candidateId, filename, status, uploadedAt, queuePos) {
  const li = document.createElement('li');
  li.className = 'queue-item';
  li.dataset.candidateId = candidateId || '';

  const ext  = filename.split('.').pop().toLowerCase();
  const icon = ext === 'pdf' ? '📄' : ext === 'docx' ? '📝' : '📃';

  li.innerHTML = `
    <div class="queue-item-icon">${icon}</div>
    <div class="queue-item-info">
      <div class="queue-item-name" title="${escHtml(filename)}">${escHtml(filename)}</div>
      <div class="queue-item-meta">${uploadedAt ? `Queue #${queuePos} · ${fmtTime(uploadedAt)}` : 'Uploading…'}</div>
    </div>
    <span class="queue-status queue-status--${status}">${capFirst(status)}</span>
  `;

  queueList.appendChild(li);
  if (candidateId) queueItems[candidateId] = li;
  return li;
}

function updateQueueItemStatus(li, status) {
  if (!li) return;
  const span = li.querySelector('.queue-status');
  if (span) {
    span.className = `queue-status queue-status--${status}`;
    span.textContent = capFirst(status);
  }
}

function clearCompleted() {
  const items = queueList.querySelectorAll('.queue-item');
  items.forEach(li => {
    const span = li.querySelector('.queue-status');
    if (span && (span.textContent === 'Complete' || span.textContent === 'Failed')) {
      li.remove();
    }
  });
  if (!queueList.children.length) uploadQueue.style.display = 'none';
}

// ── Polling ────────────────────────────────────────────────────
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchAndRefresh, 4000);
}

async function fetchAndRefresh() {
  try {
    const res  = await fetch('/api/candidates');
    allCandidates = await res.json();
    updateBadges();
    updateStatusBar();
    updateQueueStatuses();
    renderTable();
  } catch (e) {
    console.warn('Refresh error:', e);
  }
}

function updateQueueStatuses() {
  allCandidates.forEach(c => {
    const li = queueItems[c.candidate_id];
    if (li) updateQueueItemStatus(li, c.analysis_status);
  });
}

// ── Role Tabs ─────────────────────────────────────────────────
function setupRoleTabs() {
  document.querySelectorAll('.role-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.role-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRole = btn.dataset.role;
      renderTable();
      updateExportButton();
    });
  });
}

function updateBadges() {
  // Count complete candidates per role
  const counts = { all: 0, unclassified: 0 };

  allCandidates.forEach(c => {
    if (c.analysis_status !== 'complete') return;
    counts.all = (counts.all || 0) + 1;

    const role = c.primary_role || '';
    const key  = roleDisplayToKey(role);
    if (key) {
      counts[key] = (counts[key] || 0) + 1;
    } else {
      counts.unclassified = (counts.unclassified || 0) + 1;
    }
  });

  // Update all badges
  Object.keys(counts).forEach(k => {
    const el = document.getElementById(`badge-${k}`);
    if (el) el.textContent = counts[k] || 0;
  });

  if (totalCount) totalCount.textContent = `${counts.all || 0} candidate${counts.all !== 1 ? 's' : ''}`;
}

function updateStatusBar() {
  const counts = { queued: 0, processing: 0, complete: 0, failed: 0 };
  allCandidates.forEach(c => { counts[c.analysis_status] = (counts[c.analysis_status] || 0) + 1; });

  const hasAny = Object.values(counts).some(v => v > 0);
  statusBar.style.display = hasAny ? 'flex' : 'none';

  document.getElementById('statusQueued').textContent     = `${counts.queued} queued`;
  document.getElementById('statusProcessing').textContent = `${counts.processing} processing`;
  document.getElementById('statusComplete').textContent   = `${counts.complete} complete`;
  document.getElementById('statusFailed').textContent     = `${counts.failed} failed`;
}

function updateExportButton() {
  if (currentRole === 'all') {
    exportBtn.style.display = 'none';
  } else {
    exportBtn.style.display = 'flex';
  }
}

// ── Table Rendering ────────────────────────────────────────────
function renderTable() {
  // Filter
  let filtered = allCandidates.filter(c => c.analysis_status === 'complete');

  if (currentRole === 'all') {
    dashboardTitle.textContent = 'All Candidates';
  } else if (currentRole === 'unclassified') {
    dashboardTitle.textContent = 'Other / Unclassified';
    filtered = filtered.filter(c => {
      const key = roleDisplayToKey(c.primary_role || '');
      return !key || key === 'unclassified';
    });
  } else {
    const taxonomy = ROLE_TAXONOMY.find(r => r.role_key === currentRole);
    const displayName = taxonomy ? taxonomy.display_name : currentRole;
    dashboardTitle.textContent = displayName;
    filtered = filtered.filter(c => {
      const key = roleDisplayToKey(c.primary_role || '');
      return key === currentRole;
    });
  }

  // Sort: experience_score DESC, uploaded_at ASC, candidate_id ASC
  filtered.sort((a, b) => {
    const sa = a.experience_score || 0;
    const sb = b.experience_score || 0;
    if (sa !== sb) return sb - sa;
    if (a.uploaded_at < b.uploaded_at) return -1;
    if (a.uploaded_at > b.uploaded_at) return 1;
    if (a.candidate_id < b.candidate_id) return -1;
    if (a.candidate_id > b.candidate_id) return 1;
    return 0;
  });

  // Annotate ties (epsilon = 1.0)
  for (let i = 1; i < filtered.length; i++) {
    filtered[i]._fcfsTie = Math.abs((filtered[i].experience_score || 0) - (filtered[i-1].experience_score || 0)) <= 1.0;
  }
  if (filtered.length > 0) filtered[0]._fcfsTie = false;

  // Render rows
  // Remove all rows except emptyRow
  Array.from(candidatesBody.children).forEach(row => {
    if (row.id !== 'emptyRow') row.remove();
  });

  if (filtered.length === 0) {
    emptyRow.style.display = '';
    updateExportButton();
    return;
  }

  emptyRow.style.display = 'none';

  filtered.forEach((c, idx) => {
    const rank  = idx + 1;
    const topN  = rank <= 3;
    const name  = c.candidate_name || 'Unknown';
    const initial = name[0].toUpperCase();

    const row = document.createElement('tr');
    row.innerHTML = `
      <td class="col-rank">
        <div class="rank-cell">
          <div class="rank-num ${topN ? 'rank-num--top3' : ''}">${rank}</div>
        </div>
        ${c._fcfsTie ? '<span class="fcfs-badge" title="Tie broken by upload order (FCFS)">FCFS</span>' : ''}
      </td>
      <td class="col-name">
        <div class="name-cell">
          <div class="name-avatar" style="${avatarColor(initial)}">${initial}</div>
          <div>
            <div class="name-text">${escHtml(name)}</div>
            <div class="name-file">${escHtml(c.original_filename || '')}</div>
          </div>
        </div>
      </td>
      <td class="col-role">
        <div style="font-size:0.8rem;color:var(--color-text-secondary);max-width:150px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${escHtml(c.primary_role || '—')}">
          ${escHtml(shortRole(c.primary_role || '—'))}
        </div>
      </td>
      <td class="col-score"><span class="exp-score">${(c.experience_score || 0).toFixed(2)}</span></td>
      <td class="col-overall" style="font-weight:600;color:${scoreColor(c.overall_score)}">${c.overall_score || 0}</td>
      <td class="col-seniority"><span class="seniority-badge seniority-badge--${c.seniority_level || 'junior'}">${capFirst(c.seniority_level || 'junior')}</span></td>
      <td class="col-years" style="font-size:0.855rem">${(c.total_years_experience || 0).toFixed(1)}</td>
      <td class="col-queue"><span class="queue-pos">#${c.queue_position}</span></td>
      <td class="col-time ts-cell">${fmtTime(c.uploaded_at)}</td>
      <td class="col-action"><a href="/candidate/${c.candidate_id}" class="btn-view">View →</a></td>
    `;
    candidatesBody.appendChild(row);
  });

  updateExportButton();
}

// ── CSV Export ─────────────────────────────────────────────────
function exportCSV() {
  if (currentRole === 'all') return;
  window.location.href = `/api/roles/${currentRole}/export.csv`;
}

// ── Utilities ──────────────────────────────────────────────────
function roleDisplayToKey(displayName) {
  const found = ROLE_TAXONOMY.find(r => r.display_name === displayName);
  return found ? found.role_key : null;
}

function shortRole(name) {
  // Shorten for table display
  const map = {
    'Software Engineering — Frontend':  'Frontend Eng.',
    'Software Engineering — Backend':   'Backend Eng.',
    'Software Engineering — Full Stack':'Full Stack Eng.',
    'Data / Analytics':                  'Data / Analytics',
    'Design (UX/UI/Product Design)':     'Design',
    'Customer Support / Success':        'Customer Success',
    'Human Resources / Recruiting':      'HR / Recruiting',
    'Finance / Accounting':              'Finance',
  };
  return map[name] || name;
}

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
  } catch { return iso; }
}

function capFirst(s) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function scoreColor(score) {
  if (score >= 75) return 'var(--color-success)';
  if (score >= 50) return 'var(--color-warning)';
  return 'var(--color-danger)';
}

const AVATAR_COLORS = [
  'background:#4361EE;color:#fff',
  'background:#7C3AED;color:#fff',
  'background:#059669;color:#fff',
  'background:#DB2777;color:#fff',
  'background:#D97706;color:#fff',
  'background:#0891B2;color:#fff',
];
function avatarColor(letter) {
  return AVATAR_COLORS[letter.charCodeAt(0) % AVATAR_COLORS.length];
}
