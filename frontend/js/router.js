/* ==========================================================================
   路由 — 基于 hash 的轻量 SPA 路由
   ========================================================================== */

const Router = (() => {
  const routes = {};
  let currentRoute = null;
  let beforeEachGuard = null;

  /**
   * 注册路由
   */
  function on(pattern, handler) {
    routes[pattern] = handler;
  }

  /**
   * 导航守卫
   */
  function beforeEach(fn) {
    beforeEachGuard = fn;
  }

  /**
   * 解析当前 hash，支持 query 参数（如 /documents?status=failed）
   */
  function resolve() {
    let hash = window.location.hash.slice(1) || '/';

    // 剥离 query 参数用于路由匹配
    const qIdx = hash.indexOf('?');
    const query = {};
    if (qIdx !== -1) {
      const qs = hash.slice(qIdx + 1);
      hash = hash.slice(0, qIdx);
      qs.split('&').forEach(pair => {
        const [k, v] = pair.split('=');
        if (k) query[decodeURIComponent(k)] = decodeURIComponent(v || '');
      });
    }

    // 尝试匹配精确路径
    if (routes[hash]) return { handler: routes[hash], params: {}, query };

    // 尝试匹配带路径参数路由 (如 /documents/:id)
    for (const [pattern, handler] of Object.entries(routes)) {
      const paramNames = [];
      const regexStr = pattern.replace(/:([^/]+)/g, (_, name) => {
        paramNames.push(name);
        return '([^/]+)';
      });
      const regex = new RegExp(`^${regexStr}$`);
      const match = hash.match(regex);
      if (match) {
        const params = {};
        paramNames.forEach((name, i) => { params[name] = match[i + 1]; });
        return { handler, params, query };
      }
    }

    return null;
  }

  /**
   * 导航到指定路径
   */
  function navigate(path) {
    window.location.hash = path;
  }

  /**
   * 执行当前路由
   */
  async function run() {
    const resolved = resolve();
    if (!resolved) {
      navigate('/');
      return;
    }

    // 导航守卫
    if (beforeEachGuard) {
      const allowed = await beforeEachGuard(resolved);
      if (allowed === false) return;
    }

    const rawHash = window.location.hash.slice(1) || '/';
    currentRoute = { path: rawHash.split('?')[0], params: resolved.params, query: resolved.query };
    // 将 query 合并到 params 中传给 handler，方便组件读取
    await resolved.handler({ ...resolved.params, _query: resolved.query });
  }

  /**
   * 获取当前路由信息
   */
  function current() {
    return currentRoute;
  }

  /**
   * 从 hash 中解析 query 参数（供组件调用）
   */
  function getQuery() {
    const hash = window.location.hash.slice(1) || '';
    const qIdx = hash.indexOf('?');
    if (qIdx === -1) return {};
    const query = {};
    hash.slice(qIdx + 1).split('&').forEach(pair => {
      const [k, v] = pair.split('=');
      if (k) query[decodeURIComponent(k)] = decodeURIComponent(v || '');
    });
    return query;
  }

  // 监听 hash 变化
  window.addEventListener('hashchange', run);
  window.addEventListener('DOMContentLoaded', run);

  return { on, navigate, run, current, beforeEach, getQuery };
})();
