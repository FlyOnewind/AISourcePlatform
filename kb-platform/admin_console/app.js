// ============================================
// AI知识库管理中台 - 管理后台
// ============================================

// 配置
const API_KEY_STORAGE = 'kb_platform_admin_api_key';
const REMEMBER_KEY_STORAGE = 'kb_platform_remember_key';

// 状态管理
const appState = {
  currentPage: 'overview',
  selectedKbId: null,
  selectedKbName: '',
  charts: {},
  capabilitiesView: 'table',
  auditView: 'table',
  integrationTab: 'candidates'
};

// ============================================
// 工具函数
// ============================================

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatDate(dateStr) {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleString('zh-CN');
}

function badge(status) {
  const statusMap = {
    'published': { class: 'badge-published', text: '已发布' },
    'draft': { class: 'badge-draft', text: '草稿' },
    'disabled': { class: 'badge-disabled', text: '已禁用' },
    'active': { class: 'badge-published', text: '活跃' },
    'inactive': { class: 'badge-disabled', text: '停用' },
    'pending': { class: 'badge-draft', text: '待处理' },
    'processed': { class: 'badge-blue', text: '已处理' },
    'error': { class: 'badge-disabled', text: '错误' },
    'allow': { class: 'badge-published', text: '成功' },
    'deny': { class: 'badge-disabled', text: '拒绝' }
  };
  const s = statusMap[status] || { class: 'badge-gray', text: status };
  return `<span class="badge ${s.class}">${s.text}</span>`;
}

function securityLevelBadge(level) {
  const levelMap = {
    'public': { class: 'badge-blue', text: '公开' },
    'internal': { class: 'badge-draft', text: '内部' },
    'confidential': { class: 'badge-yellow', text: '机密' },
    'restricted': { class: 'badge-disabled', text: '受限' }
  };
  const l = levelMap[level] || { class: 'badge-gray', text: level };
  return `<span class="badge ${l.class}">${l.text}</span>`;
}

// ============================================
// Toast 通知
// ============================================

function showToast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const iconSvg = {
    'success': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>',
    'error': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>',
    'warning': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>',
    'info': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>'
  };

  toast.innerHTML = `
    <div class="toast-icon">${iconSvg[type]}</div>
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  `;

  container.appendChild(toast);

  toast.querySelector('.toast-close').addEventListener('click', () => {
    toast.style.animation = 'slideOut 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  });

  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ============================================
// 模态框
// ============================================

function openModal(options) {
  const { title, content, size = '', footerButtons = [] } = options;
  const overlay = document.getElementById('modal-overlay');
  const modal = document.getElementById('modal');
  const modalTitle = document.getElementById('modal-title');
  const modalBody = document.getElementById('modal-body');
  const modalFooter = document.getElementById('modal-footer');

  modal.className = `modal ${size}`;
  modalTitle.textContent = title;
  modalBody.innerHTML = content;

  if (footerButtons.length > 0) {
    modalFooter.innerHTML = footerButtons.map(btn =>
      `<button class="btn ${btn.class || 'btn-secondary'}" data-action="${btn.action || ''}">${btn.text}</button>`
    ).join('');
  } else {
    modalFooter.innerHTML = '<button class="btn btn-primary" data-action="close">关闭</button>';
  }

  overlay.classList.add('active');

  return new Promise((resolve) => {
    modalFooter.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const action = e.target.dataset.action;
        closeModal();
        resolve(action);
      });
    });
  });
}

function closeModal() {
  const overlay = document.getElementById('modal-overlay');
  overlay.classList.remove('active');
}

// ============================================
// API 封装
// ============================================

function apiKey() {
  return localStorage.getItem(API_KEY_STORAGE);
}

async function apiFetch(path, options = {}) {
  const headers = Object.assign({
    'X-API-Key': apiKey()
  }, options.headers || {});

  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const resp = await fetch(path, { ...options, headers });
    const body = await resp.json().catch(() => ({}));

    if (!resp.ok || body.success === false) {
      const msg = (body.error && body.error.message) || body.detail?.message || `请求失败 (${resp.status})`;
      throw new Error(msg);
    }

    return body.data;
  } catch (error) {
    throw error;
  }
}

// ============================================
// 认证相关
// ============================================

function showApp() {
  document.getElementById('login-view').classList.add('hidden');
  document.getElementById('app-view').classList.remove('hidden');
  loadOverview();
  initCharts();
}

