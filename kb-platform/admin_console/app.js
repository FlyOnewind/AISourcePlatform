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
  integrationTab: 'candidates',
  allData: {
    capabilities: [],
    skills: [],
    prompts: [],
    knowledgeBases: [],
    agents: []
  },
  filters: {
    globalSearch: '',
    capabilitiesSearch: '',
    skillsSearch: '',
    promptsSearch: '',
    knowledgeSearch: '',
    agentsSearch: '',
    auditSearch: ''
  }
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
// 搜索功能
// ============================================

function matchesSearch(item, searchTerm) {
  if (!searchTerm) return true;
  const term = searchTerm.toLowerCase().trim();

  // 搜索所有字符串字段
  const searchFields = [
    'name', 'description', 'capability_key', 'skill_key', 'prompt_key',
    'kb_key', 'role', 'business_domain', 'title', 'type', 'status'
  ];

  for (const field of searchFields) {
    if (item[field] && String(item[field]).toLowerCase().includes(term)) {
      return true;
    }
  }

  // 搜索标签
  if (item.tags && Array.isArray(item.tags)) {
    for (const tag of item.tags) {
      if (String(tag).toLowerCase().includes(term)) {
        return true;
      }
    }
  }

  return false;
}

async function performGlobalSearch(searchTerm) {
  if (!searchTerm.trim()) {
    showToast('请输入搜索内容', 'warning');
    return;
  }

  const term = searchTerm.toLowerCase().trim();
  const results = [];

  try {
    // 并行加载所有数据
    const [caps, skills, prompts, kbs, agents] = await Promise.all([
      apiFetch('/api/v1/capabilities'),
      apiFetch('/api/v1/skills'),
      apiFetch('/api/v1/prompts'),
      apiFetch('/api/v1/knowledge-bases'),
      apiFetch('/api/v1/agents')
    ]);

    // 搜索每个类型
    results.push(...caps.filter(c => matchesSearch(c, term)).map(c => ({...c, resultType: 'capability'})));
    results.push(...skills.filter(s => matchesSearch(s, term)).map(s => ({...s, resultType: 'skill'})));
    results.push(...prompts.filter(p => matchesSearch(p, term)).map(p => ({...p, resultType: 'prompt'})));
    results.push(...kbs.filter(k => matchesSearch(k, term)).map(k => ({...k, resultType: 'knowledge'})));
    results.push(...agents.filter(a => matchesSearch(a, term)).map(a => ({...a, resultType: 'agent'})));

    // 显示搜索结果
    showSearchResults(results, term);
  } catch (e) {
    showToast(`搜索失败: ${e.message}`, 'error');
  }
}

function showSearchResults(results, term) {
  const modalContent = `
    <div style="margin-bottom: var(--spacing-lg); padding: var(--spacing-md); background: var(--bg-tertiary); border-radius: var(--radius-md);">
      <p style="margin: 0; color: var(--text-secondary);">
        搜索 "<strong>${escapeHtml(term)}</strong>" 找到 <strong>${results.length}</strong> 个结果
      </p>
    </div>
    ${results.length ? `
      <div style="display: flex; flex-direction: column; gap: var(--spacing-sm); max-height: 400px; overflow-y: auto;">
        ${results.map(item => {
          const typeConfig = {
            capability: { icon: '⚡', label: '能力', color: 'var(--color-primary)' },
            skill: { icon: '🔧', label: '技能', color: 'var(--color-info)' },
            prompt: { icon: '💬', label: '提示词', color: 'var(--color-warning)' },
            knowledge: { icon: '📚', label: '知识库', color: 'var(--color-success)' },
            agent: { icon: '🤖', label: 'Agent', color: 'var(--color-info-light)' }
          };
          const config = typeConfig[item.resultType] || { icon: '📦', label: '资产', color: 'var(--text-muted)' };
          const name = item.name || item.title || item.capability_key || item.skill_key || item.prompt_key || item.kb_key || '未命名';
          const desc = item.description || item.business_domain || '';

          return `
            <div style="display: flex; align-items: center; gap: var(--spacing-md); padding: var(--spacing-md); background: var(--bg-secondary); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-default);"
                 onmouseover="this.style.background='var(--bg-tertiary)'"
                 onmouseout="this.style.background='var(--bg-secondary)'"
                 onclick="closeModal(); goToSearchResult('${item.resultType}', '${item.id}')">
              <span style="font-size: 1.5rem;">${config.icon}</span>
              <div style="flex: 1; min-width: 0;">
                <div style="display: flex; align-items: center; gap: var(--spacing-sm);">
                  <strong style="color: var(--text-primary);">${escapeHtml(name)}</strong>
                  <span class="badge badge-gray" style="font-size: 0.7rem;">${config.label}</span>
                </div>
                ${desc ? `<p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(desc)}</p>` : ''}
              </div>
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="var(--text-muted)" style="flex-shrink: 0;">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          `;
        }).join('')}
      </div>
    ` : `
      <div class="empty-state" style="padding: var(--spacing-2xl);">
        <div class="empty-state-icon">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <h3 class="empty-state-title">未找到结果</h3>
        <p class="empty-state-description">尝试使用其他关键词搜索</p>
      </div>
    `}
  `;

  openModal({ title: '搜索结果', content: modalContent, size: 'lg' });
}

function goToSearchResult(type, id) {
  switch (type) {
    case 'capability':
      showCapabilityDetailPage(id);
      break;
    case 'skill':
      openSkillDetail(id);
      break;
    case 'prompt':
      openPromptDetail(id);
      break;
    case 'knowledge':
      openKnowledgeDetail(id);
      break;
    case 'agent':
      navigateToPage('agents');
      break;
  }
}

// ============================================
// 详情展示增强
// ============================================

function formatJsonField(key, value) {
  if (value === null || value === undefined) {
    return `<span style="color: var(--text-muted);">—</span>`;
  }

  if (typeof value === 'boolean') {
    return value ? `<span style="color: var(--color-success);">是</span>` : `<span style="color: var(--text-muted);">否</span>`;
  }

  if (typeof value === 'number') {
    return `<span style="color: var(--color-info);">${value}</span>`;
  }

  if (typeof value === 'object') {
    const isArray = Array.isArray(value);
    const items = isArray ? value : Object.entries(value).map(([k, v]) => ({ key: k, value: v }));

    if (!items.length) {
      return `<span style="color: var(--text-muted);">${isArray ? '[]' : '{}'}</span>`;
    }

    const preview = isArray ? `[${items.length}项]` : `{${items.length}个字段}`;

    return `
      <div class="json-collapsible" style="border: 1px solid var(--border-default); border-radius: var(--radius-md); overflow: hidden;">
        <div class="json-collapsible-header" onclick="this.nextElementSibling.classList.toggle('hidden'); this.querySelector('.json-toggle-icon').style.transform = this.nextElementSibling.classList.contains('hidden') ? 'rotate(0deg)' : 'rotate(90deg)';"
             style="padding: var(--spacing-sm) var(--spacing-md); background: var(--bg-tertiary); cursor: pointer; display: flex; align-items: center; gap: var(--spacing-sm);">
          <span class="json-toggle-icon" style="transition: transform 150ms ease;">▶</span>
          <strong style="color: var(--color-info);">${escapeHtml(key)}</strong>
          <span style="color: var(--text-muted);">${preview}</span>
        </div>
        <div class="json-collapsible-content hidden" style="padding: var(--spacing-md); background: var(--bg-secondary); max-height: 300px; overflow-y: auto;">
          ${isArray ? `
            <ul style="margin: 0; padding-left: var(--spacing-lg); list-style: none;">
              ${items.map((item, i) => `
                <li style="padding: var(--spacing-xs) 0; border-bottom: 1px solid var(--border-subtle);">
                  <span style="color: var(--text-muted);">[${i}]</span>
                  ${typeof item === 'object' ? `<pre style="margin: var(--spacing-xs) 0 0 0; padding: var(--spacing-sm); background: var(--bg-primary); border-radius: var(--radius-sm); font-size: var(--font-size-sm); overflow: auto;">${escapeHtml(JSON.stringify(item, null, 2))}</pre>` : escapeHtml(String(item))}
                </li>
              `).join('')}
            </ul>
          ` : `
            <table style="width: 100%; border-collapse: collapse;">
              ${items.map(({ key: k, value: v }) => `
                <tr style="border-bottom: 1px solid var(--border-subtle);">
                  <td style="padding: var(--spacing-xs) 0; color: var(--color-warning); min-width: 100px; vertical-align: top;">${escapeHtml(String(k))}</td>
                  <td style="padding: var(--spacing-xs) 0; color: var(--text-secondary);">
                    ${typeof v === 'object' && v !== null ? `<pre style="margin: 0; padding: var(--spacing-sm); background: var(--bg-primary); border-radius: var(--radius-sm); font-size: var(--font-size-sm); overflow: auto;">${escapeHtml(JSON.stringify(v, null, 2))}</pre>` : escapeHtml(String(v))}
                  </td>
                </tr>
              `).join('')}
            </table>
          `}
        </div>
      </div>
    `;
  }

  // 处理特别长的文本（如prompt模板）
  if (typeof value === 'string' && value.length > 200) {
    return `
      <div class="json-collapsible" style="border: 1px solid var(--border-default); border-radius: var(--radius-md); overflow: hidden;">
        <div class="json-collapsible-header" onclick="this.nextElementSibling.classList.toggle('hidden'); this.querySelector('.json-toggle-icon').style.transform = this.nextElementSibling.classList.contains('hidden') ? 'rotate(0deg)' : 'rotate(90deg)';"
             style="padding: var(--spacing-sm) var(--spacing-md); background: var(--bg-tertiary); cursor: pointer; display: flex; align-items: center; gap: var(--spacing-sm);">
          <span class="json-toggle-icon" style="transition: transform 150ms ease;">▶</span>
          <strong style="color: var(--color-info);">${escapeHtml(key)}</strong>
          <span style="color: var(--text-muted);">(${value.length}字符)</span>
        </div>
        <div class="json-collapsible-content hidden" style="padding: var(--spacing-md); background: var(--bg-secondary);">
          <pre style="margin: 0; padding: var(--spacing-md); background: var(--bg-primary); border-radius: var(--radius-md); font-size: var(--font-size-sm); white-space: pre-wrap; word-break: break-word; max-height: 400px; overflow-y: auto;">${escapeHtml(value)}</pre>
        </div>
      </div>
    `;
  }

  return `<span style="color: var(--text-secondary);">${escapeHtml(String(value))}</span>`;
}

