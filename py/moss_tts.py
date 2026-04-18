# py/moss_tts.py
import asyncio
import io
import wave
import uuid
from pathlib import Path
from py.get_setting import DEFAULT_TTS_DIR, TOOL_TEMP_DIR

_moss_runtime = None
# 匹配我们在管理器中定义的根目录
MOSS_DIR_NAME = "MOSS-TTS"

def _get_moss_runtime():
    """彻底的懒加载：在第一次请求生成时，才会导入重型的 numpy/scipy/onnxruntime"""
    global _moss_runtime
    if _moss_runtime is not None:
        return _moss_runtime

    try:
        import numpy as np
        import scipy.signal
        from py.moss.tts_runtime import TTSRuntime
    except ImportError as e:
        print(f"MOSS TTS 依赖缺失，请确认 numpy/scipy/onnxruntime/sentencepiece/soundfile 已安装: {e}")
        return None

    # 将父目录丢给 TTSRuntime，它内部会根据 MANIFEST_CANDIDATE_RELATIVE_PATHS 自动定位
    model_dir = Path(DEFAULT_TTS_DIR) / MOSS_DIR_NAME
    if not (model_dir / "MOSS-TTS-Nano-100M-ONNX").exists():
        print("提示: MOSS TTS 模型未找到，请先通过 SDK 接口下载。")
        return None

    print(f"正在加载 MOSS TTS 模型 [{model_dir}]...")
    try:
        _moss_runtime = TTSRuntime(
            model_dir=str(model_dir),
            thread_count=4,  # 控制 CPU 占用
        )
        return _moss_runtime
    except Exception as e:
        print(f"加载 MOSS TTS 失败: {e}")
        return None

def _process_tts_sync(text: str, voice: str, speed: float, prompt_audio_path: str) -> bytes:
    """同步阻塞推理，返回 WAV 二进制格式"""
    import numpy as np
    import scipy.signal
    
    runtime = _get_moss_runtime()
    if not runtime:
        raise RuntimeError("MOSS TTS 模型未就绪（未下载或加载失败）")

    # MOSS TTS_runtime 代码默认会在磁盘写一个 wav，为了不残留垃圾文件，我们将路径指定到工具临时目录并及时删除
    temp_wav_path = Path(TOOL_TEMP_DIR) / f"moss_temp_{uuid.uuid4().hex}.wav"

    try:
        # 执行推理
        result = runtime.synthesize(
            text=text,
            voice=voice,
            prompt_audio_path=prompt_audio_path if prompt_audio_path else None,
            output_audio_path=str(temp_wav_path),
            sample_mode="fixed", 
            do_sample=True,
        )

        original_sr = result["sample_rate"]
        waveform = result["waveform"]

        # 调整语速逻辑
        if abs(speed - 1.0) >= 0.01:
            if waveform.ndim == 2:
                adjusted =[]
                for channel in waveform.T:
                    channel_adjusted = scipy.signal.resample(channel, int(len(channel) / speed))
                    adjusted.append(channel_adjusted)
                waveform = np.stack(adjusted, axis=1).astype(np.float32)
            else:
                waveform = scipy.signal.resample(waveform, int(len(waveform) / speed)).astype(np.float32)
            sample_rate = int(original_sr * speed)
        else:
            sample_rate = original_sr

        # 转换为 WAV 的二进制 Bytes 以供前端 StreamingResponse
        audio = np.asarray(waveform, dtype=np.float32)
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        clipped = np.clip(audio, -1.0, 1.0)
        pcm16 = np.round(clipped * 32767.0).astype(np.int16)

        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(int(pcm16.shape[1]))
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm16.tobytes())

        return wav_io.getvalue()
    finally:
        # 执行完毕后，立刻删掉刚才被写入的临时 wav，实现伪纯内存效果
        if temp_wav_path.exists():
            temp_wav_path.unlink(missing_ok=True)

async def moss_generate_audio(text: str, voice: str = "Junhao", speed: float = 1.0, prompt_audio_path: str = "") -> bytes:
    """异步封装：将繁重的推理推向线程池"""
    wav_bytes = await asyncio.to_thread(
        _process_tts_sync, text, voice, speed, prompt_audio_path
    )
    return wav_bytes