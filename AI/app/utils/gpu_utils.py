"""
GPU 探测与训练设备解析（与 VIDEO 算法任务多卡逻辑对齐）。
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Union

YoloDevice = Union[str, int, List[int]]


def _use_gpu_enabled() -> bool:
    return os.environ.get('USE_GPU', 'False').lower() == 'true'


def parse_gpu_id_list(value: str) -> List[int]:
    """解析逗号分隔的 GPU 索引，如 \"0,1,2\"。"""
    if not value:
        return []
    ids: List[int] = []
    for part in str(value).split(','):
        p = part.strip()
        if not p:
            continue
        try:
            ids.append(int(p))
        except Exception:
            continue
    seen = set()
    result: List[int] = []
    for x in ids:
        if x in seen:
            continue
        seen.add(x)
        result.append(x)
    return result


def detect_visible_gpu_ids() -> List[int]:
    """
    返回当前进程可见的 GPU 索引列表。
    若设置 CUDA_VISIBLE_DEVICES，torch 看到的是重映射后的连续索引（0..N-1）。
    """
    if not _use_gpu_enabled():
        return []

    try:
        import torch
        if not torch.cuda.is_available():
            return []
        n = int(torch.cuda.device_count())
        if n <= 0:
            return []
        return list(range(n))
    except Exception:
        return []


def get_visible_gpu_ids() -> List[int]:
    """
    获取用于训练的 GPU 列表：优先 GPU_IDS 环境变量，否则自动探测。
    """
    configured = parse_gpu_id_list(os.getenv('GPU_IDS', '').strip())
    if configured:
        return configured
    return detect_visible_gpu_ids()


def normalize_request_gpu_ids(gpu_ids: Any) -> Optional[List[int]]:
    """解析请求体中的 gpu_ids（list 或逗号分隔字符串）。"""
    if gpu_ids is None:
        return None
    if isinstance(gpu_ids, str):
        parsed = parse_gpu_id_list(gpu_ids)
        return parsed if parsed else None
    if isinstance(gpu_ids, (list, tuple)):
        result: List[int] = []
        for item in gpu_ids:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result if result else None
    try:
        return [int(gpu_ids)]
    except (TypeError, ValueError):
        return None


def resolve_yolo_train_device(
    use_gpu: bool,
    gpu_ids: Optional[List[int]] = None,
) -> YoloDevice:
    """
    解析 ultralytics YOLO train() 的 device 参数。
    - 单卡: int 索引
    - 多卡: list[int]，启用 DDP 并行训练
    - 无 GPU: 'cpu'
    """
    if not use_gpu:
        return 'cpu'

    visible = get_visible_gpu_ids()
    if not visible:
        return 'cpu'

    if gpu_ids:
        selected = [g for g in gpu_ids if g in visible]
        if not selected:
            selected = visible
    else:
        selected = visible

    if len(selected) == 1:
        return selected[0]
    return selected


def format_device_for_log(device: YoloDevice) -> str:
    if device == 'cpu':
        return 'cpu'
    if isinstance(device, list):
        return ','.join(str(d) for d in device)
    return str(device)


def check_gpu_status() -> dict:
    """检查并返回 GPU 状态（供 API 与训练日志使用）。"""
    status = {
        'use_gpu_env': _use_gpu_enabled(),
        'gpu_ids_env': os.getenv('GPU_IDS', '').strip() or None,
        'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'),
        'nvidia_visible_devices': os.environ.get('NVIDIA_VISIBLE_DEVICES'),
    }

    try:
        import torch
        status['pytorch_version'] = torch.__version__
        status['cuda_available'] = torch.cuda.is_available()
        status['cuda_version'] = (
            torch.version.cuda if hasattr(torch.version, 'cuda') else '未知'
        )
        status['device_count'] = (
            torch.cuda.device_count() if torch.cuda.is_available() else 0
        )
    except Exception as e:
        status['pytorch_version'] = None
        status['cuda_available'] = False
        status['cuda_version'] = '未知'
        status['device_count'] = 0
        status['error'] = str(e)
        status['visible_gpu_ids'] = []
        status['devices'] = []
        status['multi_gpu'] = False
        return status

    visible = get_visible_gpu_ids()
    status['visible_gpu_ids'] = visible
    status['multi_gpu'] = len(visible) > 1
    status['devices'] = []

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            status['devices'].append({
                'index': i,
                'name': torch.cuda.get_device_name(i),
                'capability': torch.cuda.get_device_capability(i),
                'total_memory_gb': round(props.total_memory / (1024 ** 3), 2),
            })
            status[f'device_{i}_name'] = torch.cuda.get_device_name(i)
            status[f'device_{i}_capability'] = torch.cuda.get_device_capability(i)

    return status
