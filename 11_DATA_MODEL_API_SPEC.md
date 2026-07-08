# 11 数据模型与API接口草案

## 1. 核心实体

```text
Agent
Capability
KnowledgeBase
Document
KnowledgeChunk
Skill
PromptTemplate
Tool
Policy
AuditLog
TraceSpan
EvaluationDataset
EvaluationRun
ApprovalTicket
```

## 2. 表结构草案

### 2.1 agents
```sql
CREATE TABLE agents (
  id UUID PRIMARY KEY,
  agent_key VARCHAR(128) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  role VARCHAR(128) NOT NULL,
  business_domain VARCHAR(128),
  owner_department VARCHAR(128),
  owner_user VARCHAR(128),
  status VARCHAR(32) NOT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 2.2 capabilities
```sql
CREATE TABLE capabilities (
  id UUID PRIMARY KEY,
  capability_key VARCHAR(128) UNIQUE NOT NULL,
  type VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  business_domain VARCHAR(128),
  tags TEXT[],
  input_schema JSONB,
  output_schema JSONB,
  security_level VARCHAR(64),
  owner_department VARCHAR(128),
  owner_user VARCHAR(128),
  status VARCHAR(32),
  current_version VARCHAR(64),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 2.3 capability_versions
```sql
CREATE TABLE capability_versions (
  id UUID PRIMARY KEY,
  capability_id UUID REFERENCES capabilities(id),
  version VARCHAR(64) NOT NULL,
  config JSONB NOT NULL,
  status VARCHAR(32),
  release_notes TEXT,
  created_by VARCHAR(128),
  created_at TIMESTAMP NOT NULL,
  UNIQUE(capability_id, version)
);
```

### 2.4 knowledge_bases
```sql
CREATE TABLE knowledge_bases (
  id UUID PRIMARY KEY,
  kb_key VARCHAR(128) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  business_domain VARCHAR(128),
  owner_department VARCHAR(128),
  security_level VARCHAR(64),
  status VARCHAR(32),
  retrieval_config JSONB DEFAULT '{}',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 2.5 documents
```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  kb_id UUID REFERENCES knowledge_bases(id),
  title VARCHAR(512),
  source_type VARCHAR(64),
  source_uri TEXT,
  object_uri TEXT,
  parse_status VARCHAR(64),
  version VARCHAR(64),
  security_level VARCHAR(64),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 2.6 knowledge_chunks
```sql
CREATE TABLE knowledge_chunks (
  id UUID PRIMARY KEY,
  doc_id UUID REFERENCES documents(id),
  kb_id UUID REFERENCES knowledge_bases(id),
  chunk_index INT,
  title_path TEXT[],
  content TEXT NOT NULL,
  summary TEXT,
  keywords TEXT[],
  embedding_id VARCHAR(255),
  version VARCHAR(64),
  security_level VARCHAR(64),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP NOT NULL
);
```

### 2.7 policies
```sql
CREATE TABLE policies (
  id UUID PRIMARY KEY,
  policy_key VARCHAR(128) UNIQUE,
  name VARCHAR(255),
  effect VARCHAR(16),
  subject JSONB,
  resource JSONB,
  actions TEXT[],
  conditions JSONB,
  status VARCHAR(32),
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

### 2.8 audit_logs
```sql
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY,
  trace_id VARCHAR(128),
  actor_type VARCHAR(64),
  actor_id VARCHAR(128),
  action VARCHAR(128),
  resource_type VARCHAR(64),
  resource_id VARCHAR(128),
  resource_version VARCHAR(64),
  decision VARCHAR(32),
  input_digest VARCHAR(128),
  output_digest VARCHAR(128),
  latency_ms INT,
  error_code VARCHAR(64),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP NOT NULL
);
```

## 3. API接口列表

### 3.1 Agent
```http
POST /api/v1/agents
GET /api/v1/agents
GET /api/v1/agents/{agent_id}
PATCH /api/v1/agents/{agent_id}
POST /api/v1/agents/{agent_id}/rotate-key
POST /api/v1/agents/{agent_id}/disable
```

### 3.2 Capability
```http
POST /api/v1/capabilities
GET /api/v1/capabilities
GET /api/v1/capabilities/{id}
PATCH /api/v1/capabilities/{id}
POST /api/v1/capabilities/search
POST /api/v1/capabilities/{id}/invoke
POST /api/v1/capabilities/{id}/publish
POST /api/v1/capabilities/{id}/rollback
POST /api/v1/capabilities/{id}/disable
```

### 3.3 Knowledge
```http
POST /api/v1/knowledge-bases
GET /api/v1/knowledge-bases
POST /api/v1/knowledge-bases/{kb_id}/documents
GET /api/v1/documents/{doc_id}
POST /api/v1/documents/{doc_id}/parse
POST /api/v1/documents/{doc_id}/publish
POST /api/v1/knowledge/search
POST /api/v1/knowledge/answer
```

### 3.4 Skill
```http
POST /api/v1/skills
GET /api/v1/skills
GET /api/v1/skills/{skill_id}
POST /api/v1/skills/{skill_id}/invoke
POST /api/v1/skills/{skill_id}/evaluate
POST /api/v1/skills/{skill_id}/publish
```

### 3.5 Prompt
```http
POST /api/v1/prompts
GET /api/v1/prompts
GET /api/v1/prompts/{prompt_id}
POST /api/v1/prompts/{prompt_id}/render
POST /api/v1/prompts/{prompt_id}/evaluate
POST /api/v1/prompts/{prompt_id}/publish
```

### 3.6 Audit
```http
GET /api/v1/audit-logs
GET /api/v1/traces/{trace_id}
GET /api/v1/metrics/overview
```

## 4. OpenAPI要求
所有接口必须提供OpenAPI文档：
- 请求Schema
- 响应Schema
- 错误码
- 示例
- 权限说明
- 是否写操作
- 是否高风险

## 5. API响应统一格式
```json
{
  "success": true,
  "data": {},
  "error": null,
  "trace_id": "trace_001",
  "timestamp": "2026-01-01T00:00:00Z"
}
```

错误格式：
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "403001",
    "message": "Agent has no permission to invoke this capability",
    "details": {}
  },
  "trace_id": "trace_001"
}
```
