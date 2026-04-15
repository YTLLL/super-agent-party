import asyncio
import json
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from py.task_center import get_task_center, TaskStatus
from py.get_setting import load_settings, get_port

class SubAgentExecutor:
    """子智能体执行器 - 完美处理周期与定时任务结束逻辑"""
    
    def __init__(self, workspace_dir: str, settings: Dict):
        self.workspace_dir = workspace_dir
        self.settings = settings
        self.port = get_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.chat_endpoint = f"{self.base_url}/v1/chat/completions"
        self.simple_chat_endpoint = f"{self.base_url}/simple_chat"
    
    async def execute_subtask(
        self,
        task_id: str,
        consensus_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        task_center = await get_task_center(self.workspace_dir)
        task = await task_center.get_task(task_id)
        max_iterations = self.settings.get("CLISettings", {}).get("max_iterations", 100)
        
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        # 标记开始
        await task_center.update_task_progress(task.task_id, 0, status=TaskStatus.RUNNING)
        
        iteration = 0
        conversation_history = []
        assistant_only_history = task.context.get("history", [])
        
        system_prompt = self._build_system_prompt(task, consensus_content)
        conversation_history.append({"role": "system", "content": system_prompt})
        conversation_history.append({"role": "user", "content": f"请执行任务：\n\n{task.description}\n\n完成后整理结果并提交。"})
        
        try:
            async with httpx.AsyncClient(timeout=600.0) as http_client:
                while iteration < max_iterations:
                    iteration += 1
                    current_progress = 10 + int((iteration / max_iterations) * 80)
                    
                    assistant_response = await self._call_llm_stream_only(
                        http_client, conversation_history, 'super-model',
                        task.task_id, task_center, current_progress, assistant_only_history
                    )
                    
                    conversation_history.append({"role": "assistant", "content": assistant_response})
                    
                    latest_task = await task_center.get_task(task_id)
                    # 检查是否通过工具完成
                    if latest_task.status == TaskStatus.COMPLETED:
                        return await self._finalize_task_record(task_id, task_center, latest_task.result, assistant_only_history, iteration)

                    # 更新进度
                    await task_center.update_task_progress(
                        task.task_id, current_progress, 
                        status=TaskStatus.RUNNING,
                        context={"history": assistant_only_history, "current_iteration": iteration}
                    )

                    # 智能检查完成状态
                    is_complete = await self._check_task_completion_smart(task, conversation_history, http_client)
                    if is_complete:
                        final_res = await self._extract_final_result(task, conversation_history, http_client)
                        return await self._finalize_task_record(task_id, task_center, final_res["full"], assistant_only_history, iteration)
                    
                    conversation_history.append({"role": "user", "content": "请继续执行。完成后请明确总结并提交。"})
                
                return {"success": False, "error": "Max iterations reached"}

        except Exception as e:
            await task_center.update_task_progress(task.task_id, 0, status=TaskStatus.FAILED, error=str(e))
            return {"success": False, "error": str(e)}

    async def _finalize_task_record(self, task_id, task_center, result, history, iteration):
        """核心逻辑：决定任务是进入 COMPLETED 还是回到 PENDING"""
        task = await task_center.get_task(task_id)
        t_type = task.context.get("task_type", "once")
        config = task.context.get("trigger_config", {})
        
        # 1. 结果存档
        results_history = task.context.get("results_history", [])
        results_history.append({
            "time": datetime.now().isoformat(),
            "result": result,
            "iteration": iteration
        })
        results_history = results_history[-20:] # 仅保留最近20次

        # 2. 日志截断
        trimmed_history = history[-30:] if len(history) > 30 else history
        
        # 3. 状态判定
        final_status = TaskStatus.COMPLETED
        final_progress = 100
        next_run_at = None
        ran_count = task.context.get("ran_count", 0)

        if t_type == "cycle":
            is_infinite = config.get("isInfiniteLoop", True)
            repeat_num = config.get("repeatNumber", 1)
            
            # 如果是无限循环，或者次数还没跑够
            if is_infinite or ran_count < repeat_num:
                try:
                    h, m, s = map(int, config.get("cycleValue", "01:00:00").split(':'))
                    next_run = datetime.now() + timedelta(hours=h, minutes=m, seconds=s)
                    final_status = TaskStatus.PENDING
                    final_progress = 0
                    next_run_at = next_run.isoformat()
                except: pass
            else:
                print(f"✅ 周期任务 {task_id} 次数已满，结束任务。")

        elif t_type == "time":
            days = config.get("days", [])
            # 如果配置了具体的星期，说明是重复执行的定时任务
            if days and len(days) > 0:
                final_status = TaskStatus.PENDING
                final_progress = 0
            else:
                # 没选星期，说明是一次性定时任务
                final_status = TaskStatus.COMPLETED
                print(f"✅ 定时任务 {task_id} 为单次触发，结束任务。")

        # 4. 更新
        new_ctx = {
            "history": trimmed_history,
            "results_history": results_history,
            "last_run_at": datetime.now().isoformat(),
            "summary": (result[:200] + "...") if result else ""
        }
        if next_run_at:
            new_ctx["next_run_at"] = next_run_at

        await task_center.update_task_progress(
            task_id, 
            final_progress, 
            status=final_status, 
            result=result, 
            context=new_ctx
        )
        return {"success": True, "task_id": task_id, "result": result}

    async def _call_llm_stream_only(self, http_client, messages, model, task_id, task_center, base_progress, display_history) -> str:
        payload = {
            "messages": messages, "model": model, "stream": True, "is_sub_agent": True,
            "disable_tools": ["create_subtask", "query_tasks_tool", "cancel_subtask"]
        }
        full_content, current_text_buffer = "", ""
        try:
            async with http_client.stream("POST", self.chat_endpoint, json=payload) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "): continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]": break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        if delta.get("content"):
                            full_content += delta["content"]
                            current_text_buffer += delta["content"]
                        if delta.get("tool_content") and task_center:
                            if current_text_buffer.strip():
                                display_history.append(current_text_buffer.strip())
                                current_text_buffer = ""
                            tool = delta["tool_content"]
                            if "finish_task" in str(tool.get("title")): continue
                            if tool.get("type") in ["tool_result", "error"]:
                                display_history.append(f"{'✅' if tool['type']=='tool_result' else '❌'} [{tool.get('title')}]\nResult: {str(tool.get('content'))[:200]}")
                                await task_center.update_task_progress(task_id, base_progress, status=TaskStatus.RUNNING, context={"history": display_history})
                    except: continue
        except: pass
        if current_text_buffer.strip(): display_history.append(current_text_buffer.strip())
        return full_content

    def _build_system_prompt(self, task, consensus_content):
        p = f"你是一个专业的任务执行助手。\n【任务】ID: {task.task_id} | 标题: {task.title}"
        if consensus_content: p += f"\n\n【共识规范】\n{consensus_content}"
        return p

    async def _check_task_completion_smart(self, task, conversation_history, http_client):
        msgs = [{"role": "system", "content": "判断任务目标是否已达成？只回YES/NO"}, {"role": "user", "content": f"目标:{task.description}\n历史:{str(conversation_history)[-2000:]}"}]
        try:
            resp = await http_client.post(self.simple_chat_endpoint, json={"messages": msgs, "model": "super-model"})
            return resp.json()["choices"][0]["message"]["content"].strip().upper().startswith("YES")
        except: return False

    async def _extract_final_result(self, task, conversation_history, http_client):
        msgs = [{"role": "system", "content": "请从对话中提取出任务的最终执行产出（报告、代码、结论）。"}, {"role": "user", "content": f"历史:{str(conversation_history)[-4000:]}"}]
        try:
            resp = await http_client.post(self.simple_chat_endpoint, json={"messages": msgs, "model": "super-model"})
            return {"full": resp.json()["choices"][0]["message"]["content"].strip()}
        except: return {"full": "任务执行完成，未提取到明确结果。"}

async def run_subtask_in_background(task_id: str, workspace_dir: str, settings: Dict, consensus_content: Optional[str] = None):
    executor = SubAgentExecutor(workspace_dir, settings)
    await executor.execute_subtask(task_id, consensus_content)