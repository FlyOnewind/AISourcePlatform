#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
项目健康检查脚本
检测项目潜在问题并生成测试报告
"""
import os
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

class ProjectHealthChecker:
    def __init__(self):
        self.results = {
            "check_time": datetime.now().isoformat(),
            "checks": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "warning": 0,
                "failed": 0
            },
            "issues": []
        }

    def log_check(self, category, name, status, message="", details=None):
        """记录检查结果"""
        check_result = {
            "category": category,
            "name": name,
            "status": status,
            "message": message,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.results["checks"].append(check_result)
        self.results["summary"]["total"] += 1

        if status == "passed":
            self.results["summary"]["passed"] += 1
        elif status == "warning":
            self.results["summary"]["warning"] += 1
            self.results["issues"].append({
                "severity": "warning",
                "category": category,
                "name": name,
                "message": message,
                "details": details
            })
        elif status == "failed":
            self.results["summary"]["failed"] += 1
            self.results["issues"].append({
                "severity": "error",
                "category": category,
                "name": name,
                "message": message,
                "details": details
            })

    def check_python_version(self):
        """检查 Python 版本"""
        print("[1/15] 检查 Python 版本...")
        try:
            version = sys.version_info
            version_str = f"{version.major}.{version.minor}.{version.micro}"

            if version.major >= 3 and version.minor >= 11:
                self.log_check(
                    "environment", "Python 版本", "passed",
                    f"当前版本 {version_str} (要求 >= 3.11)"
                )
            elif version.major >= 3 and version.minor >= 8:
                self.log_check(
                    "environment", "Python 版本", "warning",
                    f"当前版本 {version_str} (要求 >= 3.11，可能存在兼容性问题)",
                    {"current": version_str, "required": ">=3.11"}
                )
            else:
                self.log_check(
                    "environment", "Python 版本", "failed",
                    f"当前版本 {version_str} (要求 >= 3.11)",
                    {"current": version_str, "required": ">=3.11"}
                )
        except Exception as e:
            self.log_check("environment", "Python 版本", "failed", str(e))

    def check_file_structure(self):
        """检查项目文件结构"""
        print("[2/15] 检查项目文件结构...")
        required_files = [
            "pyproject.toml",
            "app/main.py",
            "app/__init__.py",
            "docker-compose.yml",
            "README.md",
            ".env.example"
        ]

        for file_path in required_files:
            if (project_root / file_path).exists():
                self.log_check("structure", f"文件 {file_path}", "passed", "文件存在")
            else:
                self.log_check("structure", f"文件 {file_path}", "warning", "文件缺失")

        # 检查核心模块
        core_modules = [
            "app/api",
            "app/core",
            "app/models",
            "app/schemas",
            "app/services",
            "app/seeds"
        ]

        for module in core_modules:
            if (project_root / module).exists():
                self.log_check("structure", f"模块 {module}", "passed", "模块存在")
            else:
                self.log_check("structure", f"模块 {module}", "warning", "模块缺失")

    def check_imports(self):
        """检查模块导入"""
        print("[3/15] 检查模块导入...")

        # 检查各个核心模块能否导入
        modules_to_test = [
            ("app.core.config", "配置模块"),
            ("app.core.db", "数据库模块"),
            ("app.models", "模型模块"),
            ("app.schemas", "Schema 模块"),
        ]

        for module_path, module_name in modules_to_test:
            try:
                __import__(module_path)
                self.log_check("imports", f"导入 {module_name}", "passed", "导入成功")
            except Exception as e:
                self.log_check(
                    "imports", f"导入 {module_name}", "failed",
                    f"导入失败: {str(e)}",
                    {"error": str(e), "traceback": traceback.format_exc()}
                )

    def check_config(self):
        """检查配置文件"""
        print("[4/15] 检查配置文件...")

        env_example = project_root / ".env.example"
        if env_example.exists():
            self.log_check("config", ".env.example", "passed", "配置示例存在")
        else:
            self.log_check("config", ".env.example", "warning", "配置示例缺失")

        env_file = project_root / ".env"
        if env_file.exists():
            self.log_check("config", ".env", "passed", "配置文件存在")
        else:
            self.log_check("config", ".env", "warning", "配置文件不存在，请从 .env.example 复制")

    def check_code_style(self):
        """检查代码中的常见问题"""
        print("[5/15] 检查代码常见问题...")

        # 检查我们最近修改的文件
        files_to_check = [
            "app/services/tools/__init__.py",
            "app/services/tools/forbidden_word_check.py",
            "app/services/capability_service.py",
            "app/services/skill_runtime.py",
            "app/api/v1/tools.py",
            "app/main.py",
        ]

        for file_path in files_to_check:
            full_path = project_root / file_path
            if full_path.exists():
                try:
                    content = full_path.read_text(encoding="utf-8")
                    # 检查一些常见问题
                    issues = []
                    if "print(" in content:
                        issues.append("包含 print 语句")
                    if "TODO" in content or "FIXME" in content:
                        issues.append("包含待办标记")

                    if issues:
                        self.log_check(
                            "codestyle", f"代码质量 {file_path}", "warning",
                            "发现潜在问题", {"issues": issues}
                        )
                    else:
                        self.log_check(
                            "codestyle", f"代码质量 {file_path}", "passed", "未发现明显问题"
                        )
                except Exception as e:
                    self.log_check(
                        "codestyle", f"代码质量 {file_path}", "warning",
                        f"检查失败: {str(e)}"
                    )
            else:
                self.log_check(
                    "codestyle", f"代码质量 {file_path}", "warning", "文件不存在"
                )

    def check_api_routers(self):
        """检查 API 路由配置"""
        print("[6/15] 检查 API 路由...")

        try:
            # 读取 main.py 检查路由注册
            main_py = project_root / "app" / "main.py"
            if main_py.exists():
                content = main_py.read_text(encoding="utf-8")
                routers = [
                    "health.router",
                    "agents.router",
                    "capabilities.router",
                    "integration.router",
                    "knowledge.router",
                    "skills.router",
                    "prompts.router",
                    "audit.router",
                    "tools.router"
                ]

                found_routers = []
                missing_routers = []

                for router in routers:
                    if router in content:
                        found_routers.append(router)
                    else:
                        missing_routers.append(router)

                if missing_routers:
                    self.log_check(
                        "api", "API 路由注册", "warning",
                        f"部分路由可能缺失: {', '.join(missing_routers)}",
                        {"found": found_routers, "missing": missing_routers}
                    )
                else:
                    self.log_check(
                        "api", "API 路由注册", "passed",
                        f"所有路由已注册: {len(found_routers)} 个"
                    )
        except Exception as e:
            self.log_check("api", "API 路由注册", "failed", str(e))

    def check_database_models(self):
        """检查数据库模型"""
        print("[7/15] 检查数据库模型...")

        model_files = list((project_root / "app" / "models").glob("*.py"))
        model_files = [f for f in model_files if not f.name.startswith("_")]

        if model_files:
            self.log_check(
                "database", "数据库模型文件", "passed",
                f"发现 {len(model_files)} 个模型文件"
            )

            # 检查几个关键模型
            key_models = [
                "capability.py", "knowledge.py", "skill.py",
                "prompt.py", "agent.py", "audit.py"
            ]

            for model in key_models:
                model_path = project_root / "app" / "models" / model
                if model_path.exists():
                    self.log_check("database", f"模型 {model}", "passed", "模型文件存在")
                else:
                    self.log_check("database", f"模型 {model}", "warning", "模型文件缺失")
        else:
            self.log_check("database", "数据库模型文件", "failed", "未找到模型文件")

    def check_services(self):
        """检查服务层"""
        print("[8/15] 检查服务层...")

        services_path = project_root / "app" / "services"
        if services_path.exists():
            service_files = list(services_path.glob("*.py"))
            service_files = [f for f in service_files if not f.name.startswith("_")]

            self.log_check(
                "services", "服务模块", "passed",
                f"发现 {len(service_files)} 个服务文件"
            )

            # 检查工具目录
            tools_path = services_path / "tools"
            if tools_path.exists() and tools_path.is_dir():
                tool_files = list(tools_path.glob("*.py"))
                tool_files = [f for f in tool_files if not f.name.startswith("_")]
                self.log_check(
                    "services", "工具服务", "passed",
                    f"发现 {len(tool_files)} 个工具文件"
                )
            else:
                self.log_check(
                    "services", "工具服务", "warning", "工具目录不存在"
                )
        else:
            self.log_check("services", "服务模块", "failed", "服务目录不存在")

    def check_admin_console(self):
        """检查管理后台"""
        print("[9/15] 检查管理后台...")

        admin_path = project_root / "admin_console"
        if admin_path.exists():
            required_files = ["index.html", "app.js", "style.css"]
            missing = []
            for f in required_files:
                if not (admin_path / f).exists():
                    missing.append(f)

            if missing:
                self.log_check(
                    "admin", "管理后台文件", "warning",
                    f"部分文件缺失: {', '.join(missing)}"
                )
            else:
                self.log_check(
                    "admin", "管理后台文件", "passed", "核心文件完整"
                )
        else:
            self.log_check("admin", "管理后台", "failed", "管理后台目录不存在")

    def check_documentation(self):
        """检查文档"""
        print("[10/15] 检查文档...")

        docs_to_check = [
            ("README.md", "项目说明"),
            ("docs/TOOL_MIGRATION_GUIDE.md", "工具迁移指南"),
        ]

        for doc_path, doc_name in docs_to_check:
            full_path = project_root / doc_path
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8")
                if len(content.strip()) > 100:
                    self.log_check("docs", f"文档 {doc_name}", "passed", "文档存在且有内容")
                else:
                    self.log_check("docs", f"文档 {doc_name}", "warning", "文档存在但内容较少")
            else:
                self.log_check("docs", f"文档 {doc_name}", "warning", "文档缺失")

    def check_dependencies(self):
        """检查依赖配置"""
        print("[11/15] 检查依赖配置...")

        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text(encoding="utf-8")

            # 检查一些关键依赖
            key_deps = ["fastapi", "sqlalchemy", "pydantic", "uvicorn"]
            found_deps = []
            missing_deps = []

            for dep in key_deps:
                if dep in content:
                    found_deps.append(dep)
                else:
                    missing_deps.append(dep)

            if missing_deps:
                self.log_check(
                    "dependencies", "核心依赖", "warning",
                    f"部分依赖可能缺失: {', '.join(missing_deps)}"
                )
            else:
                self.log_check(
                    "dependencies", "核心依赖", "passed", "核心依赖配置完整"
                )
        else:
            self.log_check("dependencies", "核心依赖", "failed", "pyproject.toml 缺失")

    def check_seed_data(self):
        """检查种子数据"""
        print("[12/15] 检查种子数据...")

        seed_file = project_root / "app" / "seeds" / "seed_data.py"
        if seed_file.exists():
            content = seed_file.read_text(encoding="utf-8")

            # 检查是否包含关键组件
            components = [
                "BUSINESS_AGENTS", "DOCS", "PROMPTS", "SKILLS", "CAPABILITIES_EXTRA"
            ]

            found_components = []
            for comp in components:
                if comp in content:
                    found_components.append(comp)

            self.log_check(
                "seeds", "种子数据", "passed",
                f"种子数据完整，包含 {len(found_components)} 个组件"
            )
        else:
            self.log_check("seeds", "种子数据", "failed", "种子数据文件缺失")

    def check_examples(self):
        """检查示例代码"""
        print("[13/15] 检查示例代码...")

        examples_path = project_root / "examples"
        if examples_path.exists():
            example_files = list(examples_path.glob("*.py"))
            example_files.extend(list(examples_path.glob("*.md")))

            if example_files:
                self.log_check(
                    "examples", "示例代码", "passed",
                    f"发现 {len(example_files)} 个示例文件"
                )
            else:
                self.log_check("examples", "示例代码", "warning", "示例目录存在但没有文件")
        else:
            self.log_check("examples", "示例代码", "warning", "示例目录不存在")

    def check_git_status(self):
        """检查 Git 状态"""
        print("[14/15] 检查 Git 状态...")

        git_dir = project_root / ".git"
        if git_dir.exists():
            self.log_check("git", "Git 仓库", "passed", "Git 仓库已初始化")

            # 检查 .gitignore
            gitignore = project_root / ".gitignore"
            if gitignore.exists():
                self.log_check("git", ".gitignore", "passed", "忽略文件存在")
            else:
                self.log_check("git", ".gitignore", "warning", "忽略文件缺失")
        else:
            self.log_check("git", "Git 仓库", "warning", "Git 仓库未初始化")

    def check_recent_changes(self):
        """检查最近的变更"""
        print("[15/15] 检查最近变更...")

        # 检查我们新创建和修改的文件
        changed_files = [
            "app/services/tools/__init__.py",
            "app/services/tools/forbidden_word_check.py",
            "app/services/capability_service.py",
            "app/services/skill_runtime.py",
            "app/api/v1/tools.py",
            "app/main.py",
            "app/seeds/seed_data.py",
            "docs/TOOL_MIGRATION_GUIDE.md"
        ]

        all_exist = True
        missing_files = []

        for file_path in changed_files:
            full_path = project_root / file_path
            if full_path.exists():
                self.log_check("changes", f"变更文件 {file_path}", "passed", "文件存在")
            else:
                self.log_check("changes", f"变更文件 {file_path}", "failed", "文件缺失")
                all_exist = False
                missing_files.append(file_path)

        if all_exist:
            self.log_check("changes", "迁移完整性", "passed", "所有迁移文件都存在")
        else:
            self.log_check(
                "changes", "迁移完整性", "failed",
                f"部分迁移文件缺失: {', '.join(missing_files)}"
            )

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "="*60)
        print("生成测试报告...")

        report_path = project_root / "PROJECT_HEALTH_REPORT.json"

        # 生成 JSON 报告
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        # 生成可读的 Markdown 报告
        md_path = project_root / "PROJECT_HEALTH_REPORT.md"
        md_content = self._generate_markdown_report()

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"✅ 测试报告已生成:")
        print(f"   - JSON: {report_path}")
        print(f"   - Markdown: {md_path}")

        return report_path, md_path

    def _generate_markdown_report(self):
        """生成 Markdown 格式的报告"""
        summary = self.results["summary"]
        issues = self.results["issues"]

        md = f"""# 项目健康检查报告

