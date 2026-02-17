# py/task_tools.py
"""主智能体使用的任务管理工具"""
import asyncio
from typing import Optional
from py.task_center import get_task_center, TaskStatus
from py.sub_agent import run_subtask_in_background

create_subtask_tool = {
    "type": "function",
    "function": {
        "name": "create_subtask",
        "description": """创建一个子任务并在后台异步执行。

⚠️ 使用场景：
- 将大任务拆分成多个独立的小任务并行执行
- 需要执行耗时较长的任务（如批量处理、深度研究）
- 需要委托给专门的子智能体处理特定领域问题

✅ 特点：
- 异步执行，不阻塞主对话
- 自动保存进度，重启后可恢复
- 可通过 query_task_progress 查看实时状态

📝 返回值：子任务ID，用于后续跟踪进度

⚠️ 注意：
- 每个子任务都是独立的对话上下文
- 子任务无法访问主对话的历史记录（除非在description中明确说明）
- 建议在description中提供完整的背景信息和明确的完成标准
- 如果不是用户要求，子任务创建后请不要主动查询其进度，客户端UI会自动将当前进度和结果显示给用户""",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "子任务的简短标题（建议不超过50字）"
                },
                "description": {
                    "type": "string",
                    "description": """子任务的详细描述，必须包含：
1. 任务目标：期望达成的具体结果
2. 背景信息：必要的上下文和前置知识
3. 完成标准：如何判断任务已完成
4. 约束条件：需要遵守的规则或限制

示例：
\"\"\"
任务目标：分析 data.csv 文件中的销售数据，生成月度报告

背景信息：
- 文件位于 ./reports/data.csv
- 包含列：date, product, quantity, revenue
- 需要关注 2024年1月-3月的数据

完成标准：
- 生成包含趋势图的 Markdown 报告
- 计算出每月总销售额和增长率
- 识别销售额 Top 3 产品

约束条件：
- 使用 Python pandas 进行数据处理
- 图表使用 matplotlib 生成
- 报告保存为 monthly_report.md
\"\"\""""
                },
                "agent_type": {
                    "type": "string",
                    "description": "使用的智能体类型（当前固定为 'default'，未来可扩展）",
                    "default": "default"
                }
            },
            "required": ["title", "description"]
        }
    }
}

query_tasks_tool = {
    "type": "function",
    "function": {
        "name": "query_task_progress",
        "description": """查询任务中心的所有任务进度和状态。

💡 使用建议：
1. 默认情况下，此工具只返回任务的【摘要】以节省上下文。
2. 如果某个任务显示 'completed'，但你想查看它的【详细报告/完整结果】，请将 verbose 参数设为 true。""",
        "parameters": {
            "type": "object",
            "properties": {
                "parent_task_id": {
                    "type": "string",
                    "description": "可选：指定父任务ID，只查询其子任务"
                },
                "status": {
                    "type": "string",
                    "description": "可选：过滤特定状态的任务",
                    "enum": ["pending", "running", "completed", "failed", "cancelled"]
                },
                "verbose": {
                    "type": "boolean",
                    "description": "是否显示任务的完整结果。查看已完成任务的具体内容时非常有用。",
                    "default": False
                }
            }
        }
    }
}

