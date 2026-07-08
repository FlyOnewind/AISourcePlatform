/* ==========================================================================
   Chunks — 知识块管理页面（v1 API）

   功能：标签页筛选（活跃/回收站）、搜索（支持按知识块标题/文档标题切换）、
         文档类型筛选、知识类型筛选、排序、分页列表、详情抽屉、编辑、删除、恢复
   样式：与仪表盘设计令牌一致（绢本 Silk Scroll）
   ========================================================================== */

const Chunks = (() => {

  let currentPage = 1;
  let selectedIds = new Set();
  let filterOptions = {};  // 从后端动态加载的筛选项
  let currentTab = 'active';  // 当前标签页: active | deleted
  let currentSearchMode = 'chunk_title';  // chunk_title | doc_title
  let previousCreateDocCategory = '通用';
  let _selectAllAbort = 0;  // 取消异步全选

  /* -----------------------------------------------------------------------
     Render — 渲染主容器
     ----------------------------------------------------------------------- */

  /**
   * 渲染知识块管理页面（路由入口），先展示骨架再异步加载数据
   */
  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '知识块管理' }]);

    // ── 立即渲染骨架，消除侧边栏点击后的空白等待感 ──
    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div><h1 class="page-title">知识块管理</h1><p class="page-subtitle">浏览和管理所有已抽取的知识块</p></div>
          <div class="page-actions">
            <button class="btn btn-outline btn-sm" disabled>批量删除</button>
            <button class="btn btn-primary" disabled>+ 新建知识块</button>
          </div>
        </div>
      </div>
      <div class="doc-tabs">
        <button class="doc-tab active" disabled>活跃</button>
        <button class="doc-tab" disabled>回收站</button>
      </div>
      <div class="loading-overlay"><div class="loading-spinner"></div><span>加载知识块列表…</span></div>
    `);

    // 动态加载筛选项
    try {
      const res = await API.searchFilters();
      filterOptions = res?.data || {};
    } catch (e) { filterOptions = {}; }

    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">知识块管理</h1>
            <p class="page-subtitle">浏览和管理所有已抽取的知识块，支持筛选、编辑、删除与恢复</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline btn-sm" onclick="Chunks.batchDelete()" id="batchDeleteChunkBtn" disabled>批量删除</button>
            <button class="btn btn-primary" onclick="Chunks.showCreateDialog()">+ 新建知识块</button>
          </div>
        </div>
      </div>

      <!-- 标签页：活跃 / 回收站 -->
      <div class="doc-tabs">
        <button class="doc-tab active" data-tab="active" onclick="Chunks.switchTab('active')">活跃</button>
        <button class="doc-tab" data-tab="deleted" onclick="Chunks.switchTab('deleted')">回收站</button>
      </div>

      <!-- 筛选工具栏 -->
      <div class="doc-toolbar kb-filter-bar chunk-filter-bar">
        <div class="chunk-search-box">
          <input class="input kb-toolbar-search" type="text" id="chunkKeyword" placeholder="搜索知识块标题 / 内容…"
                 onkeydown="if(event.key==='Enter')Chunks.load()">
          <select class="select select-sm chunk-search-mode" id="chunkSearchMode" onchange="Chunks.onSearchModeChange()">
            <option value="chunk_title">知识块</option>
            <option value="doc_title">文档</option>
          </select>
        </div>
        <select class="select select-sm" id="chunkCategoryFilter" onchange="Chunks.load()">
          <option value="">全部文档分类</option>
          ${(filterOptions.categories || []).map(c => `<option value="${UI.escapeHtml(c.value)}">${UI.escapeHtml(c.value)}</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkTypeFilter" onchange="Chunks.load()">
          <option value="">全部类型</option>
          ${(filterOptions.knowledge_types || []).map(k => `<option value="${UI.escapeHtml(k.value)}">${UI.ktypeLabel(k.value)}</option>`).join('')}
        </select>
        <select class="select select-sm" id="chunkSortFilter" onchange="Chunks.load()">
          <option value="updated_at:desc">更新时间</option>
          <option value="created_at:desc">创建时间</option>
          <option value="title:asc">标题 A-Z</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="Chunks.resetFilters()">清空筛选</button>
        <span class="doc-count" id="chunkCountText">—</span>
      </div>

      <!-- 表格 -->
      <div class="table-wrap">
        <table class="chunk-table">
          <thead>
            <tr>
              <th style="width: 3%;"><input type="checkbox" id="chunkSelectAll" onclick="Chunks.toggleSelectAll()" /></th>
              <th style="width: 28%;">知识内容</th>
              <th style="width: 13%;">来源文档</th>
              <th style="width: 8%;">分类</th>
              <th style="width: 8%;">类型</th>
              <th style="width: 7%;">状态</th>
              <th style="width: 10%;">创建时间</th>
              <th style="width: 10%;">更新时间</th>
              <th style="width: 13%;">操作</th>
            </tr>
          </thead>
          <tbody id="chunkTableBody">
            <tr><td colspan="9"><div class="loading-overlay"><div class="loading-spinner"></div><span>加载知识块…</span></div></td></tr>
          </tbody>
        </table>
      </div>

      <div id="chunkPagination" class="pagination"></div>
    `);

    await load();
  }

  /* -----------------------------------------------------------------------
     Tab — 标签页切换
     ----------------------------------------------------------------------- */

  /**
   * 切换知识块标签页（活跃/回收站），重置选中和分页状态
   * @param {string} tab - 标签页标识: active | deleted
   */
  function switchTab(tab) {
    if (currentTab === tab) return;
    currentTab = tab;
    document.querySelectorAll('.doc-tab').forEach(el => {
      el.classList.toggle('active', el.getAttribute('data-tab') === tab);
    });
    currentPage = 1;
    selectedIds.clear();
    _selectAllAbort++;
    updateBatchBtnLabel();
    load();
  }

  function updateBatchBtnLabel() {
    const btn = document.getElementById('batchDeleteChunkBtn');
    if (!btn) return;
    if (currentTab === 'deleted') {
      btn.textContent = '批量恢复';
      btn.setAttribute('onclick', 'Chunks.batchRestore()');
    } else {
      btn.textContent = '批量删除';
      btn.setAttribute('onclick', 'Chunks.batchDelete()');
    }
  }

  /* -----------------------------------------------------------------------
     Load — 加载知识块列表
     ----------------------------------------------------------------------- */

  /**
   * 根据当前筛选条件加载知识块分页列表
   * @param {number} [page=1] - 页码
   */
  async function load(page = 1) {
    currentPage = page;
    renderLoading();
    const keyword = document.getElementById('chunkKeyword')?.value?.trim() || '';
    const category = document.getElementById('chunkCategoryFilter')?.value || '';
    const knowledgeType = document.getElementById('chunkTypeFilter')?.value || '';
    const [sortBy, sortOrder] = (document.getElementById('chunkSortFilter')?.value || 'updated_at:desc').split(':');

    try {
      const res = await API.listChunks({
        page, page_size: 20,
        keyword: keyword || undefined,
        search_mode: currentSearchMode,
        category: category || undefined,
        knowledge_type: knowledgeType || undefined,
        status: currentTab,
        sort_by: sortBy || 'created_at',
        sort_order: sortOrder || 'desc',
      });
      if (!isChunkPageMounted()) return;
      renderTable(res);
    } catch (e) {
      if (!isChunkPageMounted()) return;
      renderError(e.message || '请求失败');
      UI.toast(`加载知识块失败：${e.message}`, 'error');
    }
  }

  function isChunkPageMounted() {
    return Boolean(document.getElementById('chunkTableBody'));
  }

  function renderLoading() {
    const tbody = document.getElementById('chunkTableBody');
    const pagEl = document.getElementById('chunkPagination');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="9"><div class="loading-overlay"><div class="loading-spinner"></div><span>加载知识块...</span></div></td></tr>`;
    }
    if (pagEl) pagEl.innerHTML = '';
  }

  function renderError(message) {
    const tbody = document.getElementById('chunkTableBody');
    const pagEl = document.getElementById('chunkPagination');
    if (tbody) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="9">
        <div class="empty-state empty-state-error">
          <div class="empty-state-icon">!</div>
          <div class="empty-state-title">知识块加载失败</div>
          <div class="empty-state-desc">${UI.escapeHtml(message)}</div>
          <div class="empty-actions">
            <button class="btn btn-primary" onclick="Chunks.load(${currentPage})">重新加载</button>
          </div>
        </div>
      </td></tr>`;
    }
    if (pagEl) pagEl.innerHTML = '';
  }

  function renderTable(res) {
    const data = res?.data || [];
    const selectAll = document.getElementById('chunkSelectAll');
    if (selectAll) { selectAll.checked = false; selectAll.disabled = data.length === 0; }
    const tbody = document.getElementById('chunkTableBody');
    if (!tbody) return;
    const meta = res?.metadata || {};
    const total = meta.total || 0;
    const countEl = document.getElementById('chunkCountText');
    if (countEl) countEl.textContent = `共 ${total} 个知识块`;

    if (!data.length) {
      const hasFilters = hasActiveFilters();
      tbody.innerHTML = `<tr class="empty-row"><td colspan="9">
        <div class="empty-state">
          <div class="empty-state-icon">⊞</div>
          <div class="empty-state-title">${hasFilters ? '未找到匹配知识块' : (currentTab === 'deleted' ? '回收站为空' : '暂无知识块')}</div>
          <div class="empty-state-desc">${hasFilters ? '当前筛选条件下没有知识块。可以调整关键词、文档类型或知识类型后再试。' : (currentTab === 'deleted' ? '被删除的知识块会出现在这里。' : '上传文档并完成入库后，知识块将自动出现在这里。')}</div>
          <div class="empty-actions">
            ${hasFilters ? '<button class="btn btn-secondary" onclick="Chunks.resetFilters()">清空筛选</button>' : ''}
            ${currentTab === 'active' ? '<button class="btn btn-primary" onclick="Documents.showUploadModal()">上传文档</button>' : ''}
          </div>
        </div>
      </td></tr>`;
    } else {
      tbody.innerHTML = data.map(c => `
        <tr>
          <td><input type="checkbox" value="${c.chunk_id}" class="chunk-checkbox" onclick="Chunks.toggleSelect(event)" ${selectedIds.has(c.chunk_id) ? 'checked' : ''} /></td>
          <td>
            <div class="chunk-title-cell">
              <span class="doc-title-link" onclick="Chunks.showDetail('${c.chunk_id}')">${UI.escapeHtml(c.title || '(无标题)')}</span>
              <span class="chunk-preview">${UI.escapeHtml((c.content_preview || c.content || '').substring(0, 96))}${(c.content_preview || c.content || '').length > 96 ? '…' : ''}</span>
              ${renderChunkMiniMeta(c)}
            </div>
          </td>
          <td>${UI.escapeHtml(c.doc_title || c.doc_id || '—')}</td>
          <td>${UI.escapeHtml(c.category || '通用')}</td>
          <td>${UI.ktypeBadge(c.knowledge_type)}</td>
          <td>${UI.statusBadge(c.status || 'active')}</td>
          <td>${UI.formatTime(c.created_at)}</td>
          <td>${UI.formatTime(c.updated_at)}</td>
          <td class="actions-cell">
            ${c.status === 'deleted'
              ? `<button class="btn btn-sm btn-success doc-action-btn" onclick="Chunks.restoreChunk('${c.chunk_id}')" title="恢复知识块">
                   <span class="action-icon">↶</span>恢复
                 </button>`
              : `
                <button class="btn btn-sm btn-outline doc-action-btn" onclick="Chunks.showEditDialog('${c.chunk_id}')" title="编辑知识块">
                  <span class="action-icon">✎</span>编辑
                </button>
                <button class="btn btn-sm btn-danger doc-action-btn" onclick="Chunks.deleteChunk('${c.chunk_id}')" title="删除知识块">
                  <span class="action-icon">🗑</span>删除
                </button>
              `}
          </td>
        </tr>
      `).join('');
    }

    // 分页
    const pagEl = document.getElementById('chunkPagination');
    if (!pagEl) return;
    const totalPages = meta.total_pages || 1;
    if (totalPages > 1) {
      pagEl.innerHTML = `
        <button class="btn btn-sm btn-secondary" onclick="Chunks.load(${Math.max(1, currentPage - 1)})" ${currentPage <= 1 ? 'disabled' : ''}>‹ 上一页</button>
        <span class="pagination-info">${currentPage} / ${totalPages}（共 ${total} 条）</span>
        <button class="btn btn-sm btn-secondary" onclick="Chunks.load(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一页 ›</button>`;
    } else {
      pagEl.innerHTML = total > 0 ? `<span class="pagination-info">共 ${total} 条</span>` : '';
    }
    updateBatchBtn();
  }

  function renderChunkMiniMeta(chunk) {
    const parts = [];
    if ((chunk.asset_count || 0) > 0) parts.push(`${chunk.asset_count} 资源`);
    if ((chunk.source_count || 0) > 0) parts.push(`${chunk.source_count} 来源`);
    if (!parts.length) return '';
    return `<span class="chunk-mini-meta">${parts.map(UI.escapeHtml).join(' / ')}</span>`;
  }

  function hasActiveFilters() {
    return Boolean(
      document.getElementById('chunkKeyword')?.value?.trim()
      || document.getElementById('chunkCategoryFilter')?.value
      || document.getElementById('chunkTypeFilter')?.value
    );
  }

  /** 清空所有筛选条件（关键词、分类、类型、排序），重置搜索模式并重新加载第一页 */
  function resetFilters() {
    ['chunkKeyword', 'chunkCategoryFilter', 'chunkTypeFilter'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const sortEl = document.getElementById('chunkSortFilter');
    if (sortEl) sortEl.value = 'updated_at:desc';
    const modeEl = document.getElementById('chunkSearchMode');
    if (modeEl) modeEl.value = 'chunk_title';
    currentSearchMode = 'chunk_title';
    updateSearchPlaceholder();
    load(1);
  }

  /* -----------------------------------------------------------------------
     Search mode — 搜索模式切换（可切换按"知识块标题"或"文档标题"搜索）
     ----------------------------------------------------------------------- */

  /** 切换搜索模式，更新占位提示文本，有关键词时重新搜索 */
  function onSearchModeChange() {
    const modeEl = document.getElementById('chunkSearchMode');
    currentSearchMode = modeEl?.value || 'chunk_title';
    updateSearchPlaceholder();
    // 有关键词时重新搜索（切换匹配范围），无关键词时只更新 placeholder 不请求
    const keyword = document.getElementById('chunkKeyword')?.value?.trim();
    if (keyword) load(1);
  }

  function updateSearchPlaceholder() {
    const input = document.getElementById('chunkKeyword');
    if (!input) return;
    if (currentSearchMode === 'doc_title') {
      input.placeholder = '输入文档标题关键词…';
    } else {
      input.placeholder = '输入知识块标题 / 内容关键词…';
    }
  }

  /* -----------------------------------------------------------------------
     Detail — 知识块详情抽屉
     ----------------------------------------------------------------------- */
  function _renderAssetSummary(assetRefs) {
    const list = assetRefs || [];
    const typeLabel = { image: 'image', video: 'video', audio: 'audio', attachment: 'attachment', unknown: 'unknown' };
    const counts = {};
    list.forEach((a) => {
      const t = a.asset_type || 'unknown';
      counts[t] = (counts[t] || 0) + 1;
    });
    const lines = Object.entries(counts).map(([t, n]) => `${typeLabel[t] || t} ×${n}`).join(' &emsp; ');
    return `
      <div class="detail-field" style="grid-column: span 2;">
        <label>关联资源（${list.length}）</label>
        <span>${lines || '—'}</span>
      </div>`;
  }

  function _renderSourceRefs(sourceRefs) {
    if (!sourceRefs || !sourceRefs.length) return '';
    const rows = sourceRefs.map((s) => {
      const loc = s.source_location || {};
      const path = loc.section_path?.length ? loc.section_path.join(' › ') : '';
      const page = loc.page != null ? `第 ${loc.page} 页` : '';
      const desc = [page, path].filter(Boolean).join(' · ');
      return `
        <div class="detail-ref-item">
          <span class="detail-ref-text">${UI.escapeHtml(desc || s.element_id)}</span>
        </div>
      `;
    }).join('');
    return `
      <div class="detail-section">
        <h3>来源引用（${sourceRefs.length}）</h3>
        <div class="detail-ref-list">${rows}</div>
      </div>`;
  }

  /**
   * 在右侧抽屉中显示知识块完整详情（内容、来源、资源等）
   * @param {string} chunkId - 知识块 ID
   */
  async function showDetail(chunkId) {
    UI.showDrawer('知识块详情', '<div class="loading-overlay" style="min-height:200px"><div class="loading-spinner"></div><span>加载中…</span></div>');
    try {
      const res = await API.getChunk(chunkId);
      const c = res?.data || {};
      const bodyHtml = `
        <div class="detail-grid">
          <div class="detail-field">
            <label>知识块标题</label>
            <span>${UI.escapeHtml(c.title || '(无标题)')}</span>
          </div>
          <div class="detail-field">
            <label>来源文档</label>
            <span>${UI.escapeHtml(c.doc_title || c.doc_id || '—')}</span>
          </div>
          <div class="detail-field">
            <label>类型</label>
            <span>${UI.ktypeBadge(c.knowledge_type)}</span>
          </div>
          <div class="detail-field">
            <label>分类</label>
            <span>${UI.escapeHtml(c.category || '通用')}</span>
          </div>
          <div class="detail-field">
            <label>状态</label>
            <span>${UI.statusBadge(c.status || 'active')}</span>
          </div>
          <div class="detail-field">
            <label>创建时间</label>
            <span>${UI.formatTime(c.created_at)}</span>
          </div>
          <div class="detail-field">
            <label>更新时间</label>
            <span>${UI.formatTime(c.updated_at)}</span>
          </div>
          ${_renderAssetSummary(c.asset_refs)}
        </div>

        ${_renderSourceRefs(c.source_refs)}

        <div class="detail-content">
          <h3>内容</h3>
          <pre>${UI.escapeHtml(c.content || '(无内容)')}</pre>
        </div>

      `;

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

  /**
   * 显示编辑知识块模态框（标题、分类、类型、内容），支持新增分类
   * @param {string} chunkId - 知识块 ID
   */
  async function showEditDialog(chunkId) {
    try {
      const res = await API.getChunk(chunkId);
      const c = res?.data || {};

      let existingCategories = [];
      try {
        const filtersRes = await API.searchFilters();
        existingCategories = (filtersRes?.data?.categories || []).map(cat => cat.value);
      } catch (e) { /* ignore */ }

      const currentCategory = c.category || '通用';
      const catOptions = [...new Set(['通用', ...existingCategories, currentCategory])]
        .map(cat => `<option value="${UI.escapeHtml(cat)}" ${currentCategory === cat ? 'selected' : ''}>${UI.escapeHtml(cat)}</option>`)
        .join('');

      UI.showModal(
        '编辑知识块',
        `
          <div class="form-stack">
            <div id="editChunkFormError" class="form-error is-hidden"></div>
            <div>
              <label class="field-label">标题 <span>*</span></label>
              <input id="editChunkTitle" class="input" style="width: 100%;" value="${UI.escapeHtml(c.title || '')}" />
            </div>
            <div>
              <label class="field-label">分类</label>
              <select class="select" id="editChunkCategory" onfocus="Chunks.onEditCategoryFocus()" onchange="Chunks.onEditCategorySelect()" style="width: 100%;">
                ${catOptions}
                <option value="__custom__">✚ 新增分类…</option>
              </select>
            </div>
            <div>
              <label class="field-label">类型</label>
              <select id="editChunkType" class="select" style="width: 100%;">
                <option value="declarative" ${c.knowledge_type === 'declarative' ? 'selected' : ''}>陈述型</option>
                <option value="procedural" ${c.knowledge_type === 'procedural' ? 'selected' : ''}>流程型</option>
                <option value="relational" ${c.knowledge_type === 'relational' ? 'selected' : ''}>关系型</option>
              </select>
            </div>
            <div>
              <div class="field-label-row">
                <label class="field-label">内容 <span>*</span></label>
                <span id="editChunkContentCount" class="field-counter">${(c.content || '').length} 字</span>
              </div>
              <textarea id="editChunkContent" class="textarea create-chunk-content" rows="8" style="width: 100%;"
                        oninput="Chunks.updateEditFormState()">${UI.escapeHtml(c.content || '')}</textarea>
            </div>
          </div>
        `,
        `
          <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
          <button class="btn btn-primary" onclick="Chunks.updateChunkFromDialog('${chunkId}')">保存修改</button>
        `
      );
    } catch (e) {
      UI.toast(`加载知识块失败: ${e.message}`, 'error');
    }
  }

  let _editCategoryPrevious = '';

  function onEditCategoryFocus() {
    const select = document.getElementById('editChunkCategory');
    if (select && select.value !== '__custom__') {
      _editCategoryPrevious = select.value;
    }
  }

  function onEditCategorySelect() {
    const select = document.getElementById('editChunkCategory');
    if (!select || select.value !== '__custom__') return;
    showEditCategoryDialog();
  }

  function showEditCategoryDialog() {
    UI.showModal(
      '新增分类',
      `
        <div class="form-stack">
          <div>
            <label class="field-label">分类名称 <span>*</span></label>
            <input class="input" type="text" id="editNewCategoryInput" placeholder="输入新分类名称" style="width:100%" autofocus>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="Chunks.cancelEditCategory()">取消</button>
        <button class="btn btn-primary" onclick="Chunks.confirmEditCategory()">确认添加</button>
      `
    );
    setTimeout(() => document.getElementById('editNewCategoryInput')?.focus(), 100);
  }

  function cancelEditCategory() {
    const select = document.getElementById('editChunkCategory');
    if (select && _editCategoryPrevious) {
      select.value = _editCategoryPrevious;
    }
    document.querySelector('.modal-backdrop:last-child')?.remove();
  }

  function confirmEditCategory() {
    const name = document.getElementById('editNewCategoryInput')?.value?.trim();
    if (!name) { UI.toast('请输入分类名称', 'error'); return; }

    const select = document.getElementById('editChunkCategory');
    if (select) {
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
    document.querySelector('.modal-backdrop:last-child')?.remove();
    UI.toast(`已添加分类: ${name}`, 'success');
  }

  function updateEditFormState() {
    const content = document.getElementById('editChunkContent')?.value || '';
    const counter = document.getElementById('editChunkContentCount');
    if (counter) counter.textContent = `${content.length} 字`;
  }

  /**
   * 从编辑弹窗保存知识块修改（含表单校验和重新索引触发）
   * @param {string} chunkId - 知识块 ID
   */
  async function updateChunkFromDialog(chunkId) {
    const title = document.getElementById('editChunkTitle')?.value?.trim();
    const content = document.getElementById('editChunkContent')?.value?.trim();
    const category = document.getElementById('editChunkCategory')?.value?.trim() || '通用';
    const knowledgeType = document.getElementById('editChunkType')?.value || 'declarative';
    const errorEl = document.getElementById('editChunkFormError');
    if (!title || !content || content.length < 10) {
      if (errorEl) {
        errorEl.textContent = !title ? '请输入知识块标题。' : '知识块内容至少需要 10 个字。';
        errorEl.classList.remove('is-hidden');
      }
      return;
    }

    try {
      await API.updateChunk(chunkId, {
        title,
        content,
        category,
        knowledge_type: knowledgeType,
        reindex: true,
      });
      UI.toast('知识块已更新', 'success');
      document.querySelector('.modal-backdrop:last-child')?.remove();
      document.querySelector('#modalContainer .drawer')?.remove();
      await load(currentPage);
    } catch (e) {
      const msg = e.message || '保存失败';
      if (msg.includes('重复')) {
        // 内容重复：toast 提示，弹窗不关闭，保留已填内容
        UI.toast(msg, 'warning');
      } else {
        if (errorEl) {
          errorEl.textContent = msg;
          errorEl.classList.remove('is-hidden');
        }
        UI.toast(`保存失败: ${msg}`, 'error');
      }
    }
  }

  /* -----------------------------------------------------------------------
     CRUD 操作
     ----------------------------------------------------------------------- */

  /**
   * 显示新建知识块模态框，支持挂到已有文档或创建新的手工文档
   */
  async function showCreateDialog() {
    let documents = [];
    let docLoadError = '';
    try {
      const docsRes = await API.listDocuments({ page_size: 200, status: 'active' });
      documents = docsRes?.data || [];
    } catch (e) {
      docLoadError = e.message || '文档列表加载失败';
    }

    const useExistingChecked = docLoadError ? '' : 'checked';
    const useNewChecked = docLoadError ? 'checked' : '';
    const docOptions = documents.map((d) => `
      <option value="${UI.escapeHtml(d.doc_id)}">${UI.escapeHtml(d.title || d.doc_id)} · ${UI.escapeHtml(d.doc_id)}</option>
    `).join('');
    const categories = ['通用', ...((filterOptions.categories || []).map((c) => c.value).filter(Boolean))]
      .filter((value, index, arr) => arr.indexOf(value) === index);
    previousCreateDocCategory = categories[0] || '通用';
    const categoryOptions = categories.map((c) => `
      <option value="${UI.escapeHtml(c)}">${UI.escapeHtml(c)}</option>
    `).join('');

    UI.showModal(
      '新建知识块',
      `
        <div class="form-stack create-chunk-form">
          <div id="newChunkFormError" class="form-error is-hidden"></div>

          <div>
            <label class="field-label">归属文档 <span>*</span></label>
            <div class="mode-switch create-doc-mode">
              <label>
                <input type="radio" name="newChunkDocMode" value="existing" ${useExistingChecked} ${docLoadError ? 'disabled' : ''} onchange="Chunks.toggleCreateDocMode()">
                <span>选择已有文档</span>
              </label>
              <label>
                <input type="radio" name="newChunkDocMode" value="new" ${useNewChecked} onchange="Chunks.toggleCreateDocMode()">
                <span>新建文档</span>
              </label>
            </div>
          </div>

          <div id="existingDocPanel">
            <select id="newChunkDocId" class="select" style="width: 100%;" ${docLoadError ? 'disabled' : ''}>
              <option value="">${docLoadError ? '文档列表加载失败' : '选择一个已入库文档'}</option>
              ${docOptions}
            </select>
            <div class="${docLoadError ? 'field-warning' : 'field-help'}">
              ${docLoadError ? `${UI.escapeHtml(docLoadError)}，仍可切换到"新建文档"继续创建。` : '知识块会挂到所选文档下，用于后续筛选、溯源和版本管理。'}
            </div>
          </div>

          <div id="newDocPanel" class="is-hidden">
            <div class="form-grid create-doc-grid">
              <div>
                <label class="field-label">新文档标题 <span>*</span></label>
                <input id="newChunkDocTitle" class="input" style="width: 100%;" placeholder="例如：人工补充知识" />
              </div>
              <div>
                <label class="field-label">文档分类 <span>(选择已有或新增)</span></label>
                <select id="newChunkDocCategorySelect" class="select" style="width: 100%;" onchange="Chunks.onCreateDocCategorySelect()">
                  ${categoryOptions}
                  <option value="__custom__">+ 新增分类...</option>
                </select>
              </div>
            </div>
            <div class="field-help">会先创建一个手工文档，再把当前知识块挂到这个新文档下。</div>
          </div>

          <div>
            <label class="field-label">知识块标题 <span>*</span></label>
            <input id="newChunkTitle" class="input" style="width: 100%;" placeholder="例如：退货申请条件" />
          </div>

          <div>
            <div class="field-label-row">
              <label class="field-label">内容 <span>*</span></label>
              <span id="newChunkContentCount" class="field-counter">0 字</span>
            </div>
            <textarea id="newChunkContent" class="textarea create-chunk-content" rows="7" style="width: 100%;"
                      placeholder="输入一段可以独立回答问题的知识内容，例如规则、定义、步骤或限制条件。"
                      oninput="Chunks.updateCreateFormState()"></textarea>
          </div>

          <div>
            <label class="field-label">知识块分类</label>
            <select id="newChunkCategory" class="select" style="width: 100%;">
              ${categoryOptions}
            </select>
          </div>

          <div>
            <label class="field-label">类型</label>
            <select id="newChunkType" class="select" style="width: 100%;">
              <option value="declarative">陈述型</option>
              <option value="procedural">流程型</option>
              <option value="relational">关系型</option>
            </select>
          </div>

          <div id="newChunkCategoryDialog" class="mini-dialog-backdrop is-hidden" role="dialog" aria-modal="true" aria-labelledby="newChunkCategoryDialogTitle">
            <div class="mini-dialog">
              <div class="mini-dialog-header">
                <h3 id="newChunkCategoryDialogTitle">新增文档分类</h3>
                <button type="button" class="btn-close" onclick="Chunks.cancelCreateDocCategory()">&times;</button>
              </div>
              <div class="mini-dialog-body">
                <label class="field-label">分类名称</label>
                <input id="newChunkCategoryDialogInput" class="input" style="width: 100%;" placeholder="例如：售后政策"
                       onkeydown="if(event.key==='Enter')Chunks.confirmCreateDocCategory();if(event.key==='Escape')Chunks.cancelCreateDocCategory();">
                <div id="newChunkCategoryDialogError" class="field-warning is-hidden">请输入分类名称。</div>
              </div>
              <div class="mini-dialog-footer">
                <button type="button" class="btn btn-secondary btn-sm" onclick="Chunks.cancelCreateDocCategory()">取消</button>
                <button type="button" class="btn btn-primary btn-sm" onclick="Chunks.confirmCreateDocCategory()">确认</button>
              </div>
            </div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">取消</button>
        <button class="btn btn-primary" id="confirmCreateChunkBtn">创建知识块</button>
      `
    );

    // 绑定创建按钮事件
    setTimeout(() => {
      updateCreateFormState();
      toggleCreateDocMode();
      ['newChunkDocId', 'newChunkDocTitle', 'newChunkDocCategorySelect', 'newChunkTitle', 'newChunkContent'].forEach((id) => {
        document.getElementById(id)?.addEventListener('input', updateCreateFormState);
        document.getElementById(id)?.addEventListener('change', updateCreateFormState);
      });

      document.getElementById('confirmCreateChunkBtn')?.addEventListener('click', async () => {
        const useNewDoc = isCreateNewDocumentMode();
        let docId = document.getElementById('newChunkDocId')?.value?.trim();
        const docTitle = document.getElementById('newChunkDocTitle')?.value?.trim();
        const docCategory = getCreateDocCategory();
        const title = document.getElementById('newChunkTitle')?.value?.trim();
        const content = document.getElementById('newChunkContent')?.value?.trim();
        const chunkCategory = document.getElementById('newChunkCategory')?.value?.trim() || docCategory || '通用';
        const error = validateCreateForm({ useNewDoc, docId, docTitle, docCategory, title, content });
        if (error) {
          showCreateFormError(error);
          return;
        }

        const btn = document.getElementById('confirmCreateChunkBtn');
        if (btn) {
          btn.disabled = true;
          btn.textContent = '创建中...';
        }

        let createdDocId = null;  // 追踪新建文档，用于失败回滚

        try {
          if (useNewDoc) {
            const docRes = await API.createDocument({
              title: docTitle,
              source_type: 'manual',
              source_uri: `manual://chunk-dialog/${Date.now()}`,
              category: docCategory,
              metadata: JSON.stringify({ manual: true, created_from: 'chunk_dialog' }),
            });
            docId = docRes?.data?.doc_id;
            if (!docId) throw new Error('新文档创建成功，但未返回文档 ID');
            createdDocId = docId;
          }

          await API.createChunk({
            doc_id: docId,
            title,
            content,
            knowledge_type: document.getElementById('newChunkType')?.value,
            category: chunkCategory,
          });
          UI.toast('知识块创建成功', 'success');
          document.querySelector('.modal-backdrop')?.remove();
          await load(1);
        } catch (e) {
          const msg = e.message || '创建失败';
          // 新建文档模式下创建知识块失败 → 清理孤儿文档
          if (createdDocId) {
            try {
              await API.deleteDocument(createdDocId);
            } catch (_) {
              UI.toast(`知识块创建失败，关联的空文档「${docTitle}」未能自动清理，请在文档列表中手动删除`, 'warning');
            }
          }
          // 内容重复 → toast 提示，弹窗不关闭，保留已填内容
          if (msg.includes('重复')) {
            UI.toast(msg, 'warning');
          } else {
            showCreateFormError(msg);
            UI.toast(`创建失败: ${msg}`, 'error');
          }
        } finally {
          if (btn) {
            btn.disabled = false;
            btn.textContent = '创建知识块';
          }
        }
      });
    }, 100);
  }

  function validateCreateForm({ useNewDoc, docId, docTitle, docCategory, title, content }) {
    if (useNewDoc && !docTitle) return '请输入新文档标题。';
    if (useNewDoc && !docCategory) return '请选择或输入文档分类。';
    if (!useNewDoc && !docId) return '请选择归属文档。';
    if (!title) return '请输入知识块标题。';
    if (!content) return '请输入知识块内容。';
    if (content.length < 10) return '知识块内容至少需要 10 个字，方便后续检索和重排。';
    return '';
  }

  function showCreateFormError(message) {
    const el = document.getElementById('newChunkFormError');
    if (!el) return;
    el.textContent = message;
    el.classList.remove('is-hidden');
  }

  function isCreateNewDocumentMode() {
    return document.querySelector('input[name="newChunkDocMode"]:checked')?.value === 'new';
  }

  function getCreateDocCategory() {
    const select = document.getElementById('newChunkDocCategorySelect');
    return select?.value?.trim() || '通用';
  }

  function onCreateDocCategorySelect() {
    const select = document.getElementById('newChunkDocCategorySelect');
    if (!select) return;
    if (select.value === '__custom__') {
      select.value = previousCreateDocCategory;
      showCreateDocCategoryDialog();
      return;
    }
    previousCreateDocCategory = select.value || '通用';
    // 联动：文档分类变化时同步知识块分类
    const chunkCat = document.getElementById('newChunkCategory');
    if (chunkCat) chunkCat.value = select.value;
    updateCreateFormState();
  }

  function showCreateDocCategoryDialog() {
    const dialog = document.getElementById('newChunkCategoryDialog');
    const input = document.getElementById('newChunkCategoryDialogInput');
    const error = document.getElementById('newChunkCategoryDialogError');
    if (!dialog || !input) return;
    input.value = '';
    if (error) error.classList.add('is-hidden');
    dialog.classList.remove('is-hidden');
    setTimeout(() => input.focus(), 0);
  }

  function cancelCreateDocCategory() {
    const dialog = document.getElementById('newChunkCategoryDialog');
    const select = document.getElementById('newChunkDocCategorySelect');
    if (dialog) dialog.classList.add('is-hidden');
    if (select) select.value = previousCreateDocCategory;
    updateCreateFormState();
  }

  function confirmCreateDocCategory() {
    const select = document.getElementById('newChunkDocCategorySelect');
    const input = document.getElementById('newChunkCategoryDialogInput');
    const error = document.getElementById('newChunkCategoryDialogError');
    if (!select || !input) return;
    const value = input.value.trim();
    if (!value) {
      if (error) error.classList.remove('is-hidden');
      input.focus();
      return;
    }

    const existing = [...select.options].find((option) => option.value === value);
    if (!existing) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      const customOption = select.querySelector('option[value="__custom__"]');
      select.insertBefore(option, customOption);
    }
    select.value = value;
    const chunkCategorySelect = document.getElementById('newChunkCategory');
    if (chunkCategorySelect && ![...chunkCategorySelect.options].some((option) => option.value === value)) {
      const chunkOption = document.createElement('option');
      chunkOption.value = value;
      chunkOption.textContent = value;
      chunkCategorySelect.appendChild(chunkOption);
    }
    if (chunkCategorySelect) chunkCategorySelect.value = value;
    previousCreateDocCategory = value;
    cancelCreateDocCategory();
  }

  function toggleCreateDocMode() {
    const useNewDoc = isCreateNewDocumentMode();
    const existingPanel = document.getElementById('existingDocPanel');
    const newPanel = document.getElementById('newDocPanel');
    if (existingPanel) existingPanel.classList.toggle('is-hidden', useNewDoc);
    if (newPanel) newPanel.classList.toggle('is-hidden', !useNewDoc);
    updateCreateFormState();
  }

  function updateCreateFormState() {
    const useNewDoc = isCreateNewDocumentMode();
    const docId = document.getElementById('newChunkDocId')?.value?.trim();
    const docTitle = document.getElementById('newChunkDocTitle')?.value?.trim();
    const docCategory = getCreateDocCategory();
    const title = document.getElementById('newChunkTitle')?.value?.trim();
    const content = document.getElementById('newChunkContent')?.value?.trim() || '';
    const counter = document.getElementById('newChunkContentCount');
    const btn = document.getElementById('confirmCreateChunkBtn');
    const error = document.getElementById('newChunkFormError');

    if (counter) counter.textContent = `${content.length} 字`;
    if (btn && !btn.textContent.includes('创建中')) {
      btn.disabled = (useNewDoc ? (!docTitle || !docCategory) : !docId) || !title || content.length < 10;
    }
    if (error) error.classList.add('is-hidden');
  }

  /**
   * 软删除知识块，二次确认后执行
   * @param {string} chunkId - 知识块 ID
   */
  async function deleteChunk(chunkId) {
    const ok = await UI.showConfirm('删除确认', '确认删除该知识块？', '确认删除');
    if (!ok) return;
    try {
      await API.deleteChunk(chunkId);
      UI.toast('知识块已删除', 'success');
      await load();
    } catch (e) {
      UI.toast(`删除失败: ${e.message}`, 'error');
    }
  }

  /** 从回收站恢复知识块 */
  async function restoreChunk(chunkId) {
    try {
      await API.restoreChunk(chunkId);
      UI.toast('知识块已恢复', 'success');
      await load();
    } catch (e) {
      UI.toast(`恢复失败: ${e.message}`, 'error');
    }
  }

  /* -----------------------------------------------------------------------
     Batch — 批量操作
     ----------------------------------------------------------------------- */

  /**
   * 全选/取消全选切换，异步拉取全部知识块 ID 实现跨页全选
   */
  async function toggleSelectAll() {
    const selectAll = document.getElementById('chunkSelectAll');
    const checkboxes = document.querySelectorAll('.chunk-checkbox');
    if (selectAll.checked) {
      checkboxes.forEach(cb => { cb.checked = true; selectedIds.add(cb.value); });
      const token = ++_selectAllAbort;
      try {
        const res = await API.listChunkIds({
          keyword: document.getElementById('chunkKeyword')?.value?.trim() || undefined,
          search_mode: currentSearchMode,
          category: document.getElementById('chunkCategoryFilter')?.value || undefined,
          knowledge_type: document.getElementById('chunkTypeFilter')?.value || undefined,
          status: currentTab,
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

  /** 单个复选框选中/取消切换，更新批量操作按钮状态 */
  function toggleSelect(e) {
    if (e.target.checked) selectedIds.add(e.target.value);
    else selectedIds.delete(e.target.value);
    updateBatchBtn();
  }

  function updateBatchBtn() {
    const batchBtn = document.getElementById('batchDeleteChunkBtn');
    if (!batchBtn) return;
    batchBtn.disabled = selectedIds.size === 0;
    const selectAll = document.getElementById('chunkSelectAll');
    if (selectAll) selectAll.checked = selectedIds.size > 0;
  }

  /** 批量删除选中的知识块（调用 batch API） */
  async function batchDelete() {
    if (!selectedIds.size) return;
    const ok = await UI.showConfirm('批量删除确认', `确认批量删除 ${selectedIds.size} 个知识块？`, '确认删除');
    if (!ok) return;
    try {
      await API.batchChunkOperation('delete', [...selectedIds]);
      UI.toast(`批量删除完成: ${selectedIds.size} 个知识块`, 'success');
      selectedIds.clear();
      await load();
    } catch (e) {
      UI.toast(`批量删除失败: ${e.message}`, 'error');
    }
  }

  /** 批量恢复选中的已删除知识块（调用 batch API） */
  async function batchRestore() {
    if (!selectedIds.size) return;
    const ok = await UI.showConfirm('批量恢复确认', `确认批量恢复 ${selectedIds.size} 个知识块？`, '确认恢复');
    if (!ok) return;
    try {
      await API.batchChunkOperation('restore', [...selectedIds]);
      UI.toast(`批量恢复完成: ${selectedIds.size} 个知识块`, 'success');
      selectedIds.clear();
      await load();
    } catch (e) {
      UI.toast(`批量恢复失败: ${e.message}`, 'error');
    }
  }

  return { render, load, switchTab, onSearchModeChange, showDetail, showEditDialog, updateEditFormState, updateChunkFromDialog, onEditCategoryFocus, onEditCategorySelect, cancelEditCategory, confirmEditCategory, showCreateDialog, toggleCreateDocMode, onCreateDocCategorySelect, cancelCreateDocCategory, confirmCreateDocCategory, updateCreateFormState, deleteChunk, restoreChunk, toggleSelectAll, toggleSelect, batchDelete, batchRestore, resetFilters };
})();
