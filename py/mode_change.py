import logging
from py.get_setting import load_settings, save_settings
from py.ws_manager import ws_manager

logger = logging.getLogger("app")

async def update_workspace_settings(
    cli_enabled: bool = None,
    engine: str = None,
    local_permission_mode: str = None,
    ds_permission_mode: str = None,
    cc_enabled: bool = None,
    cc_permission_mode: str = None
):
    """
    动态调整工作区工具的开启状态、执行引擎以及权限模式。
    """
    try:
        # 1. 读取当前配置
        settings = await load_settings()
        changed = False

        # 2. 修改 CLISettings (主开关和引擎)
        if cli_enabled is not None:
            settings["CLISettings"]["enabled"] = cli_enabled
            changed = True
        
        if engine in ["local", "ds"]:
            settings["CLISettings"]["engine"] = engine
            changed = True

        # 3. 修改本地环境权限
        if local_permission_mode in ["plan", "default", "auto-approve", "yolo", "cowork"]:
            settings["localEnvSettings"]["permissionMode"] = local_permission_mode
            changed = True

        # 4. 修改 Docker Sandbox 权限
        if ds_permission_mode in ["plan", "default", "auto-approve", "yolo", "cowork"]:
            settings["dsSettings"]["permissionMode"] = ds_permission_mode
            changed = True

        # 5. 修改 ccSettings (控制中心/自定义环境)
        if cc_enabled is not None:
            settings["ccSettings"]["enabled"] = cc_enabled
            changed = True
        
        if cc_permission_mode in ["plan", "default", "auto-approve", "yolo", "cowork"]:
            settings["ccSettings"]["permissionMode"] = cc_permission_mode
            changed = True

        if changed:
            # 6. 持久化到文件
            await save_settings(settings)
            
            # 7. 【关键】广播给所有活跃的 WebSocket 连接，让前端 UI 实时更新
            await ws_manager.broadcast_settings_update(settings)
            
            status_msg = "工作区设置已更新。"
            if cli_enabled is False: status_msg += " 终端工具已关闭。"
            if local_permission_mode == "yolo" or ds_permission_mode == "yolo":
                status_msg += " 注意：已开启 YOLO 模式，将不再询问用户确认直接执行命令。"
            
            return status_msg
        else:
            return "未检测到有效的设置更改参数。"

    except Exception as e:
        logger.error(f"更新工作区设置失败: {e}")
        return f"设置更新失败: {str(e)}"
    

mode_change_tool = {
    "type": "function",
    "function": {
        "name": "update_workspace_settings",
        "description": "管理工作区终端工具。可以开启/关闭终端、切换执行引擎(本地/Docker)、以及修改权限模式（如从'计划模式'切换到'执行模式'或'直接通过模式'）。",
        "parameters": {
            "type": "object",
            "properties": {
                "cli_enabled": {
                    "type": "boolean",
                    "description": "是否启用终端工具总开关"
                },
                "engine": {
                    "type": "string",
                    "enum": ["local", "ds"],
                    "description": "执行引擎：local (本地环境), ds (Docker Sandbox)"
                },
                "local_permission_mode": {
                    "type": "string",
                    "enum": ["plan", "default", "auto-approve", "yolo", "cowork"],
                    "description": "本地环境权限模式。plan:只读计划; default:需确认执行; auto-approve:自动批准修改; yolo:无限制静默执行; cowork:协作模式。"
                },
                "ds_permission_mode": {
                    "type": "string",
                    "enum": ["plan", "default", "auto-approve", "yolo", "cowork"],
                    "description": "Docker环境权限模式。同上。"
                },
                "cc_enabled": {
                    "type": "boolean",
                    "description": "是否开启 ccSettings 环境"
                },
                "cc_permission_mode": {
                    "type": "string",
                    "enum": ["plan", "default", "auto-approve", "yolo", "cowork"],
                    "description": "ccSettings 环境的权限模式。"
                }
            }
        }
    }
}