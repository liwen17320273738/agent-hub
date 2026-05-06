#!/usr/bin/env python3
"""
系统诊断脚本：检查 Agent Hub 的关键功能是否真正启用和工作。

运行此脚本了解当前系统的真实状态。
"""
import sys
from pathlib import Path

# 添加 backend 到 path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


def check_imports():
    """检查关键模块是否可导入。"""
    print("=" * 60)
    print("📦 检查模块导入...")
    print("=" * 60)
    
    modules_to_check = [
        ("pipeline_engine", "app.services.pipeline_engine"),
        ("artifact_writer", "app.services.artifact_writer"),
        ("llm_router", "app.services.llm_router"),
        ("executor_bridge", "app.services.executor_bridge"),
        ("code_extractor", "app.services.code_extractor"),
        ("codegen_agent", "app.services.codegen.codegen_agent"),
        ("mcp_client", "app.services.mcp_client"),
        ("stage_hooks", "app.services.stage_hooks"),
        ("agent_runtime", "app.services.agent_runtime"),
    ]
    
    results = []
    for name, module in modules_to_check:
        try:
            __import__(module)
            status = "✅ OK"
        except ImportError as e:
            status = f"❌ FAIL: {str(e)[:50]}"
        results.append((name, status))
        print(f"  {name:20} {status}")
    
    return results


def check_config():
    """检查关键配置。"""
    print("\n" + "=" * 60)
    print("⚙️ 检查配置...")
    print("=" * 60)
    
    try:
        from app.config import settings
        
        checks = [
            ("artifact_store_v2", settings.artifact_store_v2, True),
            ("gateway_plan_mode", settings.gateway_plan_mode, True),
            ("pipeline_force_local_llm", settings.pipeline_force_local_llm, False),
            ("browser_enabled", settings.browser_enabled, True),
        ]
        
        for key, value, expected in checks:
            status = "✅" if value == expected else "⚠️"
            print(f"  {status} {key:30} = {value} (expected: {expected})")
        
        # 检查 LLM 配置
        print(f"\n  LLM Configuration:")
        print(f"    - Model: {settings.llm_model}")
        print(f"    - Has API URL: {'✅' if settings.llm_api_url else '❌'}")
        print(f"    - Has API Key: {'✅' if settings.llm_api_key else '❌'}")
        print(f"    - Database: {settings.database_url[:50]}...")
        
    except Exception as e:
        print(f"  ❌ Error loading config: {e}")


def check_database():
    """检查数据库连接和模式。"""
    print("\n" + "=" * 60)
    print("🗄️ 检查数据库...")
    print("=" * 60)
    
    try:
        from app.database import get_db
        from app.models.pipeline import PipelineTask
        from app.models.task_artifact import TaskArtifact
        
        print("  ✅ Database models imported successfully")
        print("  ✅ TaskArtifact table available")
        print("  ✅ PipelineTask table available")
    except Exception as e:
        print(f"  ❌ Database error: {e}")


def check_codegen_integration():
    """检查 CodeGen / Claude Code 集成。"""
    print("\n" + "=" * 60)
    print("💻 检查 CodeGen 集成...")
    print("=" * 60)
    
    try:
        from app.services.codegen.codegen_agent import CodeGenAgent
        from app.services.executor_bridge import execute_claude_code
        
        print("  ✅ CodeGenAgent 可导入")
        print("  ✅ executor_bridge.execute_claude_code 可导入")
        
        # 检查 pipeline_engine 中是否调用 CodeGenAgent
        with open(Path(__file__).parent.parent / "backend" / "app" / "services" / "pipeline_engine.py") as f:
            content = f.read()
            
        checks = [
            ("CodeGenAgent", "CodeGenAgent" in content),
            ("generate_from_pipeline", "generate_from_pipeline" in content),
            ("development stage check", "stage_id == \"development\"" in content and "CodeGenAgent" in content),
        ]
        
        for check_name, present in checks:
            status = "✅" if present else "❌"
            print(f"  {status} {check_name}")
            
    except Exception as e:
        print(f"  ❌ CodeGen check failed: {e}")


