#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""简化版测试，兼容 Python 3.6。"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 60)
print("Testing Tool Migration")
print("=" * 60)

# Test 1: Import
print("\n[1/5] Testing imports...")
try:
    from app.services.tools import ToolRegistry
    print("OK: ToolRegistry imported")
except Exception as e:
    print("ERROR:", e)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Forbidden word check
print("\n[2/5] Testing forbidden word check...")
try:
    from app.services.tools.forbidden_word_check import check_forbidden_words
    result = check_forbidden_words("这是最高级的测试文本")
    print("OK: check_forbidden_words works")
    print("  passed:", result.get("passed"))
    print("  hits:", len(result.get("hits", [])))
except Exception as e:
    print("ERROR:", e)
    import traceback
    traceback.print_exc()

# Test 3: Tool definition
print("\n[3/5] Testing tool definition...")
try:
    from app.services.tools.forbidden_word_check import ForbiddenWordCheckTool
    definition = ForbiddenWordCheckTool.get_definition()
    print("OK: Tool definition loaded")
    print("  key:", definition.capability_key)
    print("  name:", definition.name)
except Exception as e:
    print("ERROR:", e)
    import traceback
    traceback.print_exc()

# Test 4: Tool registry
print("\n[4/5] Testing tool registry...")
try:
    from app.services.tools import ToolRegistry
    definitions = ToolRegistry.get_all_definitions()
    print("OK: Registry has", len(definitions), "tools")
    for d in definitions:
        print("  -", d.capability_key, ":", d.name)
except Exception as e:
    print("ERROR:", e)
    import traceback
    traceback.print_exc()

# Test 5: Verify files exist
print("\n[5/5] Checking files...")
import os
files_to_check = [
    "app/services/tools/__init__.py",
    "app/services/tools/forbidden_word_check.py",
    "app/api/v1/tools.py",
    "docs/TOOL_MIGRATION_GUIDE.md",
]
for f in files_to_check:
    exists = os.path.exists(f)
    status = "OK" if exists else "MISSING"
    print(f"  [{status}] {f}")

print("\n" + "=" * 60)
print("All tests completed!")
print("=" * 60)
