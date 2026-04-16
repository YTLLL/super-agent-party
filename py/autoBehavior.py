from py.get_setting import load_settings

async def auto_behavior(behaviorType="delay", time="00:00:00", prompt="", days=[], repeatNumber=1, isInfiniteLoop=False, platforms=["chat"]):
    # Load settings
    settings = await load_settings()
    
    # 构造新行为项
    new_behavior = {
        "enabled": True,
        "platform": platforms[0] if platforms else "chat", # 兼容旧版单一字段逻辑
        "platforms": platforms,                           # 支持多选的新字段
        "trigger": {
            "type": "time" if behaviorType == "time" else "cycle",
            "time":{
                "timeValue": time, 
                "days": days
            },
            "noInput":{
                "latency": 30, 
            },
            "cycle":{
                "cycleValue": time if behaviorType == "delay" else "00:00:30", 
                "repeatNumber": repeatNumber, 
                "isInfiniteLoop": isInfiniteLoop, 
            }
        },
        "action": {
            "type": "prompt",
            "prompt": "时间到了，"+prompt, 
            "random":{
                "events":[""],
                "type":"random",
                "orderIndex":0,
            }
        }
    }
    
    settings["behaviorSettings"]["behaviorList"].append(new_behavior)
    settings["behaviorSettings"]['enabled'] = True
    return settings


auto_behavior_tool = {
    "type": "function",
    "function": {
        "name": "auto_behavior",
        "description": "当用户需要你在特定时间、隔一段时间或在特定渠道自动执行某些行为时使用。你可以一次性设置在多个渠道（如微信、飞书、网页）同步执行任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "behaviorType": {
                    "type": "string",
                    "description": "行为类型：time（特定时间点执行，如3点钟），delay（隔一段时间执行，如5分钟后）",
                    "enum": ["time", "delay"],
                },
                "time": {
                    "type": "string",
                    "description": "时间格式 HH:MM:SS。time类型下为执行点，delay类型下为时间间隔。",
                },
                "prompt": {
                    "type": "string",
                    "description": "任务描述，例如：提醒用户开会、发送问候语",
                },
                "days": {
                    "type": "array",
                    "description": "time类型下生效，[1,2,3,4,5]代表工作日，[0]代表周日，[]不重复",
                    "items": {
                        "type": "number",
                        "enum": [0, 1, 2, 3, 4, 5, 6],
                    },
                    "default": [],
                },
                "repeatNumber": {
                    "type": "number",
                    "description": "delay类型下的重复次数 (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 1,
                },
                "isInfiniteLoop": {
                    "type": "boolean",
                    "description": "delay类型下是否无限循环",
                    "default": False,
                },
                "platforms": {
                    "type": "array",
                    "description": "要推送的渠道列表。chat:网页对话, wechat:微信, feishu:飞书, dingtalk:钉钉, telegram, discord, slack, wecom:企微",
                    "items": {
                        "type": "string",
                        "enum": ["chat", "wechat", "feishu", "dingtalk", "telegram", "discord", "slack", "wecom"]
                    },
                    "default": ["chat"],
                }
            },
            "required": ["prompt", "behaviorType"],
        },
    },
}