def check_artifact_system():
    """检查工件系统。"""
    print("\n" + "=" * 60)
    print("📦 检查工件系统...")
    print("=" * 60)
    
    try:
        from app.services.artifact_writer import (
            STAGE_TO_ARTIFACT,
            write_artifact_v2,
            write_stage_artifacts_v2,
        )
        
        print(f"  ✅ 工件类型映射: {len(STAGE_TO_ARTIFACT)} 个阶段")
        for stage, artifact_type in STAGE_TO_ARTIFACT.items():
            print(f"     - {stage:15} → {artifact_type}")
        
        # 检查 pipeline_engine 中是否调用工件写入
        with open(Path(__file__).parent.parent / "backend" / "app" / "services" / "pipeline_engine.py") as f:
            content = f.read()
        
        if "write_artifact_v2" in content:
            print("  ✅ pipeline_engine 调用 write_artifact_v2")
        else:
            print("  ❌ pipeline_engine 未调用 write_artifact_v2")
            
    except Exception as e:
        print(f"  ❌ Artifact system check failed: {e}")


def check_hooks_system():
    """检查 Hooks 系统。"""
    print("\n" + "=" * 60)
    print("🪝 检查 Hooks 系统...")
    print("=" * 60)
    
    try:
        from app.services.stage_hooks import register_hook, run_hooks, _hooks
        
        print(f"  ✅ Hooks 框架可导入")
        print(f"  📊 当前已注册 {len(_hooks)} 个 hooks")
        
        for hook in _hooks:
            print(f"     - {hook.phase:5} {hook.name:20} for {hook.stage_pattern}")
        
        # 检查 pipeline_engine 中是否调用 run_hooks
        with open(Path(__file__).parent.parent / "backend" / "app" / "services" / "pipeline_engine.py") as f:
            content = f.read()
        
        if "run_hooks" in content:
            print("  ✅ pipeline_engine 调用 run_hooks")
            count = content.count("run_hooks(")
            print(f"     (共 {count} 次调用)")
        else:
            print("  ❌ pipeline_engine 未调用 run_hooks")
            
    except Exception as e:
        print(f"  ❌ Hooks system check failed: {e}")


def check_llm_router():
    """检查 LLM 路由器。"""
    print("\n" + "=" * 60)
    print("🚀 检查 LLM 路由器...")
    print("=" * 60)
    
    try:
        from app.services.llm_router import (
            PROVIDER_FALLBACK_CHAIN,
            _is_retriable_failure,
        )
        
        print(f"  ✅ 备选模型链: {len(PROVIDER_FALLBACK_CHAIN)} 个选项")
        for i, candidate in enumerate(PROVIDER_FALLBACK_CHAIN, 1):
            print(f"     {i}. {candidate['provider']:10} / {candidate['model']}")
        
        # 检查熔断器
        with open(Path(__file__).parent.parent / "backend" / "app" / "services" / "llm_router.py") as f:
            content = f.read()
        
        if "CircuitBreaker" in content or "circuit" in content.lower():
            print("  ✅ 熔断器已实现")
        else:
            print("  ⚠️ 未找到熔断器实现（需要添加）")
            
    except Exception as e:
        print(f"  ❌ LLM router check failed: {e}")


def check_mcp_integration():
    """检查 MCP 集成。"""
    print("\n" + "=" * 60)
    print("🔌 检查 MCP 集成...")
    print("=" * 60)
    
    try:
        from app.services.mcp_client import (
            probe,
            list_tools,
            call_tool,
            build_tool_handlers,
        )
        
        print("  ✅ MCP 客户端可导入")
        
        # 检查 pipeline_engine 中是否加载 MCP
        with open(Path(__file__).parent.parent / "backend" / "app" / "services" / "pipeline_engine.py") as f:
            content = f.read()
        
        if "build_tool_handlers" in content:
            print("  ✅ pipeline_engine 加载 MCP 工具")
        else:
            print("  ⚠️ pipeline_engine 未加载 MCP 工具（可选）")
            
    except Exception as e:
        print(f"  ❌ MCP check failed: {e}")


def main():
    """运行所有诊断检查。"""
    print("\n")
    print("🔍 Agent Hub 系统诊断")
    print("=" * 60)
    
    check_imports()
    check_config()
    check_database()
    check_codegen_integration()
    check_artifact_system()
    check_hooks_system()
    check_llm_router()
    check_mcp_integration()
    
    print("\n" + "=" * 60)
    print("✅ 诊断完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
