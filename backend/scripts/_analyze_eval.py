"""分析评测数据集特征"""
import json
from collections import Counter

import os
eval_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '..', '..', 'evaluation', 'eval_dataset.json')
with open(eval_path, 'r', encoding='utf-8') as f:
    items = json.load(f)

print(f'Total items: {len(items)}')

# source distribution
src = Counter(i.get('source', '?') for i in items)
print(f'source: {dict(src)}')

# doc_id distribution
docs = Counter(i.get('doc_id', '?') for i in items)
print(f'unique docs: {len(docs)}')
print(f'per doc: min={min(docs.values())} max={max(docs.values())} avg={len(items)/len(docs):.1f}')

# distribution buckets
buckets = Counter()
for cnt in docs.values():
    if cnt <= 3: buckets['1-3'] += 1
    elif cnt <= 5: buckets['4-5'] += 1
    elif cnt <= 10: buckets['6-10'] += 1
    else: buckets['10+'] += 1
print(f'buckets: {dict(buckets)}')

# expected_chunk_ids per query
ec_counts = Counter(len(i.get('expected_chunk_ids', [])) for i in items)
print(f'expected_chunk_ids per query: {dict(ec_counts)}')

# sample
import random
random.seed(42)
samples = random.sample(items, 5)
print()
print('=== Samples ===')
for i, s in enumerate(samples):
    print(f'{i+1}. [{s.get("source")}] {s["query"][:100]}')
    print(f'   chunk_ids={len(s.get("expected_chunk_ids",[]))} keywords={len(s.get("expected_content_contains",[]))}')