function showLogin() {
  document.getElementById('login-view').classList.remove('hidden');
  document.getElementById('app-view').classList.add('hidden');
}

async function login(apiKeyInput) {
  if (!apiKeyInput.trim()) {
    showToast('请输入 API Key', 'warning');
    return;
  }

  const remember = document.getElementById('remember-key').checked;
  if (remember) {
    localStorage.setItem(API_KEY_STORAGE, apiKeyInput.trim());
    localStorage.setItem(REMEMBER_KEY_STORAGE, 'true');
  } else {
    localStorage.setItem(API_KEY_STORAGE, apiKeyInput.trim());
    localStorage.removeItem(REMEMBER_KEY_STORAGE);
  }

  try {
    await apiFetch('/api/v1/metrics/overview');
    showToast('登录成功', 'success');
    showApp();
  } catch (e) {
    showToast(`登录失败: ${e.message}`, 'error');
    localStorage.removeItem(API_KEY_STORAGE);
  }
}

function logout() {
  localStorage.removeItem(API_KEY_STORAGE);
  showToast('已退出登录', 'info');
  showLogin();
}

// ============================================
// 导航
// ============================================

function navigateToPage(pageName) {
  document.querySelectorAll('.nav-list .nav-link').forEach(link => {
    link.classList.remove('active');
    if (link.dataset.page === pageName) {
      link.classList.add('active');
    }
  });

  document.querySelectorAll('.page').forEach(page => {
    page.classList.remove('active');
  });
  document.getElementById(`page-${pageName}`).classList.add('active');

  appState.currentPage = pageName;

  switch (pageName) {
    case 'overview':
      loadOverview();
      break;
    case 'capabilities':
      loadCapabilities();
      break;
    case 'skills':
      loadSkills();
      break;
    case 'prompts':
      loadPrompts();
      break;
    case 'knowledge':
      loadKnowledgeBases();
      break;
    case 'agents':
      loadAgents();
      break;
    case 'integration':
      loadIntegration();
      break;
    case 'audit':
      loadAuditLogs();
      break;
  }
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('collapsed');
}

function toggleMobileMenu() {
  document.getElementById('sidebar').classList.toggle('mobile-open');
}

// ============================================
// 总览页面
// ============================================

const overviewCardConfig = [
  { label: '能力总数', key: 'total_capabilities', icon: 'capability' },
  { label: '已发布能力', key: 'published_capabilities', icon: 'check' },
  { label: '知识库数量', key: 'total_knowledge_bases', icon: 'knowledge' },
  { label: '文档数量', key: 'total_documents', icon: 'document' },
  { label: 'Agent数量', key: 'total_agents', icon: 'agent' },
  { label: '近24h调用量', key: 'today_invocations', icon: 'activity' },
  { label: '近24h成功率', key: 'today_success_rate', icon: 'success', format: (v) => `${(v * 100).toFixed(1)}%` },
  { label: '平均耗时', key: 'avg_latency_ms', icon: 'time', format: (v) => `${v}ms` }
];

function getCardIcon(type) {
  const icons = {
    'capability': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>',
    'check': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>',
    'knowledge': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" /></svg>',
    'document': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    'agent': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>',
    'activity': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>',
    'success': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    'time': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>'
  };
  return icons[type] || icons.capability;
}

async function loadOverview() {
  const container = document.getElementById('overview-cards');
  container.innerHTML = '<div class="loading-skeleton" style="height: 120px;"></div>'.repeat(4);

  try {
    const data = await apiFetch('/api/v1/metrics/overview');

    container.innerHTML = overviewCardConfig.map(cfg => {
      const value = data[cfg.key];
      const displayValue = cfg.format ? cfg.format(value) : value;
      return `
        <div class="stat-card">
          <div class="stat-card-icon">
            ${getCardIcon(cfg.icon)}
          </div>
          <div class="stat-card-label">${cfg.label}</div>
          <div class="stat-card-value">${displayValue}</div>
        </div>
      `;
    }).join('');

    updateCharts(data);
  } catch (e) {
    container.innerHTML = `<div class="card"><p style="color: var(--color-danger);">加载失败: ${e.message}</p></div>`;
  }
}

