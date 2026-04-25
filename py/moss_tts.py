# py/moss_tts.py
import asyncio
import io
import wave
import uuid
import threading
import logging
from pathlib import Path
from py.get_setting import DEFAULT_TTS_DIR, TOOL_TEMP_DIR

_moss_runtime = None
_runtime_lock = threading.Lock()

# 匹配我们在管理器中定义的根目录
MOSS_DIR_NAME = "MOSS-TTS"

def _get_moss_runtime():
    """彻底的懒加载：在第一次请求生成时，才会导入重型的 numpy/scipy/onnxruntime"""
    global _moss_runtime
    if _moss_runtime is not None:
        return _moss_runtime
    
    with _runtime_lock:
        # 双重检查，避免多个线程同时加载
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
            # 预热模型，避免第一次推理时卡顿
            print("正在进行模型预热...")
            _moss_runtime.warmup()
            print("MOSS TTS 模型加载完成")
            return _moss_runtime
        except Exception as e:
            print(f"加载 MOSS TTS 失败: {e}")
            return None


def _validate_audio_quality(waveform, min_energy=0.0001, max_peak=1.0):
    """
    检查生成的音频质量
    
    参数:
        waveform: numpy数组，形状为(samples, channels)或(samples,)
        min_energy: 最小平均能量，低于此值认为是静音
        max_peak: 最大峰值，超过此值认为是削波
    
    返回:
        bool: 音频是否通过质量检查
        str: 未通过的原因（如果通过则为空字符串）
    """
    import numpy as np
    
    if waveform is None:
        return False, "Waveform is None"
    
    if waveform.size == 0:
        return False, "Waveform is empty"
    
    # 检查是否全为NaN或Inf
    if np.any(np.isnan(waveform)) or np.any(np.isinf(waveform)):
        return False, "Waveform contains NaN or Inf values"
    
    # 计算能量（均方值）
    energy = np.mean(waveform ** 2)
    if energy < min_energy:
        return False, f"Audio energy too low: {energy:.6f} < {min_energy}"
    
    # 检查削波
    max_val = np.max(np.abs(waveform))
    if max_val > max_peak:
        return False, f"Audio clipping detected: peak={max_val:.3f} > {max_peak}"
    
    # 检查异常采样点比例
    zero_ratio = np.sum(np.abs(waveform) < 1e-8) / waveform.size
    if zero_ratio > 0.5:
        return False, f"Too many near-zero samples: {zero_ratio:.2%}"
    
    return True, ""


def _validate_generated_frames(frames, audio_codebook_size):
    """
    检查生成的音频帧是否合法
    
    参数:
        frames: list[list[int]]，生成的音频token序列
        audio_codebook_size: int，码本大小
    
    返回:
        bool: 帧是否合法
        str: 不合法原因
    """
    if not frames:
        return False, "No frames generated"
    
    for frame_idx, frame in enumerate(frames):
        if not frame:
            return False, f"Empty frame at index {frame_idx}"
        
        for token_idx, token in enumerate(frame):
            if token < 0 or token >= audio_codebook_size:
                return False, f"Invalid token {token} at frame {frame_idx}, position {token_idx} (valid range: 0-{audio_codebook_size-1})"
    
    return True, ""


def _process_tts_sync(text: str, voice: str, speed: float, prompt_audio_path: str) -> bytes:
    """同步阻塞推理，返回 WAV 二进制格式"""
    import numpy as np
    import scipy.signal
    import logging
    
    runtime = _get_moss_runtime()
    if not runtime:
        raise RuntimeError("MOSS TTS 模型未就绪（未下载或加载失败）")
    
    # 每次推理前重置流式解码器状态，避免状态污染
    if hasattr(runtime, 'codec_streaming_session'):
        runtime.codec_streaming_session.reset()
    
    # 清除编码缓存（可选，确保每次都是新鲜的编码）
    if hasattr(runtime, '_audio_codes_cache') and not prompt_audio_path:
        # 使用内置声音时不清理缓存，提升性能
        pass
    elif hasattr(runtime, '_audio_codes_cache'):
        # 使用自定义参考音频时，可以在这里清理
        pass

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
        
        # 验证音频质量
        is_valid, quality_msg = _validate_audio_quality(waveform)
        if not is_valid:
            logging.warning(f"Generated audio quality issue: {quality_msg}")
            # 不直接抛出异常，让客户端自己决定是否接受
        
        # 验证帧质量
        if "audio_token_ids" in result:
            audio_codebook_size = int(runtime.tts_meta["model_config"]["audio_codebook_sizes"][0])
            frames_valid, frames_msg = _validate_generated_frames(
                result["audio_token_ids"].tolist() if hasattr(result["audio_token_ids"], 'tolist') else result["audio_token_ids"],
                audio_codebook_size
            )
            if not frames_valid:
                logging.warning(f"Generated frames quality issue: {frames_msg}")

        # 调整语速逻辑
        if abs(speed - 1.0) >= 0.01:
            try:
                if waveform.ndim == 2:
                    adjusted = []
                    for channel in waveform.T:
                        channel_adjusted = scipy.signal.resample(channel, int(len(channel) / speed))
                        adjusted.append(channel_adjusted)
                    waveform = np.stack(adjusted, axis=1).astype(np.float32)
                else:
                    waveform = scipy.signal.resample(waveform, int(len(waveform) / speed)).astype(np.float32)
                sample_rate = int(original_sr * speed)
            except Exception as e:
                logging.error(f"Speed adjustment failed: {e}, using original speed")
                sample_rate = original_sr
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
        
    except Exception as e:
        # 发生异常时，确保清理状态
        if hasattr(runtime, 'codec_streaming_session'):
            runtime.codec_streaming_session.reset()
        logging.error(f"TTS generation failed: {e}")
        raise RuntimeError(f"语音生成失败: {str(e)}")
        
    finally:
        # 执行完毕后，立刻删掉刚才被写入的临时 wav，实现伪纯内存效果
        if temp_wav_path.exists():
            try:
                temp_wav_path.unlink(missing_ok=True)
            except Exception as e:
                logging.warning(f"Failed to delete temp file {temp_wav_path}: {e}")


async def moss_generate_audio(text: str, voice: str = "Junhao", speed: float = 1.0, prompt_audio_path: str = "") -> bytes:
    """异步封装：将繁重的推理推向线程池"""
    # 参数验证
    if not text or not text.strip():
        raise ValueError("文本内容不能为空")
    
    if speed <= 0 or speed > 3.0:
        raise ValueError(f"语速参数不合法: {speed}，应在 0.1-3.0 之间")
    
    try:
        wav_bytes = await asyncio.to_thread(
            _process_tts_sync, text, voice, speed, prompt_audio_path
        )
        
        if not wav_bytes:
            raise RuntimeError("生成的音频为空")
        
        return wav_bytes
        
    except asyncio.CancelledError:
        # 任务被取消时，尝试清理资源
        logging.warning("TTS generation was cancelled")
        if _moss_runtime and hasattr(_moss_runtime, 'codec_streaming_session'):
            _moss_runtime.codec_streaming_session.reset()
        raise
        
    except Exception as e:
        logging.error(f"moss_generate_audio failed: {e}")
        raise