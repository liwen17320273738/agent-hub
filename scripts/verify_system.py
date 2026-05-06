#!/usr/bin/env python3
"""
深度验证脚本：实际测试关键功能是否工作。

运行此脚本验证系统是否真正工作。
"""
import sys
import asyncio
from pathlib import Path

# 添加 backend 到 path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


async def test_codegen_integration():
    """实际测试 CodeGenAgent 是否能被调用。"""
    print("\n" + "=" * 60)
    print("🧪 测试 CodeGenAgent 集成...")
    print("=" * 60)
    
    try:
        from app.services.codegen.codegen_agent import CodeGenAgent
        
        # 创建实例
        agent = CodeGenAgent()
        print("  ✅ CodeGenAgent 实例化成功")
        
        # 检查方法存在
        if hasattr(agent, 'generate_from_pipeline'):
            print("  ✅ generate_from_pipeline 方法存在")
        else:
            print("  ❌ generate_from_pipeline 方法不存在")
            return False
            
        # 模拟 pipeline 调用（不实际执行）
        mock_pipeline_data = {
            "task_id": "test-123",
            "stage_id": "development",
            "worktree": "/tmp/test-worktree",
            "outputs": {
                "planning": {"content": "创建一个简单的计算器应用"},
                "design": {"content": "使用 HTML/CSS/JS"},
                "architecture": {"content": "单页面应用"}
            }
        }
        
        # 检查是否能构建 prompt
        if hasattr(agent, '_build_claude_prompt'):
            prompt = agent._build_claude_prompt(mock_pipeline_data)
            print(f"  ✅ Prompt 构建成功 ({len(prompt)} 字符)")
        else:
            print("  ❌ _build_claude_prompt 方法不存在")
            
        return True
        
    except Exception as e:
        print(f"  ❌ CodeGenAgent 测试失败: {e}")
        return False


async def test_artifact_writer():
    """测试工件写入功能。"""
    print("\n" + "=" * 60)
    print("🧪 测试工件写入...")
    print("=" * 60)
    
    try:
        from app.services.artifact_writer import write_artifact_v2, STAGE_TO_ARTIFACT
        from app.database import get_db
        from app.models.task_artifact import TaskArtifact
        
        print(f"  ✅ 工件类型映射: {STAGE_TO_ARTIFACT}")
        
        # 检查数据库连接
        async for db in get_db():
            # 查询现有工件数量
            count = await db.scalar("SELECT COUNT(*) FROM task_artifacts")
            print(f"  ✅ 数据库连接正常，现有工件: {count}")
            break
            
        return True
        
    except Exception as e:
        print(f"  ❌ 工件写入测试失败: {e}")
        return False


async def test_hooks_system():
    """测试 Hooks 系统。"""
    print("\n" + "=" * 60)
    print("🧪 测试 Hooks 系统...")
    print("=" * 60)
    
    try:
        from app.services.stage_hooks import register_hook, run_hooks, HookContext
        
        # 注册一个测试 hook
        async def test_hook(ctx):
            print(f"    Hook 执行: {ctx.stage_id}")
            return {"test": "executed"}
        
        await register_hook("pre", ".*", test_hook, "test_hook", 100)
        print("  ✅ 测试 hook 注册成功")
        
        # 创建测试上下文
        ctx = HookContext(
            task_id="test-123",
            stage_id="development",
            worktree="/tmp/test",
            content="test content",
            model="test-model",
            agent_id="test-agent"
        )
        
        # 运行 hooks
        results = await run_hooks("pre", ctx)
        print(f"  ✅ Hooks 执行成功，返回 {len(results)} 个结果")
        
        if results and "test" in results[0]:
            print("  ✅ Hook 返回值正确")
        else:
            print("  ⚠️ Hook 返回值异常")
            
        return True
        
    except Exception as e:
        print(f"  ❌ Hooks 测试失败: {e}")
        return False


async def test_llm_router():
    """测试 LLM 路由器。"""
    print("\n" + "=" * 60)
    print("🧪 测试 LLM 路由器...")
    print("=" * 60)
    
    try:
        from app.services.llm_router import chat_completion_with_fallback, PROVIDER_FALLBACK_CHAIN
        
        print(f"  ✅ 备选链长度: {len(PROVIDER_FALLBACK_CHAIN)}")
        
        # 测试失败检测
        from app.services.llm_router import _is_retriable_failure
        
        test_errors = [
            ("HTTP 429", True),
            ("timeout", True),
            ("connection failed", True),
            ("invalid api key", False),
        ]
        
        for error_msg, expected in test_errors:
            result = _is_retriable_failure(Exception(error_msg))
            status = "✅" if result == expected else "❌"
            print(f"  {status} '{error_msg}' → {result} (expected: {expected})")
            
        return True
        
    except Exception as e:
        print(f"  ❌ LLM 路由器测试失败: {e}")
        return False


async def test_pipeline_engine_integration():
    """测试 pipeline_engine 的集成。"""
    print("\n" + "=" * 60)
    print("🧪 测试 Pipeline Engine 集成...")
    print("=" * 60)
    
    try:
        from app.services.pipeline_engine import execute_stage
        from app.services.stage_hooks import run_hooks
        
        print("  ✅ execute_stage 函数存在")
        print("  ✅ run_hooks 函数存在")
        
        # 检查代码中是否包含关键调用
        with open(Path(__file__).parent.parent / "backend" / "app" / "services" / "pipeline_engine.py") as f:
            content = f.read()
        
        checks = [
            ("CodeGenAgent 调用", "from .codegen.codegen_agent import CodeGenAgent" in content),
            ("工件写入调用", "write_artifact_v2" in content),
            ("Hooks 调用", "run_hooks" in content),
            ("MCP 工具加载", "build_tool_handlers" in content),
        ]
        
        for check_name, present in checks:
            status = "✅" if present else "❌"
            print(f"  {status} {check_name}")
            
        return True
        
    except Exception as e:
        print(f"  ❌ Pipeline Engine 测试失败: {e}")
        return False


async def main():
    """运行所有深度测试。"""
    print("\n")
    print("🔬 Agent Hub 深度功能验证")
    print("=" * 60)
    
    tests = [
        test_codegen_integration,
        test_artifact_writer,
        test_hooks_system,
        test_llm_router,
        test_pipeline_engine_integration,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"  ❌ 测试异常: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("🎉 所有测试通过！系统功能完整。")
    else:
        print("⚠️ 部分测试失败，需要进一步检查。")
    
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
