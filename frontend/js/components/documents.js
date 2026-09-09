/* ==========================================================================
   文档管理组件 — 列表、上传、删除、恢复、入库（已迁移至 v1 API）
   ========================================================================== */

const Documents = (() => {

  const MAX_CONCURRENT_UPLOADS = 8;  // 并行上传上限，避免压垮浏览器和后端

  let currentPage = 1;
  let currentKeyword = '';
  let currentStatus = 'active';
  let currentCategory = '';
  let currentSort = 'updated_at:desc';
  let currentTab = 'active';  // 当前标签页: active | failed | processing | deleted
  let _forceFullRender = true; // 标签切换时强制完整渲染
  let _selectAllAbort = 0;     // 取消异步全选
  let selectedIds = new Set();
  let categoryOptions = [];  // 从后端动态加载的分类列表
  let pageSize = 15;  // 每页显示数量

  /**
   * 渲染文档列表页面（路由入口），从 URL 参数读取初始筛选状态
   */
  async function renderList() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '文档管理' }]);

    // 重置页面级状态，避免上次访问的残留状态导致左侧栏与显示区域对不上
    _forceFullRender = true;
    selectedIds.clear();
    _selectAllAbort++;

    // 从 URL hash 参数读取状态筛选（如 /#/documents?status=failed）
    const query = Router.getQuery();
    if (query.status && ['active', 'failed', 'processing', 'deleted'].includes(query.status)) {
      currentTab = query.status;
      currentStatus = query.status;
    } else {
      // 无 URL 参数时恢复默认标签页和筛选条件，防止上次的页面状态残留
      currentTab = 'active';
      currentStatus = 'active';
      currentKeyword = '';
      currentCategory = '';
      currentSort = 'updated_at:desc';
    }

    // 并行获取筛选项和文档列表，避免串行等待造成页面切换卡顿
    // searchFilters 带 5 分钟缓存，二次进入页面几乎瞬时返回
    const filtersPromise = API.searchFilters()
      .then(res => { categoryOptions = (res?.data?.categories || []).map(c => c.value); })
      .catch(() => { categoryOptions = []; });
    const loadPromise = loadPage(1);
    await Promise.all([filtersPromise, loadPromise]);
  }

  function renderSkeleton() {
    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">文档管理</h1>
            <p class="page-subtitle">管理已入库的文档，查看解析结果和知识块</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline btn-sm" disabled>批量操作</button>
            <button class="btn btn-primary" disabled>↑ 上传文档</button>
          </div>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="doc-tabs">
        <button class="doc-tab active" disabled data-tab="active">活跃</button>
        <button class="doc-tab" disabled data-tab="failed">失败</button>
        <button class="doc-tab" disabled data-tab="processing">处理中</button>
        <button class="doc-tab" disabled data-tab="deleted">回收站</button>
      </div>

      <!-- 搜索过滤 -->
      <div class="doc-toolbar kb-filter-bar document-filter-bar">
        <input class="input kb-toolbar-search" type="text" placeholder="搜索文档标题…" disabled>
        <select class="select select-sm" disabled>
          <option value="">全部分类</option>
        </select>
        <select class="select select-sm" disabled>
          <option value="updated_at:desc">更新时间</option>
        </select>
        <button class="btn btn-ghost btn-sm" disabled>清空筛选</button>
        <span class="doc-count"></span>
      </div>

      <!-- 文档表格 -->
      <div class="table-wrap">
        <div class="loading-overlay"><div class="loading-spinner"></div><span>加载文档列表…</span></div>
      </div>
    `);
  }

  /**
   * 加载指定页码的文档列表，根据当前筛选条件请求后端
   * @param {number} page - 页码
   */
  async function loadPage(page) {
    currentPage = page;

    try {
      const [sortBy, sortOrder] = currentSort.split(':');
      const params = {
        page,
        page_size: pageSize,
        keyword: currentKeyword || undefined,
        status: currentStatus || undefined,
        category: currentCategory || undefined,
        sort_by: sortBy || 'updated_at',
        sort_order: sortOrder || 'desc',
      };
      const res = await API.listDocuments(params);
      renderDocListHtml(res);
    } catch (e) {
      const message = friendlyErrorMessage(e);
      UI.toast(`加载文档失败：${message}`, 'error');
      renderDocListHtml(null, { errorMessage: message });
    }
  }

  function renderDocListHtml(res, state = {}) {
    const items = res?.data || [];
    const meta = res?.metadata || {};
    const total = meta.total || 0;
    const totalPages = meta.total_pages || 1;
    const hasFilters = Boolean(currentKeyword || currentCategory || currentStatus);
    const errorMessage = state.errorMessage || '';

    let rowsHtml = '';
    if (errorMessage) {
      rowsHtml = `
        <tr class="empty-row"><td colspan="7">
          <div class="empty-state empty-state-error">
            <div class="empty-state-icon">!</div>
            <div class="empty-state-title">文档列表加载失败</div>
            <div class="empty-state-desc">${UI.escapeHtml(errorMessage)}</div>
            <div class="empty-actions">
              <button class="btn btn-primary" onclick="Documents.loadPage(${currentPage})">重新加载</button>
            </div>
          </div>
        </td></tr>`;
    } else if (items.length === 0) {
      rowsHtml = `
        <tr class="empty-row"><td colspan="7">
          <div class="empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-title">${hasFilters ? '未找到匹配文档' : '暂无文档'}</div>
            <div class="empty-state-desc">${hasFilters
              ? '当前筛选条件下没有文档。可以调整关键词、分类或状态后再试。'
              : '上传文档后，可在这里查看解析结果、知识块数量和处理状态。支持 Markdown、TXT、DOCX、XLSX、HTML、PDF、PPTX 等格式。'}</div>
            <div class="empty-actions">
              ${hasFilters ? '<button class="btn btn-secondary" onclick="Documents.resetFilters()">清空筛选</button>' : ''}
              <button class="btn btn-primary" onclick="Documents.showUploadModal()">↑ 上传文档</button>
            </div>
          </div>
        </td></tr>`;
    } else {
      rowsHtml = items.map(doc => `
        <tr>
          <td><input type="checkbox" value="${doc.doc_id}" class="doc-checkbox" onclick="Documents.toggleSelect(event)" ${selectedIds.has(doc.doc_id) ? 'checked' : ''} /></td>
          <td>
            <div class="doc-title-cell">
              ${UI.fmtBadge(doc.source_type)}
              <span class="doc-title-link" onclick="Documents.showDocDetail('${doc.doc_id}')">${UI.escapeHtml(doc.title || '未命名文档')}</span>
            </div>
          </td>
          <td>${UI.escapeHtml(doc.category || '通用')}</td>
          <td>${UI.statusBadge(doc.status || 'active')}</td>
          <td>${UI.formatTime(doc.created_at)}</td>
          <td>${UI.formatTime(doc.updated_at) || UI.formatTime(doc.created_at)}</td>
          <td class="actions-cell">
            ${currentTab === 'deleted'
              ? `<button class="btn btn-sm btn-success doc-action-btn" onclick="Documents.restoreDoc('${doc.doc_id}')" title="恢复文档">
                   <span class="action-icon">↶</span>恢复
                 </button>
                 <button class="btn btn-sm btn-outline doc-action-btn" onclick="Documents.showEditDialog('${doc.doc_id}')" title="编辑文档">
                   <span class="action-icon">✎</span>编辑
                 </button>`
              : currentTab === 'failed'
              ? `
                <button class="btn btn-sm btn-outline doc-action-btn" onclick="Documents.showEditDialog('${doc.doc_id}')" title="编辑文档">
                  <span class="action-icon">✎</span>编辑
                </button>
                <button class="btn btn-sm btn-warning doc-action-btn" onclick="Documents.retryDoc('${doc.doc_id}','${UI.escapeHtml(doc.title || '')}')" title="重新处理">
                  <span class="action-icon">↻</span>重试
                </button>
                <button class="btn btn-sm btn-danger doc-action-btn" onclick="Documents.deleteDoc('${doc.doc_id}')" title="删除文档">
                  <span class="action-icon">🗑</span>删除
                </button>`
              : currentTab === 'processing'
              ? `
                <button class="btn btn-sm btn-danger doc-action-btn" onclick="Documents.deleteDoc('${doc.doc_id}')" title="删除文档">
                  <span class="action-icon">🗑</span>删除
                </button>`
              : `
                <button class="btn btn-sm btn-outline doc-action-btn" onclick="Documents.showEditDialog('${doc.doc_id}')" title="编辑文档">
                  <span class="action-icon">✎</span>编辑
                </button>
                <button class="btn btn-sm btn-primary doc-action-btn" onclick="Documents.showUpdateModal('${doc.doc_id}', '${UI.escapeHtml(doc.title)}')" title="更新文档">
                  <span class="action-icon">↑</span>更新
                </button>
                <button class="btn btn-sm btn-danger doc-action-btn" onclick="Documents.deleteDoc('${doc.doc_id}')" title="删除文档">
                  <span class="action-icon">🗑</span>删除
                </button>`}
          </td>
        </tr>
      `).join('');
    }

    // 尝试增量更新，避免完整重新渲染导致的抖动
    const contentEl = document.getElementById('content');
    const tableWrap = contentEl?.querySelector('.table-wrap');
    const docSearchInput = contentEl?.querySelector('#docSearchInput');
    const docCategoryFilter = contentEl?.querySelector('#docCategoryFilter');
    const docStatusFilter = contentEl?.querySelector('#docStatusFilter');
    const docSortFilter = contentEl?.querySelector('#docSortFilter');

    // 只有关键元素齐全且非强制重渲染时才做增量更新
    if (!_forceFullRender && tableWrap && docSearchInput && docSortFilter) {
      const tableBody = tableWrap.querySelector('tbody');
      const docCount = contentEl?.querySelector('.doc-count');
      const pagination = contentEl?.querySelector('.pagination');
      const docSelectAll = contentEl?.querySelector('#docSelectAll');
      const clearFiltersBtn = contentEl?.querySelector('button[onclick="Documents.resetFilters()"]');
      // 更新搜索输入框值
      if (docSearchInput && docSearchInput.value !== currentKeyword) {
        docSearchInput.value = currentKeyword;
      }

      // 更新分类筛选框（重建选项以确保正确）
      if (docCategoryFilter) {
        const categoryHtml = `<option value="">全部分类</option>${categoryOptions.map(c => `<option value="${UI.escapeHtml(c)}" ${currentCategory === c ? 'selected' : ''}>${UI.escapeHtml(c)}</option>`).join('')}`;
        if (docCategoryFilter.innerHTML !== categoryHtml) {
          docCategoryFilter.innerHTML = categoryHtml;
        }
      }

      // 更新状态筛选框
      if (docStatusFilter) {
        docStatusFilter.querySelectorAll('option').forEach(opt => {
          opt.selected = opt.value === currentStatus;
        });
      }

      // 更新排序选择框
      if (docSortFilter) {
        docSortFilter.querySelectorAll('option').forEach(opt => {
          opt.selected = opt.value === currentSort;
        });
      }

      // 更新表格内容
      if (tableBody) {
        tableBody.innerHTML = rowsHtml;
      }

      // 更新全选按钮状态
      if (docSelectAll) {
        docSelectAll.disabled = items.length === 0;
        docSelectAll.checked = selectedIds.size > 0;
      }

      // 更新文档计数
      docCount.textContent = errorMessage ? '' : `共 ${total} 篇文档`;

      // 更新标签页激活状态
      const docTabs = contentEl?.querySelectorAll('.doc-tab');
      if (docTabs) {
        docTabs.forEach(tab => {
          tab.classList.toggle('active', tab.getAttribute('data-tab') === currentTab);
        });
      }

      // 失败标签页有两个批量按钮，需要单独处理
      if (currentTab === 'failed') {
        const retryBtn = contentEl?.querySelector('#batchRetryBtn');
        const deleteBtn = contentEl?.querySelector('#batchDeleteDocBtn');
        if (retryBtn && !retryBtn.hasAttribute('onclick')) {
          retryBtn.setAttribute('onclick', 'Documents.batchRetry()');
        }
        if (deleteBtn && deleteBtn.getAttribute('onclick') !== 'Documents.batchDelete()') {
          deleteBtn.setAttribute('onclick', 'Documents.batchDelete()');
        }
      } else {
        const batchBtn = contentEl?.querySelector('#batchDeleteDocBtn');
        if (batchBtn) {
          if (currentTab === 'deleted') {
            batchBtn.textContent = '批量恢复';
            batchBtn.setAttribute('onclick', 'Documents.batchRestore()');
          } else {
            batchBtn.textContent = '批量删除';
            batchBtn.setAttribute('onclick', 'Documents.batchDelete()');
          }
        }
      }

      // 更新清空筛选按钮状态
      if (clearFiltersBtn) {
        clearFiltersBtn.disabled = !hasFilters;
      }

      // 更新或重建分页
      if (totalPages > 1) {
        const paginationHtml = `
          <button class="btn btn-sm btn-secondary" onclick="Documents.loadPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>‹ 上一页</button>
          <span class="pagination-info">${currentPage} / ${totalPages}（共 ${total} 篇）</span>
          <button class="btn btn-sm btn-secondary" onclick="Documents.loadPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一页 ›</button>
        `;
        if (pagination) {
          pagination.innerHTML = paginationHtml;
        } else {
          const newPagination = document.createElement('div');
          newPagination.className = 'pagination';
          newPagination.innerHTML = paginationHtml;
          tableWrap.parentNode.insertBefore(newPagination, tableWrap.nextSibling);
        }
      } else if (pagination) {
        pagination.remove();
      }

      return;  // 增量更新完成，不需要完整渲染
    }

    // 完整渲染
    _forceFullRender = false;
    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">文档管理</h1>
            <p class="page-subtitle">管理已入库的文档，查看解析结果和知识块</p>
          </div>
          <div class="page-actions">
            ${currentTab === 'failed' ? `
              <button class="btn btn-outline btn-sm" onclick="Documents.batchRetry()" id="batchRetryBtn" disabled>批量重试</button>
              <button class="btn btn-outline btn-sm" onclick="Documents.batchDelete()" id="batchDeleteDocBtn" disabled>批量删除</button>
            ` : currentTab === 'deleted' ? `
              <button class="btn btn-outline btn-sm" onclick="Documents.batchRestore()" id="batchDeleteDocBtn" disabled>批量恢复</button>
            ` : (currentTab === 'active' || currentTab === 'processing') ? `
              <button class="btn btn-outline btn-sm" onclick="Documents.batchDelete()" id="batchDeleteDocBtn" disabled>批量删除</button>
            ` : ''}
            <button class="btn btn-primary" onclick="Documents.showUploadModal()">↑ 上传文档</button>
          </div>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="doc-tabs">
        <button class="doc-tab${currentTab === 'active' ? ' active' : ''}" data-tab="active" onclick="Documents.switchTab('active')">活跃 <span class="tab-count" id="tabCountActive"></span></button>
        <button class="doc-tab${currentTab === 'failed' ? ' active' : ''}" data-tab="failed" onclick="Documents.switchTab('failed')">失败 <span class="tab-count" id="tabCountFailed"></span></button>
        <button class="doc-tab${currentTab === 'processing' ? ' active' : ''}" data-tab="processing" onclick="Documents.switchTab('processing')">处理中 <span class="tab-count" id="tabCountProcessing"></span></button>
        <button class="doc-tab${currentTab === 'deleted' ? ' active' : ''}" data-tab="deleted" onclick="Documents.switchTab('deleted')">回收站 <span class="tab-count" id="tabCountDeleted"></span></button>
      </div>

      <!-- 搜索过滤 -->
      <div class="doc-toolbar kb-filter-bar document-filter-bar">
        <input class="input kb-toolbar-search" type="text" id="docSearchInput" placeholder="搜索文档标题…" value="${UI.escapeHtml(currentKeyword)}"
               onkeydown="if(event.key==='Enter')Documents.doSearch()">
        <select class="select select-sm" id="docCategoryFilter" onchange="Documents.doSearch()">
          <option value="">全部分类</option>
          ${categoryOptions.map(c => `<option value="${UI.escapeHtml(c)}" ${currentCategory === c ? 'selected' : ''}>${UI.escapeHtml(c)}</option>`).join('')}
        </select>
        <select class="select select-sm" id="docSortFilter" onchange="Documents.doSearch()">
          <option value="updated_at:desc" ${currentSort === 'updated_at:desc' ? 'selected' : ''}>更新时间</option>
          <option value="created_at:desc" ${currentSort === 'created_at:desc' ? 'selected' : ''}>创建时间</option>
          <option value="title:asc" ${currentSort === 'title:asc' ? 'selected' : ''}>标题 A-Z</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="Documents.resetFilters()" ${hasFilters ? '' : 'disabled'}>清空筛选</button>
        <span class="doc-count">${errorMessage ? '' : `共 ${total} 篇文档`}</span>
      </div>

      <!-- 文档表格 -->
      <div class="table-wrap">
        <table class="doc-table">
          <thead>
            <tr>
              <th style="width: 4%;"><input type="checkbox" id="docSelectAll" onclick="Documents.toggleSelectAll()" ${items.length === 0 ? 'disabled' : ''} ${selectedIds.size > 0 ? 'checked' : ''} /></th>
              <th style="width: 30%;">文档名称</th>
              <th style="width: 8%;">分类</th>
              <th style="width: 8%;">状态</th>
              <th style="width: 13%;">创建时间</th>
              <th style="width: 13%;">更新时间</th>
              <th style="width: 24%;">操作</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>

      <!-- 分页 -->
      ${totalPages > 1 ? `
      <div class="pagination">
        <button class="btn btn-sm btn-secondary" onclick="Documents.loadPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>‹ 上一页</button>
        <span class="pagination-info">${currentPage} / ${totalPages}（共 ${total} 篇）</span>
        <button class="btn btn-sm btn-secondary" onclick="Documents.loadPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一页 ›</button>
      </div>` : ''}
    `);
  }

  /* -----------------------------------------------------------------------
     搜索与过滤
     ----------------------------------------------------------------------- */

  /** 根据当前搜索栏和筛选框的值重新加载第一页 */
  function doSearch() {
    currentKeyword = document.getElementById('docSearchInput')?.value?.trim() || '';
    currentCategory = document.getElementById('docCategoryFilter')?.value || '';
    currentSort = document.getElementById('docSortFilter')?.value || 'updated_at:desc';
    loadPage(1);
  }

  /**
   * 切换文档列表标签页（活跃/失败/处理中/回收站），重置筛选和选中状态
   * @param {string} tab - 标签页标识: active | failed | processing | deleted
   */
  function switchTab(tab) {
    currentTab = tab;
    currentStatus = tab;
    currentKeyword = '';
    currentCategory = '';
    currentPage = 1;
    selectedIds.clear();
    _selectAllAbort++; // 取消进行中的异步全选
    _forceFullRender = true;
    loadPage(1);
  }

  /** 清空所有筛选条件并重新加载 */
  function resetFilters() {
    currentKeyword = '';
    currentCategory = '';
    currentSort = 'updated_at:desc';
    loadPage(1);
  }

  function friendlyErrorMessage(error) {
    const raw = error?.message || '';
    if (!raw || raw === 'Failed to fetch' || raw.includes('NetworkError')) {
      return '无法连接后端服务，请确认服务已启动后重试。';
    }
    return raw;
  }

  /* -----------------------------------------------------------------------
     文档详情抽屉
     ----------------------------------------------------------------------- */

  /**
   * 在右侧抽屉中显示文档详情（元数据、状态、错误信息等）
   * @param {string} docId - 文档 ID
   */
  async function showDocDetail(docId) {
    UI.showDrawer('文档详情', '<div class="loading-overlay" style="min-height:200px"><div class="loading-spinner"></div><span>加载中…</span></div>');
    try {
      const res = await API.getDocument(docId);
      const doc = res?.data || {};
      const status = doc.status || 'active';
      const chunkCount = doc.chunk_count ?? 0;
      const elementCount = doc.element_count ?? 0;
      const assetCount = doc.asset_count ?? 0;

      const bodyHtml = `
        <div class="detail-grid">
          <div class="detail-field">
            <label>文档标题</label>
            <span>${UI.escapeHtml(doc.title || '未命名文档')}</span>
          </div>
          <div class="detail-field">
            <label>来源类型</label>
            <span>${UI.sourceTypeLabel(doc.source_type)}</span>
          </div>
          <div class="detail-field">
            <label>分类</label>
            <span>${UI.escapeHtml(doc.category || '通用')}</span>
          </div>
          <div class="detail-field">
            <label>状态</label>
            <span>${UI.statusBadge(status)}</span>
          </div>
          <div class="detail-field">
            <label>创建时间</label>
            <span>${UI.formatTime(doc.created_at)}</span>
          </div>
          <div class="detail-field">
            <label>更新时间</label>
            <span>${UI.formatTime(doc.updated_at)}</span>
          </div>
          <div class="detail-field">
            <label>知识块数量</label>
            <span>${chunkCount}</span>
          </div>
          <div class="detail-field">
            <label>解析元素数量</label>
            <span>${elementCount}</span>
          </div>
          <div class="detail-field">
            <label>资源文件数量</label>
            <span>${assetCount}</span>
          </div>
          <div class="detail-field">
            <label>文档版本</label>
            <span>V${doc.version || 1}</span>
          </div>
        </div>

        ${status === 'failed' && doc.error_message ? `
        <div style="margin-top:var(--space-4);padding:var(--space-3) var(--space-4);background:var(--cinnabar-pale);border:1px solid rgba(185,77,63,0.2);border-radius:var(--radius-md);">
          <div style="font-size:var(--text-xs);color:var(--cinnabar);font-weight:600;margin-bottom:var(--space-1)">处理错误</div>
          <div style="font-size:var(--text-sm);color:var(--cinnabar)">${UI.escapeHtml(doc.error_message)}</div>
        </div>` : ''}

      `;

      // 更新抽屉内容
      const drawerBody = document.querySelector('.drawer-body');
      if (drawerBody) drawerBody.innerHTML = bodyHtml;
    } catch (e) {
      const drawerBody = document.querySelector('.drawer-body');
      if (drawerBody) {
        drawerBody.innerHTML = `
          <div class="empty-state empty-state-error">
            <div class="empty-state-icon">!</div>
            <div class="empty-state-title">加载失败</div>
            <div class="empty-state-desc">${UI.escapeHtml(e.message)}</div>
          </div>`;
      }
    }
  }

  /* -----------------------------------------------------------------------
     处理中通知条
     ----------------------------------------------------------------------- */
  /* ----------------------------------------------------------------------
     SSE 进度弹条 — 上传后实时接收 Worker 推送的入库进度
     ----------------------------------------------------------------------- */

  /** 入库阶段的中文标签 */
  const STAGE_LABELS = {
    parsing:    '解析文档',
    extracting: '语义抽取',
    indexing:   '写入索引',
    completed:  '已完成',
    failed:     '失败',
  };

  /** status → 中文标签 */
  const STATUS_LABELS = {
    queued:      '等待处理',
    processing:  '处理中',
    completed:   '完成',
    failed:      '失败',
  };

  /**
   * 为单个上传任务建立 SSE 连接，实时推送入库进度到弹条。
   * @param {HTMLElement} el      弹条 DOM 元素
   * @param {object}      info    { jobId, docId, title }
   */
  function connectJobSSE(el, info) {
    const { jobId, title } = info;
    const source = new EventSource(`/api/v1/jobs/${jobId}/stream`);

    // ── 进度更新 ──
    source.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      const label = STAGE_LABELS[data.stage] || STATUS_LABELS[data.status] || data.stage || data.status;
      const progress = data.progress || 0;

      // 更新弹条文字：「解析文档 10%」
      const infoEl = el.querySelector('.processing-info');
      if (infoEl) {
        infoEl.textContent = `${label} ${progress}%`;
      }
    });

    // ── 完成 ──
    source.addEventListener('completed', () => {
      source.close();
      const spinner = el.querySelector('.loading-spinner');
      if (spinner) spinner.remove();
      const infoEl = el.querySelector('.processing-info');
      if (infoEl) infoEl.textContent = '完成';
      el.insertAdjacentHTML('beforeend', '<span class="processing-done"> ✓</span>');
      UI.toast(`「${title}」入库完成`, 'success');
      // 刷新文档列表
      if (typeof loadPage === 'function') loadPage(currentPage);
      // 延迟淡出
      setTimeout(() => {
        el.classList.add('fading');
        setTimeout(() => el.remove(), 400);
      }, 3000);
    });

    // ── 失败 ──
    source.addEventListener('failed', (e) => {
      source.close();
      const data = JSON.parse(e.data);
      const spinner = el.querySelector('.loading-spinner');
      if (spinner) spinner.remove();
      const infoEl = el.querySelector('.processing-info');
      if (infoEl) infoEl.textContent = '失败';
      el.insertAdjacentHTML('beforeend', '<span class="processing-error"> ✗</span>');

      const errMsg = data.error_message || '入库失败';
      UI.toast(`「${title}」入库失败：${errMsg}`, 'error');
      setTimeout(() => {
        el.classList.add('fading');
        setTimeout(() => el.remove(), 400);
      }, 5000);
    });

    // ── 连接异常兜底 ──
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        const spinner = el.querySelector('.loading-spinner');
        if (spinner) {
          spinner.remove();
          el.insertAdjacentHTML('beforeend',
            '<span class="processing-error"> ⚠ 连接断开</span>');
        }
      }
    };

    // 存储引用供页面卸载时清理
    el._sseSource = source;
  }

  /**
   * 显示处理中弹条，为每个 item 建立 SSE 连接。
   * @param {Array<{title: string, jobId: string, docId: string}>} items
   */
  function showProcessingToast(items) {
    if (!items || !items.length) return;

    let container = document.querySelector('.processing-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'processing-toast-container';
      document.body.appendChild(container);
    }

    items.forEach((item) => {
      // 去重：已有同 title + jobId 的弹条则跳过
      if (item.jobId) {
        const existing = [...container.querySelectorAll('.processing-toast-item')];
        const match = existing.find(
          el => el.dataset.jobId === item.jobId
        );
        if (match) return;
      }

      // 新增弹条
      const el = document.createElement('div');
      el.className = 'processing-toast-item';
      el.dataset.jobId = item.jobId || '';
      el.innerHTML =
        `<div class="loading-spinner" style="width:14px;height:14px;border-width:2px"></div>` +
        `<span>${UI.escapeHtml(item.title || '未命名')}</span>` +
        `<span class="processing-info">等待处理 0%</span>`;

      // 限制最多 5 条，挤掉旧弹条时关闭其 SSE 连接
      const all = container.querySelectorAll('.processing-toast-item');
      while (all.length >= 5) {
        const old = all[0];
        if (old._sseSource) old._sseSource.close();
        old.remove();
      }

      container.appendChild(el);

      // 建立 SSE 连接（替代旧轮询）
      if (item.jobId) {
        connectJobSSE(el, item);
      }
    });
  }

  /* -----------------------------------------------------------------------
     CRUD 操作（v1）
     ----------------------------------------------------------------------- */
  /**
   * 软删除文档，二次确认后执行
   * @param {string} docId - 文档 ID
   */
  async function deleteDoc(docId) {
    const ok = await UI.showConfirm('删除确认', '确认删除该文档？（注意：如果有关联的知识块，将同步删除。）', '确认删除');
    if (!ok) return;
    try {
      await API.deleteDocument(docId);
      UI.toast('文档已删除', 'success');
      loadPage(currentPage);
    } catch (e) {
      UI.toast(`删除失败: ${e.message}`, 'error');
    }
  }

  /** 从回收站恢复文档 */
  async function restoreDoc(docId) {
    try {
      await API.restoreDocument(docId);
      UI.toast('文档已恢复', 'success');
      loadPage(currentPage);
    } catch (e) {
      UI.toast(`恢复失败: ${e.message}`, 'error');
    }
  }

  /**
   * 重新处理失败的文档，显示处理中弹条并开始轮询状态
   * @param {string} docId - 文档 ID
   * @param {string} docTitle - 文档标题（用于弹条显示）
   */
  async function retryDoc(docId, docTitle) {
    try {
      showProcessingToast([{ title: docTitle || '文档', docId }]);
      await API.retryDocument(docId);
      currentTab = 'failed';
      currentStatus = 'failed';
      loadPage(currentPage);
    } catch (e) {
      UI.toast(`重试失败: ${e.message}`, 'error');
    }
  }

  /** 批量重试选中的失败文档（并行，受并发上限控制） */
  /** 批量重试失败文档（一次后端批量请求，后端异步入库，前端轮询追踪） */
  async function batchRetry() {
    if (!selectedIds.size) return;
    const ok = await UI.showConfirm('批量重试确认', `确认重新入库 ${selectedIds.size} 篇失败文档？`, '确认重试');
    if (!ok) return;
    const ids = [...selectedIds];
    try {
      const res = await API.batchRetryDocuments(ids);
      const submitted = res?.data?.submitted ?? 0;
      const skipped = res?.data?.skipped ?? 0;
      UI.toast(
        `已提交 ${submitted} 篇重试${skipped ? `，跳过 ${skipped} 篇` : ''}，请等待入库完成后刷新页面`,
        skipped ? 'warning' : 'success'
      );
    } catch (e) {
      UI.toast(`批量重试失败: ${e.message}`, 'error');
    }
    selectedIds.clear();
    loadPage(currentPage);
  }

  /** 批量恢复选中的已删除文档（一次后端批量请求） */
  async function batchRestore() {
    if (!selectedIds.size) return;
    const ok = await UI.showConfirm('批量恢复确认', `确认恢复 ${selectedIds.size} 篇已删除文档？`, '确认恢复');
    if (!ok) return;
    const ids = [...selectedIds];
    try {
      const res = await API.batchRestoreDocuments(ids);
      const restored = res?.data?.restored ?? 0;
      const reIngested = res?.data?.re_ingested ?? 0;
      const parts = [`已恢复 ${restored} 篇`];
      if (reIngested > 0) parts.push(`${reIngested} 篇已提交重入库，请等待完成后刷新页面`);
      UI.toast(parts.join('，'), 'success');
    } catch (e) {
      UI.toast(`批量恢复失败: ${e.message}`, 'error');
    }
    selectedIds.clear();
    loadPage(currentPage);
  }


  /* -----------------------------------------------------------------------
     批量操作
     ----------------------------------------------------------------------- */
  /**
   * 全选/取消全选切换，异步拉取全部文档 ID 以实现跨页全选
   */
  async function toggleSelectAll() {
    const selectAll = document.getElementById('docSelectAll');
    const checkboxes = document.querySelectorAll('.doc-checkbox');
    if (selectAll.checked) {
      // 先勾选当前页，等异步拉满后再启用按钮
      checkboxes.forEach(cb => { cb.checked = true; selectedIds.add(cb.value); });
      // 一次拉取全部 doc_id
      const token = ++_selectAllAbort;
      try {
        const res = await API.listDocumentIds({
          keyword: currentKeyword || undefined,
          status: currentStatus || undefined,
          category: currentCategory || undefined,
        });
        if (token !== _selectAllAbort) return;
        (res?.data || []).forEach(id => selectedIds.add(id));
      } catch (e) { /* skip */ }
      if (token === _selectAllAbort) updateBatchBtn();
    } else {
      selectedIds.clear();
      checkboxes.forEach(cb => { cb.checked = false; });
      updateBatchBtn();
    }
  }

  /** 单个复选框选中/取消切换 */
  function toggleSelect(e) {
    if (e.target.checked) selectedIds.add(e.target.value);
    else selectedIds.delete(e.target.value);
    updateBatchBtn();
  }

  function updateBatchBtn() {
    const btn = document.getElementById('batchDeleteDocBtn');
    if (btn) btn.disabled = selectedIds.size === 0;
    const retryBtn = document.getElementById('batchRetryBtn');
    if (retryBtn) retryBtn.disabled = selectedIds.size === 0;
  }

  /** 批量删除选中文档（一次后端批量请求，含二次确认） */
  async function batchDelete() {
    if (!selectedIds.size) return;
    const ok = await UI.showConfirm('批量删除确认', `确认批量删除 ${selectedIds.size} 篇文档？（注意：如果有关联的知识块，将同步删除。）`, '确认删除');
    if (!ok) return;
    try {
      const res = await API.batchDeleteDocuments([...selectedIds]);
      const updated = res?.data?.updated ?? 0;
      UI.toast(`批量删除完成: ${updated}/${selectedIds.size}`, updated < selectedIds.size ? 'warning' : 'success');
    } catch (e) {
      UI.toast(`批量删除失败: ${e.message}`, 'error');
    }
    selectedIds.clear();
    loadPage(currentPage);
  }

  /* -----------------------------------------------------------------------
     编辑文档元数据
     ----------------------------------------------------------------------- */

  /**
   * 显示编辑文档元数据的模态框（标题、分类），支持新增分类
   * @param {string} docId - 文档 ID
   */
  async function showEditDialog(docId) {
    try {
      const res = await API.getDocument(docId);
      const doc = res?.data || {};

      let existingCategories = [];
      try {
        const filtersRes = await API.searchFilters();
        existingCategories = (filtersRes?.data?.categories || []).map(c => c.value);
      } catch (e) { /* ignore */ }

      const currentCategory = doc.category || '通用';
      const catOptions = [...new Set(['通用', ...existingCategories, currentCategory])]
        .map(c => `<option value="${UI.escapeHtml(c)}" ${currentCategory === c ? 'selected' : ''}>${UI.escapeHtml(c)}</option>`)
        .join('');

      UI.showModal(
        '编辑文档',
        `
          <div class="form-stack">
            <div id="editDocFormError" class="form-error is-hidden"></div>
            <div>
              <label class="field-label">文档标题 <span>*</span></label>
              <input id="editDocTitle" class="input" style="width: 100%;" value="${UI.escapeHtml(doc.title || '')}" />
            </div>
            <div>
              <label class="field-label">分类</label>
              <select class="select" id="editDocCategorySelect" onfocus="Documents.onEditCategoryFocus()" onchange="Documents.onEditCategorySelect()" style="width: 100%;">
                ${catOptions}
                <option value="__custom__">✚ 新增分类…</option>
              </select>
            </div>
          </div>
        `,
        `
          <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
          <button class="btn btn-primary" onclick="Documents.saveEdit('${docId}')">保存修改</button>
        `
      );
    } catch (e) {
      UI.toast(`加载文档失败: ${e.message}`, 'error');
    }
  }

  let _editCatPrev = '';

  function onEditCategoryFocus() {
    const select = document.getElementById('editDocCategorySelect');
    if (select && select.value !== '__custom__') {
      _editCatPrev = select.value;
    }
  }

  function onEditCategorySelect() {
    const select = document.getElementById('editDocCategorySelect');
    if (!select || select.value !== '__custom__') return;
    showNewCategoryDialog('edit');
  }

  function showNewCategoryDialog(mode) {
    UI.showModal(
      '新增分类',
      `
        <div class="form-stack">
          <div>
            <label class="field-label">分类名称 <span>*</span></label>
            <input class="input" type="text" id="newCategoryInput" placeholder="输入新分类名称" style="width:100%" autofocus>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="Documents.cancelNewCategory('${mode}')">取消</button>
        <button class="btn btn-primary" onclick="Documents.confirmNewCategory('${mode}')">确认添加</button>
      `
    );
    setTimeout(() => document.getElementById('newCategoryInput')?.focus(), 100);
  }

  function cancelNewCategory(mode) {
    const selectId = mode === 'upload' ? 'docCategorySelect' : 'editDocCategorySelect';
    const select = document.getElementById(selectId);
    if (select && _editCatPrev) select.value = _editCatPrev;
    document.querySelector('.modal-backdrop:last-child')?.remove();
  }

  function confirmNewCategory(mode) {
    const name = document.getElementById('newCategoryInput')?.value?.trim();
    if (!name) { UI.toast('请输入分类名称', 'error'); return; }

    const selectId = mode === 'upload' ? 'docCategorySelect' : 'editDocCategorySelect';
    const select = document.getElementById(selectId);
    if (select) {
      // 在 __custom__ 之前插入新选项
      const customOpt = select.querySelector('option[value="__custom__"]');
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      opt.selected = true;
      if (customOpt) {
        select.insertBefore(opt, customOpt);
      } else {
        select.appendChild(opt);
      }
    }

    // 关闭最顶层弹窗
    const backdrops = document.querySelectorAll('.modal-backdrop');
    if (backdrops.length) backdrops[backdrops.length - 1].remove();
    // 使筛选项缓存失效，确保下次打开下拉时能看到新分类
    API.invalidateFiltersCache();
    UI.toast(`已添加分类: ${name}`, 'success');
  }

  /**
   * 保存文档编辑结果（标题和分类）
   * @param {string} docId - 文档 ID
   */
  async function saveEdit(docId) {
    const title = document.getElementById('editDocTitle')?.value?.trim();
    const categorySelect = document.getElementById('editDocCategorySelect');
    const errorEl = document.getElementById('editDocFormError');

    let category = '通用';
    if (categorySelect) {
      category = categorySelect.value || '通用';
    }

    if (!title) {
      if (errorEl) {
        errorEl.textContent = '请输入文档标题。';
        errorEl.classList.remove('is-hidden');
      }
      return;
    }

    try {
      await API.updateDocument(docId, { title, category });
      // 分类可能被修改，使筛选项缓存失效
      API.invalidateFiltersCache();
      UI.toast('文档已更新', 'success');
      document.querySelector('.modal-backdrop:last-child')?.remove();
      loadPage(currentPage);
    } catch (e) {
      if (errorEl) {
        errorEl.textContent = e.message || '保存失败';
        errorEl.classList.remove('is-hidden');
      }
      UI.toast(`保存失败: ${e.message}`, 'error');
    }
  }

  /* -----------------------------------------------------------------------
     上传页面（v1 上传并可自动提交入库）
     ----------------------------------------------------------------------- */
  let selectedFiles = [];

  /**
   * 显示上传文档模态框，支持拖拽、多文件选择，自动检测文件类型
   */
  async function showUploadModal() {
    // 加载已有分类
    let existingCategories = [];
    try {
      const res = await API.searchFilters();
      existingCategories = (res?.data?.categories || []).map(c => c.value);
    } catch (e) { /* ignore */ }

    UI.showModal(
      '上传文档',
      `
        <div class="upload-zone" id="uploadZone" style="border: 2px dashed var(--mist); border-radius: var(--radius-lg); padding: var(--space-6); text-align: center; cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out);">
          <span style="font-size: 2.5rem;">📁</span>
          <div style="font-weight: 550; margin-top: var(--space-2);">拖拽文件到此处，或点击选择</div>
          <div style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: var(--space-1);">可一次选择多个文件，单个文件最大 100 MB，支持 Markdown、TXT、DOCX、XLSX、HTML、PDF、PPTX 格式</div>
          <input type="file" id="fileInput" style="display: none;" accept=".md,.txt,.docx,.xlsx,.html,.htm,.pdf,.pptx" multiple>
          <button class="btn btn-primary" onclick="document.getElementById('fileInput').click();event.stopPropagation()" style="margin-top: var(--space-3);">选择文件</button>
          <div style="display: flex; gap: var(--space-1); justify-content: center; margin-top: var(--space-3);">
            <span class="badge-fmt md">MD</span><span class="badge-fmt txt">TXT</span><span class="badge-fmt docx">DOCX</span><span class="badge-fmt xlsx">XLSX</span>
            <span class="badge-fmt html">HTML</span><span class="badge-fmt pdf">PDF</span><span class="badge-fmt pptx">PPTX</span>
          </div>
        </div>

        <div id="fileInfo" style="display: none; margin-top: var(--space-4);">
          <div class="card">
            <div style="display: flex; align-items: center; gap: var(--space-3);">
              <span style="font-size: 1.5rem;">📄</span>
              <div style="flex: 1;">
                <div style="font-weight: 550;" id="fileNameDisplay">—</div>
                <div style="font-size: var(--text-xs); color: var(--ink-wash);" id="fileSizeDisplay">—</div>
              </div>
              <button class="btn btn-sm btn-ghost" onclick="Documents.clearFile()">✕</button>
            </div>
            <div id="fileListDisplay" class="upload-file-list"></div>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); margin-top: var(--space-3);">
            <div>
              <label class="field-label">文档标题 <span>(仅单文件可选)</span></label>
              <input class="input" type="text" id="docTitle" placeholder="留空则使用文件名" style="width: 100%;">
            </div>
            <div>
              <label class="field-label">分类 <span>(选择已有或输入新分类)</span></label>
              <select class="select" id="docCategorySelect" onfocus="Documents.onUploadCategoryFocus()" onchange="Documents.onCategorySelect()" style="width: 100%;">
                <option value="通用">通用</option>
                ${existingCategories.filter(c => c !== '通用').map(c => `<option value="${UI.escapeHtml(c)}">${UI.escapeHtml(c)}</option>`).join('')}
                <option value="__custom__">✚ 新增分类…</option>
              </select>
            </div>
          </div>

          <div id="uploadProgress" style="display: none; margin-top: var(--space-4);">
            <div class="upload-progress-bar"><div class="upload-progress-fill" id="uploadProgressFill" style="width: 0%;"></div></div>
            <div class="upload-progress-text" id="uploadProgressText">上传中…</div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="Documents.closeUploadModal()">取消</button>
        <button class="btn btn-primary" id="uploadBtn" onclick="Documents.doUpload()">↑ 开始上传并入库</button>
      `
    );

    selectedFiles = [];
    document.getElementById('fileInfo').style.display = 'none';

    setTimeout(() => bindUploadEvents(), 50);
  }

  function onUploadCategoryFocus() {
    const select = document.getElementById('docCategorySelect');
    if (select && select.value !== '__custom__') {
      _editCatPrev = select.value;
    }
  }

  function onCategorySelect() {
    const select = document.getElementById('docCategorySelect');
    if (!select || select.value !== '__custom__') return;
    showNewCategoryDialog('upload');
  }

  function closeUploadModal() {
    const backdrop = document.querySelector('.modal-backdrop');
    if (backdrop) backdrop.remove();
  }

  function bindUploadEvents() {
    const zone = document.getElementById('uploadZone');
    const input = document.getElementById('fileInput');
    if (!zone || !input) return;
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault(); zone.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) selectFile(e.dataTransfer.files);
    });
    input.addEventListener('change', () => { if (input.files.length > 0) selectFile(input.files); });
  }

  function selectFile(files) {
    const incoming = Array.from(files instanceof FileList ? files : [files]).filter(Boolean);
    const validFiles = [];
    let skipped = 0;
    incoming.forEach((file) => {
      if (file.size > 100 * 1024 * 1024) {
        skipped++;
        return;
      }
      validFiles.push(file);
    });
    if (skipped) UI.toast(`${skipped} 个文件超过 100 MB，已跳过`, 'error');
    if (!validFiles.length) return;

    selectedFiles = validFiles;
    renderSelectedFiles();
  }

  function renderSelectedFiles() {
    document.getElementById('fileInfo').style.display = 'block';
    const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
    const titleInput = document.getElementById('docTitle');
    document.getElementById('fileNameDisplay').textContent = selectedFiles.length === 1
      ? selectedFiles[0].name
      : `已选择 ${selectedFiles.length} 个文件`;
    document.getElementById('fileSizeDisplay').textContent = selectedFiles.length === 1
      ? UI.formatSize(selectedFiles[0].size)
      : `合计 ${UI.formatSize(totalSize)}`;

    if (titleInput) {
      titleInput.disabled = selectedFiles.length > 1;
      titleInput.placeholder = selectedFiles.length > 1 ? '多文件上传时自动使用文件名' : '留空则使用文件名';
      if (selectedFiles.length > 1) titleInput.value = '';
    }

    const listEl = document.getElementById('fileListDisplay');
    if (listEl) {
      listEl.innerHTML = selectedFiles.map((file, index) => `
        <div class="upload-file-item">
          <span class="upload-file-name">${UI.escapeHtml(file.name)}</span>
          <span class="upload-file-size">${UI.formatSize(file.size)}</span>
          <button class="btn btn-sm btn-ghost" onclick="Documents.removeSelectedFile(${index})">移除</button>
        </div>
      `).join('');
    }
  }

  function clearFile() {
    selectedFiles = [];
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('fileInput').value = '';
  }

  function removeSelectedFile(index) {
    selectedFiles.splice(index, 1);
    if (!selectedFiles.length) {
      clearFile();
      return;
    }
    renderSelectedFiles();
  }

  /**
   * 带并发上限的并行执行：最多同时运行 limit 个任务，完成一个补一个。
   * @param {Array} tasks - 返回 Promise 的函数数组
   * @param {number} limit - 最大并发数
   * @returns {Promise<Array>} - 与输入顺序一致的结果数组（每项为 {status, value/reason}）
   */
  async function runWithConcurrencyLimit(tasks, limit) {
    const results = new Array(tasks.length);
    let index = 0;

    async function worker() {
      while (index < tasks.length) {
        const i = index++;
        try {
          results[i] = { status: 'fulfilled', value: await tasks[i]() };
        } catch (e) {
          results[i] = { status: 'rejected', reason: e };
        }
      }
    }

    const workers = Array.from({ length: Math.min(limit, tasks.length) }, () => worker());
    await Promise.all(workers);
    return results;
  }

  /**
   * 执行文档上传并自动入库，支持多文件并行上传和替换模式（同名文档覆盖）
   * 并发上限由 MAX_CONCURRENT_UPLOADS 控制
   * @param {string|null} [replaceDocId=null] - 要替换的文档 ID
   * @param {boolean} [confirmReplace=false] - 是否已确认替换
   */
  async function doUpload(replaceDocId = null, confirmReplace = false) {
    if (!selectedFiles.length) { UI.toast('请先选择文件', 'error'); return; }
    const categorySelect = document.getElementById('docCategorySelect');
    const category = categorySelect?.value || '通用';

    // 先关闭弹窗，但延迟 DOM 重操作，避免和 FormData 构造冲突阻塞主线程
    const fileList = selectedFiles.slice();
    closeUploadModal();

    try {
      // 立即上传（此时 DOM 还干净），一次 HTTP 请求发送全部文件
      const res = await API.uploadDocument(fileList, category, { replaceDocId, confirmReplace });

      // 上传完成后再做 DOM 操作
      currentTab = 'active';
      currentStatus = 'active';
      loadPage(1);
      const data = res?.data || {};
      const results = data.files || [];

      let success = 0;
      let duplicate = 0;
      let failed = 0;
      const successItems = [];

      for (const r of results) {
        if (r.error) {
          failed++;
          UI.toast(`「${r.file_name}」上传失败: ${r.error}`, 'error');
        } else if (r.duplicate) {
          duplicate++;
          UI.toast(`「${r.file_name}」内容重复，已跳过`, 'info');
        } else {
          success++;
          successItems.push({ title: r.file_name, jobId: r.job_id, docId: r.doc_id });
        }
      }

      const parts = [`成功 ${success}`];
      if (duplicate) parts.push(`重复 ${duplicate}`);
      if (failed) parts.push(`失败 ${failed}`);
      UI.toast(`上传完成：${parts.join('，')}`, failed ? 'warning' : 'success');
      loadPage(1);
      // 更新弹条为实际 docId 以便 SSE 轮询入库状态
      if (successItems.length) showProcessingToast(successItems);
    } catch (e) {
      UI.toast(`上传失败: ${e.message}`, 'error');
    }
  }

  function showReplaceConfirmModal(suggestedData, file, title, category) {
    const backdrop = document.querySelector('.modal-backdrop');
    if (backdrop) backdrop.remove();

    UI.showModal(
      '检测到同名文件',
      `
        <div style="padding: var(--space-4) 0;">
          <div style="display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4);">
            <span style="font-size: 2rem;">⚠️</span>
            <div>
              <div style="font-weight: 550;">已存在同名文档</div>
              <div style="font-size: var(--text-sm); color: var(--ink-wash);">
                文档：${UI.escapeHtml(suggestedData.suggested_doc_title || '未命名')}
              </div>
            </div>
          </div>
          <div style="background: var(--mist); padding: var(--space-3); border-radius: var(--radius-md);">
            <div style="font-size: var(--text-sm); color: var(--ink-wash);">
              即将上传：${UI.escapeHtml(file.name)}
            </div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="Documents.closeUploadModal();">取消</button>
        <button class="btn btn-outline" onclick="Documents.uploadAsNew('${UI.escapeHtml(suggestedData.suggested_doc_id)}')">作为新文档上传</button>
        <button class="btn btn-primary" onclick="Documents.confirmReplace('${UI.escapeHtml(suggestedData.suggested_doc_id)}')">替换现有文档</button>
      `
    );
  }

  async function uploadAsNew(skipDocId) {
    closeUploadModal();
    UI.toast('将作为新文档上传', 'info');
    showUploadModal();
  }

  async function confirmReplace(docId) {
    const backdrop = document.querySelector('.modal-backdrop');
    if (backdrop) backdrop.remove();

    showUploadModal();
    setTimeout(() => {
      selectedFiles = [selectedFiles[0]];
      renderSelectedFiles();
      const btn = document.getElementById('uploadBtn');
      if (btn) {
        btn.textContent = '↑ 确认替换并上传';
        btn.onclick = () => Documents.doUpload(docId, true);
      }
    }, 100);
  }

  let updatingDocId = null;

  async function showUpdateModal(docId, docTitle) {
    updatingDocId = docId;

    let existingCategories = [];
    try {
      const res = await API.searchFilters();
      existingCategories = (res?.data?.categories || []).map(c => c.value);
    } catch (e) { /* ignore */ }

    UI.showModal(
      `更新文档：${docTitle}`,
      `
        <div class="upload-zone" id="updateUploadZone" style="border: 2px dashed var(--mist); border-radius: var(--radius-lg); padding: var(--space-6); text-align: center; cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out);">
          <span style="font-size: 2.5rem;">📁</span>
          <div style="font-weight: 550; margin-top: var(--space-2);">选择新版本文件</div>
          <div style="font-size: var(--text-xs); color: var(--ink-wash); margin-top: var(--space-1);">旧版本将被软删除，新知识块将重新生成</div>
          <input type="file" id="updateFileInput" style="display: none;" accept=".md,.txt,.docx,.xlsx,.html,.htm,.pdf,.pptx">
          <button class="btn btn-primary" onclick="document.getElementById('updateFileInput').click();event.stopPropagation()" style="margin-top: var(--space-3);">选择文件</button>
        </div>

        <div id="updateFileInfo" style="display: none; margin-top: var(--space-4);">
          <div class="card">
            <div style="display: flex; align-items: center; gap: var(--space-3);">
              <span style="font-size: 1.5rem;">📄</span>
              <div style="flex: 1;">
                <div style="font-weight: 550;" id="updateFileNameDisplay">—</div>
                <div style="font-size: var(--text-xs); color: var(--ink-wash);" id="updateFileSizeDisplay">—</div>
              </div>
              <button class="btn btn-sm btn-ghost" onclick="Documents.clearUpdateFile()">✕</button>
            </div>
          </div>

          <div id="updateUploadProgress" style="display: none; margin-top: var(--space-4);">
            <div class="upload-progress-bar"><div class="upload-progress-fill" id="updateUploadProgressFill" style="width: 0%;"></div></div>
            <div class="upload-progress-text" id="updateUploadProgressText">上传中…</div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
        <button class="btn btn-primary" id="updateUploadBtn" onclick="Documents.doUpdateUpload()" disabled>↑ 更新文档</button>
      `
    );

    setTimeout(() => {
      const zone = document.getElementById('updateUploadZone');
      const input = document.getElementById('updateFileInput');
      if (zone && input) {
        zone.addEventListener('click', () => input.click());
        zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', (e) => {
          e.preventDefault(); zone.classList.remove('drag-over');
          if (e.dataTransfer.files.length > 0) selectUpdateFile(e.dataTransfer.files[0]);
        });
        input.addEventListener('change', () => { if (input.files.length > 0) selectUpdateFile(input.files[0]); });
      }
    }, 50);
  }

  let selectedUpdateFile = null;

  function selectUpdateFile(file) {
    if (!file) return;
    if (file.size > 100 * 1024 * 1024) {
      UI.toast('文件超过 100 MB', 'error');
      return;
    }
    selectedUpdateFile = file;
    document.getElementById('updateFileInfo').style.display = 'block';
    document.getElementById('updateFileNameDisplay').textContent = file.name;
    document.getElementById('updateFileSizeDisplay').textContent = UI.formatSize(file.size);
    const btn = document.getElementById('updateUploadBtn');
    if (btn) btn.disabled = false;
  }

  function clearUpdateFile() {
    selectedUpdateFile = null;
    document.getElementById('updateFileInfo').style.display = 'none';
    const input = document.getElementById('updateFileInput');
    if (input) input.value = '';
    const btn = document.getElementById('updateUploadBtn');
    if (btn) btn.disabled = true;
  }

  async function doUpdateUpload() {
    if (!selectedUpdateFile || !updatingDocId) {
      UI.toast('请先选择文件', 'error');
      return;
    }

    const file = selectedUpdateFile;
    const updateTitle = file.name || '文档';

    // 立即关闭弹窗
    document.querySelector('.modal-backdrop:last-child')?.remove();
    currentTab = 'active';
    currentStatus = 'active';
    loadPage(1);

    try {
      const result = await API.uploadDocument(file, '通用', {
        replaceDocId: updatingDocId,
        confirmReplace: true,
      });

      const data = result?.data || {};
      if (data.duplicate) {
        UI.toast('文件内容与已有文档重复，更新已取消', 'error');
      } else if (data.suggested_replace) {
        UI.toast('检测到同名文件，请重新操作', 'error');
      } else {
        UI.toast('文档已更新', 'success');
        loadPage(1);
        showProcessingToast([{ title: updateTitle, jobId: data.job_id, docId: data.doc_id }]);
      }
    } catch (e) {
      UI.toast(`更新失败: ${e.message}`, 'error');
    }
  }

  return { renderList, showUploadModal, closeUploadModal, onCategorySelect, onEditCategoryFocus, onEditCategorySelect, showNewCategoryDialog, cancelNewCategory, confirmNewCategory, doSearch, switchTab, resetFilters, loadPage, deleteDoc, restoreDoc, retryDoc, batchRetry, batchRestore, showEditDialog, saveEdit, toggleSelectAll, toggleSelect, batchDelete, selectFile, clearFile, removeSelectedFile, doUpload, showUpdateModal, selectUpdateFile, clearUpdateFile, doUpdateUpload, confirmReplace, uploadAsNew, showDocDetail };
})();
