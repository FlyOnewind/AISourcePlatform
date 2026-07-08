/* ==========================================================================
   仪表盘组件 — 系统概览、统计数据、服务状态面板

   数据来源（全部通过 v1 API）：
     - GET /api/v1/health         → 整体状态 + 外部依赖详情
     - GET /api/v1/documents      → 文档总数、失败/处理中文档数
     - GET /api/v1/chunks         → 知识块总数
   ========================================================================== */

const Dashboard = (() => {

  /**
   * 将后端依赖状态码转为中文展示文本
   * @param {string} status - ok | error | not_configured
   * @returns {string} 正常 | 异常 | 未配置
   */
  function _formatStatus(status) {
    if (status === 'ok') return '正常';
    if (status === 'error') return '异常';
    if (status === 'not_configured') return '未配置';
    return status || '—';
  }

  /**
   * 将后端依赖状态码转为 CSS 类名
   * @param {string} status - ok | error
   * @returns {string} is-ok | is-error | ''
   */
  function _getStatusClass(status) {
    if (status === 'ok') return 'is-ok';
    if (status === 'error') return 'is-error';
    return '';
  }

  /** 渲染仪表盘页面（先展示骨架，再异步填充数据） */
  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘' }]);

    // ── 立即渲染骨架，消除侧边栏点击后的空白等待感 ──
    UI.render(`
      <div class="page-header">
        <h1 class="page-title">知识库概览</h1>
        <p class="page-subtitle">文档入库、语义抽取、混合检索 — 一站式知识管理</p>
      </div>
      <div class="loading-overlay"><div class="loading-spinner"></div><span>加载仪表盘…</span></div>
    `);

    // ── 全部数据并行获取（health + 4 个统计查询，每个独立容错） ──
    const [healthRes, docsRes, chunksRes, failedRes, processingRes] = await Promise.all([
      API.health().catch(() => null),
      API.listDocuments({ page: 1, page_size: 1 }).catch(() => null),
      API.listChunks({ page: 1, page_size: 1 }).catch(() => null),
      API.listDocuments({ page: 1, page_size: 1, status: 'failed' }).catch(() => null),
      API.listDocuments({ page: 1, page_size: 1, status: 'processing' }).catch(() => null),
    ]);

    const apiOnline = healthRes !== null;
    const healthOk = healthRes?.data?.status === 'ok';
    const depStatuses = healthRes?.data?.dependencies || {};
    const docCount = docsRes?.metadata?.total || 0;
    const chunkCount = chunksRes?.metadata?.total || 0;
    const failedDocCount = failedRes?.metadata?.total || 0;
    const processingDocCount = processingRes?.metadata?.total || 0;

    // ── 组装外部依赖列表（按固定顺序） ──
    const externalDeps = [
      depStatuses.postgresql,
      depStatuses.milvus,
      depStatuses.minio,
      depStatuses.llm
    ].filter(Boolean);

    // ── 用真实数据替换骨架，渲染完整页面 ──
    UI.render(`
      <div class="page-header">
        <h1 class="page-title">知识库概览</h1>
        <p class="page-subtitle">文档入库、语义抽取、混合检索 — 一站式知识管理</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon">▦</div>
          <div class="stat-label">文档总数</div>
          <div class="stat-value">${UI.formatNumber(docCount)}</div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⊞</div>
          <div class="stat-label">知识块总数</div>
          <div class="stat-value">${UI.formatNumber(chunkCount)}</div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">⌕</div>
          <div class="stat-label">处理中的文档数</div>
          <div class="stat-value stat-value-sm">${processingDocCount}</div>
          <div class="stat-detail"><span>${failedDocCount ? `${failedDocCount} 个失败文档待处理` : '暂无失败文档'}</span></div>
        </div>
      </div>

      <div class="dashboard-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <h3 class="card-title">系统状态</h3>
              <p class="card-subtitle">外部服务连接状态</p>
            </div>
            <span class="badge badge-${healthOk ? 'success' : 'error'}">${healthOk ? '正常' : '异常'}</span>
          </div>
          <div class="status-panel">
            <div class="status-section">
              <div class="status-item status-item-main">
                <span class="status-item-label">API 服务</span>
                <span class="status-item-value ${apiOnline ? 'is-ok' : 'is-error'}">
                  ${apiOnline ? '在线' : '离线'}
                </span>
              </div>
            </div>

            ${externalDeps.length ? `
              <div class="status-section">
                <div class="status-group-header">外部服务</div>
                <div class="status-grid">
                  ${externalDeps.map(dep => `
                    <div class="status-item">
                      <span class="status-item-label">${dep.name}</span>
                      <span class="status-item-value ${_getStatusClass(dep.status)}">
                        ${_formatStatus(dep.status)}
                      </span>
                    </div>
                  `).join('')}
                </div>
              </div>
            ` : ''}
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h3 class="card-title">快速操作</h3></div>
          <div class="quick-actions">
            <button class="btn btn-primary btn-lg" onclick="Documents.showUploadModal()">↑ 上传文档</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/search')">⌕ 搜索知识</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/documents')">▦ 浏览文档</button>
            <button class="btn btn-secondary btn-lg" onclick="App.router.navigate('/chunks')">⊞ 知识块管理</button>
          </div>
        </div>
      </div>

      <div class="card action-card">
        <div class="card-header">
          <div>
            <h3 class="card-title">待处理事项</h3>
            <p class="card-subtitle">优先处理会影响检索可用性的异常</p>
          </div>
        </div>
        <div class="action-list">
          <button class="action-row" onclick="App.router.navigate('/documents?status=failed')">
            <span>失败文档</span>
            <strong>${failedDocCount}</strong>
          </button>
          <button class="action-row" onclick="App.router.navigate('/documents?status=processing')">
            <span>处理中文档</span>
            <strong>${processingDocCount}</strong>
          </button>
        </div>
      </div>
    `);
  }

  return { render };
})();
