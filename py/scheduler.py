import asyncio
import os
from datetime import datetime, timedelta
from py.task_center import get_task_center, TaskStatus
from py.sub_agent import run_subtask_in_background

class AgentScheduler:
    def __init__(self, settings_ref: dict):
        # 引用全局 settings，确保 cc_path 修改后能实时感知
        self.settings = settings_ref

    async def start_loop(self):
        print("⏰ [调度中心] 启动成功，监控已就绪...")
        while True:
            try:
                workspace_dir = self.settings.get("CLISettings", {}).get("cc_path")
                if workspace_dir and os.path.exists(workspace_dir):
                    await self._scan_and_trigger(workspace_dir)
            except Exception as e:
                print(f"❌ [调度中心] 轮询异常: {e}")
            
            await asyncio.sleep(30) # 30秒检查一次，适合分钟级的定时

    async def _scan_and_trigger(self, workspace_dir):
        task_center = await get_task_center(workspace_dir)
        tasks = await task_center.list_tasks()
        now = datetime.now()
        current_time_hm = now.strftime("%H:%M") # 用于定时触发匹配
        current_weekday = now.isoweekday() # 1-7 (周一到周日)
        # 注意：前端 Sunday 是 0，这里做个转换
        ui_weekday = 0 if current_weekday == 7 else current_weekday

        for task in tasks:
            # 只有处于 PENDING (待处理) 或 COMPLETED (周期任务复用) 状态的任务才参与调度
            # 我们不触发已经在 RUNNING 的任务
            if task.status == TaskStatus.RUNNING:
                continue

            t_type = task.context.get("task_type")
            config = task.context.get("trigger_config", {})

            # --- 1. 定时模式 (time) ---
            if t_type == "time":
                time_val = config.get("timeValue", "")[:5] # 取 HH:mm
                days = config.get("days", []) # [1, 2, 3...]
                
                # 如果 星期匹配 且 时间匹配
                if ui_weekday in days and current_time_hm == time_val:
                    # 避免在同一分钟内重复触发
                    if task.context.get("last_trigger_minute") != current_time_hm:
                        await self._execute(task, workspace_dir, {"last_trigger_minute": current_time_hm})

            # --- 2. 周期模式 (cycle) ---
            elif t_type == "cycle":
                next_run_str = task.context.get("next_run_at")
                
                # 如果还没有设置下次运行时间，则初始化它
                if not next_run_str:
                    await self._update_next_cycle_time(task, workspace_dir)
                    continue

                next_run_at = datetime.fromisoformat(next_run_str)
                if now >= next_run_at:
                    # 检查运行次数限制
                    is_infinite = config.get("isInfiniteLoop", True)
                    repeat_num = config.get("repeatNumber", 1)
                    ran_count = task.context.get("ran_count", 0)

                    if is_infinite or ran_count < repeat_num:
                        await self._execute(task, workspace_dir, {"ran_count": ran_count + 1})
                        # 触发后立即计算下一次时间
                        await self._update_next_cycle_time(task, workspace_dir)

    async def _execute(self, task, workspace_dir, extra_context):
        """执行任务并更新状态"""
        print(f"🚀 [调度中心] 触发任务: {task.title} (ID: {task.task_id})")
        task_center = await get_task_center(workspace_dir)
        
        # 更新为运行中，并存入触发标记(比如防止重复触发的分钟数或运行次数)
        await task_center.update_task_progress(
            task.task_id, 
            status=TaskStatus.RUNNING, 
            progress=0,
            context=extra_context
        )

        # 丢进后台运行
        asyncio.create_task(
            run_subtask_in_background(
                task_id=task.task_id,
                workspace_dir=workspace_dir,
                settings=self.settings
            )
        )

    async def _update_next_cycle_time(self, task, workspace_dir):
        """计算周期任务的下一次执行时间"""
        config = task.context.get("trigger_config", {})
        cycle_str = config.get("cycleValue", "01:00:00") # HH:mm:ss
        
        try:
            h, m, s = map(int, cycle_str.split(':'))
            delta = timedelta(hours=h, minutes=m, seconds=s)
            # 至少间隔 1 分钟，防止死循环
            if delta.total_seconds() < 60:
                delta = timedelta(minutes=1)
            
            next_run = datetime.now() + delta
            task_center = await get_task_center(workspace_dir)
            await task_center.update_task_progress(
                task.task_id,
                progress=task.progress,
                context={"next_run_at": next_run.isoformat()}
            )
        except:
            pass