cancel_subtask_tool = {
    "type": "function",
    "function": {
        "name": "cancel_subtask",
        "description": """取消一个正在执行或待执行的子任务。

⚠️ 注意：
- 只能取消 pending 或 running 状态的任务
- 已完成(completed)或已失败(failed)的任务无法取消
- 取消操作是异步的，可能需要几秒钟生效

💡 使用场景：
- 发现任务定义有误，需要重新创建
- 任务执行时间过长，需要中止
- 用户改变需求，不再需要该任务的结果""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要取消的任务ID"
                }
            },
            "required": ["task_id"]
        }
    }
}

# 工具实现函数

async def create_subtask(
    title: str,
    description: str,
    agent_type: str = "default",
    workspace_dir: str = None,
    settings: dict = None,
    parent_task_id: Optional[str] = None,
    consensus_content: Optional[str] = None
) -> str:
    """创建并启动子任务（不需要 base_url）"""
    task_center = await get_task_center(workspace_dir)
    
    # 创建任务
    task = await task_center.create_task(
        title=title,
        description=description,
        parent_task_id=parent_task_id,
        agent_type=agent_type
    )
    
    # 在后台异步执行（SubAgentExecutor 内部会自动获取端口）
    asyncio.create_task(
        run_subtask_in_background(
            task_id=task.task_id,
            workspace_dir=workspace_dir,
            settings=settings, 
            consensus_content=consensus_content
        )
    )
    
    return f"✅ 子任务已创建并开始执行\n\n任务ID: {task.task_id}\n标题: {task.title}\n请不要主动查询任务进度，客户端UI会自动将当前进度和结果显示给用户"

async def query_task_progress(
    workspace_dir: str,
    parent_task_id: Optional[str] = None,
    status: Optional[str] = None,
    verbose: bool = False
) -> str:
    """查询任务进度 - 主智能体视角的全量查看版"""
    from py.task_center import get_task_center, TaskStatus
    
    task_center = await get_task_center(workspace_dir)
    status_enum = TaskStatus(status) if status else None
    
    tasks = await task_center.list_tasks(
        parent_task_id=parent_task_id,
        status=status_enum
    )
    
    if not tasks:
        return "📋 任务中心当前没有相关任务。"
    
    result_lines = [f"📋 任务中心状态 (共 {len(tasks)} 个任务)"]
    if verbose:
        result_lines.append("📢 [详情模式] 已开启：正在提取完整过程记录与最终产出...")
    result_lines.append("-" * 30)
    
    for task in tasks:
        icon = "✅" if task.status == TaskStatus.COMPLETED else "🔄" if task.status == TaskStatus.RUNNING else "⏳"
        result_lines.append(f"{icon} [{task.task_id}] {task.title}")
        result_lines.append(f"   状态: {task.status.value.upper()} | 进度: {task.progress}%")
        
        # 获取 context 中的历史记录
        history = task.context.get("history", [])
        
        # --- 情况 1：任务正在运行 ---
        if task.status == TaskStatus.RUNNING:
            if history:
                # 即使不是 verbose，也给主智能体看最后一步，让它放心
                result_lines.append(f"   执行动态: {history[-1][:100]}...")
            if verbose and history:
                # 全量模式下，列出已完成的所有中间步骤
                result_lines.append("   📜 已完成步骤:")
                for i, step in enumerate(history, 1):
                    result_lines.append(f"     {i}. {step[:200]}...")

        # --- 情况 2：任务已完成 ---
        elif task.status == TaskStatus.COMPLETED:
            if verbose:
                # 1. 展示中间思考/执行过程 (History)
                if history:
                    result_lines.append("   📜 执行过程回溯:")
                    for i, step in enumerate(history, 1):
                        # 缩进显示每一轮助手干了什么
                        step_fmt = step.replace('\n', '\n        ')
                        result_lines.append(f"     第 {i} 阶段产出:\n        {step_fmt}")
                        result_lines.append("        " + "-"*10)
                
                # 2. 展示最终核心结果 (Result)
                result_lines.append(f"   🎯 最终完整产出:\n{task.result}\n")
            else:
                # 非全量模式下只给摘要
                summary = task.context.get('summary') or (task.result[:150] + "..." if task.result else "无结果内容")
                result_lines.append(f"   📝 结果摘要: {summary}")
                result_lines.append(f"   💡 (提示: 使用 verbose=true 可查看包含执行过程的完整报告)")

        elif task.status == TaskStatus.FAILED:
            result_lines.append(f"   ❌ 错误信息: {task.error}")

        result_lines.append("") # 任务间的空行

    return "\n".join(result_lines)

async def cancel_subtask(workspace_dir: str, task_id: str) -> str:
    """取消子任务"""
    task_center = await get_task_center(workspace_dir)
    
    success = await task_center.cancel_task(task_id)
    
    if success:
        return f"✅ 任务 {task_id} 已取消"
    else:
        return f"❌ 取消任务 {task_id} 失败（任务不存在或已完成）"