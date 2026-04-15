# py/ytdm.py
from __future__ import annotations
import asyncio, threading, time
import uuid
from googleapiclient.discovery import build
from typing import Optional, Callable

class YouTubeDMClient:
    """
    极简轮询客户端
    用法：client = YouTubeDMClient(api_key, video_id, on_message)
          client.start()   # 非阻塞，内部启动线程
          ...
          client.stop()    # 线程安全退出
    """
    def __init__(self,
                 api_key: str,
                 video_id: str,
                 on_message: Callable[[dict], None],
                 poll_interval: int = 5):
        self.api_key = api_key
        self.video_id = video_id
        self.on_message = on_message
        self.poll_interval = poll_interval

        self._yt = build("youtube", "v3", developerKey=api_key)
        self._chat_id: Optional[str] = None
        self._page_token: Optional[str] = None
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --------- 外部调用 ---------
    def start(self):
        """非阻塞启动"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """线程安全停止"""
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.poll_interval + 1)

    # --------- 内部轮询 ---------
    def _run(self):
        self._chat_id = self._get_live_chat_id()
        print('[YouTube] got chat_id:', self._chat_id)   # ← 新增
        if not self._chat_id:
            print('[YouTube] 未开播，线程退出')
            return

        while not self._stop_evt.is_set():
            try:
                self._poll_once()
                print('[YouTube] poll_once done')        # ← 新增
            except Exception as e:
                print('[YouTube] poll error:', e)
            time.sleep(self.poll_interval)

    def _get_live_chat_id(self) -> Optional[str]:
        rsp = self._yt.videos().list(
            id=self.video_id,
            part="liveStreamingDetails"
        ).execute()
        if not rsp["items"]:
            return None
        return rsp["items"][0]["liveStreamingDetails"].get("activeLiveChatId")


    def _poll_once(self):
        """
        YouTube 轮询核心逻辑
        识别类型：textMessageEvent(弹幕), superChatEvent(SC), fanFundingEvent(会员赞助)
        """
        rsp = self._yt.liveChatMessages().list(
            liveChatId=self._chat_id,
            part="snippet,authorDetails",
            pageToken=self._page_token,
            maxResults=2000
        ).execute()

        for item in rsp["items"]:
            author = item["authorDetails"]["displayName"]
            msg_type = item["snippet"].get("type")
            
            # 1. 统一类型映射初始化
            danmu_type = "danmaku"
            content = ""
            
            # 2. 根据 YouTube 消息类型解析内容
            if msg_type == "textMessageEvent":
                # 普通弹幕
                danmu_type = "danmaku"
                text = item["snippet"]["displayMessage"]
                content = f"{author}: {text}"
                
            elif msg_type == "superChatEvent":
                # 醒目留言 (SC)
                danmu_type = "super_chat"
                details = item["snippet"].get("superChatDetails", {})
                user_text = details.get("userComment", "")
                amount = details.get("amountDisplayString", "Price Hidden")
                if user_text:
                    content = f"{author} sent a Super Chat ({amount}): {user_text}"
                else:
                    content = f"{author} sent a Super Chat ({amount})"
                    
            elif msg_type == "fanFundingEvent": 
                # 频道会员/赞助 (YouTube 赠礼类)
                danmu_type = "gift"
                content = f"{author} sponsored the channel!"
                
            else:
                # 兜底：其他类型（如进场占位符等）统统转为普通文本显示
                text = item["snippet"].get("displayMessage", "")
                content = f"{author}: {text}"

            # 3. 构造统一格式并广播
            msg = {
                'id': str(uuid.uuid4()),
                "type": "message",
                "content": content,
                "danmu_type": danmu_type,
                "platform": "youtube"
            }
            self.on_message(msg)

        # 更新下一次抓取的 Token
        self._page_token = rsp.get("nextPageToken")
        