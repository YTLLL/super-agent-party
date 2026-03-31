import asyncio
import pyautogui
import pyperclip
import platform
import json
from typing import List, Optional, Tuple

# 开启安全防故障机制：鼠标移动到屏幕四个角落将引发 pyautogui.FailSafeException 中断程序
pyautogui.FAILSAFE = True

def _percent_to_pixel(x_percent: float, y_percent: float) -> Tuple[int, int]:
    """
    内部辅助函数：将千分比 (0 到 1000) 转换为当前屏幕的实际像素坐标。
    处理了边界限制，防止坐标超出屏幕。
    """
    width, height = pyautogui.size()
    
    # 限制在 0 到 1000 之间
    x_percent = max(0, min(1000, float(x_percent)))
    y_percent = max(0, min(1000, float(y_percent)))
    
    # 转换为像素（最大值为 分辨率 - 1，因为像素是从 0 开始计算的）
    px = min(int(width * (x_percent / 1000)), width - 1)
    py = min(int(height * (y_percent / 1000)), height - 1)
    
    return px, py

async def mouse_move_async(x: float, y: float, duration: float = 0.5) -> str:
    """移动鼠标到屏幕千分比位置"""
    if x < 0 or x > 1000 or y < 0 or y > 1000:
        return "千分比坐标超出范围，请输入 0 到 1000 之间的值。"
    px, py = _percent_to_pixel(x, y)
    await asyncio.to_thread(pyautogui.moveTo, px, py, duration)
    return f"鼠标已成功移动到屏幕位置 ({x}‰, {y}‰)，实际像素坐标 ({px}, {py})，耗时 {duration} 秒。"

async def mouse_click_async(button: str = "left", clicks: int = 1, x: Optional[float] = None, y: Optional[float] = None) -> str:
    """点击鼠标（支持千分比坐标）"""
    if x is not None and y is not None:
        if x < 0 or x > 1000 or y < 0 or y > 1000:    
            return "千分比坐标超出范围，请输入 0 到 1000 之间的值。"
        px, py = _percent_to_pixel(x, y)
        await asyncio.to_thread(pyautogui.click, x=px, y=py, clicks=clicks, button=button)
        return f"鼠标已移动到 ({x}‰, {y}‰) 并使用 {button} 键点击了 {clicks} 次。"
    else:
        await asyncio.to_thread(pyautogui.click, clicks=clicks, button=button)
        return f"鼠标在当前位置使用 {button} 键点击了 {clicks} 次。"

async def mouse_double_click_async(button: str = "left", clicks: int = 1, x: Optional[float] = None, y: Optional[float] = None) -> str:
    """点击鼠标（支持千分比坐标）"""
    if x is not None and y is not None:
        if x < 0 or x > 1000 or y < 0 or y > 1000:    
            return "千分比坐标超出范围，请输入 0 到 1000 之间的值。"
        px, py = _percent_to_pixel(x, y)
        await asyncio.to_thread(pyautogui.click, x=px, y=py, clicks=clicks, button=button)
        return f"鼠标已移动到 ({x}‰, {y}‰) 并使用 {button} 键点击了 {clicks} 次。"
    else:
        await asyncio.to_thread(pyautogui.click, clicks=clicks, button=button)
        return f"鼠标在当前位置使用 {button} 键点击了 {clicks} 次。"

async def mouse_drag_async(x: float, y: float, duration: float = 0.5, button: str = "left") -> str:
    """拖拽鼠标到指定千分比位置"""
    if x < 0 or x > 1000 or y < 0 or y > 1000:    
        return "千分比坐标超出范围，请输入 0 到 1000 之间的值。"
    px, py = _percent_to_pixel(x, y)
    await asyncio.to_thread(pyautogui.dragTo, px, py, duration, button=button)
    return f"鼠标已按住 {button} 键拖拽到了位置 ({x}‰, {y}‰)。"

async def mouse_scroll_async(clicks: int) -> str:
    """
    滚动鼠标。
    clicks > 0 为向上滚动，clicks < 0 为向下滚动。
    """
    await asyncio.to_thread(pyautogui.scroll, clicks)
    direction = "向上" if clicks > 0 else "向下"
    return f"鼠标滚轮已{direction}滚动了 {abs(clicks)} 个单位。"

