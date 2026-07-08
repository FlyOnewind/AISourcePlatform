/* ==========================================================================
   通用组件 — Toast、Modal、侧边栏、面包屑、格式化工具
   ========================================================================== */

const UI = (() => {

  /* -----------------------------------------------------------------------
     Toast 消息
     ----------------------------------------------------------------------- */

  /**
   * 显示浮动提示消息，支持自动消失
   * @param {string} message - 提示文本
   * @param {string} [type='info'] - 提示类型: info | success | error | warning
   * @param {number} [duration=4000] - 显示毫秒数，0 表示不自动消失
   */
  function toast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `
      <span>${escapeHtml(message)}</span>
      <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(el);

    if (duration > 0) {
      setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(16px)';
        el.style.transition = 'all 200ms ease-out';
        setTimeout(() => el.remove(), 200);
      }, duration);
    }
  }

  /* -----------------------------------------------------------------------
     模态框
     ----------------------------------------------------------------------- */

  /**
   * 显示模态弹窗
   * @param {string} title - 弹窗标题
   * @param {string} bodyHtml - 弹窗主体 HTML
   * @param {string} [footerHtml=''] - 弹窗底部 HTML（通常放操作按钮）
   * @returns {{ close: Function, backdrop: HTMLElement }} 关闭方法和 backdrop 元素引用
   */
  function showModal(title, bodyHtml, footerHtml = '') {
    const container = document.getElementById('modalContainer');
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h2 class="modal-title">${escapeHtml(title)}</h2>
          <button class="modal-close" id="modalCloseBtn">&times;</button>
        </div>
        <div class="modal-body">${bodyHtml}</div>
        ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
      </div>
    `;

    const close = () => {
      backdrop.style.opacity = '0';
      backdrop.style.transition = 'opacity 200ms ease-out';
      setTimeout(() => backdrop.remove(), 200);
    };

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close();
    });
    backdrop.querySelector('#modalCloseBtn')?.addEventListener('click', close);

    container.appendChild(backdrop);
    return { close, backdrop };
  }

  /* -----------------------------------------------------------------------
     侧边栏渲染
     ----------------------------------------------------------------------- */

  /**
   * 根据当前路径高亮侧边栏导航项
   * @param {string} currentPath - 当前路由路径
   */
  function renderSidebar(currentPath) {
    const nav = document.getElementById('sidebarNav');

    const items = [
      { path: '/',             icon: '▤', label: '仪表盘' },
      { path: '/documents',    icon: '▦', label: '文档管理' },
      { path: '/chunks',       icon: '⊞', label: '知识块管理' },
      { path: '/search',       icon: '⌕', label: '知识搜索' },
    ];

    nav.innerHTML = items.map(item => `
      <a class="nav-item${currentPath === item.path ? ' active' : ''}"
         href="#${item.path}"
         data-path="${item.path}">
        <span class="nav-icon">${item.icon}</span>
        <span>${item.label}</span>
      </a>
    `).join('');
  }

  /* -----------------------------------------------------------------------
     面包屑
     ----------------------------------------------------------------------- */

  /**
   * 设置页面面包屑导航
   * @param {Array<{label: string, path?: string}>} parts - 面包屑分段，每段包含 label 和可选的 path
   */
  function setBreadcrumb(parts) {
    const el = document.getElementById('breadcrumb');
    el.innerHTML = parts.map((p, i) =>
      i < parts.length - 1
        ? `<a href="${p.path || '#'}">${escapeHtml(p.label)}</a> › `
        : `<span>${escapeHtml(p.label)}</span>`
    ).join('');
  }

  /* -----------------------------------------------------------------------
     HTML 转义
     ----------------------------------------------------------------------- */

  /**
   * HTML 特殊字符转义，防止 XSS 注入
   * @param {string} str - 原始字符串
   * @returns {string} 转义后的安全字符串
   */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /* -----------------------------------------------------------------------
     时间格式化
     ----------------------------------------------------------------------- */

  /**
   * ISO 时间字符串格式化为 yyyy-MM-dd HH:mm
   * @param {string} isoStr - ISO 8601 时间字符串
   * @returns {string} 格式化后的时间字符串
   */
  function formatTime(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${y}-${mo}-${day} ${h}:${mi}`;
  }

  /**
   * 字节数格式化为人类可读的文件大小（B / KB / MB）
   * @param {number} bytes - 字节数
   * @returns {string} 格式化后的大小字符串
   */
  function formatSize(bytes) {
    if (bytes == null) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  /**
   * 数字格式化为中文计数（过万显示为"X.X 万"，否则千分位）
   * @param {number} n - 数值
   * @returns {string} 格式化后的数字字符串
   */
  function formatNumber(n) {
    if (n == null) return '0';
    if (n >= 10000) return `${(n / 10000).toFixed(1)} 万`;
    return n.toLocaleString('zh-CN');
  }

  /* -----------------------------------------------------------------------
     文档格式徽章
     ----------------------------------------------------------------------- */

  /**
   * 根据源文件类型生成彩色格式徽章 HTML
   * @param {string} sourceType - 源文件类型（markdown/docx/pdf 等）
   * @returns {string} 徽章 HTML 字符串
   */
  function fmtBadge(sourceType) {
    const t = (sourceType || '').toLowerCase();
    const map = {
      markdown: 'md', md: 'md', txt: 'txt', text: 'txt',
      docx: 'docx', xlsx: 'xlsx', html: 'html', htm: 'html',
      pdf: 'pdf', pptx: 'pptx',
    };
    const cls = map[t] || 'txt';
    const label = cls.toUpperCase();
    return `<span class="badge-fmt ${cls}">${label}</span>`;
  }

  /**
   * 将源文件类型转为人类可读的中文/英文标签
   * @param {string} sourceType - 源文件类型代码
   * @returns {string} 可读标签（如 Markdown、PDF、手工录入）
   */
  function sourceTypeLabel(sourceType) {
    const map = {
      markdown: 'Markdown',
      md: 'Markdown',
      txt: 'TXT',
      text: 'TXT',
      docx: 'DOCX',
      xlsx: 'XLSX',
      html: 'HTML',
      htm: 'HTML',
      pdf: 'PDF',
      pptx: 'PPTX',
      manual: '手工录入',
      unknown: '未知格式',
    };
    return map[(sourceType || '').toLowerCase()] || sourceType || '未知格式';
  }

  /* -----------------------------------------------------------------------
     知识类型徽章
     ----------------------------------------------------------------------- */

  /**
   * 根据知识类型生成彩色徽章 HTML（陈述型/关系型/流程型）
   * @param {string} type - 知识类型: declarative | relational | procedural
   * @returns {string} 徽章 HTML 字符串
   */
  function ktypeBadge(type) {
    const map = {
      declarative: '陈述型',
      relational: '关系型',
      procedural: '流程型',
    };
    const label = map[type] || type || '未知';
    return `<span class="badge-ktype ${type || ''}">${label}</span>`;
  }

  /* -----------------------------------------------------------------------
     知识类型纯文本标签（用于下拉选项等非徽章场景）
     ----------------------------------------------------------------------- */

  /**
   * 知识类型纯文本标签（用于下拉选项等非徽章场景）
   * @param {string} type - 知识类型代码
   * @returns {string} 中文标签
   */
  function ktypeLabel(type) {
    const map = {
      declarative: '陈述型',
      relational: '关系型',
      procedural: '流程型',
    };
    return map[type] || type || '未知';
  }

  /* -----------------------------------------------------------------------
     状态徽章
     ----------------------------------------------------------------------- */

  /**
   * 根据文档/知识块状态生成彩色状态徽章 HTML
   * @param {string} status - 状态值: active | deleted | failed | processing | ready
   * @returns {string} 徽章 HTML 字符串
   */
  function statusBadge(status) {
    const map = {
      active:    ['success', '活跃'],
      deleted:   ['error', '已删除'],
      failed:    ['error', '失败'],
      processing:['info', '处理中'],
      ready:     ['success', '就绪'],
    };
    const [cls, label] = map[status] || ['neutral', status || '未知'];
    return `<span class="badge badge-${cls}">${label}</span>`;
  }

  /* -----------------------------------------------------------------------
     快捷渲染到 #content
     ----------------------------------------------------------------------- */

  /**
   * 将 HTML 直接渲染到主内容区 #content
   * @param {string} html - HTML 字符串
   */
  function render(html) {
    document.getElementById('content').innerHTML = html;
  }

  /* -----------------------------------------------------------------------
     服务状态指示器 — 顶部 banner 的 ◉ 状态灯

     三态显示，由 GET /api/v1/health 驱动：
       - ok       → ◉ 服务在线（全部外部依赖正常）
       - degraded → ◉ 服务异常（进程存活，部分依赖不可用）
       - 请求失败  → ◉ 服务离线（进程未存活）
     每 10 秒轮询一次。
     ----------------------------------------------------------------------- */
  const ServiceStatus = {
    timer: null,

    /**
     * 更新服务状态指示器的 UI 状态
     * @param {string} status - ok | warning | error
     * @param {string} label - 显示文本
     */
    update(status, label) {
      const el = document.getElementById('serviceStatus');
      if (!el) return;
      el.className = `service-status-indicator status-${status}`;
      el.querySelector('.service-status-label').textContent = label;
    },

    /**
     * 发起健康检查请求并更新指示器状态
     */
    async check() {
      try {
        const res = await API.health();
        if (res?.data?.status === 'ok') {
          // 全部外部依赖正常
          this.update('ok', '服务在线');
        } else {
          // degraded：进程存活但部分外部依赖不可用（如 LLM 超时）
          this.update('warning', '服务异常');
        }
      } catch (e) {
        // 请求失败：后端进程未存活或网络不可达
        this.update('error', '服务离线');
      }
    },

    /**
     * 启动定时轮询健康检查
     * @param {number} [intervalMs=10000] - 轮询间隔毫秒
     */
    startPolling(intervalMs = 10000) {
      this.stopPolling();
      this.check();
      this.timer = setInterval(() => this.check(), intervalMs);
    },

    /** 停止定时轮询 */
    stopPolling() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }
    },
  };

  /* -----------------------------------------------------------------------
     抽屉面板
     ----------------------------------------------------------------------- */

  /**
   * 从右侧滑出的抽屉面板
   * @param {string} title - 抽屉标题
   * @param {string} bodyHtml - 抽屉内容 HTML
   * @returns {{ close: Function, el: HTMLElement }} 关闭方法和 DOM 元素引用
   */
  function showDrawer(title, bodyHtml) {
    const container = document.getElementById('modalContainer');
    const el = document.createElement('div');
    el.className = 'drawer';
    el.innerHTML = `
      <div class="drawer-overlay"></div>
      <div class="drawer-content">
        <div class="drawer-header">
          <h2>${escapeHtml(title)}</h2>
          <button class="btn-close" id="drawerCloseBtn">&times;</button>
        </div>
        <div class="drawer-body">${bodyHtml}</div>
      </div>
    `;
    const close = () => {
      el.querySelector('.drawer-content').style.transform = 'translateX(100%)';
      el.querySelector('.drawer-overlay').style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    };
    el.querySelector('#drawerCloseBtn').addEventListener('click', close);
    el.querySelector('.drawer-overlay').addEventListener('click', close);
    container.appendChild(el);
    return { close, el };
  }

  /* -----------------------------------------------------------------------
     确认对话框
     ----------------------------------------------------------------------- */

  /**
   * 显示确认对话框，返回 Promise
   * @param {string} title - 对话框标题
   * @param {string} message - 确认提示信息
   * @param {string} [confirmLabel='确认'] - 确认按钮文本
   * @param {string} [cancelLabel='取消'] - 取消按钮文本
   * @returns {Promise<boolean>} 用户点击确认为 true，取消为 false
   */
  function showConfirm(title, message, confirmLabel = '确认', cancelLabel = '取消') {
    return new Promise((resolve) => {
      showModal(
        title,
        `<p style="color:var(--ink-soft);line-height:1.6">${escapeHtml(message)}</p>`,
        `
          <button class="btn btn-secondary" id="confirmCancelBtn">${escapeHtml(cancelLabel)}</button>
          <button class="btn btn-primary" id="confirmOkBtn">${escapeHtml(confirmLabel)}</button>
        `
      );
      // 绑定事件（需要在DOM渲染后）
      setTimeout(() => {
        document.getElementById('confirmCancelBtn')?.addEventListener('click', () => {
          document.querySelector('.modal-backdrop:last-child')?.remove();
          resolve(false);
        });
        document.getElementById('confirmOkBtn')?.addEventListener('click', () => {
          document.querySelector('.modal-backdrop:last-child')?.remove();
          resolve(true);
        });
      }, 50);
    });
  }

  return {
    toast, showModal, showDrawer, showConfirm, renderSidebar, setBreadcrumb,
    escapeHtml, formatTime, formatSize, formatNumber,
    fmtBadge, sourceTypeLabel, ktypeBadge, ktypeLabel, statusBadge, render,
    ServiceStatus,
  };
})();
