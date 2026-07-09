// 管理后台前端逻辑：纯 fetch + 原生 DOM，无构建步骤。
const API_KEY_STORAGE = "kb_platform_admin_api_key";

function apiKey() {
  return localStorage.getItem(API_KEY_STORAGE);
}

async function apiFetch(path, options = {}) {
  const headers = Object.assign({ "X-API-Key": apiKey() }, options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, { ...options, headers });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok || body.success === false) {
    const msg = (body.error && body.error.message) || body.detail?.message || `请求失败 (${resp.status})`;
    throw new Error(msg);
  }
  return body.data;
}

function badge(status) {
  const cls = status === "published" ? "published" : status === "disabled" ? "disabled" : "draft";
  return `<span class="badge ${cls}">${status}</span>`;
}

// ---- Login ----
function showApp() {
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("app-view").classList.remove("hidden");
  loadOverview();
}

function showLogin() {
  document.getElementById("login-view").classList.remove("hidden");
  document.getElementById("app-view").classList.add("hidden");
}

document.getElementById("login-btn").addEventListener("click", async () => {
  const key = document.getElementById("api-key-input").value.trim();
  if (!key) return alert("请输入 API Key");
  localStorage.setItem(API_KEY_STORAGE, key);
  try {
    await apiFetch("/api/v1/metrics/overview");
    showApp();
  } catch (e) {
    alert("登录失败: " + e.message);
    localStorage.removeItem(API_KEY_STORAGE);
  }
});

document.getElementById("logout-btn").addEventListener("click", () => {
  localStorage.removeItem(API_KEY_STORAGE);
  showLogin();
});

// ---- Navigation ----
document.querySelectorAll(".nav-list li").forEach((li) => {
  li.addEventListener("click", () => {
    document.querySelectorAll(".nav-list li").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".page").forEach((x) => x.classList.remove("active"));
    li.classList.add("active");
    const page = li.dataset.page;
    document.getElementById(`page-${page}`).classList.add("active");
    if (page === "overview") loadOverview();
    if (page === "capabilities") loadCapabilities();
    if (page === "knowledge") loadKnowledgeBases();
    if (page === "agents") loadAgents();
    if (page === "audit") loadAuditLogs();
  });
});

// ---- Overview ----
async function loadOverview() {
  const el = document.getElementById("overview-cards");
  el.innerHTML = "<p>加载中...</p>";
  try {
    const m = await apiFetch("/api/v1/metrics/overview");
    el.innerHTML = [
      ["能力总数", m.total_capabilities],
      ["已发布能力", m.published_capabilities],
      ["知识库数量", m.total_knowledge_bases],
      ["文档数量", m.total_documents],
      ["Agent数量", m.total_agents],
      ["近24h调用量", m.today_invocations],
      ["近24h成功率", (m.today_success_rate * 100).toFixed(1) + "%"],
      ["平均耗时(ms)", m.avg_latency_ms],
    ].map(([label, value]) => `<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
  } catch (e) {
    el.innerHTML = `<p style="color:var(--danger)">加载失败: ${e.message}</p>`;
  }
}

// ---- Capabilities ----
async function loadCapabilities() {
  const type = document.getElementById("cap-type-filter").value;
  const tbody = document.getElementById("cap-table-body");
  tbody.innerHTML = "<tr><td colspan='6'>加载中...</td></tr>";
  try {
    const qs = type ? `?type=${type}` : "";
    const caps = await apiFetch(`/api/v1/capabilities${qs}`);
    tbody.innerHTML = caps.map((c) => `
      <tr>
        <td>${c.name}</td><td>${c.type}</td><td>${c.business_domain || "-"}</td>
        <td>${badge(c.status)}</td><td>${c.current_version}</td><td>${c.security_level}</td>
      </tr>`).join("") || "<tr><td colspan='6'>暂无数据</td></tr>";
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='6' style="color:var(--danger)">${e.message}</td></tr>`;
  }
}
document.getElementById("cap-refresh-btn").addEventListener("click", loadCapabilities);
document.getElementById("cap-type-filter").addEventListener("change", loadCapabilities);

// ---- Knowledge ----
async function loadKnowledgeBases() {
  const tbody = document.getElementById("kb-table-body");
  const kbSelect = document.getElementById("upload-kb-id");
  tbody.innerHTML = "<tr><td colspan='6'>加载中...</td></tr>";
  try {
    const kbs = await apiFetch("/api/v1/knowledge-bases");
    kbSelect.innerHTML = [
      '<option value="">请选择知识库</option>',
      ...kbs.map((kb) => `<option value="${kb.id}">${kb.name} (${kb.kb_key})</option>`),
    ].join("");
    tbody.innerHTML = kbs.map((kb) => `
      <tr data-kb-id="${kb.id}">
        <td>${kb.name}</td><td>${kb.kb_key}</td><td>${kb.business_domain || "-"}</td>
        <td>${kb.security_level}</td><td>${badge(kb.status)}</td>
        <td><button onclick="loadDocuments('${kb.id}')">查看文档</button></td>
      </tr>`).join("") || "<tr><td colspan='6'>暂无数据</td></tr>";
  } catch (e) {
    kbSelect.innerHTML = '<option value="">请选择知识库</option>';
    tbody.innerHTML = `<tr><td colspan='6' style="color:var(--danger)">${e.message}</td></tr>`;
  }
}

document.getElementById("kb-create-btn").addEventListener("click", async () => {
  const kbKey = document.getElementById("kb-create-key").value.trim();
  const kbName = document.getElementById("kb-create-name").value.trim();
  const kbDomain = document.getElementById("kb-create-domain").value.trim();
  const kbSecurity = document.getElementById("kb-create-security").value;

  if (!kbKey || !kbName) {
    alert("请填写 kb_key 和知识库名称");
    return;
  }

  try {
    await apiFetch("/api/v1/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({
        kb_key: kbKey,
        name: kbName,
        business_domain: kbDomain || null,
        security_level: kbSecurity,
      }),
    });
    document.getElementById("kb-create-key").value = "";
    document.getElementById("kb-create-name").value = "";
    document.getElementById("kb-create-domain").value = "";
    alert("知识库创建成功");
    loadKnowledgeBases();
  } catch (e) {
    alert("知识库创建失败: " + e.message);
  }
});