async def keyboard_type_async(text: str) -> str:
    """
    输入文本。为了完美支持中文，采用剪贴板复制粘贴的方式。
    """
    def _type_text():
        # 备份当前剪贴板
        old_clipboard = pyperclip.paste()
        try:
            pyperclip.copy(text)
            # 根据不同操作系统使用不同的粘贴快捷键
            sys_os = platform.system()
            if sys_os == "Darwin":  # macOS
                pyautogui.hotkey("command", "v")
            else:  # Windows/Linux
                pyautogui.hotkey("ctrl", "v")
        finally:
            # 恢复剪贴板（可选，这里选择恢复以不干扰用户原本的剪贴板）
            # 暂停一小会儿确保粘贴动作已触发
            import time
            time.sleep(0.1)
            pyperclip.copy(old_clipboard)

    await asyncio.to_thread(_type_text)
    return f"已成功通过键盘输入文本：'{text}'"

async def keyboard_press_async(key: str, presses: int = 1) -> str:
    """按下单个按键（如 enter, tab, esc, space 等）"""
    await asyncio.to_thread(pyautogui.press, key, presses)
    return f"已按下键盘按键 '{key}' {presses} 次。"

async def keyboard_hotkey_async(keys: List[str]) -> str:
    """按下组合快捷键（如 ctrl+c, alt+tab 等）"""
    await asyncio.to_thread(pyautogui.hotkey, *keys)
    return f"已触发组合键：{' + '.join(keys)}。"

async def keyboard_hold_async(keys: List[str], duration: float) -> str:
    """
    长按一个或多个按键一段时间后释放。
    常用于游戏中控制角色移动（如长按 'w' 走 2 秒）。
    """
    def _hold_logic():
        try:
            # 按下所有指定的键
            for key in keys:
                pyautogui.keyDown(key)
            # 等待指定时间
            import time
            time.sleep(duration)
        finally:
            # 无论是否发生异常，确保释放按键
            for key in reversed(keys):
                pyautogui.keyUp(key)

    await asyncio.to_thread(_hold_logic)
    return f"已成功长按组合键 {keys} 持续 {duration} 秒。"

async def mouse_hold_async(button: str, duration: float) -> str:
    """
    长按鼠标按键一段时间后释放。
    常用于游戏中开火、蓄力或 UI 中的长按操作。
    """
    def _hold_logic():
        try:
            pyautogui.mouseDown(button=button)
            import time
            time.sleep(duration)
        finally:
            pyautogui.mouseUp(button=button)

    await asyncio.to_thread(_hold_logic)
    return f"已成功按住鼠标 {button} 键持续 {duration} 秒。"

async def wait_async(seconds: float) -> str:
    """等待一段时间，让页面或程序加载"""
    await asyncio.sleep(seconds)
    return f"已等待 {seconds} 秒。"

async def screenshot_async() -> str:
    """获取截图"""
    await asyncio.sleep(0.2)
    return "[Getting screenshot]"

# ================= 对应的 OpenAI 工具 Schema 定义 =================

mouse_move_tool = {
    "type": "function",
    "function": {
        "name": "mouse_move_async",
        "description": "将鼠标移动到屏幕上的指定位置。坐标使用千分比表示（0到1000）。(0,0)是屏幕左上角，(1000,1000)是右下角，(500,500)是屏幕正中心。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "目标水平坐标(X轴)，范围 0 到 1000 的千分比。例如 500 表示宽度正中间","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "目标垂直坐标(Y轴)，范围 0 到 1000 的千分比。例如 500 表示高度正中间","maximum": 1000, "minimum": 0},
                "duration": {"type": "number", "description": "移动耗时（秒），默认为0.5秒。为了拟真，建议不要设为0", "default": 0.5}
            },
            "required": ["x", "y"]
        }
    }
}

mouse_click_tool = {
    "type": "function",
    "function": {
        "name": "mouse_click_async",
        "description": "点击鼠标。如果传入千分比坐标，则会先移动到该位置再点击；如果不传坐标则在当前位置点击。",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "点击的按键，左键/右键/中键"},
                "clicks": {"type": "integer", "description": "点击次数。1为单击，2为双击，当你需要打开链接或文件时，建议使用双击。如果单击某个图标没有任何反应，也要优先考虑双击。", "default": 1},
                "x": {"type": "number", "description": "点击前的目标水平坐标（0 到 1000 的千分比），可选","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "点击前的目标垂直坐标（0 到 1000 的千分比），可选","maximum": 1000, "minimum": 0}
            },
            "required": ["button"]
        }
    }
}

mouse_double_click_tool = {
    "type": "function",
    "function": {
        "name": "mouse_double_click_async",
        "description": "双击鼠标以快速打开链接、文件、应用等。如果传入千分比坐标，则会先移动到该位置再点击；如果不传坐标则在当前位置点击。",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "点击的按键，左键/右键/中键"},
                "x": {"type": "number", "description": "点击前的目标水平坐标（0 到 1000 的千分比），可选","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "点击前的目标垂直坐标（0 到 1000 的千分比），可选","maximum": 1000, "minimum": 0}
            },
            "required": ["button"]
        }
    }
}


