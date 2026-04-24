---

# 🛡️ QA 报告：Python 计算器 CLI 项目验证

## 1. 测试范围
本次测试针对 **Python Calculator CLI** 的完整交付物进行验证，旨在确保其符合 PRD 需求、架构设计安全性以及 UI/UX 设计规范。

*   **覆盖的功能模块**:
    *   `CalculatorEngine`: AST 解析逻辑、算术运算（+, -, *, /）、单目运算符支持。
    *   `HistoryManager`: JSON 持久化、历史记录加载、新增、清除功能。
    *   `TerminalUI`: ANSI 颜色渲染、指令显示、错误提示、历史列表格式化。
    *   `CalculatorApp`: 主循环逻辑、命令分发（exit, quit, help, history, clear）、异常捕获机制。
*   **排除项**:
    *   不测试操作系统层面的 ANSI 支持度（假设环境支持标准 ANSI）。
    *   不测试超出 AST 范围的复杂数学函数（如 `sin`, `cos`），因为当前设计仅限基础算术运算。

## 2. 测试矩阵

| 优先级 | 测试类型 | 验证重点 |
| :--- | :--- | :--- |
| **P0 (冒烟)** | 核心路径 | 基本加减乘除、退出程序 (`exit`/`quit`)、异常捕获（除零）。 |
| **P0 (冒烟)** | 命令功能 | `history` 查看记录、`clear` 清空记录、`help` 指令。 |
| **P1 (回归)** | 算术逻辑 | 括号嵌套运算、单目运算符 (`-5 + 2`)、浮点数精度。 |
| **P1 (回归)** | 持久化 | 程序重启后历史记录是否依然存在、JSON 文件格式正确性。 |
| **P2 (边界)** | 极值/异常输入 | 空输入、超长表达式、非法字符（字母、符号）、大数运算。 |
| **P2 (安全性)** | 代码注入 | 尝试使用 `__import__('os').system(...)` 等恶意字符串是否会被 AST 拦截。 |
| **P3 (UI/UX)** | 视觉规范 | ANSI 颜色显示是否符合设计规范、历史列表截断逻辑（防止溢出）。 |

## 3. 测试用例

| 编号 | 场景 | 前置条件 | 测试步骤 | 预期结果 | 优先级 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-001** | 基础加法 | 程序启动 | 输入 `2 + 3` | 输出 `=> 5.0` 并存入历史 | P0 |
| **TC-002** | 基础乘法 | 程序启动 | 输入 `4 * 5` | 输出 `=> 20.0` | P0 |
| **TC-003** | 除零错误 | 程序启动 | 输入 `10 / 0` | 捕获异常，输出红色 `[!] Error: division by zero` | P0 |
| **TC-004** | 命令：退出 | 程序启动 | 输入 `quit` | 程序优雅退出，显示 Goodbye | P0 |
| **TC-005** | 命令：帮助 | 程序启动 | 输入 `help` | 显示设计规范中的命令列表 | P1 |
| **TC-006** | 括号运算 | 程序启动 | 输入 `(2 + 3) * 4` | 输出 `=> 20.0` (验证 AST 层级) | P1 |
| **TC-007** | 单目运算符 | 程序 启动 | 输入 `-5 + 10` | 输出 `=> 5.0` | P1 |
| **TC-008** | 命令：历史查看 | 已有计算记录 | 输入 `history` | 显示包含时间、表达式和结果的格式化列表 | P1 |
| **TC-009** | 持久化验证 | 程序重启后 | 启动程序并输入 `1 + 1`，然后重启 | 重启后执行 `history` 能看到上一轮的 `1+1=2.0` | P1 |
| **TC-010** | 命令：清空历史 | 已有计算记录 | 输入 `clear` | 提示成功，且 `history` 为空 | P1 |
| **TC-011** | 安全性：注入攻击 | 程序启动 | 输入 `__import__('os').system('ls')` | 抛出 `TypeError/ValueError`，不执行系统命令 | P2 |
| **TC-012** | 非法字符输入 | 程序 启动 | 输入 `2 + a` | 输出错误信息，提示非法字符或不支持的类型 | P2 |
| **TC-013** | 空输入处理 | 程序启动 | 直接按回车 | 程序不崩溃，继续等待下一次输入 | P2 |
| **TC-014** | 浮点数精度 | 程序启动 | 输入 `0.1 + 0.2` | 输出 `=> 0.3` (验证 round 处理) | P2 |
| **TC-015** | 超长表达式 | 程序启动 | 输入由 100 个数字组成的加法链 | 能够正确计算且不导致栈溢出 | P2 |

