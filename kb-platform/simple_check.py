#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""简化版项目检查脚本"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("="*60)
print("Project Health Check")
print("="*60)

results = {
    "check_time": datetime.now().isoformat(),
    "passed": 0,
    "warning": 0,
    "failed": 0,
    "issues": []
}

def check(name, condition, message, is_warning=False):
    """简化的检查函数"""
    if condition:
        results["passed"] += 1
        print(f"[OK] {name}: {message}")
    else:
        if is_warning:
            results["warning"] += 1
            results["issues"].append({"type": "warning", "name": name, "message": message})
            print(f"[WARN] {name}: {message}")
        else:
            results["failed"] += 1
            results["issues"].append({"type": "error", "name": name, "message": message})
            print(f"[FAIL] {name}: {message}")

# 1. Python version
print("\n[1/15] Checking Python version...")
version = sys.version_info
version_str = f"{version.major}.{version.minor}.{version.micro}"
check("Python Version", version.major >=3 and version.minor >= 8,
      f"Python {version_str} (needs >=3.11 for full compatibility)", is_warning=True)

# 2. File structure
print("\n[2/15] Checking file structure...")
required_files = [
    "pyproject.toml", "app/main.py", "app/__init__.py",
    "docker-compose.yml", "README.md", ".env.example"
]
for f in required_files:
    exists = (project_root / f).exists()
    check(f"File {f}", exists, f"File exists" if exists else "File missing", is_warning=True)

# 3. Check tools files
print("\n[3/15] Checking tools migration files...")
tool_files = [
    "app/services/tools/__init__.py",
    "app/services/tools/forbidden_word_check.py",
    "app/api/v1/tools.py",
    "docs/TOOL_MIGRATION_GUIDE.md"
]
for f in tool_files:
    exists = (project_root / f).exists()
    check(f"Migration File {f}", exists, "File created successfully")

# 4. Check main.py has tools router
print("\n[4/15] Checking API router registration...")
main_py = project_root / "app" / "main.py"
if main_py.exists():
    content = main_py.read_text(encoding="utf-8")
    has_tools_import = "tools.router" in content or "app.api.v1.tools" in content
    check("Tools Router Import", has_tools_import, "Tools router imported", is_warning=True)
    has_tools_include = "include_router(tools.router" in content
    check("Tools Router Included", has_tools_include, "Tools router registered", is_warning=True)

# 5. Check capability service changes
print("\n[5/15] Checking capability service...")
cap_service = project_root / "app/services/capability_service.py"
if cap_service.exists():
    content = cap_service.read_text(encoding="utf-8")
    has_tool_registry = "ToolRegistry" in content or "create_tool_executor" in content
    check("Capability Service Updated", has_tool_registry, "Service uses ToolRegistry", is_warning=True)

# 6. Check skill runtime changes
print("\n[6/15] Checking skill runtime...")
skill_runtime = project_root / "app/services/skill_runtime.py"
if skill_runtime.exists():
    content = skill_runtime.read_text(encoding="utf-8")
    has_tool_update = "ToolRegistry" in content or "create_tool_executor" in content
    check("Skill Runtime Updated", has_tool_update, "Runtime uses ToolRegistry", is_warning=True)

# 7. Check seed data update
print("\n[7/15] Checking seed data...")
seed_data = project_root / "app/seeds/seed_data.py"
if seed_data.exists():
    content = seed_data.read_text(encoding="utf-8")
    has_tool_import = "ToolRegistry" in content
    has_get_tool = "get_tool_capabilities" in content
    check("Seed Data Updated", has_tool_import or has_get_tool,
          "Seed data uses ToolRegistry", is_warning=True)

# 8. Check admin console
print("\n[8/15] Checking admin console...")
admin_files = ["admin_console/index.html", "admin_console/app.js", "admin_console/style.css"]
for f in admin_files:
    exists = (project_root / f).exists()
    check(f"Admin {f}", exists, "File exists", is_warning=True)

# 9. Check database models
print("\n[9/15] Checking database models...")
models_dir = project_root / "app/models"
if models_dir.exists():
    model_files = list(models_dir.glob("*.py"))
    model_count = len([f for f in model_files if not f.name.startswith("_")])
    check("Database Models", model_count > 5, f"Found {model_count} model files")

# 10. Check services
print("\n[10/15] Checking services...")
services_dir = project_root / "app/services"
if services_dir.exists():
    service_files = list(services_dir.glob("*.py"))
    service_count = len([f for f in service_files if not f.name.startswith("_")])
    check("Services", service_count > 5, f"Found {service_count} service files")

# 11. Check config files
print("\n[11/15] Checking config files...")
check("pyproject.toml", (project_root / "pyproject.toml").exists(), "Project config exists")
check(".env.example", (project_root / ".env.example").exists(), "Env example exists", is_warning=True)

# 12. Check git
print("\n[12/15] Checking git...")
check("Git Repo", (project_root / ".git").exists(), "Git initialized", is_warning=True)
check(".gitignore", (project_root / ".gitignore").exists(), "Gitignore exists", is_warning=True)

# 13. Check documentation
print("\n[13/15] Checking documentation...")
check("README.md", (project_root / "README.md").exists(), "Readme exists", is_warning=True)
check("Migration Guide", (project_root / "docs/TOOL_MIGRATION_GUIDE.md").exists(),
      "Migration guide created")

# 14. Check examples
print("\n[14/15] Checking examples...")
examples_dir = project_root / "examples"
if examples_dir.exists():
    example_files = list(examples_dir.glob("*.py"))
    check("Examples", len(example_files) > 0, f"Found {len(example_files)} examples", is_warning=True)

# 15. Summary check
print("\n[15/15] Final summary...")
all_migration_files_exist = all(
    (project_root / f).exists() for f in tool_files
)
check("Migration Complete", all_migration_files_exist, "All migration files created")

# Print summary
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
total = results["passed"] + results["warning"] + results["failed"]
print(f"Total checks: {total}")
print(f"Passed: {results['passed']}")
print(f"Warnings: {results['warning']}")
print(f"Failed: {results['failed']}")
print("="*60)

# Save results
report_path = project_root / "CHECK_RESULTS.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nResults saved to: {report_path}")

if results["issues"]:
    print("\nISSUES FOUND:")
    for issue in results["issues"]:
        prefix = "ERROR" if issue["type"] == "error" else "WARN"
        print(f"[{prefix}] {issue['name']}: {issue['message']}")
else:
    print("\nNo critical issues found!")

print("\nDone!")
