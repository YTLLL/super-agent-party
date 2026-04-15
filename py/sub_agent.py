import asyncio
import json
import httpx
from datetime import datetime
from typing import Dict, List, Optional, Any
from py.task_center import get_task_center, TaskStatus
from py.get_setting import load_settings, get_port

class SubAgentExecutor:
    """子智能体执行器 - 支持单次、定时与周期任务状态维护"""
    
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
        """执行子任务的主循环"""
        task_center = await get_task_center(self.workspace_dir)
        task = await task_center.get_task(task_id)
        max_iterations = self.settings.get("CLISettings", {}).get("max_iterations", 100)
        
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        # 1. 标记任务开始执行
        await task_center.update_task_progress(
            task_id=task_id, 
            progress=0, 
            status=TaskStatus.RUNNING
        )
        
        iteration = 0
        conversation_history = []
        # 获取已有历史，如果是周期任务再次运行，这里会继承之前的最后几条状态
        assistant_only_history = task.context.get("history", [])
        
        # 构建 System Prompt
        system_prompt = self._build_system_prompt(task, consensus_content)
        conversation_history.append({"role": "system", "content": system_prompt})
        
        initial_user_msg = f"请执行以下任务：\n\n{task.description}\n\n要求：完成后请整理出最终结果。"
        conversation_history.append({"role": "user", "content": initial_user_msg})
        
        try:
            async with httpx.AsyncClient(timeout=600.0) as http_client:
                while iteration < max_iterations:
                    iteration += 1
                    # 计算进度条 (10% - 90%)
                    current_progress = 10 + int((iteration / max_iterations) * 80)
                    print(f"[SubAgent] Task {task_id} - Iteration {iteration}")
                    
                    # 2. 调用 LLM (流式接收)
                    assistant_response = await self._call_llm_stream_only(
                        http_client=http_client,
                        messages=conversation_history,
                        model='super-model',
                        task_id=task_id,
                        task_center=task_center,
                        base_progress=current_progress,
                        display_history=assistant_only_history
                    )
                    
                    conversation_history.append({
                        "role": "assistant",
                        "content": assistant_response
                    })
                    
                    # 3. 检查任务是否通过工具(finish_task)标记为完成
                    latest_task = await task_center.get_task(task_id)
                    if latest_task.status == TaskStatus.COMPLETED:
                        return await self._finalize_task_record(task_id, task_center, latest_task.result, assistant_only_history, iteration)

                    # 4. 更新运行中状态和上下文
                    await task_center.update_task_progress(
                        task_id=task_id,
                        progress=current_progress,
                        status=TaskStatus.RUNNING,
                        context={"history": assistant_only_history, "current_iteration": iteration}
                    )

                    # 5. 隐式完成智能检查 (针对没调工具但在对话中确认完成的情况)
                    is_complete = await self._check_task_completion_smart(
                        task=task,
                        conversation_history=conversation_history,
                        http_client=http_client
                    )
                    
                    if is_complete:
                        print(f"⚡ [SubAgent] Implicit completion detected for {task_id}")
                        final_res = await self._extract_final_result(task, conversation_history, http_client)
                        return await self._finalize_task_record(task_id, task_center, final_res["full"], assistant_only_history, iteration)
                    
                    # 若未完成，继续提示
                    conversation_history.append({
                        "role": "user",
                        "content": "请继续执行任务。如果已完成所有步骤，请通过 finish_task 工具提交结果，或总结给出最终产出。"
                    })
                
                # 超出迭代次数限制
                error_msg = "Max iterations reached"
                await task_center.update_task_progress(task_id=task_id, status=TaskStatus.FAILED, error=error_msg)
                return {"success": False, "error": error_msg}

        except Exception as e:
            print(f"❌ [SubAgent] Error executing {task_id}: {str(e)}")
            await task_center.update_task_progress(task_id=task_id, status=TaskStatus.FAILED, error=str(e))
            return {"success": False, "error": str(e)}

    async def _finalize_task_record(self, task_id, task_center, result, history, iteration):
        """
        统一处理任务完成时的记录更新。
        特别针对周期/定时任务：清理历史记录，防止 JSON 膨胀。
        """
        print(f"🚀 [SubAgent] Task {task_id} finishing. Cleaning up history.")
        
        # 关键优化：如果是周期/定时任务，只保留最近 10 条执行动态，防止 context 字段超出数据库/文件限制
        trimmed_history = history[-10:] if len(history) > 10 else history
        
        await task_center.update_task_progress(
            task_id=task_id,
            progress=100,
            status=TaskStatus.COMPLETED,
            result=result,
            context={
                "history": trimmed_history,
                "last_run_at": datetime.now().isoformat(),
                "summary": (result[:200] + "...") if result else "No result"
            }
        )
        return {
            "success": True,
            "task_id": task_id,
            "result": result,
            "iterations": iteration
        }

    async def _call_llm_stream_only(
        self, 
        http_client: httpx.AsyncClient, 
        messages: List[Dict], 
        model: str,
        task_id: str = None,
        task_center: Any = None,
        base_progress: int = 0,
        display_history: List[str] = None
    ) -> str:
        payload = {
            "messages": messages,
            "model": model,
            "stream": True, 
            "temperature": 0.5,
            "max_tokens": self.settings.get('max_tokens', 4000),
            "is_sub_agent": True,
            "disable_tools": ["create_subtask", "query_tasks_tool", "cancel_subtask"] 
        }

        full_content = ""
        current_text_buffer = ""
        tool_step_counter = 0

        try:
            async with http_client.stream("POST", self.chat_endpoint, json=payload, headers={"Content-Type": "application/json"}) as response:
                if response.status_code != 200:
                    raise Exception(f"API Error {response.status_code}")

                async for line in response.aiter_lines():
                    if not line.strip(): continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]": break
                        try:
                            chunk = json.loads(data_str)
                            if "error" in chunk or not chunk.get("choices"): continue
                            
                            delta = chunk["choices"][0].get("delta", {})

                            content = delta.get("content")
                            if content:
                                full_content += content
                                current_text_buffer += content

                            tool_data = delta.get("tool_content")
                            if tool_data and task_center and task_id:
                                if current_text_buffer.strip():
                                    display_history.append(current_text_buffer.strip())
                                    current_text_buffer = ""
                                
                                tool_type = tool_data.get("type")
                                tool_title = str(tool_data.get("title", "Unknown")).strip()
                                
                                # finish_task 逻辑：状态已在 task_tools.py 更改，此处仅记录历史
                                if "finish_task" in tool_title:
                                    res_content = tool_data.get("content", "")
                                    display_history.append(f"✅ [{tool_title}]\n结果已提交。")
                                    continue 

                                # 普通工具更新
                                if tool_type in ["tool_result", "error"]:
                                    tool_step_counter += 1
                                    res_content = tool_data.get("content", "")
                                    icon = "✅" if tool_type == "tool_result" else "❌"
                                    
                                    short_res = str(res_content)[:300] + "..." if len(str(res_content)) > 300 else str(res_content)
                                    display_history.append(f"{icon} [{tool_title}]\nResult: {short_res}")
                                    
                                    micro_progress = min(base_progress + (tool_step_counter * 2), 99)
                                    
                                    await task_center.update_task_progress(
                                        task_id=task_id,
                                        progress=micro_progress,
                                        status=TaskStatus.RUNNING,
                                        context={"history": display_history}
                                    )
                        except: continue

        except Exception as e:
             raise Exception(f"Stream Failed: {str(e)}")

        if current_text_buffer.strip() and display_history is not None:
            display_history.append(current_text_buffer.strip())

        return full_content if full_content else "(任务执行中...)"
    
    def _build_system_prompt(self, task, consensus_content: Optional[str]) -> str:
        prompt = f"你是一个专业的任务执行助手。\n【任务信息】ID: {task.task_id} | 标题: {task.title}\n【执行要求】专注完成任务，使用可用工具，完成后明确调用 finish_task 工具提交结果。"
        if consensus_content: 
            prompt += f"\n\n【工作区共识规范】\n{consensus_content}\n"
        return prompt
    
    async def _check_task_completion_smart(self, task, conversation_history, http_client) -> bool:
        recent = self._get_recent_conversation(conversation_history)
        msgs = [{"role": "system", "content": "判断任务是否完成，只回复YES或NO。"},
                {"role": "user", "content": f"任务目标：{task.description}\n最近进展：{recent}\n请问任务目标是否已达成？"}]
        try:
            resp = await http_client.post(self.simple_chat_endpoint, json={"messages": msgs, "model": "super-model", "stream": False})
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip().upper().startswith("YES")
        except: pass
        return False
    
    async def _extract_final_result(self, task, conversation_history, http_client) -> Dict[str, str]:
        history_str = ""
        for msg in conversation_history:
            if msg["role"] in ["assistant", "user"]:
                content = msg["content"] if msg["content"] else "[执行了工具操作]"
                history_str += f"{msg['role']}: {content}\n"
        msgs = [{"role": "system", "content": "请从对话历史中提取出任务的最终执行结果。"},
                {"role": "user", "content": f"任务目标：{task.description}\n\n历史记录：\n{history_str[-6000:]}\n\n请整理最终产出："}]
        full_res = "未提取到结果"
        try:
            resp = await http_client.post(self.simple_chat_endpoint, json={"messages": msgs, "model": "super-model", "stream": False})
            if resp.status_code == 200: 
                full_res = resp.json()["choices"][0]["message"]["content"].strip()
        except: 
            full_res = "\n".join([m["content"] for m in conversation_history if m["role"] == "assistant" and m["content"]][-2:])
        return {"full": full_res, "summary": full_res[:200] + "..."}

    def _get_recent_conversation(self, conversation_history: List[Dict]) -> str:
        texts = []
        for msg in reversed(conversation_history[-5:]):
            content = str(msg.get('content'))[:200] if msg.get('content') else "[Tool Call]"
            texts.append(f"{msg['role']}: {content}")
        return "\n".join(texts)

async def run_subtask_in_background(task_id: str, workspace_dir: str, settings: Dict, consensus_content: Optional[str] = None):
    executor = SubAgentExecutor(workspace_dir, settings)
    await executor.execute_subtask(task_id, consensus_content)