function initCharts() {
  // 调用趋势图
  const invocationCtx = document.getElementById('invocation-chart');
  if (invocationCtx && !appState.charts.invocation) {
    appState.charts.invocation = new Chart(invocationCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: '调用次数',
          data: [],
          borderColor: 'rgb(56, 189, 248)',
          backgroundColor: 'rgba(56, 189, 248, 0.1)',
          fill: true,
          tension: 0.4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.1)' },
            ticks: { color: 'rgba(255, 255, 255, 0.7)' }
          },
          y: {
            grid: { color: 'rgba(255, 255, 255, 0.1)' },
            ticks: { color: 'rgba(255, 255, 255, 0.7)' }
          }
        }
      }
    });
  }

  // 资产分布图
  const assetsCtx = document.getElementById('assets-chart');
  if (assetsCtx && !appState.charts.assets) {
    appState.charts.assets = new Chart(assetsCtx, {
      type: 'doughnut',
      data: {
        labels: ['能力', '知识库', 'Skills', 'Prompts', 'Agents'],
        datasets: [{
          data: [0, 0, 0, 0, 0],
          backgroundColor: [
            'rgba(56, 189, 248, 0.8)',
            'rgba(74, 222, 128, 0.8)',
            'rgba(167, 139, 250, 0.8)',
            'rgba(251, 191, 36, 0.8)',
            'rgba(96, 165, 250, 0.8)'
          ]
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: 'rgba(255, 255, 255, 0.7)' }
          }
        }
      }
    });
  }
}

function updateCharts(data) {
  // 模拟调用趋势数据
  const hours = [];
  const invocations = [];
  const now = new Date();
  for (let i = 23; i >= 0; i--) {
    const h = new Date(now - i * 60 * 60 * 1000);
    hours.push(`${h.getHours()}:00`);
    invocations.push(Math.floor(Math.random() * 100 + 50));
  }

  if (appState.charts.invocation) {
    appState.charts.invocation.data.labels = hours;
    appState.charts.invocation.data.datasets[0].data = invocations;
    appState.charts.invocation.update();
  }

  if (appState.charts.assets) {
    appState.charts.assets.data.datasets[0].data = [
      data.total_capabilities,
      data.total_knowledge_bases,
      Math.floor(data.total_capabilities * 0.3),
      Math.floor(data.total_capabilities * 0.4),
      data.total_agents
    ];
    appState.charts.assets.update();
  }
}

// ============================================
// 能力目录
// ============================================

