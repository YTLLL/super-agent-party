# py/moss_model_manager.py
import asyncio
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks

from py.get_setting import DEFAULT_TTS_DIR

router = APIRouter(prefix="/moss-model")

MOSS_DIR_NAME = "MOSS-TTS"
HF_REPOS =[
    "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
    "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
]
MS_REPOS =[
    "openmoss/MOSS-TTS-Nano-100M-ONNX",
    "openmoss/MOSS-Audio-Tokenizer-Nano-ONNX"
]

# 两个仓库总计大小约为 784 MB
TARGET_TOTAL_BYTES = 784 * 1024 * 1024  

download_status = {
    "is_downloading": False,
    "source": None,
    "error": None,
    "done": False
}

def get_moss_base_dir() -> Path:
    return Path(DEFAULT_TTS_DIR) / MOSS_DIR_NAME

def is_model_ready() -> bool:
    base_dir = get_moss_base_dir()
    dir1 = base_dir / "MOSS-TTS-Nano-100M-ONNX"
    dir2 = base_dir / "MOSS-Audio-Tokenizer-Nano-ONNX"
    return (
        dir1.exists() and any(dir1.iterdir()) and
        dir2.exists() and any(dir2.iterdir())
    )

def get_dir_size(path: Path) -> int:
    """递归计算目录下的文件总大小（涵盖 SDK 下载时的临时文件）"""
    total = 0
    if not path.exists():
        return total
    try:
        for f in path.rglob('*'):
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
    except Exception:
        pass
    return total

def _download_sync(source: str):
    global download_status
    try:
        base_dir = get_moss_base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        
        if source == "modelscope":
            from modelscope.hub.snapshot_download import snapshot_download
            for repo_id in MS_REPOS:
                repo_name = repo_id.split("/")[-1]
                target_dir = str(base_dir / repo_name)
                snapshot_download(repo_id, local_dir=target_dir)
                
        elif source == "huggingface":
            from huggingface_hub import snapshot_download
            for repo_id in HF_REPOS:
                repo_name = repo_id.split("/")[-1]
                target_dir = str(base_dir / repo_name)
                # 关键：设置 local_dir_use_symlinks=False 才能让进度扫描精确生效
                snapshot_download(repo_id=repo_id, local_dir=target_dir, local_dir_use_symlinks=False)
                
        download_status["done"] = True
    except Exception as e:
        download_status["error"] = str(e)
    finally:
        download_status["is_downloading"] = False

@router.get("/status")
def status():
    percent = 0
    if is_model_ready():
        percent = 100
    elif download_status["is_downloading"]:
        # 实时计算当前文件夹大小
        current_bytes = get_dir_size(get_moss_base_dir())
        percent = int((current_bytes / TARGET_TOTAL_BYTES) * 100)
        # 限制在 0-99 之间，直到最后由 is_model_ready 判定为 100
        percent = max(0, min(99, percent))
        
    return {
        "exists": is_model_ready(), 
        "downloading": download_status["is_downloading"],
        "download_error": download_status["error"],
        "percent": percent
    }

@router.post("/download/{source}")
async def download(source: str, background_tasks: BackgroundTasks):
    if source not in ["modelscope", "huggingface"]:
        raise HTTPException(status_code=400)
    if download_status["is_downloading"]:
        return {"status": "正在下载中，请勿重复提交"}
    if is_model_ready():
        return {"status": "模型已存在，无需下载"}

    download_status["is_downloading"] = True
    download_status["source"] = source
    download_status["error"] = None
    download_status["done"] = False
    
    background_tasks.add_task(asyncio.to_thread, _download_sync, source)
    return {"status": "started"}

@router.delete("/remove")
def remove():
    import shutil
    d = get_moss_base_dir()
    if d.exists():
        shutil.rmtree(d)
    return {"ok": True}