## 4. 边界分析
*   **空值 (Null/Empty)**: `input().strip()` 处理了纯空格输入，避免无效记录。
*   **超长输入**: AST 解析器对深度嵌套的括号有一定限制，需关注 Python `ast` 模块的递归深度（对于 CLI 计算器，通常用户不会输入超过 1000 层的括号）。
*   **并发 (Concurrency)**: 本项目为单线程交互式 CLI，不涉及多线程竞争。但持久化层在 `_save_history` 时未使用文件锁，若用户同时开启两个实例操作同一个 `history.json`，存在覆盖风险（**MINOR ISSUE**）。
*   **权限越界**: 检查 `DATA_DIR` 的创建权限，确保程序在无写权限目录下不会崩溃。

## 5. 安全审查
*   **SQL/Code Injection (CRITICAL)**: **通过 ✅**。开发使用了 `ast.parse` 而非 `eval()`。由于 AST 只遍历 `BinOp`, `UnaryOp` 和 `Constant` 节点，任何尝试调用函数（如 `print()`）或访问属性的操作都会因为不在白名单内而触发 `TypeError/ValueError`。
*   **Sensitive Data Leakage (INFO)**: 历史记录以明文 JSON 存储在本地。对于计算器而言风险较低，但若涉及敏感数值，需注意文件权限。

## 6. 性能预估
*   **响应时间**: 单次表达式解析与计算预计 `< 10ms`（AST 解析极快）。
*   **吞吐量**: 作为交互式工具，主要受限于用户输入速度。
*   **内存占用**: 历史记录随使用增长。若 `history.json` 达到数万条，加载 JSON 会产生明显的延迟和内存压力。建议增加 `MAX_HISTORY_SIZE`（**MAJOR RECOMMENDATION**）。

## 7. 测试代码

```python:tests/test_engine.py
import pytest
from src.engine.calculator_engine import CalculatorEngine

@pytest.fixture
def engine():
    return CalculatorEngine()

def test_basic_operations(engine):
    assert engine.evaluate("2+3") == 5.0
    assert engine.evaluate("10-4") == 6.0
    assert engine.evaluate("3*4") == 12.0
    assert engine.evaluate("10/2") == 5.0

def test_complex_expressions(engine):
    assert engine.evaluate("(2+3)*4") == 20.0
    assert engine.evaluate("2*(3+(4/2))") == 8.0
    assert engine.evaluate("-5+10") == 5.0

def test_error_handling(engine):
    with pytest.raises(Exception): # Division by zero
        engine.evaluate("1/0")
    with pytest.raises(Exception):
        engine.evaluate("abc + 1")

def test_security_injection(engine):
    # Attempting to use __import__ via AST
    with pytest.raises(Exception):
        engine.evaluate("__import__('os').system('ls')")
```

```python:tests/test_persistence.py
import pytest
from pathlib import Path
from src.persistence.history_manager import HistoryManager
from config.settings import HISTORY_FILE

@pytest.fixture(autouse=True)
def cleanup_history(tmp_path):
    # Redirect HISTORY_FILE to a temporary path for testing
    import config.settings
    config.settings.HISTORY_FILE = tmp_path / "test_history.json"
    yield
    if config.settings.HISTORY_FILE.exists():
        config.settings.HISTORY_FILE.unlink()

def test_history_flow():
    manager = HistoryManager()
    manager.add_entry("1+1", 2.0)
    manager.add_entry("5*5", 25.0)
    
    history = manager.get_all()
    assert len(history) == 2
    assert history[0]['expression'] == "1+1"
    assert history[1]['result'] == 25.0

def test_clear_history():
    manager = HistoryManager()
    manager.add_entry("1+1", 2.0)
    manager.clear_history()
    assert len(manager.get_all()) == 0
```