async function loadCapabilities() {
  const type = document.getElementById('cap-type-filter')?.value || '';
  const status = document.getElementById('cap-status-filter')?.value || '';
  const tableBody = document.getElementById('cap-table-body');
  const gridView = document.getElementById('cap-grid-view');

  tableBody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    let qs = '';
    const params = [];
    if (type) params.push(`type=${encodeURIComponent(type)}`);
    if (status) params.push(`status=${encodeURIComponent(status)}`);
    if (params.length) qs = '?' + params.join('&');

    const caps = await apiFetch(`/api/v1/capabilities${qs}`);

    // 表格视图
    tableBody.innerHTML = caps.length ? caps.map(c => `
      <tr>
        <td><strong>${escapeHtml(c.name)}</strong></td>
        <td>${escapeHtml(c.type)}</td>
        <td>${escapeHtml(c.business_domain || '-')}</td>
        <td>${badge(c.status)}</td>
        <td>v${escapeHtml(c.current_version)}</td>
        <td>${securityLevelBadge(c.security_level)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-secondary" onclick="openCapabilityDetail('${c.id}')">详情</button>
            <button class="btn btn-sm btn-primary" onclick="showCapabilityDetailPage('${c.id}')">查看</button>
          </div>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无数据</td></tr>';

    // 网格视图
    gridView.innerHTML = caps.length ? caps.map(c => `
      <div class="asset-card" onclick="showCapabilityDetailPage('${c.id}')">
        <div class="asset-card-header">
          <div class="asset-card-icon capability">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div class="asset-card-status">${badge(c.status)}</div>
        </div>
        <div class="asset-card-body">
          <h4 class="asset-card-title">${escapeHtml(c.name)}</h4>
          <p class="asset-card-subtitle">${escapeHtml(c.capability_key)}</p>
          <p class="asset-card-description">${escapeHtml(c.description || '暂无描述')}</p>
        </div>
        <div class="asset-card-footer">
          <span class="asset-card-meta">${escapeHtml(c.type)}</span>
          <span class="asset-card-meta">v${escapeHtml(c.current_version)}</span>
        </div>
      </div>
    `).join('') : `
      <div class="card" style="grid-column: 1 / -1;">
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
            </svg>
          </div>
          <h3 class="empty-state-title">暂无能力</h3>
          <p class="empty-state-description">创建第一个能力开始使用</p>
        </div>
      </div>
    `;
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

async function openCapabilityDetail(id) {
  try {
    const [data, permissions] = await Promise.all([
      apiFetch(`/api/v1/capabilities/${id}`),
      apiFetch(`/api/v1/capabilities/${id}/permissions`)
    ]);
    showAssetDetail(`Capability: ${data.name}`, { ...data, permissions });
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

async function showCapabilityDetailPage(id) {
  navigateToPage('detail');
  await openCapabilityDetail(id);
}

function toggleCapabilitiesView(view) {
  appState.capabilitiesView = view;
  const tableView = document.getElementById('cap-table-view');
  const gridView = document.getElementById('cap-grid-view');

  document.querySelectorAll('#capabilities .view-toggle button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === view);
  });

  if (view === 'table') {
    tableView.classList.remove('hidden');
    gridView.classList.add('hidden');
  } else {
    tableView.classList.add('hidden');
    gridView.classList.remove('hidden');
  }
}

// ============================================
// Skills
// ============================================

async function loadSkills() {
  const tableBody = document.getElementById('skill-table-body');
  tableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    const skills = await apiFetch('/api/v1/skills');
    tableBody.innerHTML = skills.length ? skills.map(s => `
      <tr>
        <td><strong>${escapeHtml(s.name)}</strong></td>
        <td><code>${escapeHtml(s.skill_key)}</code></td>
        <td>${escapeHtml(s.type || '-')}</td>
        <td>${badge(s.status)}</td>
        <td>v${escapeHtml(s.version)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-secondary" onclick="openSkillDetail('${s.id}')">详情</button>
          </div>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无数据</td></tr>';
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

async function openSkillDetail(id) {
  try {
    const data = await apiFetch(`/api/v1/skills/${id}`);
    showAssetDetail(`Skill: ${data.name}`, data);
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

// ============================================
// Prompts
// ============================================

async function loadPrompts() {
  const tableBody = document.getElementById('prompt-table-body');
  tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    const prompts = await apiFetch('/api/v1/prompts');
    tableBody.innerHTML = prompts.length ? prompts.map(p => `
      <tr>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td><code>${escapeHtml(p.prompt_key)}</code></td>
        <td>${badge(p.status)}</td>
        <td>v${escapeHtml(p.version)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-secondary" onclick="openPromptDetail('${p.id}')">详情</button>
          </div>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无数据</td></tr>';
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

async function openPromptDetail(id) {
  try {
    const data = await apiFetch(`/api/v1/prompts/${id}`);
    showAssetDetail(`Prompt: ${data.name}`, data);
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

// ============================================
// 知识库
// ============================================

async function loadKnowledgeBases() {
  const gridView = document.getElementById('kb-grid-view');
  const kbSelect = document.getElementById('upload-kb-id');

  gridView.innerHTML = '<div class="loading-skeleton" style="height: 150px;"></div>'.repeat(3);

  try {
    const kbs = await apiFetch('/api/v1/knowledge-bases');

    if (kbSelect) {
      kbSelect.innerHTML = '<option value="">请选择知识库</option>' + kbs.map(kb =>
        `<option value="${kb.id}">${kb.name} (${kb.kb_key})</option>`
      ).join('');
    }

    gridView.innerHTML = kbs.length ? kbs.map(kb => `
      <div class="card" style="cursor: pointer;" onclick="loadDocuments('${kb.id}', '${escapeHtml(kb.name)}')">
        <div class="card-header" style="padding-bottom: var(--spacing-md);">
          <div style="display: flex; align-items: center; gap: var(--spacing-md);">
            <div class="asset-card-icon knowledge">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            </div>
            <div>
              <h4 style="margin: 0;">${escapeHtml(kb.name)}</h4>
              <p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">${escapeHtml(kb.kb_key)}</p>
            </div>
          </div>
          ${badge(kb.status)}
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: var(--spacing-md);">
          <div>
            <p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">业务域</p>
            <p style="margin: 0;">${escapeHtml(kb.business_domain || '-')}</p>
          </div>
          <div>
            <p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">密级</p>
            <p style="margin: 0;">${securityLevelBadge(kb.security_level)}</p>
          </div>
        </div>
        <div style="margin-top: var(--spacing-md); padding-top: var(--spacing-md); border-top: 1px solid var(--border-subtle); display: flex; gap: var(--spacing-sm);">
          <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); openKnowledgeDetail('${kb.id}')">详情</button>
          <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); loadDocuments('${kb.id}', '${escapeHtml(kb.name)}')">查看文档</button>
        </div>
      </div>
    `).join('') : `
      <div class="card" style="grid-column: 1 / -1;">
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
          </div>
          <h3 class="empty-state-title">暂无知识库</h3>
          <p class="empty-state-description">创建第一个知识库开始上传文档</p>
        </div>
      </div>
    `;
  } catch (e) {
    gridView.innerHTML = `<div class="card" style="grid-column: 1 / -1;"><p style="color: var(--color-danger);">加载失败: ${e.message}</p></div>`;
  }
}

async function openKnowledgeDetail(id) {
  try {
    const [detail, docs] = await Promise.all([
      apiFetch(`/api/v1/knowledge-bases/${id}`),
      apiFetch(`/api/v1/knowledge-bases/${id}/documents`)
    ]);
    showAssetDetail(`Knowledge Base: ${detail.name}`, { ...detail, documents: docs });
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

async function createKnowledgeBase() {
  const kbKey = document.getElementById('kb-create-key').value.trim();
  const kbName = document.getElementById('kb-create-name').value.trim();
  const kbDomain = document.getElementById('kb-create-domain').value.trim();
  const kbSecurity = document.getElementById('kb-create-security').value;

  if (!kbKey || !kbName) {
    showToast('请填写知识库 Key 和名称', 'warning');
    return;
  }

  try {
    await apiFetch('/api/v1/knowledge-bases', {
      method: 'POST',
      body: JSON.stringify({
        kb_key: kbKey,
        name: kbName,
        business_domain: kbDomain || null,
        security_level: kbSecurity
      })
    });

    document.getElementById('kb-create-key').value = '';
    document.getElementById('kb-create-name').value = '';
    document.getElementById('kb-create-domain').value = '';
    document.getElementById('kb-create-form').classList.add('hidden');

    showToast('知识库创建成功', 'success');
    loadKnowledgeBases();
  } catch (e) {
    showToast(`创建失败: ${e.message}`, 'error');
  }
}

async function loadDocuments(kbId, kbName) {
  appState.selectedKbId = kbId;
  appState.selectedKbName = kbName || '知识库';

  const docSection = document.getElementById('doc-section');
  const docDesc = document.getElementById('doc-section-desc');
  const kbSelect = document.getElementById('upload-kb-id');
  const tableBody = document.getElementById('doc-table-body');

  docSection.classList.remove('hidden');
  docDesc.textContent = `管理「${appState.selectedKbName}」中的文档`;

  if (kbSelect) kbSelect.value = kbId;
  tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    const docs = await apiFetch(`/api/v1/knowledge-bases/${kbId}/documents`);
    tableBody.innerHTML = docs.length ? docs.map(d => `
      <tr>
        <td><strong>${escapeHtml(d.title)}</strong></td>
        <td>${badge(d.parse_status)}</td>
        <td>${d.chunk_count || 0}</td>
        <td>v${escapeHtml(d.version)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-secondary" onclick="openDocumentDetail('${d.id}')">详情</button>
          </div>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无文档</td></tr>';
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

async function openDocumentDetail(id) {
  try {
    const data = await apiFetch(`/api/v1/documents/${id}`);
    showAssetDetail(`Document: ${data.title}`, data);
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

async function uploadDocuments() {
  const kbId = appState.selectedKbId || document.getElementById('upload-kb-id')?.value;
  const fileInput = document.getElementById('upload-file');

  if (!kbId) {
    showToast('请先选择知识库', 'warning');
    return;
  }
  if (!fileInput.files.length) {
    showToast('请选择要上传的文件', 'warning');
    return;
  }

  try {
    for (const file of fileInput.files) {
      const formData = new FormData();
      formData.append('file', file);
      await apiFetch(`/api/v1/knowledge-bases/${kbId}/documents`, {
        method: 'POST',
        body: formData
      });
    }

    showToast('文档上传成功', 'success');
    fileInput.value = '';
    document.getElementById('upload-section').classList.add('hidden');
    loadDocuments(kbId, appState.selectedKbName);
  } catch (e) {
    showToast(`上传失败: ${e.message}`, 'error');
  }
}

// ============================================
// Agents
// ============================================

async function loadAgents() {
  const gridView = document.getElementById('agents-grid-view');
  gridView.innerHTML = '<div class="loading-skeleton" style="height: 150px;"></div>'.repeat(3);

  try {
    const agents = await apiFetch('/api/v1/agents');

    gridView.innerHTML = agents.length ? agents.map(a => `
      <div class="card">
        <div class="card-header" style="padding-bottom: var(--spacing-md);">
          <div style="display: flex; align-items: center; gap: var(--spacing-md);">
            <div class="user-avatar" style="width: 48px; height: 48px; font-size: var(--font-size-lg);">
              ${a.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h4 style="margin: 0;">${escapeHtml(a.name)}</h4>
              <p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">${escapeHtml(a.role || '-')}</p>
            </div>
          </div>
          ${badge(a.status === 'active' ? 'published' : 'disabled')}
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: var(--spacing-md);">
          <div>
            <p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">业务域</p>
            <p style="margin: 0;">${escapeHtml(a.business_domain || '-')}</p>
          </div>
          <div>
            <p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">主控</p>
            <p style="margin: 0;">${a.is_master ? '是' : '否'}</p>
          </div>
        </div>
      </div>
    `).join('') : `
      <div class="card" style="grid-column: 1 / -1;">
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
          </div>
          <h3 class="empty-state-title">暂无Agent</h3>
          <p class="empty-state-description">创建第一个Agent开始使用</p>
        </div>
      </div>
    `;
  } catch (e) {
    gridView.innerHTML = `<div class="card" style="grid-column: 1 / -1;"><p style="color: var(--color-danger);">加载失败: ${e.message}</p></div>`;
  }
}

// ============================================
// 集成管理
// ============================================

async function loadIntegration() {
  if (appState.integrationTab === 'candidates') {
    await loadAssetCandidates();
  } else {
    await loadCollaborationTasks();
  }
}

function switchIntegrationTab(tab) {
  appState.integrationTab = tab;

  document.querySelectorAll('#integration-tabs button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });

  document.getElementById('candidates-tab').classList.toggle('hidden', tab !== 'candidates');
  document.getElementById('tasks-tab').classList.toggle('hidden', tab !== 'tasks');

  loadIntegration();
}

async function loadAssetCandidates() {
  const tableBody = document.getElementById('candidates-table-body');
  tableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    const candidates = await apiFetch('/api/v1/asset-candidates');
    tableBody.innerHTML = candidates.length ? candidates.map(c => `
      <tr>
        <td><code>${escapeHtml(c.candidate_key)}</code></td>
        <td>${escapeHtml(c.asset_type)}</td>
        <td>${escapeHtml(c.submitted_by || '-')}</td>
        <td>${badge(c.status)}</td>
        <td>${formatDate(c.created_at)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-secondary" onclick="openCandidateDetail('${c.id}')">详情</button>
          </div>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无数据</td></tr>';
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

async function loadCollaborationTasks() {
  const tableBody = document.getElementById('tasks-table-body');
  tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    // 注意：这里需要后端API支持，暂时做模拟
    const tasks = []; // await apiFetch('/api/v1/collaboration-tasks');
    tableBody.innerHTML = tasks.length ? tasks.map(t => `
      <tr>
        <td><code>${escapeHtml(t.task_key)}</code></td>
        <td>${escapeHtml(t.caller_agent_key || '-')}</td>
        <td>${badge(t.status)}</td>
        <td>${formatDate(t.created_at)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-sm btn-secondary" onclick="openTaskDetail('${t.id}')">详情</button>
          </div>
        </td>
      </tr>
    `).join('') : '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无数据</td></tr>';
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

async function openCandidateDetail(id) {
  try {
    const data = await apiFetch(`/api/v1/asset-candidates/${id}`);
    showAssetDetail(`Asset Candidate: ${data.candidate_key}`, data);
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

async function openTaskDetail(id) {
  try {
    const data = await apiFetch(`/api/v1/collaboration-tasks/${id}`);
    showAssetDetail(`Collaboration Task: ${data.task_key}`, data);
  } catch (e) {
    showToast(`获取详情失败: ${e.message}`, 'error');
  }
}

// ============================================
// 审计日志
// ============================================

async function loadAuditLogs() {
  const tableBody = document.getElementById('audit-table-body');
  const timeline = document.getElementById('audit-timeline');

  tableBody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    const logs = await apiFetch('/api/v1/audit-logs?limit=50');

    // 表格视图
    tableBody.innerHTML = logs.length ? logs.map(l => `
      <tr>
        <td>${formatDate(l.created_at)}</td>
        <td><code style="font-size: 11px;">${escapeHtml(l.trace_id)}</code></td>
        <td>${escapeHtml(l.actor_id)}</td>
        <td>${escapeHtml(l.action)}</td>
        <td>${escapeHtml(l.resource_type || '-')}/${escapeHtml(l.resource_id || '-')}</td>
        <td>${badge(l.decision)}</td>
        <td>${l.latency_ms ? `${l.latency_ms}ms` : '-'}</td>
      </tr>
    `).join('') : '<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">暂无数据</td></tr>';

    // 时间线视图
    timeline.innerHTML = logs.length ? logs.map(l => `
      <div class="timeline-item">
        <div class="timeline-dot ${l.decision === 'allow' ? 'success' : 'error'}"></div>
        <div class="timeline-card">
          <div class="timeline-header">
            <span class="timeline-action">${escapeHtml(l.action)}</span>
            <span class="timeline-time">${formatDate(l.created_at)}</span>
          </div>
          <div class="timeline-details">
            <strong>${escapeHtml(l.actor_id)}</strong> → ${escapeHtml(l.resource_type || '-')}/${escapeHtml(l.resource_id || '-')}
            ${l.latency_ms ? `(${l.latency_ms}ms)` : ''}
          </div>
        </div>
      </div>
    `).join('') : '<p style="text-align: center; color: var(--text-muted); padding: var(--spacing-xl);">暂无数据</p>';
  } catch (e) {
    tableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载失败: ${e.message}</td></tr>`;
  }
}

function toggleAuditView(view) {
  appState.auditView = view;
  const tableView = document.getElementById('audit-table-view');
  const timelineView = document.getElementById('audit-timeline-view');

  document.querySelectorAll('#audit .view-toggle button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === view);
  });

  if (view === 'table') {
    tableView.classList.remove('hidden');
    timelineView.classList.add('hidden');
  } else {
    tableView.classList.add('hidden');
    timelineView.classList.remove('hidden');
  }
}

// ============================================
// 资产详情
// ============================================

function showAssetDetail(title, data) {
  navigateToPage('detail');
  const container = document.getElementById('asset-detail');

  container.innerHTML = `
    <div class="detail-header">
      <div class="detail-title-group">
        <div class="detail-icon">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <div>
          <h3 class="detail-title">${escapeHtml(title)}</h3>
        </div>
      </div>
      <div class="detail-actions">
        <button class="btn btn-secondary" onclick="copyDetailData()">复制JSON</button>
      </div>
    </div>
    <div class="detail-section">
      <h4 class="detail-section-title">详细信息</h4>
      <div class="detail-code">
        <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </div>
    </div>
  `;

  appState.currentDetailData = data;
}

function clearAssetDetail() {
  const container = document.getElementById('asset-detail');
  container.innerHTML = `
    <div class="detail-panel-empty">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <h3 class="empty-state-title">暂无选中资产</h3>
        <p class="empty-state-description">从其他页面选择一个资产查看详细信息</p>
      </div>
    </div>
  `;
  appState.currentDetailData = null;
}

function copyDetailData() {
  if (appState.currentDetailData) {
    navigator.clipboard.writeText(JSON.stringify(appState.currentDetailData, null, 2));
    showToast('已复制到剪贴板', 'success');
  }
}

// ============================================
// 拖拽上传
// ============================================

function initDropzone() {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('upload-file');

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener('click', () => fileInput.click());

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    fileInput.files = e.dataTransfer.files;
  });
}

// ============================================
// 事件绑定
// ============================================

function bindEvents() {
  // 登录
  document.getElementById('login-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const apiKeyInput = document.getElementById('api-key-input').value;
    login(apiKeyInput);
  });

  // 退出
  document.getElementById('logout-btn').addEventListener('click', logout);

  // 侧边栏切换
  const sidebarToggle = document.getElementById('sidebar-toggle');
  if (sidebarToggle) sidebarToggle.addEventListener('click', toggleSidebar);

  // 移动端菜单
  const mobileMenuBtn = document.getElementById('mobile-menu-btn');
  if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', toggleMobileMenu);

  // 导航
  document.querySelectorAll('.nav-list .nav-link').forEach(link => {
    link.addEventListener('click', () => {
      const page = link.dataset.page;
      navigateToPage(page);
      document.getElementById('sidebar').classList.remove('mobile-open');
    });
  });

  // 能力目录
  const capTypeFilter = document.getElementById('cap-type-filter');
  const capStatusFilter = document.getElementById('cap-status-filter');
  if (capTypeFilter) capTypeFilter.addEventListener('change', loadCapabilities);
  if (capStatusFilter) capStatusFilter.addEventListener('change', loadCapabilities);

  const capRefreshBtn = document.getElementById('cap-refresh-btn');
  if (capRefreshBtn) capRefreshBtn.addEventListener('click', loadCapabilities);

  // 视图切换
  document.querySelectorAll('#capabilities .view-toggle button').forEach(btn => {
    btn.addEventListener('click', () => toggleCapabilitiesView(btn.dataset.view));
  });

  // 知识库创建
  const kbCreateToggle = document.getElementById('kb-create-form-toggle');
  const kbCreateForm = document.getElementById('kb-create-form');
  const kbCreateCancel = document.getElementById('kb-create-cancel');
  if (kbCreateToggle) kbCreateToggle.addEventListener('click', () => kbCreateForm.classList.toggle('hidden'));
  if (kbCreateCancel) kbCreateCancel.addEventListener('click', () => kbCreateForm.classList.add('hidden'));

  const kbCreateBtn = document.getElementById('kb-create-btn');
  if (kbCreateBtn) kbCreateBtn.addEventListener('click', createKnowledgeBase);

  // 文档上传
  const uploadToggle = document.getElementById('upload-toggle-btn');
  const uploadSection = document.getElementById('upload-section');
  const uploadCancel = document.getElementById('upload-cancel');
  if (uploadToggle) uploadToggle.addEventListener('click', () => uploadSection.classList.toggle('hidden'));
  if (uploadCancel) uploadCancel.addEventListener('click', () => uploadSection.classList.add('hidden'));

  const uploadBtn = document.getElementById('upload-btn');
  if (uploadBtn) uploadBtn.addEventListener('click', uploadDocuments);

  // 审计日志
  const auditRefreshBtn = document.getElementById('audit-refresh-btn');
  if (auditRefreshBtn) auditRefreshBtn.addEventListener('click', loadAuditLogs);

  document.querySelectorAll('#audit .view-toggle button').forEach(btn => {
    btn.addEventListener('click', () => toggleAuditView(btn.dataset.view));
  });

  // 集成管理标签切换
  document.querySelectorAll('#integration-tabs button').forEach(btn => {
    btn.addEventListener('click', () => switchIntegrationTab(btn.dataset.tab));
  });

  // 详情清空
  const detailClearBtn = document.getElementById('detail-clear-btn');
  if (detailClearBtn) detailClearBtn.addEventListener('click', clearAssetDetail);

  // 模态框
  const modalClose = document.getElementById('modal-close');
  const modalOverlay = document.getElementById('modal-overlay');
  if (modalClose) modalClose.addEventListener('click', closeModal);
  if (modalOverlay) modalOverlay.addEventListener('click', (e) => {
    if (e.target === modalOverlay) closeModal();
  });

  // 初始化拖拽上传
  initDropzone();
}

// ============================================
// 初始化
// ============================================

function init() {
  // 检查是否记住登录
  const savedKey = localStorage.getItem(API_KEY_STORAGE);
  const remember = localStorage.getItem(REMEMBER_KEY_STORAGE);

  if (savedKey) {
    document.getElementById('api-key-input').value = savedKey;
    document.getElementById('remember-key').checked = !!remember;
  }

  // 绑定事件
  bindEvents();

  // 自动登录（如果有保存的key）
  if (savedKey) {
    apiFetch('/api/v1/metrics/overview')
      .then(() => {
        showApp();
      })
      .catch(() => {
        showLogin();
      });
  } else {
    showLogin();
  }
}

// 页面加载完成后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// 暴露全局函数
window.navigateToPage = navigateToPage;
window.openCapabilityDetail = openCapabilityDetail;
window.showCapabilityDetailPage = showCapabilityDetailPage;
window.openSkillDetail = openSkillDetail;
window.openPromptDetail = openPromptDetail;
window.openKnowledgeDetail = openKnowledgeDetail;
window.openDocumentDetail = openDocumentDetail;
window.loadDocuments = loadDocuments;
window.openCandidateDetail = openCandidateDetail;
window.openTaskDetail = openTaskDetail;
window.copyDetailData = copyDetailData;
