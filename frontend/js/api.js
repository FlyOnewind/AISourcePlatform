/* ==========================================================================
   API 客户端 — 封装所有后端 API 调用（主版本 v1）

   前端所有功能统一使用 v1 接口；旧版接口仅由后端保留兼容期。
   ========================================================================== */

const API = (() => {
  const BASE = '';

  /* -----------------------------------------------------------------------
     通用请求封装
     ----------------------------------------------------------------------- */

  /**
   * 将参数对象转换为 URL 查询字符串，自动过滤 null/undefined 值，支持数组参数
   * @param {object} params - 查询参数对象
   * @returns {string} 查询字符串（不含前导 ?）
   */
  function toQueryString(params = {}) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      if (Array.isArray(value)) {
        value.forEach(item => {
          if (item !== undefined && item !== null) qs.append(key, item);
        });
        return;
      }
      qs.append(key, value);
    });
    return qs.toString();
  }

  /**
   * 将查询参数拼接到路径上，自动处理已有查询字符串的情况
   * @param {string} path - URL 路径
   * @param {object} params - 查询参数对象
   * @returns {string} 带查询字符串的完整路径
   */
  function withParams(path, params) {
    const qs = toQueryString(params);
    if (!qs) return path;
    return `${path}${path.includes('?') ? '&' : '?'}${qs}`;
  }

  /**
   * 通用 HTTP 请求封装，支持 JSON / FormData 请求体、超时控制和统一错误处理
   * @param {string} method - HTTP 方法 (GET/POST/PATCH/DELETE)
   * @param {string} path - API 路径
   * @param {object} [opts] - 可选参数
   * @param {object} [opts.body] - 请求体，支持普通对象和 FormData
   * @param {object} [opts.params] - URL 查询参数
   * @param {number} [opts.timeout=30000] - 请求超时毫秒数
   * @returns {Promise<object|null>} 解析后的 JSON 响应，空响应体返回 null
   */
  async function request(method, path, opts = {}) {
    const { body, params, timeout = 30000 } = opts;
    const url = `${BASE}${withParams(path, params)}`;

    const headers = {};
    let reqBody = null;

    if (body) {
      if (body instanceof FormData) {
        reqBody = body;
      } else {
        headers['Content-Type'] = 'application/json';
        reqBody = JSON.stringify(body);
      }
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
      const res = await fetch(url, { method, headers, body: reqBody, signal: controller.signal });

      if (!res.ok) {
        const errText = await res.text().catch(() => '');
        let errMsg = `HTTP ${res.status}`;
        try {
          const errJson = JSON.parse(errText);
          // 兼容 v1 统一错误结构 { error: { message } } 和旧结构 { detail }
          errMsg = errJson?.error?.message || errJson?.detail || errJson?.message || errMsg;
        } catch (e) { /* ignore */ }
        throw new Error(errMsg);
      }

      // 检查废弃响应头
      const deprecated = res.headers.get('X-Deprecated');
      if (deprecated) {
        console.warn(`[API] 调用了已废弃的接口: ${method} ${path} — ${deprecated}`);
      }

      const text = await res.text();
      if (!text.trim()) return null;
      return JSON.parse(text);
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error('请求超时，请稍后重试');
      }
      if (err instanceof TypeError && (err.message === 'Failed to fetch' || err.message.includes('NetworkError'))) {
        throw new Error('无法连接后端服务，请确认服务已启动后重试。');
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  function get(path, opts) { return request('GET', path, opts); }
  function post(path, body, opts) { return request('POST', path, { ...opts, body }); }

  /* =======================================================================
     API v1 — 健康检查
     ======================================================================= */

  /** 获取系统健康状态，包含各外部依赖的连接状态 */
  async function health() { return get('/api/v1/health'); }

  /* =======================================================================
     API v1 — 文档管理（主版本）
     ======================================================================= */
  /** 获取文档分页列表 */
  async function listDocuments(params = {}) {
    return get('/api/v1/documents', { params });
  }
  /** 获取全部文档 ID 列表（用于全选等批量操作） */
  async function listDocumentIds(params = {}) {
    return get('/api/v1/documents/ids', { params });
  }
  /** 创建手工文档 */
  async function createDocument(params) {
    return post('/api/v1/documents', null, { params });
  }
  /** 获取单个文档详情 */
  async function getDocument(docId) {
    return get(`/api/v1/documents/${docId}`);
  }
  /** 获取文档的解析元素列表 */
  async function listDocumentElements(docId, params = {}) {
    return get(`/api/v1/documents/${docId}/elements`, { params });
  }
  /** 更新文档元数据（标题、分类等） */
  async function updateDocument(docId, params) {
    return request('PATCH', `/api/v1/documents/${docId}`, { params, timeout: 30000 });
  }
  /** 软删除文档 */
  async function deleteDocument(docId) {
    return request('DELETE', `/api/v1/documents/${docId}`, { timeout: 30000 });
  }
  /** 批量软删除文档 */
  async function batchDeleteDocuments(docIds) {
    return post('/api/v1/documents/batch-delete', { doc_ids: docIds });
  }
  /** 批量重试失败文档 */
  async function batchRetryDocuments(docIds) {
    return post('/api/v1/documents/batch-retry', { doc_ids: docIds });
  }
  /** 批量恢复已删除文档 */
  async function batchRestoreDocuments(docIds) {
    return post('/api/v1/documents/batch-restore', { doc_ids: docIds });
  }
  /** 从回收站恢复文档 */
  async function restoreDocument(docId) {
    return post(`/api/v1/documents/${docId}/restore`);
  }
  /** 重新处理失败的文档 */
  async function retryDocument(docId) {
    return post(`/api/v1/documents/${docId}/retry`);
  }
  /**
   * 上传文档文件（支持 multipart/form-data），可指定标题、分类及替换选项。
   * 上传后自动异步入库，返回 {job_id, doc_id, status: "queued"}。
   * @param {File} file - 文件对象
   * @param {string} [title=''] - 文档标题，为空则使用文件名
   * @param {string} [category='通用'] - 文档分类
   * @param {object} [options] - 可选参数
   * @param {string} [options.replaceDocId] - 替换已有文档的 ID
   * @param {boolean} [options.confirmReplace] - 是否确认替换
   */
  /**
   * 上传文档（支持单文件或多文件），一次 HTTP 请求完成。
   * 多文件时浏览器只发一个 multipart 请求，避免并发请求阻塞主线程。
   * @param {File|File[]} files - 单个文件或文件数组
   * @param {string} [category='通用'] - 文档分类
   * @param {object} [options] - 可选参数
   * @param {string} [options.replaceDocId] - 替换已有文档的 ID（仅单文件有效）
   * @param {boolean} [options.confirmReplace] - 是否确认替换（仅单文件有效）
   */
  async function uploadDocument(files, category = '通用', options = {}) {
    const fd = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    fileList.forEach(f => fd.append('files', f));
    if (category) fd.append('category', category);
    const params = {
      replace_doc_id: options.replaceDocId,
      confirm_replace: options.confirmReplace,
    };
    // 多文件时给更长超时
    const timeout = fileList.length > 1 ? 120000 : 60000;
    return post('/api/v1/documents/upload', fd, { params, timeout });
  }

  /** 查询异步入库任务状态（Restful 备用，正常情况下使用 SSE） */
  async function getJobStatus(jobId) {
    return get(`/api/v1/jobs/${jobId}`);
  }

  /** 获取文档的版本历史记录 */
  async function getDocumentHistory(docId) {
    return get(`/api/v1/documents/${docId}/history`);
  }
  /* =======================================================================
     API v1 — 知识块管理（主版本）
     ======================================================================= */
  /** 获取知识块分页列表 */
  async function listChunks(params = {}) { return get('/api/v1/chunks', { params }); }
  /** 获取全部知识块 ID 列表（用于全选等批量操作） */
  async function listChunkIds(params = {}) { return get('/api/v1/chunks/ids', { params }); }
  /** 创建知识块（需指定归属文档） */
  async function createChunk(params)     { return post('/api/v1/chunks', null, { params }); }
  /** 获取单个知识块详情 */
  async function getChunk(chunkId)       { return get(`/api/v1/chunks/${chunkId}`); }
  /** 更新知识块内容或元数据，支持触发重建索引 */
  async function updateChunk(chunkId, params) {
    return request('PATCH', `/api/v1/chunks/${chunkId}`, { params, timeout: 30000 });
  }
  /** 软删除知识块 */
  async function deleteChunk(chunkId) {
    return request('DELETE', `/api/v1/chunks/${chunkId}`, { timeout: 30000 });
  }
  /** 从回收站恢复知识块 */
  async function restoreChunk(chunkId) {
    return post(`/api/v1/chunks/${chunkId}/restore`);
  }
  /** 批量操作知识块（删除 / 恢复） */
  async function batchChunkOperation(action, chunkIds, status = null) {
    return post('/api/v1/chunks/batch', { action, chunk_ids: chunkIds, status });
  }

  /* =======================================================================
     API v1 — 检索（主版本）
     ======================================================================= */
  /**
   * 执行混合检索（向量 + BM25 → RRF 融合 → LLM Rerank）
   * @param {string} query - 查询文本
   * @param {number} [topK=10] - 返回结果数量
   * @param {object} [filters] - 过滤条件（分类、知识类型、状态等）
   * @param {object} [options] - 检索选项（是否启用混合检索、查询改写、高亮等）
   */
  async function search(query, topK = 10, filters = {}, options = {}) {
    return post('/api/v1/search', { query, top_k: topK, filters, options }, { timeout: 180000 });
  }

  /** 筛选项缓存（5 分钟 TTL），减少页面切换时的网络等待 */
  let _filtersCache = null;
  let _filtersCacheTime = 0;
  const FILTERS_CACHE_TTL = 5 * 60 * 1000;

  /** 获取检索可用的筛选项（分类列表、知识类型列表等），带缓存 */
  async function searchFilters() {
    if (_filtersCache && (Date.now() - _filtersCacheTime) < FILTERS_CACHE_TTL) {
      return _filtersCache;
    }
    const result = await get('/api/v1/search/filters');
    _filtersCache = result;
    _filtersCacheTime = Date.now();
    return result;
  }

  /** 使筛选项缓存失效（新增/编辑分类后调用，确保下次获取最新数据） */
  function invalidateFiltersCache() {
    _filtersCache = null;
    _filtersCacheTime = 0;
  }

  /* =======================================================================
     公开 API — v1 方法为默认导出
     ======================================================================= */
  return {
    // ── v1 健康检查 ──
    health,
    // ── v1 文档 ──
    listDocuments, listDocumentIds, createDocument, getDocument, listDocumentElements, updateDocument,
    deleteDocument, batchDeleteDocuments, batchRetryDocuments, batchRestoreDocuments,
    restoreDocument, retryDocument, uploadDocument, getDocumentHistory,
    // ── v1 知识块 ──
    listChunks, listChunkIds, createChunk, getChunk, updateChunk,
    deleteChunk, restoreChunk,
    batchChunkOperation,
    // ── v1 检索 ──
    search, searchFilters, invalidateFiltersCache,
  };
})();