async function loadDocuments(kbId) {
  document.getElementById("upload-kb-id").value = kbId;
  const tbody = document.getElementById("doc-table-body");
  tbody.innerHTML = "<tr><td colspan='4'>加载中...</td></tr>";
  try {
    const docs = await apiFetch(`/api/v1/knowledge-bases/${kbId}/documents`);
    tbody.innerHTML = docs.map((d) => `
      <tr><td>${d.title}</td><td>${d.parse_status}</td><td>${d.chunk_count}</td><td>${d.version}</td></tr>
    `).join("") || "<tr><td colspan='4'>暂无文档</td></tr>";
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='4' style="color:var(--danger)">${e.message}</td></tr>`;
  }
}

document.getElementById("upload-btn").addEventListener("click", async () => {
  const kbId = document.getElementById("upload-kb-id").value.trim();
  const fileInput = document.getElementById("upload-file");
  if (!kbId || !fileInput.files.length) return alert("请填写知识库ID并选择文件");
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  try {
    await apiFetch(`/api/v1/knowledge-bases/${kbId}/documents`, { method: "POST", body: formData });
    alert("上传成功，已完成解析与索引");
    loadDocuments(kbId);
  } catch (e) {
    alert("上传失败: " + e.message);
  }
});

// ---- Agents ----
async function loadAgents() {
  const tbody = document.getElementById("agent-table-body");
  tbody.innerHTML = "<tr><td colspan='5'>加载中...</td></tr>";
  try {
    const agents = await apiFetch("/api/v1/agents");
    tbody.innerHTML = agents.map((a) => `
      <tr>
        <td>${a.name}</td><td>${a.role}</td><td>${a.business_domain || "-"}</td>
        <td>${badge(a.status === "active" ? "published" : "disabled")}</td><td>${a.is_master ? "是" : "否"}</td>
      </tr>`).join("") || "<tr><td colspan='5'>暂无数据</td></tr>";
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='5' style="color:var(--danger)">${e.message}</td></tr>`;
  }
}

// ---- Audit ----
async function loadAuditLogs() {
  const tbody = document.getElementById("audit-table-body");
  tbody.innerHTML = "<tr><td colspan='7'>加载中...</td></tr>";
  try {
    const logs = await apiFetch("/api/v1/audit-logs?limit=50");
    tbody.innerHTML = logs.map((l) => `
      <tr>
        <td>${new Date(l.created_at).toLocaleString()}</td><td>${l.trace_id}</td><td>${l.actor_id}</td>
        <td>${l.action}</td><td>${l.resource_type || "-"}/${l.resource_id || "-"}</td>
        <td>${badge(l.decision === "allow" ? "published" : "disabled")}</td><td>${l.latency_ms ?? "-"}</td>
      </tr>`).join("") || "<tr><td colspan='7'>暂无数据</td></tr>";
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='7' style="color:var(--danger)">${e.message}</td></tr>`;
  }
}
document.getElementById("audit-refresh-btn").addEventListener("click", loadAuditLogs);

// ---- Init ----
if (apiKey()) {
  showApp();
} else {
  showLogin();
}