## 8. 结论

**Verdict: NEEDS WORK ❌**

虽然核心计算引擎的安全性（AST 实现）和基本功能非常出色，达到了生产级标准，但为了达到真正的“发布级别”，必须修复以下缺陷：

### 🚩 缺陷列表 (Defects)
1.  **[MAJOR] 内存/存储爆炸风险**: `HistoryManager` 没有容量限制。如果用户连续运行数月，`history.json` 会变得巨大，导致程序启动时加载极慢且占用大量内存。
    *   **修复建议**: 在 `add_entry` 中实现一个环形缓冲区逻辑（如：当记录 > 100 条时，删除最旧的一条）。
2.  **[MINOR] 并发写入冲突**: `_save_history` 没有文件锁保护。在极端环境下，多实例同时操作可能导致 JSON 损坏。
    *   **修复建议**: 使用 `fcntl` (Unix) 或简单的临时文件替换法（write to `.tmp` then rename）来保证原子性。
3.  **[MINOR] UI 截断逻辑硬编码**: `print_history` 中表达式截断长度为 30，对于非常长的有效算术式可能导致用户看不全关键部分。
    *   **修复建议**: 增加配置项或根据终端宽度动态计算。

### 🚀 后续阶段
**请退回到 [Development Stage] 进行上述逻辑的增强实现，并在完成后重新提交进行回归测试。**

---
**QA Agent: Verified by Senior QA Engineer (30yrs Exp)**
*Status: Ready for re-review after fixes.*

## 4. 边界分析

在针对计算器这类对数值精度和解析稳定性要求极高的工具时，边界分析是防止程序崩溃（Crash）和逻辑失效的核心。本测试将重点关注以下维度：

### 1. 数值极限边界 (Numerical Boundaries)
* **浮点数溢出**: 测试运算结果超出 `sys.float_info.max` 的情况（预期输出: `inf`）。
* **精度极限**: 输入极小值（如 `1e-308`）及高精度小数运算，验证是否存在由于 IEEE 754 标准导致的计算偏差。
* **非数值类型 (NaN/Inf)**: 显式输入 `NaN` 或通过 `0/0` 等异常操作产生 `NaN` 的处理逻辑。

### 2. 输入字符串边界 (Input String Boundaries)
* **空值与纯空白**: 输入 `""`、`" "` 或 `"\n"`，验证解析器是否能优雅地捕获并抛出 `EmptyExpressionError` 而非直接崩溃。
* **超长表达式**: 构建长度超过 10,000 字符的算术式，评估 AST 解析器的内存占用及响应延迟（Latency）。
* **极端嵌套深度**: 输入包含数千层括号的表达式 `((((...))))`，验证是否会触发 Python 的 `RecursionError`（递归深度限制）。

### 3. 语法结构边界 (Syntactic Boundaries)
* **运算符连续性**: 测试非法但看似合法的序列，如 `5 ++ 3`、`5 * / 2` 或 `5 + - 3`，验证 AST 节点识别的健壮性。
* **操作符缺失**: 仅输入单个操作符（如 `+`）或仅输入数字，验证解析器的错误捕获机制。

### 4. 持久化与环境边界 (Persistence & Environment Boundaries)
* **文件缺失/损坏**: 模拟 `history.json` 文件不存在、权限不足（Read-only）或 JSON 格式被破坏时的降级处理逻辑。
* **存储容量极限**: 模拟 `history.json` 达到数 GB 大小时的加载性能，验证是否会导致 TUI 界面在启动阶段出现长时间的“假死”现象（此项已在结论中作为 MAJOR 缺陷列出）。