mouse_drag_tool = {
    "type": "function",
    "function": {
        "name": "mouse_drag_async",
        "description": "按住鼠标按键并拖拽到指定千分比位置。常用于拖动窗口、滑块、框选等操作。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "拖拽终点水平坐标（0 到 1000 的千分比）","maximum": 1000, "minimum": 0},
                "y": {"type": "number", "description": "拖拽终点垂直坐标（0 到 1000 的千分比）","maximum": 1000, "minimum": 0},
                "duration": {"type": "number", "description": "拖拽过程耗时（秒）", "default": 0.5},
                "button": {"type": "string", "enum": ["left", "right"], "description": "按住哪个键拖拽，默认左键", "default": "left"}
            },
            "required": ["x", "y"]
        }
    }
}

mouse_scroll_tool = {
    "type": "function",
    "function": {
        "name": "mouse_scroll_async",
        "description": "滚动鼠标滚轮以浏览网页或文档。正数表示向上滚动，负数表示向下滚动。",
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {"type": "integer", "description": "滚动单位。大于0为向上滚，小于0为向下滚。如 500 或 -500。一般网页滚动一次可以尝试 300 到 800 的数值。"}
            },
            "required": ["clicks"]
        }
    }
}

keyboard_type_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_type_async",
        "description": "在当前焦点输入框中输入一段文本。支持输入中文和英文字符。注意：调用前请确保已经点击了正确的输入框使之获得了焦点！",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "需要输入的具体文本内容"}
            },
            "required": ["text"]
        }
    }
}

keyboard_press_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_press_async",
        "description": "按下单个功能按键。常用于输入回车(enter)、退格(backspace)、转义(esc)、制表符(tab)、方向键等。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名称，有效值例如: enter, space, esc, backspace, tab, up, down, left, right, delete, pagedown, pageup等。"},
                "presses": {"type": "integer", "description": "按下次数，默认1次", "default": 1}
            },
            "required": ["key"]
        }
    }
}

keyboard_hotkey_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_hotkey_async",
        "description": "按下键盘组合快捷键。例如复制是['ctrl', 'c']，切换窗口是['alt', 'tab']。如果是mac系统请使用'command'代替'ctrl'。",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "快捷键组合数组，必须按照按下的先后顺序排列。例如: ['ctrl', 'shift', 'esc']"
                }
            },
            "required": ["keys"]
        }
    }
}

wait_tool = {
    "type": "function",
    "function": {
        "name": "wait_async",
        "description": "让操作暂停并等待一段时间。在点击了加载页面的链接、启动软件、或者输入内容后，必须调用此工具等待 UI 刷新完成，否则下一步操作可能会因为找不到目标而失败。",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "需要等待的秒数，如 1, 2.5, 5等。如果网速慢或程序加载慢，请适当延长。"}
            },
            "required": ["seconds"]
        }
    }
}

keyboard_hold_tool = {
    "type": "function",
    "function": {
        "name": "keyboard_hold_async",
        "description": "长按键盘上的一个或多个按键一段时间。这对于控制游戏角色移动或执行需要按住的操作非常有用。",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要按住的按键列表。例如 ['w'] 或 ['w', 'shift']。"
                },
                "duration": {
                    "type": "number", 
                    "description": "按住的时长（秒）。"
                }
            },
            "required": ["keys", "duration"]
        }
    }
}

mouse_hold_tool = {
    "type": "function",
    "function": {
        "name": "mouse_hold_async",
        "description": "长按鼠标某个按键一段时间。适用于游戏中的蓄力、持续开火或某些 UI 的长按菜单。",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {
                    "type": "string", 
                    "enum": ["left", "right", "middle"],
                    "description": "要按住的鼠标按键。"
                },
                "duration": {
                    "type": "number", 
                    "description": "按住的时长（秒）。"
                }
            },
            "required": ["button", "duration"]
        }
    }
}

screenshot_async_tool = {
    "type": "function",
    "function": {
        "name": "screenshot_async",
        "description": "截取带有千分比辅助网格的当前桌面的图像"
    }
}

# 导出所有工具到列表，方便主程序统一挂载
computer_use_tools = [
    wait_tool
    
]

desktopVision_use_tools = [
    screenshot_async_tool
]

mouse_use_tools = [
    mouse_move_tool,
    mouse_click_tool,
    mouse_double_click_tool,
    mouse_drag_tool,
    mouse_scroll_tool,
    mouse_hold_tool,
]

keyboard_use_tools = [
    keyboard_type_tool,
    keyboard_press_tool,
    keyboard_hotkey_tool,
    keyboard_hold_tool,
]