function renderDetailSection(title, fields) {
  const filteredFields = fields.filter(f => f.value !== undefined && f.value !== null && f.value !== '');

  if (!filteredFields.length) {
    return '';
  }

  return `
    <div class="detail-section">
      <h4 class="detail-section-title">${escapeHtml(title)}</h4>
      <div class="detail-fields">
        ${filteredFields.map(field => `
          <div class="detail-field">
            <div class="detail-field-label">${escapeHtml(field.label)}</div>
            <div class="detail-field-value">
              ${field.raw ? field.raw : formatJsonField(field.key, field.value)}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function getTypeIcon(type) {
  const icons = {
    'knowledge_base': '📚',
    'tool': '🔧',
    'skill': '⚡',
    'prompt': '💬',
    'agent': '🤖',
    'document': '📄'
  };
  return icons[type] || '📦';
}

function showAssetDetail(title, data) {
  navigateToPage('detail');
  const container = document.getElementById('asset-detail');

  // 根据数据类型构建不同的详情展示
  let sections = [];
  let icon = '📦';

  // Skill详情
  if (data.skill_key || (data.type && ['prompt_skill', 'rag_skill', 'tool_skill', 'workflow_skill', 'agent_skill'].includes(data.type))) {
    icon = '⚡';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'name', label: '名称', value: data.name },
        { key: 'skill_key', label: 'Key', value: data.skill_key },
        { key: 'type', label: '类型', value: data.type },
        { key: 'description', label: '描述', value: data.description },
        { key: 'business_domain', label: '业务域', value: data.business_domain },
        { key: 'version', label: '版本', value: data.version ? `v${data.version}` : undefined },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined }
      ]),
      renderDetailSection('配置', [
        { key: 'input_schema', label: '输入Schema', value: data.input_schema },
        { key: 'output_schema', label: '输出Schema', value: data.output_schema },
        { key: 'prompt_key', label: '关联Prompt', value: data.prompt_key },
        { key: 'dependencies', label: '依赖项', value: data.dependencies },
        { key: 'allowed_agent_roles', label: '允许的Agent角色', value: data.allowed_agent_roles }
      ])
    ];
  }
  // Prompt详情
  else if (data.prompt_key || (data.template && data.variables)) {
    icon = '💬';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'name', label: '名称', value: data.name },
        { key: 'prompt_key', label: 'Key', value: data.prompt_key },
        { key: 'description', label: '描述', value: data.description },
        { key: 'owner', label: '负责人', value: data.owner },
        { key: 'version', label: '版本', value: data.version ? `v${data.version}` : undefined },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined }
      ]),
      renderDetailSection('配置', [
        { key: 'variables', label: '变量', value: data.variables },
        { key: 'model_config', label: '模型配置', value: data.model_config || data.model_config_ }
      ]),
      renderDetailSection('模板内容', [
        { key: 'template', label: '提示词模板', value: data.template }
      ])
    ];
  }
  // Knowledge Base详情
  else if (data.kb_key || (data.documents && data.kb_key === undefined)) {
    icon = '📚';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'name', label: '名称', value: data.name },
        { key: 'kb_key', label: 'Key', value: data.kb_key },
        { key: 'business_domain', label: '业务域', value: data.business_domain },
        { key: 'owner_department', label: '负责部门', value: data.owner_department },
        { key: 'security_level', label: '密级', raw: data.security_level ? securityLevelBadge(data.security_level) : undefined },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined }
      ]),
      renderDetailSection('配置', [
        { key: 'retrieval_config', label: '检索配置', value: data.retrieval_config }
      ])
    ];

    // 如果有文档信息，添加文档列表
    if (data.documents && data.documents.length) {
      sections.push({
        title: '文档列表',
        content: `
          <div style="border: 1px solid var(--border-default); border-radius: var(--radius-md); overflow: hidden;">
            <table class="data-table" style="border: none; margin: 0;">
              <thead>
                <tr>
                  <th>文档名</th>
                  <th>状态</th>
                  <th>切片数</th>
                  <th>版本</th>
                </tr>
              </thead>
              <tbody>
                ${data.documents.map(d => `
                  <tr>
                    <td><strong>${escapeHtml(d.title)}</strong></td>
                    <td>${badge(d.parse_status)}</td>
                    <td>${d.chunk_count || 0}</td>
                    <td>v${escapeHtml(d.version || '1.0')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `
      });
    }
  }
  // Document详情
  else if (data.title && data.kb_id && data.kb_key === undefined) {
    icon = '📄';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'title', label: '标题', value: data.title },
        { key: 'source_type', label: '来源类型', value: data.source_type },
        { key: 'source_uri', label: '来源URI', value: data.source_uri },
        { key: 'object_uri', label: '存储URI', value: data.object_uri },
        { key: 'version', label: '版本', value: data.version ? `v${data.version}` : undefined },
        { key: 'parse_status', label: '解析状态', raw: data.parse_status ? badge(data.parse_status) : undefined },
        { key: 'security_level', label: '密级', raw: data.security_level ? securityLevelBadge(data.security_level) : undefined }
      ]),
      renderDetailSection('解析信息', [
        { key: 'chunk_count', label: '切片数量', value: data.chunk_count },
        { key: 'parse_error', label: '解析错误', value: data.parse_error },
        { key: 'metadata', label: '元数据', value: data.metadata || data.metadata_ }
      ])
    ];
  }
  // Agent详情
  else if (data.role !== undefined || (data.is_master !== undefined)) {
    icon = '🤖';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'name', label: '名称', value: data.name },
        { key: 'role', label: '角色', value: data.role },
        { key: 'description', label: '描述', value: data.description },
        { key: 'business_domain', label: '业务域', value: data.business_domain },
        { key: 'is_master', label: '主控Agent', value: data.is_master },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined }
      ]),
      renderDetailSection('配置', [
        { key: 'system_prompt', label: '系统提示词', value: data.system_prompt },
        { key: 'capabilities', label: '可用能力', value: data.capabilities },
        { key: 'config', label: '额外配置', value: data.config }
      ])
    ];
  }
  // Capability详情
  else if (data.capability_key || (data.type && ['knowledge_base', 'tool', 'skill', 'prompt', 'agent', 'workflow'].includes(data.type))) {
    icon = getTypeIcon(data.type);
    sections = [
      renderDetailSection('基本信息', [
        { key: 'name', label: '名称', value: data.name },
        { key: 'capability_key', label: 'Key', value: data.capability_key },
        { key: 'type', label: '类型', value: data.type },
        { key: 'description', label: '描述', value: data.description },
        { key: 'business_domain', label: '业务域', value: data.business_domain },
        { key: 'owner_department', label: '负责部门', value: data.owner_department },
        { key: 'owner_user', label: '负责人', value: data.owner_user },
        { key: 'current_version', label: '当前版本', value: data.current_version ? `v${data.current_version}` : undefined },
        { key: 'security_level', label: '密级', raw: data.security_level ? securityLevelBadge(data.security_level) : undefined },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined }
      ]),
      renderDetailSection('配置', [
        { key: 'tags', label: '标签', value: data.tags },
        { key: 'scenarios', label: '适用场景', value: data.scenarios },
        { key: 'input_schema', label: '输入Schema', value: data.input_schema },
        { key: 'output_schema', label: '输出Schema', value: data.output_schema },
        { key: 'examples', label: '示例', value: data.examples },
        { key: 'endpoint', label: '端点', value: data.endpoint },
        { key: 'timeout_ms', label: '超时时间(ms)', value: data.timeout_ms },
        { key: 'side_effect', label: '副作用', value: data.side_effect },
        { key: 'allowed_agent_roles', label: '允许的Agent角色', value: data.allowed_agent_roles }
      ]),
      renderDetailSection('元数据', [
        { key: 'ref_id', label: '关联ID', value: data.ref_id },
        { key: 'metadata', label: '扩展元数据', value: data.metadata || data.metadata_ }
      ])
    ];

    // 如果有权限信息
    if (data.permissions) {
      sections.push(renderDetailSection('权限配置', [
        { key: 'permissions', label: '权限列表', value: data.permissions }
      ]));
    }
  }
  // 资产候选
  else if (data.candidate_key) {
    icon = '📋';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'candidate_key', label: '候选Key', value: data.candidate_key },
        { key: 'asset_type', label: '资产类型', value: data.asset_type },
        { key: 'submitted_by', label: '提交者', value: data.submitted_by },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined },
        { key: 'created_at', label: '提交时间', value: formatDate(data.created_at) }
      ]),
      renderDetailSection('候选内容', [
        { key: 'asset_data', label: '资产数据', value: data.asset_data },
        { key: 'submission_note', label: '提交说明', value: data.submission_note }
      ])
    ];
  }
  // 协作任务
  else if (data.task_key) {
    icon = '🔗';
    sections = [
      renderDetailSection('基本信息', [
        { key: 'task_key', label: '任务Key', value: data.task_key },
        { key: 'caller_agent_key', label: '调用者Agent', value: data.caller_agent_key },
        { key: 'target_agent_key', label: '目标Agent', value: data.target_agent_key },
        { key: 'status', label: '状态', raw: data.status ? badge(data.status) : undefined },
        { key: 'created_at', label: '创建时间', value: formatDate(data.created_at) }
      ]),
      renderDetailSection('任务内容', [
        { key: 'task_input', label: '任务输入', value: data.task_input },
        { key: 'task_output', label: '任务输出', value: data.task_output },
        { key: 'result_decision', label: '结果决策', value: data.result_decision },
        { key: 'result_reason', label: '决策理由', value: data.result_reason }
      ])
    ];
  }
  // 默认通用展示
  else {
    icon = '📦';

    // 分成三组：基本信息、配置信息、元信息
    const basicFields = [];
    const configFields = [];
    const metaFields = [];

    const basicKeys = ['name', 'title', 'description', 'type', 'status', 'version', 'business_domain'];
    const metaKeys = ['id', 'created_at', 'updated_at', 'ref_id', 'metadata', 'metadata_'];

    for (const [key, value] of Object.entries(data)) {
      if (key.startsWith('_')) continue;

      const field = { key, label: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()), value };

      if (basicKeys.includes(key)) {
        basicFields.push(field);
      } else if (metaKeys.includes(key)) {
        metaFields.push(field);
      } else {
        configFields.push(field);
      }
    }

    sections = [
      renderDetailSection('基本信息', basicFields),
      renderDetailSection('配置信息', configFields),
      renderDetailSection('元信息', metaFields)
    ];
  }

  container.innerHTML = `
    <div class="detail-header">
      <div class="detail-title-group">
        <div class="detail-icon" style="font-size: 2rem; display: flex; align-items: center; justify-content: center;">
          ${icon}
        </div>
        <div>
          <h3 class="detail-title">${escapeHtml(title)}</h3>
          ${data.created_at || data.updated_at ? `
            <p class="detail-meta" style="margin: var(--spacing-xs) 0 0 0; color: var(--text-muted); font-size: var(--font-size-sm);">
              ${data.created_at ? `创建: ${formatDate(data.created_at)}` : ''}
              ${data.updated_at ? ` | 更新: ${formatDate(data.updated_at)}` : ''}
            </p>
          ` : ''}
        </div>
      </div>
      <div class="detail-actions">
        <button class="btn btn-secondary" onclick="copyDetailData()">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" style="width: 16px; height: 16px;">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
          </svg>
          复制JSON
        </button>
        <button class="btn btn-primary" onclick="toggleRawJson()">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" style="width: 16px; height: 16px;">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
          查看原始JSON
        </button>
      </div>
    </div>

    <div id="detail-sections">
      ${sections.filter(s => s).map(s =>
        typeof s === 'string' ? s : `
          <div class="detail-section">
            <h4 class="detail-section-title">${escapeHtml(s.title)}</h4>
            ${s.content}
          </div>
        `
      ).join('')}
    </div>

    <div id="detail-raw-json" class="hidden">
      <div class="detail-section">
        <h4 class="detail-section-title">原始JSON</h4>
        <div class="detail-code">
          <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </div>
      </div>
    </div>
  `;

  appState.currentDetailData = data;
  appState.showingRawJson = false;
}

function toggleRawJson() {
  const sections = document.getElementById('detail-sections');
  const rawJson = document.getElementById('detail-raw-json');
  appState.showingRawJson = !appState.showingRawJson;

  if (appState.showingRawJson) {
    sections.classList.add('hidden');
    rawJson.classList.remove('hidden');
  } else {
    sections.classList.remove('hidden');
    rawJson.classList.add('hidden');
  }
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
  const search = document.getElementById('cap-search')?.value || '';
  const tableBody = document.getElementById('cap-table-body');
  const gridView = document.getElementById('cap-grid-view');

  tableBody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    let qs = '';
    const params = [];
    if (type) params.push(`type=${encodeURIComponent(type)}`);
    if (status) params.push(`status=${encodeURIComponent(status)}`);
    if (params.length) qs = '?' + params.join('&');

    let caps = await apiFetch(`/api/v1/capabilities${qs}`);

    // 应用搜索过滤
    if (search) {
      caps = caps.filter(c => matchesSearch(c, search));
    }

    // 保存数据用于搜索
    appState.allData.capabilities = caps;

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
    `).join('') : `<tr><td colspan="7" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">${search ? '没有匹配的结果' : '暂无数据'}</td></tr>`;

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
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${search ? 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z' : 'M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4'}"/>
            </svg>
          </div>
          <h3 class="empty-state-title">${search ? '没有匹配的结果' : '暂无能力'}</h3>
          <p class="empty-state-description">${search ? '尝试使用其他关键词搜索' : '创建第一个能力开始使用'}</p>
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
  const search = document.getElementById('skill-search')?.value || '';
  const tableBody = document.getElementById('skill-table-body');
  tableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    let skills = await apiFetch('/api/v1/skills');

    // 应用搜索过滤
    if (search) {
      skills = skills.filter(s => matchesSearch(s, search));
    }

    // 保存数据用于搜索
    appState.allData.skills = skills;

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
    `).join('') : `<tr><td colspan="6" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">${search ? '没有匹配的结果' : '暂无数据'}</td></tr>`;
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
  const search = document.getElementById('prompt-search')?.value || '';
  const tableBody = document.getElementById('prompt-table-body');
  tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl);">加载中...</td></tr>';

  try {
    let prompts = await apiFetch('/api/v1/prompts');

    // 应用搜索过滤
    if (search) {
      prompts = prompts.filter(p => matchesSearch(p, search));
    }

    // 保存数据用于搜索
    appState.allData.prompts = prompts;

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
    `).join('') : `<tr><td colspan="5" style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">${search ? '没有匹配的结果' : '暂无数据'}</td></tr>`;
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
  const search = document.getElementById('knowledge-search')?.value || '';
  const gridView = document.getElementById('kb-grid-view');
  const kbSelect = document.getElementById('upload-kb-id');

  gridView.innerHTML = '<div class="loading-skeleton" style="height: 150px;"></div>'.repeat(3);

  try {
    let kbs = await apiFetch('/api/v1/knowledge-bases');

    // 应用搜索过滤
    if (search) {
      kbs = kbs.filter(kb => matchesSearch(kb, search));
    }

    // 保存数据用于搜索
    appState.allData.knowledgeBases = kbs;

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
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${search ? 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z' : 'M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253'}"/>
            </svg>
          </div>
          <h3 class="empty-state-title">${search ? '没有匹配的结果' : '暂无知识库'}</h3>
          <p class="empty-state-description">${search ? '尝试使用其他关键词搜索' : '创建第一个知识库开始上传文档'}</p>
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
// 搜索功能
// ============================================

function matchesSearch(item, searchTerm) {
  if (!searchTerm) return true;
  const term = searchTerm.toLowerCase().trim();

  const searchFields = [
    'name', 'description', 'capability_key', 'skill_key', 'prompt_key',
    'kb_key', 'role', 'business_domain', 'title', 'type', 'status'
  ];

  for (const field of searchFields) {
    if (item[field] && String(item[field]).toLowerCase().includes(term)) {
      return true;
    }
  }

  if (item.tags && Array.isArray(item.tags)) {
    for (const tag of item.tags) {
      if (String(tag).toLowerCase().includes(term)) {
        return true;
      }
    }
  }

  return false;
}

async function performGlobalSearch(searchTerm) {
  if (!searchTerm.trim()) {
    showToast('请输入搜索内容', 'warning');
    return;
  }

  const term = searchTerm.toLowerCase().trim();
  const results = [];

  try {
    const [caps, skills, prompts, kbs, agents] = await Promise.all([
      apiFetch('/api/v1/capabilities'),
      apiFetch('/api/v1/skills'),
      apiFetch('/api/v1/prompts'),
      apiFetch('/api/v1/knowledge-bases'),
      apiFetch('/api/v1/agents')
    ]);

    results.push(...caps.filter(c => matchesSearch(c, term)).map(c => ({...c, resultType: 'capability'})));
    results.push(...skills.filter(s => matchesSearch(s, term)).map(s => ({...s, resultType: 'skill'})));
    results.push(...prompts.filter(p => matchesSearch(p, term)).map(p => ({...p, resultType: 'prompt'})));
    results.push(...kbs.filter(k => matchesSearch(k, term)).map(k => ({...k, resultType: 'knowledge'})));
    results.push(...agents.filter(a => matchesSearch(a, term)).map(a => ({...a, resultType: 'agent'})));

    const content = `
      <div style="margin-bottom: var(--spacing-md); padding: var(--spacing-md); background: var(--bg-tertiary); border-radius: var(--radius-md);">
        <p style="margin: 0; color: var(--text-secondary);">
          搜索 "<strong>${escapeHtml(term)}</strong>" 找到 <strong>${results.length}</strong> 个结果
        </p>
      </div>
      ${results.length ? `
        <div style="display: flex; flex-direction: column; gap: var(--spacing-sm); max-height: 400px; overflow-y: auto;">
          ${results.map(item => {
            const typeConfig = {
              capability: { icon: '⚡', label: '能力', color: 'var(--color-primary)' },
              skill: { icon: '🔧', label: '技能', color: 'var(--color-info)' },
              prompt: { icon: '💬', label: '提示词', color: 'var(--color-warning)' },
              knowledge: { icon: '📚', label: '知识库', color: 'var(--color-success)' },
              agent: { icon: '🤖', label: 'Agent', color: 'var(--color-info-light)' }
            };
            const config = typeConfig[item.resultType] || { icon: '📦', label: '资产', color: 'var(--text-muted)' };
            const name = item.name || item.title || item.capability_key || item.skill_key || item.prompt_key || item.kb_key || '未命名';
            const desc = item.description || item.business_domain || '';

            return `
              <div style="display: flex; align-items: center; gap: var(--spacing-md); padding: var(--spacing-md); background: var(--bg-secondary); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast);"
                  onmouseover="this.style.background='var(--bg-hover)'"
                  onmouseout="this.style.background='var(--bg-secondary)'"
                  onclick="closeModal(); goToSearchResult('${item.resultType}', '${item.id}')">
                <span style="font-size: 1.5rem;">${config.icon}</span>
                <div style="flex: 1; min-width: 0;">
                  <div style="display: flex; align-items: center; gap: var(--spacing-sm);">
                    <strong style="color: var(--text-primary);">${escapeHtml(name)}</strong>
                    <span class="badge badge-gray" style="font-size: 0.7rem;">${config.label}</span>
                  </div>
                  ${desc ? `<p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(desc)}</p>` : ''}
                </div>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="var(--text-muted)" style="flex-shrink: 0;">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                </svg>
              </div>
            `;
          }).join('')}
        </div>
      ` : `
        <div class="empty-state" style="padding: var(--spacing-xl);">
          <div class="empty-state-icon">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <h3 class="empty-state-title">未找到结果</h3>
          <p class="empty-state-description">尝试使用其他关键词搜索</p>
        </div>
      `}
    `;

    openModal({ title: '搜索结果', content, size: 'lg' });
  } catch (e) {
    showToast(`搜索失败: ${e.message}`, 'error');
  }
}

function goToSearchResult(type, id) {
  switch (type) {
    case 'capability':
      showCapabilityDetailPage(id);
      break;
    case 'skill':
      openSkillDetail(id);
      break;
    case 'prompt':
      openPromptDetail(id);
      break;
    case 'knowledge':
      openKnowledgeDetail(id);
      break;
    case 'agent':
      navigateToPage('agents');
      break;
  }
}

// ============================================
// 能力注册功能
// ============================================

const CAPABILITY_TEMPLATES = {
  operation: {
    name: '运营智能体',
    capabilities: [
      {
        capability_key: 'kb_store_operation',
        type: 'knowledge_base',
        name: '门店运营知识库',
        description: '包含门店运营指南、活动方案、销售技巧等知识',
        business_domain: 'retail',
        tags: ['门店', '运营', '销售'],
        scenarios: ['门店运营', '活动策划', '销售培训'],
        owner_department: '运营部',
        security_level: 'internal'
      },
      {
        capability_key: 'kb_live_operation',
        type: 'knowledge_base',
        name: '直播运营知识库',
        description: '包含直播流程、话术、场控等直播运营知识',
        business_domain: 'live',
        tags: ['直播', '话术', '场控'],
        scenarios: ['直播策划', '话术生成'],
        owner_department: '运营部',
        security_level: 'internal'
      },
      {
        capability_key: 'tool_customer_segment',
        type: 'tool',
        name: '客户分层分析工具',
        description: '根据客户消费数据进行分层分析',
        business_domain: 'retail',
        tags: ['客户', '分层', '分析'],
        scenarios: ['客户画像', '营销策略'],
        owner_department: '运营部',
        endpoint: 'http://localhost:8030/tools/customer-segment',
        input_schema: {
          type: 'object',
          properties: {
            customer_ids: { type: 'array', items: { type: 'string' }, description: '客户ID列表' },
            start_date: { type: 'string', format: 'date', description: '开始日期' },
            end_date: { type: 'string', format: 'date', description: '结束日期' }
          },
          required: ['customer_ids']
        },
        output_schema: {
          type: 'object',
          properties: {
            segments: { type: 'array', description: '客户分层结果' },
            summary: { type: 'string', description: '分析摘要' }
          }
        },
        security_level: 'internal'
      },
      {
        capability_key: 'tool_metric_calc',
        type: 'tool',
        name: '活动指标计算工具',
        description: '计算直播活动的各项KPI指标',
        business_domain: 'live',
        tags: ['指标', 'KPI', '分析'],
        scenarios: ['活动分析', '效果评估'],
        owner_department: '运营部',
        endpoint: 'http://localhost:8030/tools/metric-calc',
        input_schema: {
          type: 'object',
          properties: {
            activity_id: { type: 'string', description: '活动ID' },
            metrics: { type: 'array', items: { type: 'string' }, description: '需要计算的指标' }
          },
          required: ['activity_id']
        },
        output_schema: {
          type: 'object',
          properties: {
            results: { type: 'object', description: '指标结果' },
            summary: { type: 'string', description: '总结' }
          }
        },
        security_level: 'internal'
      },
      {
        capability_key: 'skill_live_script_generator',
        type: 'skill',
        name: '直播话术生成技能',
        description: '根据产品特点生成直播话术',
        business_domain: 'live',
        tags: ['话术', '直播', '文案'],
        scenarios: ['直播准备', '文案生成'],
        owner_department: '运营部',
        input_schema: {
          type: 'object',
          properties: {
            product_name: { type: 'string', description: '产品名称' },
            product_features: { type: 'array', items: { type: 'string' }, description: '产品特点' },
            target_audience: { type: 'string', description: '目标受众' },
            duration: { type: 'integer', description: '预计时长（分钟）' }
          },
          required: ['product_name', 'product_features']
        },
        output_schema: {
          type: 'object',
          properties: {
            opening: { type: 'string', description: '开场话术' },
            introduction: { type: 'string', description: '产品介绍' },
            interaction: { type: 'string', description: '互动环节' },
            closing: { type: 'string', description: '结束话术' }
          }
        },
        security_level: 'internal'
      },
      {
        capability_key: 'prompt_store_diagnosis',
        type: 'prompt',
        name: '门店运营诊断提示词',
        description: '诊断门店运营问题的提示词模板',
        business_domain: 'retail',
        tags: ['诊断', '分析', '建议'],
        scenarios: ['门店分析', '问题诊断', '优化建议'],
        owner_department: '运营部',
        input_schema: {
          type: 'object',
          properties: {
            store_data: { type: 'object', description: '门店数据' },
            period: { type: 'string', description: '分析周期' }
          },
          required: ['store_data']
        },
        output_schema: {
          type: 'object',
          properties: {
            issues: { type: 'array', description: '发现的问题' },
            suggestions: { type: 'array', description: '优化建议' }
          }
        },
        security_level: 'internal'
      },
      {
        capability_key: 'agent_operation',
        type: 'agent',
        name: '运营方案生成能力',
        description: '运营智能体的综合能力入口',
        business_domain: 'retail',
        tags: ['运营', '方案', '综合'],
        scenarios: ['方案策划', '活动策划', '运营优化'],
        owner_department: '运营部',
        security_level: 'internal'
      }
    ],
    permissions: [
      {
        subject_type: 'agent',
        subject_code: 'master_agent',
        permission: 'invoke',
        conditions: { requires_audit: false }
      },
      {
        subject_type: 'agent',
        subject_code: 'finance_agent',
        permission: 'read',
        conditions: {}
      }
    ]
  },
  finance: {
    name: '财务智能体',
    capabilities: [
      {
        capability_key: 'tool_finance_roi_calc',
        type: 'tool',
        name: '财务ROI计算工具',
        description: '根据预算、预计销售额和毛利率计算活动ROI',
        business_domain: 'finance',
        tags: ['ROI', '预算', '财务'],
        scenarios: ['预算审批', '投资评估', '活动策划'],
        owner_department: '财务部',
        endpoint: 'http://localhost:8030/tools/roi-calc',
        input_schema: {
          type: 'object',
          properties: {
            budget: { type: 'number', description: '预算金额' },
            expected_sales: { type: 'number', description: '预计销售额' },
            gross_margin_rate: { type: 'number', description: '毛利率 (0-1)' }
          },
          required: ['budget', 'expected_sales', 'gross_margin_rate']
        },
        output_schema: {
          type: 'object',
          properties: {
            roi: { type: 'number', description: 'ROI比率' },
            gross_profit: { type: 'number', description: '毛利润' },
            risk_level: { type: 'string', description: '风险等级' },
            suggestion: { type: 'string', description: '建议' }
          }
        },
        security_level: 'confidential',
        side_effect: 'read_only'
      }
    ],
    permissions: [
      {
        subject_type: 'agent',
        subject_code: 'master_agent',
        permission: 'invoke',
        conditions: { requires_audit: true }
      },
      {
        subject_type: 'agent',
        subject_code: 'finance_agent',
        permission: 'invoke',
        conditions: { requires_audit: true }
      }
    ]
  }
};

function showRegistryWizard(type) {
  if (type === 'custom') {
    showCreateCapabilityModal();
    return;
  }

  const template = CAPABILITY_TEMPLATES[type];
  if (!template) {
    showToast('未知的注册类型', 'error');
    return;
  }

  const content = `
    <div style="margin-bottom: var(--spacing-md);">
      <h4 style="margin-bottom: var(--spacing-sm);">确认注册以下能力</h4>
      <p style="color: var(--text-muted);">即将注册 ${template.capabilities.length} 个${template.name}能力</p>
    </div>
    <div style="max-height: 300px; overflow-y: auto; margin-bottom: var(--spacing-md);">
      ${template.capabilities.map((cap, idx) => `
        <div style="display: flex; align-items: center; gap: var(--spacing-md); padding: var(--spacing-md); background: var(--bg-tertiary); border-radius: var(--radius-md); margin-bottom: var(--spacing-sm);">
          <input type="checkbox" id="reg-cap-${idx}" checked style="width: 18px; height: 18px;">
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: var(--spacing-sm);">
              <strong>${escapeHtml(cap.name)}</strong>
              <span class="badge badge-blue" style="font-size: 0.7rem;">${escapeHtml(cap.type)}</span>
            </div>
            <p style="margin: var(--spacing-xs) 0 0 0; font-size: var(--font-size-sm); color: var(--text-muted);">${escapeHtml(cap.description || '')}</p>
          </div>
        </div>
      `).join('')}
    </div>
    <div style="border-top: 1px solid var(--border-subtle); padding-top: var(--spacing-md);">
      <label class="checkbox-group" style="margin-bottom: var(--spacing-sm);">
        <input type="checkbox" id="reg-auto-perm" checked>
        <span>自动配置默认权限</span>
      </label>
      <label class="checkbox-group">
        <input type="checkbox" id="reg-auto-publish">
        <span>注册后直接发布</span>
      </label>
    </div>
  `;

  openModal({
    title: `注册${template.name}能力`,
    content,
    size: 'lg',
    footerButtons: [
      { text: '取消', action: 'cancel', class: 'btn-secondary' },
      { text: '开始注册', action: 'confirm', class: 'btn-primary' }
    ]
  }).then(async (action) => {
    if (action !== 'confirm') return;

    const autoPerm = document.getElementById('reg-auto-perm').checked;
    const autoPublish = document.getElementById('reg-auto-publish').checked;

    await registerCapabilitiesFromTemplate(type, autoPerm, autoPublish);
  });
}

async function registerCapabilitiesFromTemplate(type, autoPerm = true, autoPublish = false) {
  const template = CAPABILITY_TEMPLATES[type];
  const registered = [];

  try {
    for (const capData of template.capabilities) {
      try {
        const cap = await apiFetch('/api/v1/capabilities', {
          method: 'POST',
          body: JSON.stringify(capData)
        });
        registered.push(cap);
        showToast(`注册成功: ${capData.name}`, 'success');

        if (autoPerm && template.permissions) {
          for (const perm of template.permissions) {
            try {
              await apiFetch(`/api/v1/capabilities/${cap.id}/permissions`, {
                method: 'POST',
                body: JSON.stringify(perm)
              });
            } catch (e) {
              console.warn('权限配置失败:', e);
            }
          }
        }

        if (autoPublish) {
          try {
            await apiFetch(`/api/v1/capabilities/${cap.id}/publish`, {
              method: 'POST',
              body: JSON.stringify({ release_notes: '通过注册向导发布' })
            });
          } catch (e) {
            console.warn('发布失败:', e);
          }
        }
      } catch (e) {
        if (e.message?.includes('已存在')) {
          showToast(`跳过已存在: ${capData.name}`, 'info');
        } else {
          showToast(`注册失败: ${capData.name} - ${e.message}`, 'error');
        }
      }
    }

    showToast(`注册完成! 成功注册 ${registered.length} 个能力`, 'success');
    loadCapabilities();
  } catch (e) {
    showToast(`注册失败: ${e.message}`, 'error');
  }
}

function showCreateCapabilityModal() {
  const content = `
    <div style="display: flex; flex-direction: column; gap: var(--spacing-md);">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">能力Key *</label>
          <input type="text" id="create-cap-key" class="input" placeholder="如: tool_custom_function">
        </div>
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">类型 *</label>
          <select id="create-cap-type" class="select">
            <option value="tool">工具 Tool</option>
            <option value="skill">技能 Skill</option>
            <option value="prompt">提示词 Prompt</option>
            <option value="knowledge_base">知识库</option>
            <option value="agent">Agent</option>
            <option value="workflow">工作流</option>
          </select>
        </div>
      </div>
      <div>
        <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">名称 *</label>
        <input type="text" id="create-cap-name" class="input" placeholder="能力显示名称">
      </div>
      <div>
        <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">描述</label>
        <textarea id="create-cap-desc" class="input" placeholder="能力描述" rows="2" style="min-height: 60px;"></textarea>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">业务域</label>
          <input type="text" id="create-cap-domain" class="input" placeholder="如: retail, finance">
        </div>
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">所属部门</label>
          <input type="text" id="create-cap-dept" class="input" placeholder="如: 运营部">
        </div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">密级</label>
          <select id="create-cap-security" class="select">
            <option value="public">公开</option>
            <option value="internal" selected>内部</option>
            <option value="confidential">机密</option>
            <option value="restricted">受限</option>
          </select>
        </div>
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">副作用</label>
          <select id="create-cap-sideeffect" class="select">
            <option value="read_only">只读</option>
            <option value="write">写操作</option>
            <option value="approval_required">需要审批</option>
          </select>
        </div>
      </div>
      <div>
        <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">标签 (逗号分隔)</label>
        <input type="text" id="create-cap-tags" class="input" placeholder="如: 销售, 分析, 文案">
      </div>
      <div>
        <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">Endpoint (工具类型)</label>
        <input type="text" id="create-cap-endpoint" class="input" placeholder="http://...">
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">输入Schema (JSON)</label>
          <textarea id="create-cap-input-schema" class="input" rows="4" placeholder='{
  "type": "object",
  "properties": {
    "param1": { "type": "string" }
  }
}'></textarea>
        </div>
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">输出Schema (JSON)</label>
          <textarea id="create-cap-output-schema" class="input" rows="4" placeholder='{
  "type": "object",
  "properties": {
    "result": { "type": "string" }
  }
}'></textarea>
        </div>
      </div>
    </div>
  `;

  openModal({
    title: '创建新能力',
    content,
    size: 'xl',
    footerButtons: [
      { text: '取消', action: 'cancel', class: 'btn-secondary' },
      { text: '创建', action: 'confirm', class: 'btn-primary' }
    ]
  }).then(async (action) => {
    if (action !== 'confirm') return;
    await createNewCapability();
  });
}

async function createNewCapability() {
  const key = document.getElementById('create-cap-key')?.value?.trim();
  const type = document.getElementById('create-cap-type')?.value;
  const name = document.getElementById('create-cap-name')?.value?.trim();
  const desc = document.getElementById('create-cap-desc')?.value?.trim();
  const domain = document.getElementById('create-cap-domain')?.value?.trim();
  const dept = document.getElementById('create-cap-dept')?.value?.trim();
  const security = document.getElementById('create-cap-security')?.value;
  const sideEffect = document.getElementById('create-cap-sideeffect')?.value;
  const tagsStr = document.getElementById('create-cap-tags')?.value?.trim();
  const endpoint = document.getElementById('create-cap-endpoint')?.value?.trim();
  const inputSchemaStr = document.getElementById('create-cap-input-schema')?.value?.trim();
  const outputSchemaStr = document.getElementById('create-cap-output-schema')?.value?.trim();

  if (!key || !name) {
    showToast('请填写必要信息', 'warning');
    return;
  }

  const tags = tagsStr ? tagsStr.split(/[,，]/).map(t => t.trim()).filter(t => t) : [];

  let input_schema = {};
  let output_schema = {};

  if (inputSchemaStr) {
    try {
      input_schema = JSON.parse(inputSchemaStr);
    } catch (e) {
      showToast('输入Schema格式错误', 'warning');
      return;
    }
  }

  if (outputSchemaStr) {
    try {
      output_schema = JSON.parse(outputSchemaStr);
    } catch (e) {
      showToast('输出Schema格式错误', 'warning');
      return;
    }
  }

  try {
    const data = {
      capability_key: key,
      type,
      name,
      description: desc || undefined,
      business_domain: domain || undefined,
      owner_department: dept || undefined,
      security_level: security,
      side_effect: sideEffect,
      tags,
      scenarios: [],
      allowed_agent_roles: [],
      endpoint: endpoint || undefined,
      timeout_ms: 30000,
      current_version: '1.0.0',
      input_schema,
      output_schema,
      examples: [],
      metadata: {}
    };

    const cap = await apiFetch('/api/v1/capabilities', {
      method: 'POST',
      body: JSON.stringify(data)
    });

    showToast('能力创建成功!', 'success');
    closeModal();
    loadCapabilities();

    setTimeout(() => {
      showCapabilityDetailPage(cap.id);
    }, 300);
  } catch (e) {
    showToast(`创建失败: ${e.message}`, 'error');
  }
}

// ============================================
// 详情页面增强
// ============================================

function showAssetDetail(title, data) {
  navigateToPage('detail');
  appState.currentDetailData = data;

  const container = document.getElementById('asset-detail');
  const isCapability = data.capability_key || (data.type && ['tool', 'skill', 'prompt', 'agent', 'knowledge_base', 'workflow'].includes(data.type));

  if (isCapability) {
    renderCapabilityDetail(container, data, title);
  } else {
    renderGenericDetail(container, data, title);
  }
}

function renderCapabilityDetail(container, data, title) {
  const typeColors = {
    knowledge_base: '#4ade80',
    tool: '#38bdf8',
    skill: '#a78bfa',
    prompt: '#fbbf24',
    agent: '#60a5fa',
    workflow: '#f472b6'
  };

  const typeNames = {
    knowledge_base: '知识库',
    tool: '工具',
    skill: '技能',
    prompt: '提示词',
    agent: 'Agent',
    workflow: '工作流'
  };

  const typeIcon = getTypeIcon(data.type);
  const typeColor = typeColors[data.type] || '#94a3b8';
  const typeName = typeNames[data.type] || data.type;

  container.innerHTML = `
    <div class="detail-header">
      <div class="detail-title-group">
        <div class="detail-icon" style="background: ${typeColor}20; color: ${typeColor}; font-size: 28px;">
          ${typeIcon}
        </div>
        <div>
          <h3 class="detail-title">${escapeHtml(data.name || title)}</h3>
          <div style="display: flex; align-items: center; gap: var(--spacing-sm); margin-top: var(--spacing-xs); flex-wrap: wrap;">
            <span class="badge badge-blue">${escapeHtml(typeName)}</span>
            ${data.capability_key ? `<code style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-size: 12px;">${escapeHtml(data.capability_key)}</code>` : ''}
            ${data.status ? badge(data.status) : ''}
            ${data.security_level ? securityLevelBadge(data.security_level) : ''}
          </div>
        </div>
      </div>
      <div class="detail-actions" style="display: flex; gap: var(--spacing-sm); flex-wrap: wrap;">
        ${data.status === 'draft' ? `<button class="btn btn-primary" onclick="publishCurrentCapability()">发布能力</button>` : ''}
        ${data.status === 'published' ? `<button class="btn btn-secondary" onclick="disableCurrentCapability()">停用</button>` : ''}
        ${data.status === 'disabled' ? `<button class="btn btn-primary" onclick="enableCurrentCapability()">启用</button>` : ''}
        <button class="btn btn-secondary" onclick="showPermissionManager()">权限管理</button>
        <button class="btn btn-secondary" onclick="copyDetailData()">复制JSON</button>
        <button class="btn btn-secondary" onclick="toggleRawJson()">原始JSON</button>
      </div>
    </div>

    <div id="detail-sections">
      ${renderDetailSection('基本信息', [
        { label: 'Key', value: data.capability_key },
        { label: '类型', value: typeName },
        { label: '描述', value: data.description },
        { label: '业务域', value: data.business_domain },
        { label: '所属部门', value: data.owner_department },
        { label: '负责人', value: data.owner_user },
        { label: '状态', raw: data.status ? badge(data.status) : '' },
        { label: '版本', value: data.current_version || data.version },
        { label: '密级', raw: data.security_level ? securityLevelBadge(data.security_level) : '' }
      ])}

      ${data.endpoint ? renderDetailSection('调用配置', [
        { label: 'Endpoint', value: data.endpoint },
        { label: '超时时间', value: data.timeout_ms ? `${data.timeout_ms}ms` : '' },
        { label: '副作用', value: data.side_effect }
      ]) : ''}

      ${data.tags && data.tags.length ? renderDetailSection('标签', [
        { label: '标签', raw: `<div style="display: flex; flex-wrap: wrap; gap: var(--spacing-sm);">${data.tags.map(t => `<span class="badge badge-blue">${escapeHtml(t)}</span>`).join('')}</div>` }
      ]) : ''}

      ${data.scenarios && data.scenarios.length ? renderDetailSection('适用场景', [
        { label: '场景', raw: `<div style="display: flex; flex-wrap: wrap; gap: var(--spacing-sm);">${data.scenarios.map(s => `<span class="badge badge-published">${escapeHtml(s)}</span>`).join('')}</div>` }
      ]) : ''}

      ${data.input_schema && Object.keys(data.input_schema).length ? renderSchemaSection('输入Schema', data.input_schema) : ''}
      ${data.output_schema && Object.keys(data.output_schema).length ? renderSchemaSection('输出Schema', data.output_schema) : ''}

      ${data.examples && data.examples.length ? renderExamplesSection(data.examples) : ''}
    </div>

    <div id="detail-raw-json" class="hidden">
      <div class="detail-section">
        <h4 class="detail-section-title">原始JSON</h4>
        <div class="detail-code">
          <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </div>
      </div>
    </div>

    <div id="permission-manager" class="hidden" style="margin-top: var(--spacing-xl);">
      <div class="detail-section">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--spacing-md);">
          <h4 class="detail-section-title" style="margin: 0;">权限配置</h4>
          <button class="btn btn-sm btn-primary" onclick="showAddPermissionModal()">添加权限</button>
        </div>
        <div id="permissions-list">
          <div style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">
            加载权限中...
          </div>
        </div>
      </div>
    </div>
  `;

  loadPermissionsForDetail(data.id);
}

function getTypeIcon(type) {
  const icons = {
    knowledge_base: '📚',
    tool: '🔧',
    skill: '⚡',
    prompt: '💬',
    agent: '🤖',
    workflow: '🔄'
  };
  return icons[type] || '📦';
}

function renderDetailSection(title, fields) {
  const filtered = fields.filter(f => f.value || f.raw);
  if (!filtered.length) return '';

  return `
    <div class="detail-section">
      <h4 class="detail-section-title">${escapeHtml(title)}</h4>
      <div class="detail-fields">
        ${filtered.map(field => `
          <div class="detail-field">
            <div class="detail-field-label">${escapeHtml(field.label)}</div>
            <div class="detail-field-value">
              ${field.raw ? field.raw : (field.value ? escapeHtml(String(field.value)) : '<span style="color: var(--text-muted);">-</span>')}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function renderSchemaSection(title, schema) {
  return `
    <div class="detail-section">
      <h4 class="detail-section-title">${escapeHtml(title)}</h4>
      <div class="json-collapsible" style="border: 1px solid var(--border-default); border-radius: var(--radius-lg);">
        <div class="json-collapsible-header" onclick="toggleJsonCollapsible(this)" style="cursor: pointer;">
          <span class="json-toggle-icon" style="transition: transform 150ms;">▶</span>
          <strong>展开查看Schema</strong>
        </div>
        <div class="json-collapsible-content hidden" style="padding: var(--spacing-md);">
          <pre style="margin: 0; font-family: 'SF Mono', Monaco, monospace; font-size: 12px; line-height: 1.6; overflow-x: auto;">${escapeHtml(JSON.stringify(schema, null, 2))}</pre>
        </div>
      </div>
    </div>
  `;
}

function renderExamplesSection(examples) {
  return `
    <div class="detail-section">
      <h4 class="detail-section-title">示例</h4>
      ${examples.map((ex, idx) => `
        <div class="json-collapsible" style="border: 1px solid var(--border-default); border-radius: var(--radius-lg); margin-bottom: var(--spacing-sm);">
          <div class="json-collapsible-header" onclick="toggleJsonCollapsible(this)" style="cursor: pointer;">
            <span class="json-toggle-icon" style="transition: transform 150ms;">▶</span>
            <strong>示例 ${idx + 1}</strong>
          </div>
          <div class="json-collapsible-content hidden" style="padding: var(--spacing-md);">
            <pre style="margin: 0; font-family: 'SF Mono', Monaco, monospace; font-size: 12px; line-height: 1.6; overflow-x: auto;">${escapeHtml(typeof ex === 'object' ? JSON.stringify(ex, null, 2) : String(ex))}</pre>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function toggleJsonCollapsible(header) {
  const content = header.nextElementSibling;
  const icon = header.querySelector('.json-toggle-icon');
  content.classList.toggle('hidden');
  icon.style.transform = content.classList.contains('hidden') ? 'rotate(0deg)' : 'rotate(90deg)';
}

function renderGenericDetail(container, data, title) {
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
        <button class="btn btn-secondary" onclick="toggleRawJson()">原始JSON</button>
      </div>
    </div>

    <div id="detail-sections">
      <div class="detail-section">
        <h4 class="detail-section-title">详细信息</h4>
        <div class="detail-code">
          <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </div>
      </div>
    </div>

    <div id="detail-raw-json" class="hidden">
      <div class="detail-section">
        <h4 class="detail-section-title">原始JSON</h4>
        <div class="detail-code">
          <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </div>
      </div>
    </div>
  `;
}

function toggleRawJson() {
  const sections = document.getElementById('detail-sections');
  const rawJson = document.getElementById('detail-raw-json');
  const permMgr = document.getElementById('permission-manager');

  if (sections && !sections.classList.contains('hidden')) {
    sections.classList.add('hidden');
    if (permMgr) permMgr.classList.add('hidden');
    rawJson?.classList.remove('hidden');
  } else {
    sections?.classList.remove('hidden');
    rawJson?.classList.add('hidden');
  }
}

async function publishCurrentCapability() {
  const data = appState.currentDetailData;
  if (!data || !data.id) {
    showToast('没有选中的能力', 'warning');
    return;
  }

  try {
    await apiFetch(`/api/v1/capabilities/${data.id}/publish`, {
      method: 'POST',
      body: JSON.stringify({ release_notes: '通过管理后台发布' })
    });
    showToast('发布成功!', 'success');
    openCapabilityDetail(data.id);
  } catch (e) {
    showToast(`发布失败: ${e.message}`, 'error');
  }
}

async function disableCurrentCapability() {
  const data = appState.currentDetailData;
  if (!data || !data.id) {
    showToast('没有选中的能力', 'warning');
    return;
  }

  try {
    await apiFetch(`/api/v1/capabilities/${data.id}/disable`, {
      method: 'POST'
    });
    showToast('已停用', 'success');
    openCapabilityDetail(data.id);
  } catch (e) {
    showToast(`操作失败: ${e.message}`, 'error');
  }
}

async function enableCurrentCapability() {
  const data = appState.currentDetailData;
  if (!data || !data.id) {
    showToast('没有选中的能力', 'warning');
    return;
  }

  try {
    const cap = await apiFetch(`/api/v1/capabilities/${data.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'draft' })
    });
    showToast('已启用', 'success');
    openCapabilityDetail(data.id);
  } catch (e) {
    showToast(`操作失败: ${e.message}`, 'error');
  }
}

function showPermissionManager() {
  const sections = document.getElementById('detail-sections');
  const rawJson = document.getElementById('detail-raw-json');
  const permMgr = document.getElementById('permission-manager');

  sections?.classList.add('hidden');
  rawJson?.classList.add('hidden');
  permMgr?.classList.remove('hidden');
}

async function loadPermissionsForDetail(capabilityId) {
  if (!capabilityId) return;

  const listEl = document.getElementById('permissions-list');
  if (!listEl) return;

  try {
    const permissions = await apiFetch(`/api/v1/capabilities/${capabilityId}/permissions`);

    if (!permissions || !permissions.length) {
      listEl.innerHTML = `
        <div style="text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">
          暂无权限配置
        </div>
      `;
      return;
    }

    listEl.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: var(--spacing-sm);">
        ${permissions.map(perm => `
          <div style="padding: var(--spacing-md); background: var(--bg-tertiary); border-radius: var(--radius-md); display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="display: flex; align-items: center; gap: var(--spacing-sm); margin-bottom: var(--spacing-xs);">
                <span class="badge badge-published">${escapeHtml(perm.subject_type)}</span>
                <code style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 12px;">${escapeHtml(perm.subject_code)}</code>
                <span style="color: var(--text-secondary);">→</span>
                <span class="badge badge-blue">${escapeHtml(perm.permission)}</span>
              </div>
              ${perm.conditions && Object.keys(perm.conditions).length ? `<p style="margin: 0; font-size: var(--font-size-sm); color: var(--text-muted);">条件: ${escapeHtml(JSON.stringify(perm.conditions))}</p>` : ''}
            </div>
            <button class="btn btn-sm btn-secondary" onclick="deletePermission('${perm.id}')">删除</button>
          </div>
        `).join('')}
      </div>
    `;
  } catch (e) {
    listEl.innerHTML = `<div style="text-align: center; padding: var(--spacing-xl); color: var(--color-danger);">加载权限失败: ${escapeHtml(e.message)}</div>`;
  }
}

function showAddPermissionModal() {
  const content = `
    <div style="display: flex; flex-direction: column; gap: var(--spacing-md);">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">主体类型</label>
          <select id="perm-subject-type" class="select">
            <option value="agent">Agent</option>
            <option value="user">用户</option>
            <option value="role">角色</option>
            <option value="department">部门</option>
          </select>
        </div>
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">主体代码</label>
          <input type="text" id="perm-subject-code" class="input" placeholder="如: master_agent">
        </div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-md);">
        <div>
          <label style="display: block; margin-bottom: var-spacing-xs); font-weight: 500;">权限类型</label>
          <select id="perm-permission" class="select">
            <option value="read">读取 read</option>
            <option value="invoke">调用 invoke</option>
            <option value="manage">管理 manage</option>
          </select>
        </div>
        <div>
          <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">状态</label>
          <select id="perm-status" class="select">
            <option value="active">激活</option>
            <option value="inactive">禁用</option>
          </select>
        </div>
      </div>
      <div>
        <label style="display: block; margin-bottom: var(--spacing-xs); font-weight: 500;">条件 (JSON, 可选)</label>
        <textarea id="perm-conditions" class="input" rows="3" placeholder='{ "requires_audit": true }'></textarea>
      </div>
    </div>
  `;

  openModal({
    title: '添加权限',
    content,
    footerButtons: [
      { text: '取消', action: 'cancel', class: 'btn-secondary' },
      { text: '添加', action: 'confirm', class: 'btn-primary' }
    ]
  }).then(async (action) => {
    if (action !== 'confirm') return;
    await addPermission();
  });
}

async function addPermission() {
  const data = appState.currentDetailData;
  if (!data || !data.id) {
    showToast('没有选中的能力', 'warning');
    return;
  }

  const subjectType = document.getElementById('perm-subject-type')?.value;
  const subjectCode = document.getElementById('perm-subject-code')?.value?.trim();
  const permission = document.getElementById('perm-permission')?.value;
  const status = document.getElementById('perm-status')?.value;
  const conditionsStr = document.getElementById('perm-conditions')?.value?.trim();

  if (!subjectCode) {
    showToast('请填写主体代码', 'warning');
    return;
  }

  let conditions = {};
  if (conditionsStr) {
    try {
      conditions = JSON.parse(conditionsStr);
    } catch (e) {
      showToast('条件JSON格式错误', 'warning');
      return;
    }
  }

  try {
    await apiFetch(`/api/v1/capabilities/${data.id}/permissions`, {
      method: 'POST',
      body: JSON.stringify({
        subject_type: subjectType,
        subject_code: subjectCode,
        permission,
        status,
        conditions
      })
    });

    showToast('权限添加成功!', 'success');
    closeModal();
    loadPermissionsForDetail(data.id);
  } catch (e) {
    showToast(`添加失败: ${e.message}`, 'error');
  }
}

async function deletePermission(permissionId) {
  const data = appState.currentDetailData;
  if (!data || !data.id) return;

  if (!confirm('确定要删除这个权限配置吗?')) return;

  try {
    await apiFetch(`/api/v1/capabilities/${data.id}/permissions/${permissionId}`, {
      method: 'DELETE'
    });
    showToast('权限已删除', 'success');
    loadPermissionsForDetail(data.id);
  } catch (e) {
    showToast(`删除失败: ${e.message}`, 'error');
  }
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

  // 全局搜索
  const globalSearch = document.getElementById('global-search');
  if (globalSearch) {
    globalSearch.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        performGlobalSearch(e.target.value);
      }
    });
  }

  // 能力目录
  const capSearch = document.getElementById('cap-search');
  const capTypeFilter = document.getElementById('cap-type-filter');
  const capStatusFilter = document.getElementById('cap-status-filter');
  if (capSearch) {
    let capSearchTimeout;
    capSearch.addEventListener('input', () => {
      clearTimeout(capSearchTimeout);
      capSearchTimeout = setTimeout(loadCapabilities, 300);
    });
  }
  if (capTypeFilter) capTypeFilter.addEventListener('change', loadCapabilities);
  if (capStatusFilter) capStatusFilter.addEventListener('change', loadCapabilities);

  const capRefreshBtn = document.getElementById('cap-refresh-btn');
  if (capRefreshBtn) capRefreshBtn.addEventListener('click', loadCapabilities);

  // 视图切换
  document.querySelectorAll('#capabilities .view-toggle button').forEach(btn => {
    btn.addEventListener('click', () => toggleCapabilitiesView(btn.dataset.view));
  });

  // Skills搜索
  const skillSearch = document.getElementById('skill-search');
  if (skillSearch) {
    let skillSearchTimeout;
    skillSearch.addEventListener('input', () => {
      clearTimeout(skillSearchTimeout);
      skillSearchTimeout = setTimeout(loadSkills, 300);
    });
  }

  // Prompts搜索
  const promptSearch = document.getElementById('prompt-search');
  if (promptSearch) {
    let promptSearchTimeout;
    promptSearch.addEventListener('input', () => {
      clearTimeout(promptSearchTimeout);
      promptSearchTimeout = setTimeout(loadPrompts, 300);
    });
  }

  // 知识库搜索
  const knowledgeSearch = document.getElementById('knowledge-search');
  if (knowledgeSearch) {
    let knowledgeSearchTimeout;
    knowledgeSearch.addEventListener('input', () => {
      clearTimeout(knowledgeSearchTimeout);
      knowledgeSearchTimeout = setTimeout(loadKnowledgeBases, 300);
    });
  }

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

  // 创建能力按钮
  const capCreateBtn = document.getElementById('cap-create-btn');
  if (capCreateBtn) capCreateBtn.addEventListener('click', showCreateCapabilityModal);

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
window.showRegistryWizard = showRegistryWizard;
window.showCreateCapabilityModal = showCreateCapabilityModal;
window.publishCurrentCapability = publishCurrentCapability;
window.disableCurrentCapability = disableCurrentCapability;
window.enableCurrentCapability = enableCurrentCapability;
window.showPermissionManager = showPermissionManager;
window.showAddPermissionModal = showAddPermissionModal;
window.deletePermission = deletePermission;
window.toggleJsonCollapsible = toggleJsonCollapsible;
window.toggleRawJson = toggleRawJson;
window.copyDetailData = copyDetailData;
