/* ==========================================================================
   App — 应用入口，路由注册与初始化
   ========================================================================== */

const App = (() => {

  /* -----------------------------------------------------------------------
     路由注册
     ----------------------------------------------------------------------- */
  function initRouter() {
    // 仪表盘
    Router.on('/', async () => {
      UI.renderSidebar('/');
      await Dashboard.render();
    });

    // 文档列表
    Router.on('/documents', async () => {
      UI.renderSidebar('/documents');
      await Documents.renderList();
    });

    // 文档详情
    Router.on('/documents/:id', async (params) => {
      UI.renderSidebar('/documents');
      await DocumentDetail.render(params.id);
    });

    // 搜索
    Router.on('/search', async () => {
      UI.renderSidebar('/search');
      await SearchPage.render();
    });

    // ── v1 路由 ──

    // 知识块管理
    Router.on('/chunks', async () => {
      UI.renderSidebar('/chunks');
      await Chunks.render();
    });

    // 系统状态已集成到仪表盘中，不再作为独立页面
  }

  /* -----------------------------------------------------------------------
     服务状态详情弹窗
     ----------------------------------------------------------------------- */
  async function showServiceStatusDetail() {
    let statusHtml = '<div class="loading-overlay"><div class="loading-spinner"></div><span>检查服务状态…</span></div>';
    UI.showModal('服务状态详情', statusHtml);

    try {
      const [healthRes] = await Promise.all([
        API.health(),
      ]);

      const overallOk = healthRes?.data?.status === 'ok';
      const deps = healthRes?.data?.dependencies || {};
      const version = healthRes?.meta?.version || '1.0.0';

      statusHtml = `
        <div style="margin-bottom: var(--space-4);">
          <div style="display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4);">
            <span style="font-size: 2rem;">${overallOk ? '✅' : '⚠️'}</span>
            <div>
              <div style="font-size: var(--text-lg); font-weight: 600; color: ${overallOk ? 'var(--celadon-deep)' : 'var(--cinnabar)'};">
                ${overallOk ? '服务运行正常' : '服务状态异常'}
              </div>
              <div style="font-size: var(--text-sm); color: var(--ink-wash);">版本 v${version}</div>
            </div>
          </div>
        </div>

        <div class="status-panel">
          ${Object.entries(deps).map(([key, dep]) => {
            const status = dep.status || 'unknown';
            const statusInfo = {
              'ok': { color: 'var(--jade)', icon: '✓', label: '正常' },
              'error': { color: 'var(--cinnabar)', icon: '✗', label: '异常' },
              'not_configured': { color: 'var(--ink-wash-light)', icon: '—', label: '未配置' },
            };
            const info = statusInfo[status] || { color: 'var(--ink-wash)', icon: '?', label: status };

            return `
              <div class="status-item">
                <span class="status-item-label">${dep.name || key}</span>
                <span class="status-item-value" style="color: ${info.color};">
                  ${info.icon} ${info.label}
                </span>
              </div>
            `;
          }).join('')}
        </div>

        <div style="margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--mist);">
          <p style="font-size: var(--text-sm); color: var(--ink-wash); margin: 0;">
            📡 每隔 10 秒自动刷新服务状态
          </p>
        </div>
      `;

      const modalBody = document.querySelector('.modal:last-child .modal-body');
      if (modalBody) modalBody.innerHTML = statusHtml;
    } catch (e) {
      const errorHtml = `
        <div style="text-align: center; padding: var(--space-6) 0;">
          <div style="font-size: 2.5rem; margin-bottom: var(--space-3);">❌</div>
          <div style="font-size: var(--text-lg); font-weight: 600; color: var(--cinnabar); margin-bottom: var(--space-2);">
            无法连接后端服务
          </div>
          <p style="font-size: var(--text-sm); color: var(--ink-wash); margin: 0;">
            ${UI.escapeHtml(e.message || '请确认服务已启动并可正常访问')}
          </p>
        </div>
      `;
      const modalBody = document.querySelector('.modal:last-child .modal-body');
      if (modalBody) modalBody.innerHTML = errorHtml;
    }
  }

  /* -----------------------------------------------------------------------
     初始化
     ----------------------------------------------------------------------- */
  async function init() {
    initRouter();

    // 初始化服务状态监控
    UI.ServiceStatus.startPolling(10000);

    // 点击服务状态指示器查看详情
    document.getElementById('serviceStatus')?.addEventListener('click', showServiceStatusDetail);

    // 移动端菜单切换
    document.getElementById('mobileMenuBtn')?.addEventListener('click', () => {
      document.getElementById('sidebar')?.classList.toggle('open');
    });

    // 点击内容区关闭移动端侧边栏
    document.getElementById('content')?.addEventListener('click', () => {
      document.getElementById('sidebar')?.classList.remove('open');
    });

    // 键盘快捷键: Ctrl+K / Cmd+K 快速跳转搜索
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        Router.navigate('/search');
      }
    });

    // 启动路由
    await Router.run();
  }

  // DOM 加载完成后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return {
    router: Router,
    dashboard: Dashboard,
    documents: Documents,
    documentDetail: DocumentDetail,
    search: SearchPage,
    ui: UI,
    api: API,
  };
})();
