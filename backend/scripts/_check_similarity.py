"""检查跨文档语义重复程度 - 改进版"""

import numpy as np
from app.core.deps import milvus_manager
from llm.volcengine_client import embedding_client
from app.db.engine import get_engine
from sqlalchemy import text
from collections import defaultdict
import random

random.seed(42)
coll = milvus_manager.collection
print(f'Milvus entities: {coll.num_entities}')

def cosine(v1, v2):
    """计算两个向量的余弦相似度"""
    v1 = np.array(v1) / (np.linalg.norm(v1) + 1e-8)
    v2 = np.array(v2) / (np.linalg.norm(v2) + 1e-8)
    return float(np.dot(v1, v2))

# ── 1. 检查向量是否已归一化 ──
engine = get_engine()
with engine.connect() as conn:
    r = conn.execute(text("SELECT content FROM knowledge_chunks WHERE status='active' LIMIT 3"))
    for row in r:
        v = embedding_client.embed_text([row[0][:200]])[0]
        norm = np.linalg.norm(v)
        print(f'vector norm={norm:.4f} (1.0 = normalized)')

# ── 2. 采样并计算相似度 ──
print()
with engine.connect() as conn:
    r = conn.execute(text(
        "SELECT chunk_id, doc_id, content FROM knowledge_chunks WHERE status='active' "
        "AND length(content) > 20 ORDER BY RANDOM() LIMIT 500"
    ))
    all_chunks = r.fetchall()
print(f'sampled chunks: {len(all_chunks)}')

doc_chunks = defaultdict(list)
for c in all_chunks:
    doc_chunks[c[1]].append((c[0], c[2]))
print(f'unique docs in sample: {len(doc_chunks)}')

# 只取有 >=2 个 chunk 的文档
multi_chunk_docs = {k: v for k, v in doc_chunks.items() if len(v) >= 2}
print(f'docs with >=2 chunks: {len(multi_chunk_docs)}')

# ── 嵌入缓存 ──
print('embedding chunks...')
embed_cache = {}
texts_to_embed = []
keys_to_embed = []
for doc_id, chunks in multi_chunk_docs.items():
    for cid, ct in chunks:
        if cid not in embed_cache:
            texts_to_embed.append(ct[:500])
            keys_to_embed.append(cid)

# 分批 embed
batch_size = 20
for i in range(0, len(texts_to_embed), batch_size):
    batch = texts_to_embed[i:i+batch_size]
    vecs = embedding_client.embed_text(batch)
    for j, v in enumerate(vecs):
        embed_cache[keys_to_embed[i+j]] = v
    if i % 200 == 0:
        print(f'  embedded {min(i+batch_size, len(texts_to_embed))}/{len(texts_to_embed)}')
print(f'embedded {len(embed_cache)} unique chunks')

# ── 3. 同文档最相似对 ──
print()
print('=== 同文档 MAX 相似度（每个文档取最相似的一对）===')
same_doc_max_sims = []
for doc_id, chunks in multi_chunk_docs.items():
    max_sim = 0.0
    for i in range(len(chunks)):
        vi = embed_cache[chunks[i][0]]
        for j in range(i+1, len(chunks)):
            vj = embed_cache[chunks[j][0]]
            sim = cosine(vi, vj)
            if sim > max_sim:
                max_sim = sim
    same_doc_max_sims.append(max_sim)
    if len(same_doc_max_sims) >= 100:
        break

print(f'n={len(same_doc_max_sims)}')
print(f'mean={np.mean(same_doc_max_sims):.4f} median={np.median(same_doc_max_sims):.4f}')
print(f'std={np.std(same_doc_max_sims):.4f} max={np.max(same_doc_max_sims):.4f} min={np.min(same_doc_max_sims):.4f}')
print(f'>=0.95: {sum(1 for s in same_doc_max_sims if s>=0.95)}')
print(f'>=0.90: {sum(1 for s in same_doc_max_sims if s>=0.90)}')
print(f'>=0.80: {sum(1 for s in same_doc_max_sims if s>=0.80)}')
print(f'>=0.70: {sum(1 for s in same_doc_max_sims if s>=0.70)}')

# ── 4. 跨文档最相似对 ──
print()
print('=== 跨文档 MAX 相似度（每对文档取最相似的两个 chunk）===')
doc_ids = list(multi_chunk_docs.keys())
cross_doc_max_sims = []
for _ in range(100):
    d1, d2 = random.sample(doc_ids, 2)
    max_sim = 0.0
    for c1 in multi_chunk_docs[d1]:
        v1 = embed_cache.get(c1[0])
        if v1 is None:
            continue
        for c2 in multi_chunk_docs[d2]:
            v2 = embed_cache.get(c2[0])
            if v2 is None:
                continue
            sim = cosine(v1, v2)
            if sim > max_sim:
                max_sim = sim
    cross_doc_max_sims.append(max_sim)

print(f'n={len(cross_doc_max_sims)}')
print(f'mean={np.mean(cross_doc_max_sims):.4f} median={np.median(cross_doc_max_sims):.4f}')
print(f'std={np.std(cross_doc_max_sims):.4f} max={np.max(cross_doc_max_sims):.4f} min={np.min(cross_doc_max_sims):.4f}')
print(f'>=0.95: {sum(1 for s in cross_doc_max_sims if s>=0.95)}')
print(f'>=0.90: {sum(1 for s in cross_doc_max_sims if s>=0.90)}')
print(f'>=0.80: {sum(1 for s in cross_doc_max_sims if s>=0.80)}')
print(f'>=0.70: {sum(1 for s in cross_doc_max_sims if s>=0.70)}')