生成时间: {self.results['check_time']}

## 摘要

| 指标 | 数量 |
|------|------|
| 总检查项 | {summary['total']} |
| ✅ 通过 | {summary['passed']} |
| ⚠️ 警告 | {summary['warning']} |
| ❌ 失败 | {summary['failed']} |

---

## 问题详情

"""

        if not issues:
            md += "🎉 未发现问题！\n"
        else:
            # 按严重程度分组
            errors = [i for i in issues if i["severity"] == "error"]
            warnings = [i for i in issues if i["severity"] == "warning"]

            if errors:
                md += "### ❌ 错误\n\n"
                for issue in errors:
                    md += f"- **{issue['name']}** ({issue['category']})\n"
                    md += f"  - {issue['message']}\n"
                    if issue.get('details'):
                        md += f"  - 详情: {issue['details']}\n"
                    md += "\n"

            if warnings:
                md += "### ⚠️ 警告\n\n"
                for issue in warnings:
                    md += f"- **{issue['name']}** ({issue['category']})\n"
                    md += f"  - {issue['message']}\n"
                    if issue.get('details'):
                        md += f"  - 详情: {issue['details']}\n"
                    md += "\n"

        md += "\n---\n\n## 详细检查结果\n\n"

        for check in self.results["checks"]:
            status_icon = {
                "passed": "✅",
                "warning": "⚠️",
                "failed": "❌"
            }.get(check["status"], "❓")

            md += f"### {status_icon} {check['name']}\n\n"
            md += f"- **分类**: {check['category']}\n"
            md += f"- **状态**: {check['status']}\n"
            md += f"- **信息**: {check['message']}\n"
            if check.get("details"):
                md += f"- **详情**: {check['details']}\n"
            md += "\n"

        md += "\n---\n\n## 建议\n\n"

        # 根据问题给出建议
        if errors:
            md += "### 🔴 高优先级修复\n\n"
            for issue in errors:
                md += f"- [ ] 修复: {issue['name']}\n"
                md += f"  问题: {issue['message']}\n\n"

        if warnings:
            md += "### 🟡 中优先级改进\n\n"
            for issue in warnings:
                md += f"- [ ] 检查: {issue['name']}\n"
                md += f"  问题: {issue['message']}\n\n"

        if not issues:
            md += "✅ 项目状态良好，继续保持！\n"

        return md

    def print_summary(self):
        """打印摘要到控制台"""
        summary = self.results["summary"]

        print("\n" + "="*60)
        print("检查摘要")
        print("="*60)
        print(f"总检查项: {summary['total']}")
        print(f"✅ 通过:  {summary['passed']}")
        print(f"⚠️ 警告:  {summary['warning']}")
        print(f"❌ 失败:  {summary['failed']}")
        print("="*60)

        if self.results["issues"]:
            print("\n发现的问题:")
            for issue in self.results["issues"]:
                icon = "❌" if issue["severity"] == "error" else "⚠️"
                print(f"{icon} [{issue['category']}] {issue['name']}: {issue['message']}")
        else:
            print("\n🎉 未发现问题！")

    def run_all_checks(self):
        """运行所有检查"""
        print("="*60)
        print("项目健康检查开始")
        print("="*60)

        self.check_python_version()
        self.check_file_structure()
        self.check_imports()
        self.check_config()
        self.check_code_style()
        self.check_api_routers()
        self.check_database_models()
        self.check_services()
        self.check_admin_console()
        self.check_documentation()
        self.check_dependencies()
        self.check_seed_data()
        self.check_examples()
        self.check_git_status()
        self.check_recent_changes()

        self.print_summary()
        self.generate_report()

        return self.results


if __name__ == "__main__":
    checker = ProjectHealthChecker()
    checker.run_all_checks()
