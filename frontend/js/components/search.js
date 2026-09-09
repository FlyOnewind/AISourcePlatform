/* ==========================================================================
   搜索页面组件 — 混合检索（v1 API），含过滤面板、结果详情、检索调试
   ========================================================================== */

const SearchPage = (() => {

  let lastResult = null;
  let lastQuery = '';
  let pendingTopKSelectId = '';

  /**
   * 渲染搜索页面（路由入口），先展示骨架再异步加载筛选项
   */
  async function render() {
    UI.setBreadcrumb([{ label: '仪表盘', path: '#/' }, { label: '知识搜索' }]);

    // ── 立即渲染骨架，消除侧边栏点击后的空白等待感 ──
    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div><h1 class="page-title">知识搜索</h1><p class="page-subtitle">按问题检索知识块，支持分类、知识类型过滤与混合检索</p></div>
        </div>
      </div>
      <div class="loading-overlay"><div class="loading-spinner"></div><span>加载搜索…</span></div>
    `);

    // 加载筛选项
    let filterOptions = {};
    try {
      const res = await API.searchFilters();
      filterOptions = res?.data || {};
    } catch (e) { /* ignore */ }
    categoryOptions = (filterOptions.categories || []).map(c => c.value);

    UI.render(`
      <div class="page-header">
        <div class="page-header-row">
          <div>
            <h1 class="page-title">知识搜索</h1>
            <p class="page-subtitle">按问题检索知识块，支持分类、知识类型过滤与混合检索</p>
          </div>
        </div>
      </div>

      <!-- 搜索筛选工具栏 -->
      <div class="doc-toolbar kb-filter-bar search-filter-bar">
        <div class="search-input-wrap">
          <span class="search-input-icon">⌕</span>
          <input class="input kb-toolbar-search" type="text" id="searchInput" placeholder="输入问题，检索最相关的知识块…" autofocus
                 onkeydown="if(event.key==='Enter')SearchPage.doSearch()">
          <select id="searchTopK" class="select select-sm search-topk" data-current-value="3" onchange="SearchPage.handleTopKChange('searchTopK')">
            <option value="3" selected>Top 3</option>
            <option value="5">Top 5</option>
            <option value="8">Top 8</option>
            <option value="__custom__">自定义...</option>
          </select>
        </div>
        <button class="btn btn-primary" onclick="SearchPage.doSearch()">搜索</button>
        <div class="multi-select" id="searchCategoryWrap">
          <button type="button" class="select select-sm multi-select-trigger" id="searchCategoryTrigger" onclick="SearchPage.toggleCategoryDropdown(event)">
            <span>全部文档分类</span>
          </button>
          <div class="multi-select-dropdown is-hidden" id="searchCategoryDropdown">
            ${(filterOptions.categories || []).map(c => `
              <label class="multi-select-item">
                <input type="checkbox" value="${UI.escapeHtml(c.value)}" onchange="SearchPage.onCategoryCheckboxChange()">
                <span>${UI.escapeHtml(c.value)}</span>
              </label>
            `).join('')}
          </div>
        </div>
        <div class="multi-select" id="searchKtypeWrap">
          <button type="button" class="select select-sm multi-select-trigger" id="searchKtypeTrigger" onclick="SearchPage.toggleKtypeDropdown(event)">
            <span>全部类型</span>
          </button>
          <div class="multi-select-dropdown is-hidden" id="searchKtypeDropdown">
            ${(filterOptions.knowledge_types || []).map(k => `
              <label class="multi-select-item">
                <input type="checkbox" value="${UI.escapeHtml(k.value)}" onchange="SearchPage.onKtypeCheckboxChange()">
                <span>${UI.escapeHtml(UI.ktypeLabel(k.value))}</span>
              </label>
            `).join('')}
          </div>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="SearchPage.resetFilters()">清除筛选</button>
        <span class="doc-count" id="searchCountText"></span>
      </div>

      <!-- 搜索结果 -->
      <div id="searchResults" style="margin-top: var(--space-4);">
        <div class="empty-state">
          <div class="empty-state-icon">⌕</div>
          <div class="empty-state-title">输入查询开始搜索</div>
          <div class="empty-state-desc">支持自然语言问题，系统将自动改写查询并执行混合检索（向量 + BM25 + Rerank）</div>
        </div>
      </div>
    `);
  }

  /**
   * 执行混合检索，收集当前筛选条件后调用后端搜索接口
   */
  async function doSearch() {
    const query = document.getElementById('searchInput')?.value?.trim();
    if (!query) return;

    const topK = readTopK('searchTopK', 3);

    lastQuery = query;
    document.getElementById('searchResults').innerHTML = `<div class="loading-overlay"><div class="loading-spinner"></div><span>搜索中…</span></div>`;

    try {
      const filters = {};
      // 收集多选分类
      const checkedCats = document.querySelectorAll('#searchCategoryDropdown input[type="checkbox"]:checked');
      const selectedCategories = Array.from(checkedCats).map(cb => cb.value);
      if (selectedCategories.length > 0) filters.categories = selectedCategories;
      // 收集多选知识类型
      const checkedKtypes = document.querySelectorAll('#searchKtypeDropdown input[type="checkbox"]:checked');
      const selectedKtypes = Array.from(checkedKtypes).map(cb => cb.value);
      if (selectedKtypes.length > 0) filters.knowledge_types = selectedKtypes;
      // Milvus 层已强制 status == "active"，无需前端重复过滤

      const res = await API.search(query, topK, filters, {
        hybrid: true,
        rewrite: true,
      });

      const data = res?.data || {};
      const meta = res?.metadata || {};
      data.rewritten_query = meta.rewritten_query || '';
      data.total_count = meta.total_count || 0;
      lastResult = data;
      renderResults(data, query);
    } catch (e) {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state empty-state-error"><div class="empty-state-icon">!</div><div class="empty-state-title">搜索失败</div><div class="empty-state-desc">${UI.escapeHtml(e.message)}</div></div>`;
    }
  }

  /* -----------------------------------------------------------------------
     清除筛选 — 清空分类、类型，保留搜索词和 TopK
     ----------------------------------------------------------------------- */
  function resetFilters() {
    // 清空分类多选
    const catCbs = document.querySelectorAll('#searchCategoryDropdown input[type="checkbox"]');
    catCbs.forEach(cb => { cb.checked = false; });
    updateCategoryTrigger();
    // 清空知识类型多选
    const ktypeCbs = document.querySelectorAll('#searchKtypeDropdown input[type="checkbox"]');
    ktypeCbs.forEach(cb => { cb.checked = false; });
    updateKtypeTrigger();
    // 不修改搜索词和 TopK
    // 如果搜索框中有内容则重新搜索
    const query = document.getElementById('searchInput')?.value?.trim();
    if (query) {
      doSearch();
    } else {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">⌕</div>
          <div class="empty-state-title">输入查询开始搜索</div>
          <div class="empty-state-desc">支持自然语言问题，系统将自动改写查询并执行混合检索（向量 + BM25 + Rerank）</div>
        </div>`;
      const countEl = document.getElementById('searchCountText');
      if (countEl) countEl.textContent = '';
    }
  }

  function renderResults(data, query) {
    const results = data.results || [];
    const total = data.total_count || results.length;
    const rewritten = data.rewritten_query || '';

    // 更新工具栏计数
    const countEl = document.getElementById('searchCountText');
    if (countEl) countEl.textContent = `共 ${total} 条结果`;

    if (results.length === 0) {
      document.getElementById('searchResults').innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🔍</div>
          <div class="empty-state-title">未找到相关结果</div>
          <div class="empty-state-desc">尝试使用不同的关键词或调整过滤条件</div>
        </div>`;
      return;
    }

    const itemsHtml = results.map((item, i) => {
      const sc = item.score_components || {};
      const rerankLabel = sc.rerank != null ? sc.rerank.toFixed(4) : '—';
      const rerankCls = sc.rerank != null ? '' : 'score-na';
      return `
      <div class="result-card" onclick="SearchPage.showResultDetail('${item.chunk_id}')">
        <div class="result-card-header">
          <span class="result-card-title">#${i + 1} ${UI.escapeHtml(item.title || '未命名知识块')}</span>
          <span class="result-card-score" title="Vec ${sc.vector?.toFixed(4) || '0'} / BM25 ${sc.bm25?.toFixed(4) || '0'} / RRF ${sc.rrf?.toFixed(4) || '0'} / LLM ${rerankLabel}">
            ${(item.score || 0).toFixed(4)}
            <span class="score-detail">
              <span>Vec  ${sc.vector?.toFixed(4) || '0.0000'}</span>
              <span>BM25 ${sc.bm25?.toFixed(4) || '0.0000'}</span>
              <span>RRF  ${sc.rrf?.toFixed(4) || '0.0000'}</span>
              <span class="${rerankCls}">LLM  ${rerankLabel}</span>
            </span>
          </span>
        </div>
        <div class="result-card-content">${UI.escapeHtml((item.content || '').substring(0, 250))}${item.content?.length > 250 ? '…' : ''}</div>
        <div class="result-card-meta">
          ${UI.ktypeBadge(item.knowledge_type)}
          <span class="tag">${UI.escapeHtml(item.category || '')}</span>
          ${item.doc_title ? `<span class="tag">来源文档：${UI.escapeHtml(item.doc_title)}</span>` : ''}
        </div>
      </div>
    `}).join('');

    document.getElementById('searchResults').innerHTML = `
      <div class="search-stats">
        <span>查询: <strong>${UI.escapeHtml(query)}</strong></span>
        ${rewritten ? `<span>改写: <strong>${UI.escapeHtml(rewritten)}</strong></span>` : ''}
        <span>共 <strong>${total}</strong> 条结果</span>
      </div>
      <div class="result-list">${itemsHtml}</div>
    `;
  }

  /**
   * 在模态框中展示知识块的完整内容和评分明细
   * @param {string} chunkId - 知识块 ID
   */
  function showResultDetail(chunkId) {
    const item = (lastResult?.results || []).find(r => r.chunk_id === chunkId);
    if (!item) return;

    UI.showModal(
      `知识块详情 — ${UI.escapeHtml(item.title || chunkId)}`,
      `
        <div style="font-size: var(--text-sm); line-height: 1.6;">
          <div style="display: flex; gap: var(--space-2); margin-bottom: var(--space-3); flex-wrap: wrap;">
            ${UI.ktypeBadge(item.knowledge_type)}
            <span class="tag">${UI.escapeHtml(item.category || '')}</span>
            <span class="tag">Score: ${(item.score || 0).toFixed(4)}</span>
          </div>
          <div style="margin-bottom: var(--space-4);">
            <h4>内容</h4>
            <pre class="code-block">${UI.escapeHtml(item.content || '')}</pre>
          </div>
          ${item.doc_title ? `<p><strong>来源文档:</strong> ${UI.escapeHtml(item.doc_title)} (${item.doc_id})</p>` : ''}
          ${(item.source_refs || []).length ? `
            <div><strong>来源引用:</strong>
              ${item.source_refs.map(ref => {
                const sectionPath = (ref.source_location?.section_path || []).join(' › ');
                return sectionPath ? `
                  <div style="font-size: var(--text-xs); color: var(--ink-wash); padding: var(--space-1) 0;">
                    📄 ${UI.escapeHtml(sectionPath)}
                  </div>` : '';
              }).filter(Boolean).join('')}
            </div>` : ''}
        </div>
      `,
      `<button class="btn btn-secondary" onclick="this.closest('.modal-backdrop').remove()">关闭</button>`
    );
  }

  /**
   * 从 select 元素中读取 TopK 数值，处理自定义值情况
   * @param {string} selectId - select 元素 ID
   * @param {number} fallback - 解析失败时的默认值
   * @returns {number} TopK 值（1-15 之间）
   */
  function readTopK(selectId, fallback) {
    const select = document.getElementById(selectId);
    const raw = select?.value === '__custom__' ? select.dataset.currentValue : select?.value;
    const value = parseInt(raw || `${fallback}`, 10);
    return Number.isFinite(value) ? Math.min(15, Math.max(1, value)) : fallback;
  }

  /**
   * 处理 TopK 下拉框变化，如果选择"自定义"则弹出数量输入框
   * @param {string} selectId - select 元素 ID
   */
  function handleTopKChange(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return;
    if (select.value !== '__custom__') {
      select.dataset.currentValue = select.value;
      return;
    }
    pendingTopKSelectId = selectId;
    const currentValue = readTopK(selectId, 3);
    select.value = `${currentValue}`;
    showCustomTopKDialog();
  }

  function showCustomTopKDialog() {
    UI.showModal(
      '自定义 TopK',
      `
        <div class="form-stack">
          <div>
            <label class="field-label">检索数量 <span>*</span></label>
            <input id="customTopKInput" class="input input-number" type="number" min="1" max="15" step="1"
                   value="" placeholder="请输入检索数量" style="width: 100%; text-align: left;"
                   onkeydown="if(event.key==='Enter')SearchPage.confirmCustomTopK();if(event.key==='Escape')SearchPage.cancelCustomTopK();">
            <div class="field-help">请输入 1 到 15 之间的整数。</div>
            <div id="customTopKError" class="field-warning is-hidden">请输入 1 到 15 之间的整数。</div>
          </div>
        </div>
      `,
      `
        <button class="btn btn-secondary" onclick="SearchPage.cancelCustomTopK()">取消</button>
        <button class="btn btn-primary" onclick="SearchPage.confirmCustomTopK()">确认</button>
      `
    );
    setTimeout(() => document.getElementById('customTopKInput')?.focus(), 50);
  }

  /** 取消自定义 TopK 输入，恢复之前的值 */
  function cancelCustomTopK() {
    const select = document.getElementById(pendingTopKSelectId);
    if (select) select.value = select.dataset.currentValue || '3';
    document.querySelector('.modal-backdrop:last-child')?.remove();
    pendingTopKSelectId = '';
  }

  /** 确认自定义 TopK 值，校验后更新下拉框选项 */
  function confirmCustomTopK() {
    const input = document.getElementById('customTopKInput');
    const error = document.getElementById('customTopKError');
    const value = parseInt(input?.value || '', 10);
    if (!Number.isFinite(value) || value < 1 || value > 15) {
      if (error) error.classList.remove('is-hidden');
      input?.focus();
      return;
    }

    const select = document.getElementById(pendingTopKSelectId);
    if (select) {
      upsertCustomTopKOption(select, value);
      select.value = `${value}`;
      select.dataset.currentValue = `${value}`;
    }
    document.querySelector('.modal-backdrop:last-child')?.remove();
    pendingTopKSelectId = '';
  }

  function upsertCustomTopKOption(select, value) {
    const customOption = select.querySelector('option[data-custom-topk="true"]');
    const presetOption = [...select.options].find((option) =>
      option.value === `${value}` && option.dataset.customTopk !== 'true'
    );
    if (presetOption) {
      customOption?.remove();
      return;
    }
    if (customOption) {
      customOption.value = `${value}`;
      customOption.textContent = `Top ${value}（自定义）`;
      return;
    }
    const option = document.createElement('option');
    option.value = `${value}`;
    option.textContent = `Top ${value}（自定义）`;
    option.dataset.customTopk = 'true';
    select.insertBefore(option, select.querySelector('option[value="__custom__"]'));
  }

  /**
   * 切换分类多选下拉的显示/隐藏
   */
  function toggleCategoryDropdown(event) {
    event.stopPropagation();
    const dropdown = document.getElementById('searchCategoryDropdown');
    if (!dropdown) return;
    dropdown.classList.toggle('is-hidden');
  }

  /**
   * 分类 checkbox 变化时更新触发按钮文案，自动触发搜索
   */
  function onCategoryCheckboxChange() {
    updateCategoryTrigger();
    doSearch();
  }

  /**
   * 更新分类触发按钮的显示文案（"全部文档分类" / 单个分类名 / "已选 N 个分类"）
   */
  function updateCategoryTrigger() {
    const checkboxes = document.querySelectorAll('#searchCategoryDropdown input[type="checkbox"]:checked');
    const count = checkboxes.length;
    const trigger = document.getElementById('searchCategoryTrigger');
    if (!trigger) return;
    const span = trigger.querySelector('span');
    if (!span) return;
    if (count === 0) {
      span.textContent = '全部文档分类';
    } else if (count === 1) {
      span.textContent = checkboxes[0].value;
    } else {
      span.textContent = `已选 ${count} 个分类`;
    }
  }

  // ── 知识类型多选下拉 ──────────────────────────────────────────────

  function toggleKtypeDropdown(event) {
    event.stopPropagation();
    const dropdown = document.getElementById('searchKtypeDropdown');
    if (!dropdown) return;
    dropdown.classList.toggle('is-hidden');
  }

  function onKtypeCheckboxChange() {
    updateKtypeTrigger();
    doSearch();
  }

  function updateKtypeTrigger() {
    const checkboxes = document.querySelectorAll('#searchKtypeDropdown input[type="checkbox"]:checked');
    const count = checkboxes.length;
    const trigger = document.getElementById('searchKtypeTrigger');
    if (!trigger) return;
    const span = trigger.querySelector('span');
    if (!span) return;
    if (count === 0) {
      span.textContent = '全部类型';
    } else if (count === 1) {
      span.textContent = UI.ktypeLabel(checkboxes[0].value);
    } else {
      span.textContent = `已选 ${count} 个类型`;
    }
  }

  // 点击下拉外部区域关闭下拉（统一处理分类和知识类型）
  document.addEventListener('click', function (e) {
    [
      { trigger: 'searchCategoryTrigger', dropdown: 'searchCategoryDropdown' },
      { trigger: 'searchKtypeTrigger', dropdown: 'searchKtypeDropdown' },
    ].forEach(({ trigger: tid, dropdown: did }) => {
      const trigger = document.getElementById(tid);
      const dropdown = document.getElementById(did);
      if (dropdown && trigger && !trigger.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.classList.add('is-hidden');
      }
    });
  });

  return {
    render, doSearch, showResultDetail,
    handleTopKChange, cancelCustomTopK, confirmCustomTopK, resetFilters,
    toggleCategoryDropdown, onCategoryCheckboxChange,
    toggleKtypeDropdown, onKtypeCheckboxChange,
  };
})();
