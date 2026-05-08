#!/usr/bin/env python3
"""
统一的抓拍算法任务服务程序
整合缓流器、抽帧器、推帧器功能，支持追踪和告警
参照test_services_pipeline.py和test_services_pipeline_tracking.py

@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import os
import sys
import time
import threading
import logging
import subprocess
import signal
import queue
import cv2
import numpy as np
import requests
import json
import socket
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import zlib
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from croniter import croniter

# 添加VIDEO模块路径
video_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, video_root)

# 导入VIDEO模块的模型
from models import db, AlgorithmTask, Device
from app.utils.gb28181_source import resolve_gb28181_source
from app.utils.alert_images_paths import resolve_alert_images_root


def _parse_gpu_id_list(value: str) -> List[int]:
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
    # 去重但保序
    seen = set()
    result: List[int] = []
    for x in ids:
        if x in seen:
            continue
        seen.add(x)
        result.append(x)
    return result


def _detect_visible_gpu_ids() -> List[int]:
    """
    返回当前进程“可见”的GPU索引列表（用于推理/ultralytics/torch）。
    若 torch 不可用或CUDA不可用则返回空列表。
    """
    use_gpu = os.environ.get('USE_GPU', 'False').lower() == 'true'
    if not use_gpu:
        return []

    try:
        import torch  # type: ignore
        if not torch.cuda.is_available():
            return []
        n = int(torch.cuda.device_count())
        if n <= 0:
            return []
        return list(range(n))
    except Exception:
        return []


_VISIBLE_GPU_IDS: List[int] = []
_GPU_ASSIGNMENTS: Dict[str, int] = {}
_GPU_RR_COUNTER = 0
_GPU_SCHED_LOCK = threading.Lock()


def _get_infer_gpu_policy() -> str:
    v = (os.getenv("INFER_GPU_POLICY") or os.getenv("GPU_POLICY") or "hash").strip().lower()
    return v if v in ("hash", "round_robin") else "hash"


def _ensure_gpu_ids_initialized() -> None:
    global _VISIBLE_GPU_IDS
    if _VISIBLE_GPU_IDS:
        return

    configured = _parse_gpu_id_list(os.getenv("GPU_IDS", "").strip())
    if configured:
        _VISIBLE_GPU_IDS = configured
        return
    _VISIBLE_GPU_IDS = _detect_visible_gpu_ids()


def _stable_key_hash(s: str) -> int:
    return int(zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF)


def get_infer_device(device_key: Any = None) -> str:
    """给推理用：返回 'cpu' 或 'cuda:{idx}'，按设备稳定分配到多张GPU。"""
    _ensure_gpu_ids_initialized()
    if not _VISIBLE_GPU_IDS:
        return "cpu"

    key_str = str(device_key if device_key is not None else "default")
    with _GPU_SCHED_LOCK:
        cached = _GPU_ASSIGNMENTS.get(key_str)
        if cached is None:
            global _GPU_RR_COUNTER
            policy = _get_infer_gpu_policy()
            if policy == "round_robin":
                idx = _GPU_RR_COUNTER % len(_VISIBLE_GPU_IDS)
                _GPU_RR_COUNTER += 1
                gpu_id = _VISIBLE_GPU_IDS[idx]
            else:
                gpu_id = _VISIBLE_GPU_IDS[_stable_key_hash(key_str) % len(_VISIBLE_GPU_IDS)]
            _GPU_ASSIGNMENTS[key_str] = gpu_id
            cached = gpu_id
    return f"cuda:{cached}"


# Flask应用实例（延迟创建，避免导入run模块时的副作用）
_flask_app = None


def get_flask_app():
    """获取Flask应用实例（延迟创建，避免导入run模块时的副作用）"""
    global _flask_app
    if _flask_app is None:
        from flask import Flask
        app = Flask(__name__)
        # 从环境变量获取数据库URL
        database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/iot_video')
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,
            'pool_recycle': 3600,
            'pool_size': 10,
            'max_overflow': 20,
            'connect_args': {
                'connect_timeout': 10,
            }
        }

        # 初始化数据库
        db.init_app(app)
        _flask_app = app
    return _flask_app


# 导入追踪器（使用相对导入）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'utils'))
from tracker import SimpleTracker

# 加载环境变量
load_dotenv()

# OpenCV FFmpeg 解码参数（与 stream_forward_service / realtime_algorithm_service 对齐）
# 抓拍任务也会受上游流抖动影响，设置默认捕获选项可减少解码花屏/撕裂。
# RTSP 传输：优先 AI_RTSP_TRANSPORT，其次 OPENCV_/FFMPEG_；默认 tcp（抗丢包更稳；局域网要低延迟可设 AI_RTSP_TRANSPORT=udp）
_EFFECTIVE_RTSP_TRANSPORT = (
    os.getenv("AI_RTSP_TRANSPORT")
    or os.getenv("OPENCV_FFMPEG_RTSP_TRANSPORT")
    or os.getenv("FFMPEG_RTSP_TRANSPORT")
    or "tcp"
).strip().lower()
if _EFFECTIVE_RTSP_TRANSPORT not in ("tcp", "udp"):
    _EFFECTIVE_RTSP_TRANSPORT = "tcp"

_OPENCV_FFMPEG_OPTIONS_CUSTOM = bool(os.getenv("OPENCV_FFMPEG_CAPTURE_OPTIONS"))
if not _OPENCV_FFMPEG_OPTIONS_CUSTOM:
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        f"rtsp_transport;{_EFFECTIVE_RTSP_TRANSPORT}"
        "|stimeout;10000000"
        "|rw_timeout;5000000"
        "|max_delay;500000"
        "|fflags;nobuffer+discardcorrupt+genpts"
        "|flags;low_delay"
        "|err_detect;ignore_err"
    )

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

if _OPENCV_FFMPEG_OPTIONS_CUSTOM:
    logger.info(
        "OpenCV RTSP: 已设置 OPENCV_FFMPEG_CAPTURE_OPTIONS（自定义），"
        "实际 rtsp_transport 以 options 为准（未走 AI_RTSP_TRANSPORT 默认拼接）"
    )
else:
    logger.info(
        "OpenCV RTSP: rtsp_transport=%s（由 AI_RTSP_TRANSPORT / OPENCV_FFMPEG_RTSP_TRANSPORT / "
        "FFMPEG_RTSP_TRANSPORT 决定；局域网极低延迟可试 udp）",
        _EFFECTIVE_RTSP_TRANSPORT,
    )

# 全局变量
TASK_ID = int(os.getenv('TASK_ID', '0'))
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/iot_video')
VIDEO_SERVICE_PORT = os.getenv('VIDEO_SERVICE_PORT', '6000')
# 网关地址（用于构建完整的告警hook URL）
GATEWAY_URL = os.getenv('GATEWAY_URL', 'http://localhost:48080')
ALERT_HOOK_URL = f"http://localhost:{VIDEO_SERVICE_PORT}/video/alert/hook"

# 数据库会话
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db_session = scoped_session(SessionLocal)

# 全局变量
stop_event = threading.Event()
task_config = None
yolo_models = {}
# 为每个摄像头创建独立的追踪器
trackers = {}  # {device_id: SimpleTracker}
# 为每个摄像头创建独立的帧缓存队列
frame_buffers = {}  # {device_id: {frame_number: frame_data}}
buffer_locks = {}  # {device_id: threading.Lock()}
# 为每个摄像头创建独立的帧索引计数器
frame_counts = {}  # {device_id: int}
# 为每个摄像头创建独立的队列
extract_queues = {}  # {device_id: queue.Queue}
detection_queues = {}  # {device_id: queue.Queue}
push_queues = {}  # {device_id: queue.Queue}
# 摄像头流连接（VideoCapture对象）
device_caps = {}  # {device_id: cv2.VideoCapture}
# 告警抑制：记录每个设备上次告警推送时间（抓拍算法任务不使用告警抑制）
# 注意：抓拍算法任务不需要告警抑制，所有检测到的告警都会立即发送
last_alert_time = {}  # {device_id: timestamp}（已废弃，不再使用）
alert_suppression_interval = 5.0  # 告警抑制间隔：5秒（已废弃，不再使用）
alert_time_lock = threading.Lock()  # 告警时间戳锁（已废弃，不再使用）

# 配置参数（抓拍算法链路）：优先 AI_*，其次 VIEW_*（与 stream_forward / 实时算法对齐），再回退通用变量
# 帧率：用于拉流侧节奏等；降低可减少 CPU 占用
SOURCE_FPS = int(os.getenv('AI_SOURCE_FPS', os.getenv('VIEW_SOURCE_FPS', os.getenv('SOURCE_FPS', '25'))))
# 分辨率：抓拍用于缩放后再抽帧/推理的目标分辨率（可与观看链路 VIEW_TARGET_* 对齐）
TARGET_WIDTH = int(os.getenv('AI_TARGET_WIDTH', os.getenv('VIEW_TARGET_WIDTH', os.getenv('TARGET_WIDTH', '1280'))))
TARGET_HEIGHT = int(os.getenv('AI_TARGET_HEIGHT', os.getenv('VIEW_TARGET_HEIGHT', os.getenv('TARGET_HEIGHT', '720'))))
TARGET_RESOLUTION = (TARGET_WIDTH, TARGET_HEIGHT)
EXTRACT_INTERVAL = int(os.getenv('EXTRACT_INTERVAL', '2'))
BUFFER_SIZE = int(os.getenv('BUFFER_SIZE', '70'))
MIN_BUFFER_FRAMES = int(os.getenv('MIN_BUFFER_FRAMES', '15'))
MAX_WAIT_TIME = float(os.getenv('MAX_WAIT_TIME', '0.08'))
# 抓拍任务不推 RTMP，无 FFmpeg 编码阶段（与实时推理服务的推流链路不同）
# YOLO检测参数（优化以降低CPU占用）
YOLO_IMG_SIZE = int(os.getenv('YOLO_IMG_SIZE', '640'))  # 高清场景下提升小目标检测和叠框细节
# 队列大小配置（优化以处理高负载）
DETECTION_QUEUE_SIZE = int(os.getenv('DETECTION_QUEUE_SIZE', '100'))  # 检测队列大小（默认100，原50）
PUSH_QUEUE_SIZE = int(os.getenv('PUSH_QUEUE_SIZE', '100'))  # 推帧队列大小（默认100，原50）
EXTRACT_QUEUE_SIZE = int(os.getenv('EXTRACT_QUEUE_SIZE', '1'))  # 抽帧队列大小（默认1，每个摄像头只保留1帧）
# 检测工作线程数量（优化以提升处理能力）
YOLO_WORKER_THREADS = int(os.getenv('YOLO_WORKER_THREADS', '2'))  # YOLO检测线程数（默认2，原1）
# 画质分档：优先 AI_VIDEO_QUALITY_PROFILE，其次 VIEW_VIDEO_QUALITY_PROFILE
VIDEO_QUALITY_PROFILE = os.getenv(
    'AI_VIDEO_QUALITY_PROFILE',
    os.getenv('VIEW_VIDEO_QUALITY_PROFILE', os.getenv('VIDEO_QUALITY_PROFILE', '')),
).strip().lower()
QUALITY_PROFILE_PRESETS = {
    'low': {
        'source_fps': 15,
        'target_width': 640,
        'target_height': 360,
        'yolo_img_size': 416,
    },
    'medium': {
        'source_fps': 20,
        'target_width': 1280,
        'target_height': 720,
        'yolo_img_size': 512,
    },
    'high': {
        'source_fps': 25,
        'target_width': 1280,
        'target_height': 720,
        'yolo_img_size': 640,
    },
}
if VIDEO_QUALITY_PROFILE in QUALITY_PROFILE_PRESETS:
    selected_profile = QUALITY_PROFILE_PRESETS[VIDEO_QUALITY_PROFILE]
    SOURCE_FPS = selected_profile['source_fps']
    TARGET_WIDTH = selected_profile['target_width']
    TARGET_HEIGHT = selected_profile['target_height']
    TARGET_RESOLUTION = (TARGET_WIDTH, TARGET_HEIGHT)
    YOLO_IMG_SIZE = selected_profile['yolo_img_size']
# 抓拍结果最大等待时长（秒）：超过该时长仍未返回检测结果则丢弃，避免延迟累积
SNAPSHOT_RESULT_MAX_WAIT_SEC = float(os.getenv('SNAPSHOT_RESULT_MAX_WAIT_SEC', '5.0'))

FACE_CLASS_KEYWORDS = ('face', 'facial', 'person_face', '人脸')
PLATE_CLASS_KEYWORDS = ('plate', 'license_plate', 'licence_plate', 'car_plate', '车牌')


def _normalize_detection_class_name(class_name: str) -> str:
    """标准化类别名，便于匹配中英文和不同命名风格。"""
    return str(class_name or '').strip().lower().replace('-', '_').replace(' ', '_')


def _is_face_class(class_name: str) -> bool:
    normalized = _normalize_detection_class_name(class_name)
    return any(keyword in normalized for keyword in FACE_CLASS_KEYWORDS)


def _is_plate_class(class_name: str) -> bool:
    normalized = _normalize_detection_class_name(class_name)
    return any(keyword in normalized for keyword in PLATE_CLASS_KEYWORDS)


def _should_keep_detection(class_name: str) -> bool:
    """
    根据任务配置过滤检测类别：
    - 关闭人脸检测时，过滤人脸类结果
    - 关闭车牌检测时，过滤车牌类结果
    """
    if not task_config:
        return True

    if _is_face_class(class_name) and not bool(getattr(task_config, 'face_detection_enabled', True)):
        return False
    if _is_plate_class(class_name) and not bool(getattr(task_config, 'plate_detection_enabled', True)):
        return False
    return True


def _is_valid_model_file(path: str) -> bool:
    """检查模型文件是否真实存在且非空（避免“下载成功但没落盘/0字节”）"""
    try:
        if not path:
            return False
        if not os.path.exists(path):
            return False
        return os.path.getsize(path) > 0
    except Exception:
        return False


def _build_absolute_url(maybe_path_or_url: str) -> Optional[str]:
    """将 /api/v1/... 之类的路径补全成可下载的 http(s)://... URL"""
    if not maybe_path_or_url:
        return None
    if maybe_path_or_url.startswith('http://') or maybe_path_or_url.startswith('https://'):
        return maybe_path_or_url
    if maybe_path_or_url.startswith('/'):
        # 浏览器经前端(如 8888)代理可访问 /api/v1/buckets/...，DEVICE 网关(48080)未必暴露该路径
        base = os.getenv('MODEL_DOWNLOAD_BASE_URL') or os.getenv('GATEWAY_URL') or 'http://localhost:48080'
        if not base.endswith('/'):
            base += '/'
        return urllib.parse.urljoin(base, maybe_path_or_url.lstrip('/'))
    return None


def _normalize_minio_endpoint(raw: str) -> str:
    """Minio 客户端要求 host:port，去掉误配的 scheme。"""
    s = (raw or '').strip()
    for prefix in ('https://', 'http://'):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    return s.rstrip('/')


def _download_model_from_minio_direct(bucket_name: str, object_key: str, local_path: str) -> bool:
    """
    在算法服务本机路径落盘（与 AI 服务的 download_model_forVideo 不同：后者写在 AI 容器内，
    跨容器时算法任务会收到 code=0 但本机文件不存在/为空）。
    需配置与 AI 模块一致的 MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY / MINIO_SECURE。
    """
    endpoint = _normalize_minio_endpoint(os.getenv('MINIO_ENDPOINT', '').strip())
    if not endpoint:
        return False
    try:
        from minio import Minio
        from minio.error import S3Error
    except ImportError:
        logger.warning('未安装 minio 包，跳过直连 MinIO 下载')
        return False
    access_key = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
    secret_key = os.getenv('MINIO_SECRET_KEY', 'minioadmin')
    secure = os.getenv('MINIO_SECURE', 'false').lower() == 'true'
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    tmp_path = f"{local_path}.minio.tmp"
    try:
        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        client.fget_object(bucket_name, object_key, tmp_path)
        if _is_valid_model_file(tmp_path):
            os.replace(tmp_path, local_path)
            return _is_valid_model_file(local_path)
        logger.warning(f"直连MinIO下载后文件无效: {tmp_path}")
        return False
    except S3Error as e:
        logger.warning(f"直连MinIO下载失败(S3): bucket={bucket_name}, object={object_key}, error={e}")
        return False
    except Exception as e:
        logger.warning(f"直连MinIO下载失败: bucket={bucket_name}, object={object_key}, error={e}")
        return False
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _download_url_to_file(url: str, dst_path: str, timeout=(5, 300)) -> bool:
    """下载URL到本地文件，成功返回True（会写临时文件再原子替换）"""
    if not url or not dst_path:
        return False
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    tmp_path = f"{dst_path}.tmp"
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(tmp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        if _is_valid_model_file(tmp_path):
            os.replace(tmp_path, dst_path)
            return _is_valid_model_file(dst_path)
        return False
    except Exception as e:
        logger.warning(f"从URL下载模型失败: url={url}, dst={dst_path}, error={str(e)}")
        return False
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def download_model_file(model_id: int, model_path: str) -> Optional[str]:
    """下载模型文件到本地

    Args:
        model_id: 模型ID（正数表示数据库模型，负数表示默认模型）
        model_path: 模型路径（MinIO URL或本地路径）

    Returns:
        str: 本地模型文件路径，失败返回None
    """
    try:
        video_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # 默认模型映射
        default_model_map = {
            -1: 'yolo11n.pt',
            -2: 'yolov8n.pt',
        }

        # 如果是负数ID，表示默认模型
        if model_id < 0:
            model_filename = default_model_map.get(model_id)
            if not model_filename:
                logger.error(f"未知的默认模型ID: {model_id}")
                return None

            # 默认模型路径：VIDEO目录下
            local_path = os.path.join(video_root, model_filename)
            if os.path.exists(local_path):
                logger.info(f"默认模型文件已存在: {local_path}")
                return local_path
            else:
                logger.warning(f"默认模型文件不存在: {local_path}，请确保文件已下载")
                return None

        # 正数ID，从数据库或MinIO下载
        # 创建模型存储目录
        model_storage_dir = os.path.join(video_root, 'data', 'models', str(model_id))
        os.makedirs(model_storage_dir, exist_ok=True)

        # 从model_path中提取文件名
        if not model_path:
            logger.error(f"模型 {model_id} 的路径为空")
            return None

        # 如果是MinIO URL，需要下载
        if model_path.startswith('/api/v1/buckets/'):
            try:
                parsed = urllib.parse.urlparse(model_path)
                path_parts = parsed.path.split('/')

                # 提取bucket名称
                if len(path_parts) >= 5 and path_parts[3] == 'buckets':
                    bucket_name = path_parts[4]
                else:
                    raise ValueError(f'URL格式不正确: {model_path}')

                # 提取object_key
                query_params = urllib.parse.parse_qs(parsed.query)
                object_key = query_params.get('prefix', [None])[0]

                if not object_key:
                    raise ValueError(f'URL中缺少prefix参数: {model_path}')

                filename = os.path.basename(object_key) or f"model_{model_id}.pt"
                local_path = os.path.join(model_storage_dir, filename)

                # 如果文件已存在，直接返回
                if os.path.exists(local_path):
                    logger.info(f"模型文件已存在，跳过下载: {local_path}")
                    return local_path

                # 优先本容器直连 MinIO（跨容器调用 AI 的 destination_path 会落在 AI 容器，导致本机文件始终无效）
                logger.info(f"开始从MinIO下载模型文件: bucket={bucket_name}, object={object_key}")
                if _download_model_from_minio_direct(bucket_name, object_key, local_path):
                    logger.info(
                        f"✅ 直连MinIO下载模型成功: {local_path} (size={os.path.getsize(local_path)})")
                    return local_path

                import requests
                import os as os_module

                ai_service_url = os_module.getenv('AI_SERVICE_URL', 'http://localhost:5000')
                try:
                    response = requests.post(
                        f"{ai_service_url}/model/download_model_forVideo",
                        headers={'X-Authorization': f'Bearer {os.getenv("JWT_TOKEN", "")}'},
                        json={
                            'bucket_name': bucket_name,
                            'object_key': object_key,
                            'destination_path': local_path
                        },
                        timeout=(5, 300)
                    )
                    if response.status_code == 200:
                        result = response.json()
                        if result.get('code') == 0:
                            if _is_valid_model_file(local_path):
                                logger.debug(f'模型下载完成: {local_path} (size={os.path.getsize(local_path)})')
                                return local_path
                            else:
                                size = None
                                try:
                                    size = os.path.getsize(local_path) if os.path.exists(local_path) else None
                                except Exception:
                                    pass
                                logger.error(f"下载返回成功但文件无效: {local_path} (size={size})，将尝试HTTP直链下载")
                                abs_url = _build_absolute_url(model_path)
                                if abs_url and _download_url_to_file(abs_url, local_path):
                                    logger.info(
                                        f"✅ 通过HTTP直链下载模型成功: {local_path} (size={os.path.getsize(local_path)})")
                                    return local_path
                                return None
                        else:
                            logger.warning(f"模型下载失败: {result}")
                            return None
                    else:
                        try:
                            err = response.json()
                            logger.warning(f"模型下载失败: {err}")
                        except Exception:
                            logger.warning(f"模型下载失败: HTTP {response.status_code}, {response.text}")
                        return None
                except Exception as e:
                    logger.warning(f"模型下载异常: {str(e)}")
                    return None

            except Exception as e:
                logger.error(f"解析MinIO URL失败: {str(e)}", exc_info=True)
                return None
        else:
            # 本地路径
            if os.path.isabs(model_path):
                local_path = model_path
            else:
                local_path = os.path.join(video_root, model_path)

            if os.path.exists(local_path):
                logger.info(f"模型文件已存在: {local_path}")
                return local_path
            else:
                logger.error(f"模型文件不存在: {local_path}")
                return None

    except Exception as e:
        logger.error(f"下载模型文件失败: model_id={model_id}, error={str(e)}", exc_info=True)
        return None


def load_yolo_models(model_ids: List[int]) -> Dict[int, Any]:
    """加载YOLO模型列表

    Args:
        model_ids: 模型ID列表（正数表示数据库模型，负数表示默认模型）

    Returns:
        Dict[int, YOLO]: 模型字典 {model_id: YOLO模型实例}
    """
    try:
        from ultralytics import YOLO

        models = {}

        for model_id in model_ids:
            try:
                # 默认模型映射
                default_model_map = {
                    -1: 'yolo11n.pt',
                    -2: 'yolov8n.pt',
                }

                # 如果是负数ID，表示默认模型
                if model_id < 0:
                    model_filename = default_model_map.get(model_id)
                    if not model_filename:
                        logger.warning(f"未知的默认模型ID: {model_id}，跳过")
                        continue

                    video_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    model_path = os.path.join(video_root, model_filename)

                    if not os.path.exists(model_path):
                        logger.warning(f"默认模型文件不存在: {model_path}，尝试从ultralytics下载")
                        # 尝试从ultralytics下载（如果本地不存在）
                        model_path = model_filename  # ultralytics会自动下载
                else:
                    # 正数ID，从数据库获取模型信息
                    import requests
                    import os as os_module
                    ai_service_url = os_module.getenv('AI_SERVICE_URL', 'http://localhost:5000')

                    try:
                        response = requests.get(
                            f"{ai_service_url}/model/{model_id}",
                            headers={'X-Authorization': f'Bearer {os_module.getenv("JWT_TOKEN", "")}'},
                            timeout=5
                        )
                        if response.status_code == 200:
                            model_data = response.json()
                            if model_data.get('code') == 0:
                                model_info = model_data.get('data', {})
                                model_path = model_info.get('model_path') or model_info.get('onnx_model_path')

                                if not model_path:
                                    logger.warning(f"模型 {model_id} 没有模型路径，跳过")
                                    continue

                                # 下载模型文件到本地
                                local_path = download_model_file(model_id, model_path)
                                if local_path:
                                    model_path = local_path
                                else:
                                    # 对于MinIO下载URL，如果落盘失败则不要继续用URL当本地路径加载YOLO
                                    if isinstance(model_path, str) and model_path.startswith('/api/v1/buckets/'):
                                        # 兜底：尝试HTTP直链下载到本地
                                        video_root = os.path.dirname(
                                            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                                        model_storage_dir = os.path.join(video_root, 'data', 'models', str(model_id))
                                        os.makedirs(model_storage_dir, exist_ok=True)

                                        filename = f"model_{model_id}.pt"
                                        try:
                                            parsed = urllib.parse.urlparse(model_path)
                                            query_params = urllib.parse.parse_qs(parsed.query)
                                            object_key = query_params.get('prefix', [None])[0]
                                            if object_key:
                                                filename = os.path.basename(object_key) or filename
                                        except Exception:
                                            pass
                                        fallback_local = os.path.join(model_storage_dir, filename)
                                        abs_url = _build_absolute_url(model_path)
                                        if abs_url and _download_url_to_file(abs_url, fallback_local):
                                            model_path = fallback_local
                                            logger.info(
                                                f"✅ 兜底HTTP下载成功，将使用本地模型文件加载: model_id={model_id}, path={model_path}")
                                        else:
                                            logger.error(
                                                f"模型 {model_id} 下载失败（落盘/直链均失败），跳过该模型以避免加载失败: {model_path}")
                                            continue
                                    logger.warning(f"模型 {model_id} 下载失败，尝试使用原始路径")
                            else:
                                logger.warning(f"获取模型 {model_id} 信息失败: {model_data.get('msg')}")
                                continue
                        else:
                            logger.warning(f"获取模型 {model_id} 信息失败: HTTP {response.status_code}")
                            continue
                    except Exception as e:
                        logger.warning(f"获取模型 {model_id} 信息异常: {str(e)}")
                        continue

                # 加载YOLO模型
                logger.info(f"正在加载YOLO模型: model_id={model_id}, path={model_path}")
                yolo_model = YOLO(str(model_path))
                models[model_id] = yolo_model
                logger.info(f"✅ YOLO模型加载成功: model_id={model_id}")

            except Exception as e:
                logger.error(f"❌ 加载YOLO模型失败: model_id={model_id}, error={str(e)}", exc_info=True)
                continue

        return models

    except Exception as e:
        logger.error(f"加载YOLO模型列表失败: {str(e)}", exc_info=True)
        return {}


def load_task_config():
    """从数据库加载任务配置（重启时会重新加载，确保获取最新的摄像头信息）"""
    global task_config, yolo_models, tracker

    try:
        logger.info(f"🔄 正在从数据库重新加载任务配置: task_id={TASK_ID}")
        # 刷新数据库会话，确保获取最新数据
        db_session.expire_all()

        task = db_session.query(AlgorithmTask).filter_by(id=TASK_ID).first()
        if not task:
            logger.error(f"任务 {TASK_ID} 不存在")
            return False

        task_config = task

        # 解析模型ID列表
        model_ids = []
        if task.model_ids:
            try:
                model_ids = json.loads(task.model_ids) if isinstance(task.model_ids, str) else task.model_ids
            except:
                pass

        if not model_ids:
            logger.error(f"任务 {TASK_ID} 没有配置模型ID列表")
            return False

        # 加载YOLO模型列表
        yolo_models = load_yolo_models(model_ids)
        if not yolo_models:
            logger.error(f"任务 {TASK_ID} 没有成功加载任何模型")
            return False

        logger.info(f"✅ 成功加载 {len(yolo_models)} 个YOLO模型")

        # 从摄像头列表获取输入流地址（支持RTSP和RTMP）
        # 注意：抓拍算法任务不推流，只读取输入流
        device_streams = {}
        if task.devices:
            # 刷新设备关联关系，确保获取最新的设备信息
            db_session.refresh(task)
            for device in task.devices:
                # 刷新设备对象，确保获取最新的source
                db_session.refresh(device)
                # 输入流地址（支持RTSP/RTMP，以及通过gb28181://虚拟源动态解析）
                rtsp_url = resolve_gb28181_source(device.source, logger=logger) if device.source else None
                if not rtsp_url:
                    logger.warning(f"设备 {device.id} 未获取到可用输入流地址，跳过该设备")
                    continue
                device_streams[device.id] = {
                    'rtsp_url': rtsp_url,  # 输入流地址
                    'device_name': device.name or device.id
                }
                input_type = "RTSP" if rtsp_url and rtsp_url.startswith(
                    'rtsp://') else "RTMP" if rtsp_url and rtsp_url.startswith('rtmp://') else "输入流"
                logger.info(f"📹 设备 {device.id} ({device.name or device.id}): {input_type}={rtsp_url}")

        # 将设备流地址信息存储到task_config中（通过动态属性）
        task_config.device_streams = device_streams

        # 为每个摄像头初始化独立的资源
        for device_id, stream_info in device_streams.items():
            # 初始化帧缓存队列
            frame_buffers[device_id] = {}
            buffer_locks[device_id] = threading.Lock()
            frame_counts[device_id] = 0

            # 初始化队列（使用可配置的大小）
            extract_queues[device_id] = queue.Queue(maxsize=EXTRACT_QUEUE_SIZE)
            detection_queues[device_id] = queue.Queue(maxsize=DETECTION_QUEUE_SIZE)
            push_queues[device_id] = queue.Queue(maxsize=PUSH_QUEUE_SIZE)

            # 初始化cron相关变量（清理旧状态）
            if device_id in device_last_extract_cron_time:
                device_last_extract_cron_time.pop(device_id, None)

            # 初始化追踪器（如果启用）
            if task.tracking_enabled:
                trackers[device_id] = SimpleTracker(
                    similarity_threshold=task.tracking_similarity_threshold,
                    max_age=task.tracking_max_age,
                    smooth_alpha=task.tracking_smooth_alpha
                )
                logger.info(f"设备 {device_id} 追踪器初始化成功")

        # 记录cron表达式配置（如果存在）
        cron_expression = getattr(task, 'cron_expression', None)
        if cron_expression and cron_expression.strip():
            logger.info(f"⏰ 抓拍算法任务已配置cron表达式: {cron_expression}，将按cron时间执行抽帧")
        else:
            logger.info(f"⏰ 抓拍算法任务未配置cron表达式，将按抽帧间隔持续抽帧")

        logger.info(f"任务配置加载成功: {task.task_name}, 模型IDs: {model_ids}, 关联设备数: {len(device_streams)}")

        if task.tracking_enabled:
            logger.info(f"已为 {len(trackers)} 个设备初始化追踪器")

        return True
    except Exception as e:
        logger.error(f"加载任务配置失败: {str(e)}", exc_info=True)
        return False


# 存储每个设备上次抽帧的cron时间点（用于确保每个cron时间点只抽1帧）
device_last_extract_cron_time = {}  # {device_id: 上次抽帧的cron时间点（datetime对象）}
device_extract_cron_lock = threading.Lock()  # 保护device_last_extract_cron_time的锁


def should_extract_frame_by_cron(device_id: str, current_time: float) -> bool:
    """检查当前时间是否匹配cron表达式，决定是否应该抽帧
    确保每个cron时间点只抽1帧，抽完后停止，直到下一个cron时间点

    Args:
        device_id: 设备ID
        current_time: 当前时间戳

    Returns:
        bool: True表示应该抽帧，False表示不应该抽帧（静默）
    """
    global task_config, device_last_extract_cron_time

    # 如果没有任务配置，默认允许抽帧（向后兼容）
    if not task_config:
        return True

    # 获取cron表达式（仅抓拍算法任务有cron配置）
    cron_expression = getattr(task_config, 'cron_expression', None)

    # 如果没有配置cron表达式，默认允许抽帧（向后兼容）
    if not cron_expression or not cron_expression.strip():
        return True

    try:
        # 每次检查时都创建新的cron迭代器，基于当前时间
        current_dt = datetime.fromtimestamp(current_time)
        cron_iter = croniter(cron_expression, current_dt)

        # 获取当前时间的上一个执行时间（这是当前应该执行的cron时间点）
        prev_time = cron_iter.get_prev(datetime)
        next_time = cron_iter.get_next(datetime)

        # 计算时间差
        time_since_prev = (current_dt - prev_time).total_seconds()
        time_to_next = (next_time - current_dt).total_seconds()

        # 判断当前时间是否在cron执行时间窗口内
        # 只检查距离上一个执行时间是否在窗口内（前后各2秒的容差窗口）
        cron_window = 2.0  # cron执行时间窗口（秒）
        # 确保当前时间在prev_time之后，且距离prev_time小于窗口时间
        in_cron_window = time_since_prev >= 0 and time_since_prev < cron_window

        # 确保每个cron时间点只抽1帧（使用锁保护，避免并发问题）
        should_extract = False
        if in_cron_window:
            # 使用锁保护，确保原子性检查和更新
            with device_extract_cron_lock:
                # 检查是否已经在当前cron时间点抽过帧了
                last_extract_cron_time = device_last_extract_cron_time.get(device_id)

                # 如果还没有抽过帧，或者上次抽帧的cron时间点与当前不同，则允许抽帧
                if last_extract_cron_time is None or last_extract_cron_time != prev_time:
                    should_extract = True
                    # 立即更新上次抽帧的cron时间点（在返回True之前就更新，避免并发问题）
                    device_last_extract_cron_time[device_id] = prev_time
                    logger.info(
                        f"⏰ 设备 {device_id} cron匹配，允许抽帧: 当前时间={current_dt.strftime('%Y-%m-%d %H:%M:%S')}, cron时间点={prev_time.strftime('%Y-%m-%d %H:%M:%S')}, 距离上一个执行时间={time_since_prev:.2f}秒")
                else:
                    # 已经在当前cron时间点抽过帧了，不再抽帧
                    should_extract = False
                    logger.debug(
                        f"🔇 设备 {device_id} 已在当前cron时间点抽过帧，跳过: cron时间点={prev_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            # 不在cron时间窗口内，不抽帧
            should_extract = False

        return should_extract

    except Exception as e:
        logger.error(f"❌ 设备 {device_id} 检查cron表达式失败: cron={cron_expression}, error={str(e)}", exc_info=True)
        # 出错时默认不允许抽帧，避免影响正常功能
        return False


def send_alert_event_async(alert_data: Dict):
    """异步发送告警事件到 sink hook 接口（后台线程）- 抓拍算法任务专用"""

    def _send():
        try:
            device_id = alert_data.get('device_id')
            if not task_config or not task_config.alert_event_enabled:
                logger.warning(
                    f"⚠️  告警事件未启用，跳过发送: device_id={device_id}, alert_event_enabled={task_config.alert_event_enabled if task_config else None}")
                return

            logger.info(
                f"🚨 开始异步发送告警事件: device_id={device_id}, object={alert_data.get('object')}, event={alert_data.get('event')}")

            # 通过 HTTP 发送告警事件到 sink hook 接口
            # sink 会负责将告警投入 Kafka
            try:
                # 标记为抓拍算法任务（确保task_type正确传递）
                alert_data['task_type'] = 'snapshot'
                # 检测开关由算法服务透传给 alert_hook_service，避免 alert_hook_service 再查库
                if 'face_detection_enabled' not in alert_data:
                    alert_data['face_detection_enabled'] = bool(
                        getattr(task_config, 'face_detection_enabled', False)
                    )
                if 'plate_detection_enabled' not in alert_data:
                    alert_data['plate_detection_enabled'] = bool(
                        getattr(task_config, 'plate_detection_enabled', False)
                    )
                # 如果information是字典，也添加task_type
                if 'information' in alert_data and isinstance(alert_data['information'], dict):
                    alert_data['information']['task_type'] = 'snapshot'
                response = requests.post(
                    ALERT_HOOK_URL,
                    json=alert_data,
                    timeout=5,
                    headers={'Content-Type': 'application/json'}
                )
                if response.status_code == 200:
                    logger.debug(f"告警事件已发送到 sink hook: device_id={device_id}")
                else:
                    logger.warning(
                        f"发送告警事件到 sink hook 失败: status_code={response.status_code}, response={response.text}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"发送告警事件到 sink hook 异常: {str(e)}")
        except Exception as e:
            logger.error(f"❌ 发送告警事件失败: device_id={alert_data.get('device_id')}, error={str(e)}", exc_info=True)

    # 在后台线程中异步执行
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def cleanup_alert_images(alert_image_dir: str, max_images: int = 300, keep_ratio: float = 0.1):
    """清理告警图片目录，当图片数量超过限制时，删除最旧的图片

    Args:
        alert_image_dir: 告警图片目录路径
        max_images: 最大图片数量，超过此数量时触发清理（默认300张）
        keep_ratio: 保留比例（0.0-1.0），例如0.1表示保留最新的10%（删除90%）
    """
    try:
        if not os.path.exists(alert_image_dir):
            return

        # 获取所有jpg图片文件
        image_files = []
        for filename in os.listdir(alert_image_dir):
            if filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'):
                file_path = os.path.join(alert_image_dir, filename)
                if os.path.isfile(file_path):
                    # 获取文件修改时间
                    mtime = os.path.getmtime(file_path)
                    image_files.append((file_path, mtime))

        total_images = len(image_files)

        # 如果图片数量未超过限制，不需要清理
        if total_images <= max_images:
            return

        # 按修改时间排序（最旧的在前）
        image_files.sort(key=lambda x: x[1])

        # 计算需要保留的图片数量（最新的10%）
        keep_count = max(1, int(total_images * keep_ratio))

        # 计算需要删除的图片数量（最旧的90%）
        delete_count = total_images - keep_count

        # 删除最旧的图片
        deleted_count = 0
        for i in range(delete_count):
            try:
                file_path = image_files[i][0]
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"删除告警图片失败: {file_path}, 错误: {str(e)}")

        if deleted_count > 0:
            logger.info(
                f"告警图片清理完成: 目录={alert_image_dir}, 总数={total_images}, 删除={deleted_count}, 保留={keep_count}")
    except Exception as e:
        logger.error(f"清理告警图片失败: {str(e)}", exc_info=True)


def cleanup_srs_recordings(srs_record_dir: str = '/data/playbacks', max_recordings: int = 500, keep_ratio: float = 0.1):
    """清理SRS录像目录，当录像数量超过限制时，删除最旧的录像

    Args:
        srs_record_dir: SRS录像目录路径，默认为 /data/playbacks
        max_recordings: 最大录像数量，超过此数量时触发清理
        keep_ratio: 保留比例（0.0-1.0），例如0.1表示保留最新的10%
    """
    try:
        if not os.path.exists(srs_record_dir):
            logger.debug(f"SRS录像目录不存在: {srs_record_dir}")
            return

        # 递归获取所有.flv录像文件
        recording_files = []
        for root, dirs, files in os.walk(srs_record_dir):
            for filename in files:
                if filename.lower().endswith('.flv'):
                    file_path = os.path.join(root, filename)
                    if os.path.isfile(file_path):
                        # 获取文件修改时间
                        try:
                            mtime = os.path.getmtime(file_path)
                            recording_files.append((file_path, mtime))
                        except Exception as e:
                            logger.warning(f"获取文件修改时间失败: {file_path}, 错误: {str(e)}")
                            continue

        total_recordings = len(recording_files)

        # 如果录像数量未超过限制，不需要清理
        if total_recordings <= max_recordings:
            logger.debug(f"SRS录像目录检查: 总数={total_recordings}, 未超过限制={max_recordings}")
            return

        # 按修改时间排序（最旧的在前）
        recording_files.sort(key=lambda x: x[1])

        # 计算需要保留的录像数量（最新的10%）
        keep_count = max(1, int(total_recordings * keep_ratio))

        # 计算需要删除的录像数量（最旧的90%）
        delete_count = total_recordings - keep_count

        # 不再删除 /data/playbacks 目录下的录像文件，只记录统计信息
        if delete_count > 0:
            logger.debug(
                f"SRS录像统计: 目录={srs_record_dir}, 总数={total_recordings}, 应删除={delete_count}, 保留={keep_count}（已禁用删除 /data/playbacks 逻辑）")
    except Exception as e:
        logger.error(f"清理SRS录像失败: {str(e)}", exc_info=True)


def save_alert_image(frame: np.ndarray, device_id: str, frame_number: int, detection: Dict) -> Optional[str]:
    """保存告警图片到本地目录

    Args:
        frame: 图片帧
        device_id: 设备ID
        frame_number: 帧号
        detection: 检测结果字典

    Returns:
        图片保存路径，如果保存失败返回None
    """
    try:
        # 创建告警图片保存目录（ALERT_IMAGES_DIR=/app/alert_images 与 iot-sink 挂载对齐）
        video_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        images_root = resolve_alert_images_root(video_root)
        alert_image_dir = os.path.join(images_root, f'task_{TASK_ID}', device_id)
        os.makedirs(alert_image_dir, exist_ok=True)

        # 生成图片文件名（包含时间戳和帧号）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        track_id = detection.get('track_id', 0)
        class_name = detection.get('class_name', 'unknown')
        image_filename = f"{timestamp}_frame{frame_number}_track{track_id}_{class_name}.jpg"
        image_path = os.path.join(alert_image_dir, image_filename)

        # 保存图片
        cv2.imwrite(image_path, frame)

        logger.debug(f"告警图片已保存: {image_path}")

        # 保存后检查并清理旧图片（超过300张时，删除最旧的90%）
        cleanup_alert_images(alert_image_dir, max_images=300, keep_ratio=0.1)

        return image_path
    except Exception as e:
        logger.error(f"保存告警图片失败: {str(e)}", exc_info=True)
        return None


def send_heartbeat():
    """发送心跳到VIDEO服务"""
    try:
        import socket
        import os as os_module

        # 获取服务器IP
        server_ip = os_module.getenv('POD_IP', '')
        if not server_ip:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                server_ip = s.getsockname()[0]
                s.close()
            except:
                server_ip = 'localhost'

        # 获取进程ID
        process_id = os_module.getpid()

        # 构建日志路径
        video_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_base_dir = os.path.join(video_root, 'logs')
        log_path = os.path.join(log_base_dir, f'task_{TASK_ID}')

        # 构建心跳URL
        heartbeat_url = f"http://localhost:{VIDEO_SERVICE_PORT}/video/algorithm/heartbeat/realtime"

        # 发送心跳
        response = requests.post(
            heartbeat_url,
            json={
                'task_id': TASK_ID,
                'server_ip': server_ip,
                'port': None,  # 实时算法服务不监听端口
                'process_id': process_id,
                'log_path': log_path
            },
            timeout=5
        )
        response.raise_for_status()
        logger.debug(f"心跳上报成功: task_id={TASK_ID}")
    except Exception as e:
        logger.warning(f"心跳上报失败: {str(e)}")


def heartbeat_worker():
    """心跳上报工作线程"""
    logger.info("💓 心跳上报线程启动")
    while not stop_event.is_set():
        try:
            send_heartbeat()
            # 每10秒发送一次心跳
            for _ in range(10):
                if stop_event.is_set():
                    break
                time.sleep(1)
        except Exception as e:
            logger.error(f"心跳上报线程异常: {str(e)}", exc_info=True)
            time.sleep(10)
    logger.info("💓 心跳上报线程停止")


def srs_recording_cleanup_worker():
    """SRS录像清理工作线程"""
    logger.info("🧹 SRS录像清理线程启动")
    # 获取SRS录像目录路径（可通过环境变量配置，默认为 /data/playbacks）
    srs_record_dir = os.getenv('SRS_RECORD_DIR', '/data/playbacks')

    while not stop_event.is_set():
        try:
            # 清理SRS录像目录（超过500个时，删除最旧的90%）
            cleanup_srs_recordings(srs_record_dir, max_recordings=500, keep_ratio=0.1)
            # 每60秒检查一次
            for _ in range(60):
                if stop_event.is_set():
                    break
                time.sleep(1)
        except Exception as e:
            logger.error(f"SRS录像清理线程异常: {str(e)}", exc_info=True)
            time.sleep(60)
    logger.info("🧹 SRS录像清理线程停止")


def save_tracking_target(track_data: Dict):
    """处理追踪目标（不保存到数据库，仅用于追踪逻辑）"""
    # 不再保存到数据库，仅用于追踪逻辑处理
    pass


def save_tracking_targets_periodically():
    """定期处理追踪目标（后台线程，不保存到数据库）"""
    logger.info("💾 追踪目标处理线程启动（不保存到数据库）")
    while not stop_event.is_set():
        try:
            if task_config and task_config.tracking_enabled:
                # 仅用于追踪逻辑处理，不保存到数据库
                for device_id, tracker in trackers.items():
                    try:
                        # 获取需要处理的追踪目标（用于追踪逻辑，不保存）
                        tracks_to_process = tracker.get_tracks_for_save()
                        # 这里可以添加其他追踪相关的处理逻辑，但不保存到数据库
                        if tracks_to_process and len(tracks_to_process) > 0:
                            logger.debug(f"设备 {device_id} 有 {len(tracks_to_process)} 个追踪目标需要处理")
                    except Exception as e:
                        logger.error(f"处理设备 {device_id} 的追踪目标失败: {str(e)}", exc_info=True)

            # 每5秒检查一次
            for _ in range(50):
                if stop_event.is_set():
                    break
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"追踪目标处理线程异常: {str(e)}", exc_info=True)
            time.sleep(5)
    logger.info("💾 追踪目标处理线程停止")


def check_and_stop_existing_stream(stream_url: str):
    """检查并停止现有的 RTMP 流（通过 SRS HTTP API）

    当检测到流已存在时，会检查流是否真的在活动：
    1. 如果流存在但没有活跃的发布者（僵尸连接），直接清理流资源
    2. 如果流存在且有发布者，检查发布者连接是否真的在活动
    3. 如果发布者连接已断开，强制清理流资源
    4. 如果发布者连接正常，断开发布者连接

    Args:
        stream_url: RTMP流地址，格式如 rtmp://localhost:1935/live/stream
    """
    try:
        # 从 RTMP URL 中提取流名称和主机
        # rtmp://localhost:1935/live/test_input -> live/test_input
        if not stream_url.startswith('rtmp://'):
            logger.warning("⚠️  无效的RTMP URL格式，跳过流检查")
            return

        # 解析URL: rtmp://host:port/path -> (host, port, path)
        url_part = stream_url.replace('rtmp://', '')
        if '/' in url_part:
            host_port = url_part.split('/')[0]
            stream_path = '/'.join(url_part.split('/')[1:])
        else:
            host_port = url_part
            stream_path = ""

        if not stream_path:
            logger.warning("⚠️  无法从 URL 中提取流路径，跳过流检查")
            return

        # 提取主机地址（用于SRS API调用）
        if ':' in host_port:
            rtmp_host = host_port.split(':')[0]
        else:
            rtmp_host = host_port

        # 重要：算法服务可能使用 host 网络模式，必须使用 localhost 访问 SRS
        # 如果 RTMP URL 中使用的是容器名（如 srs-server 或 srs），需要强制转换为 localhost
        # 这样可以避免在 host 网络模式下尝试解析容器名导致的连接失败
        if rtmp_host in ['srs-server', 'srs', 'SRS']:
            logger.info(f'检测到 SRS 配置使用容器名 {rtmp_host}，强制转换为 localhost（算法服务可能使用 host 网络模式）')
            rtmp_host = 'localhost'

        # SRS HTTP API 地址（默认端口 1985）
        srs_api_url = f"http://{rtmp_host}:1985/api/v1/streams/"
        srs_clients_api_url = f"http://{rtmp_host}:1985/api/v1/clients/"

        logger.info(f"🔍 检查现有流: {stream_path}")

        try:
            # 获取所有流
            response = requests.get(srs_api_url, timeout=3)
            if response.status_code == 200:
                streams = response.json()

                # 查找匹配的流
                stream_to_stop = None
                if isinstance(streams, dict) and 'streams' in streams:
                    stream_list = streams['streams']
                elif isinstance(streams, list):
                    stream_list = streams
                else:
                    stream_list = []

                for stream in stream_list:
                    stream_name = stream.get('name', '')
                    stream_app = stream.get('app', '')
                    stream_stream = stream.get('stream', '')

                    # 匹配流路径（格式：app/stream）
                    # 使用精确匹配，避免误匹配其他流
                    full_stream_path = f"{stream_app}/{stream_stream}" if stream_stream else stream_app

                    # 精确匹配：只有当流路径完全匹配时才停止
                    # 这样可以避免误停止其他设备的流
                    if stream_path == full_stream_path:
                        stream_to_stop = stream
                        break

                if stream_to_stop:
                    stream_id = stream_to_stop.get('id', '')
                    publish_info = stream_to_stop.get('publish', {})
                    publish_cid = publish_info.get('cid', '') if isinstance(publish_info, dict) else None

                    logger.warning(f"⚠️  发现现有流: {stream_path} (ID: {stream_id})")

                    # 检查是否有活跃的发布者
                    if not publish_cid:
                        # 流存在但没有发布者（僵尸流），直接清理
                        logger.warning(f"   流存在但没有活跃的发布者（僵尸流），直接清理...")
                        try:
                            stop_url = f"{srs_api_url}{stream_id}"
                            stop_response = requests.delete(stop_url, timeout=3)
                            if stop_response.status_code in [200, 204]:
                                logger.info(f"✅ 已清理僵尸流: {stream_path}")
                                time.sleep(1)  # 等待流完全停止
                                return
                        except Exception as e:
                            logger.warning(f"   清理僵尸流异常: {str(e)}")
                    else:
                        # 有发布者ID，检查发布者连接是否真的在活动
                        logger.info(f"   检查发布者连接状态: {publish_cid}")
                        try:
                            # 获取客户端信息，检查连接是否真的存在
                            client_info_url = f"{srs_clients_api_url}{publish_cid}"
                            client_response = requests.get(client_info_url, timeout=2)

                            if client_response.status_code == 200:
                                client_info = client_response.json()
                                # 检查客户端是否真的在活动
                                client_active = client_info.get('active', True) if isinstance(client_info,
                                                                                              dict) else True

                                if not client_active:
                                    # 客户端已断开，清理僵尸流
                                    logger.warning(f"   发布者连接已断开（僵尸连接），清理流资源...")
                                    try:
                                        stop_url = f"{srs_api_url}{stream_id}"
                                        stop_response = requests.delete(stop_url, timeout=3)
                                        if stop_response.status_code in [200, 204]:
                                            logger.info(f"✅ 已清理僵尸流: {stream_path}")
                                            time.sleep(1)
                                            return
                                    except Exception as e:
                                        logger.warning(f"   清理僵尸流异常: {str(e)}")
                                else:
                                    # 客户端连接正常，尝试断开
                                    logger.info(f"   发布者连接正常，尝试断开连接...")
                                    try:
                                        stop_response = requests.delete(client_info_url, timeout=3)
                                        if stop_response.status_code in [200, 204]:
                                            logger.info(f"✅ 已断开发布者客户端，流将自动停止")
                                            time.sleep(2)  # 等待流完全停止
                                            return
                                        else:
                                            logger.warning(
                                                f"   断开客户端失败 (状态码: {stop_response.status_code})，尝试其他方法...")
                                    except Exception as e:
                                        logger.warning(f"   断开客户端异常: {str(e)}，尝试其他方法...")
                            else:
                                # 无法获取客户端信息，可能连接已断开，尝试清理流
                                logger.warning(
                                    f"   无法获取发布者信息 (状态码: {client_response.status_code})，可能连接已断开，尝试清理流...")
                                try:
                                    # 先尝试断开客户端（即使可能已断开）
                                    try:
                                        requests.delete(client_info_url, timeout=2)
                                    except:
                                        pass

                                    # 然后清理流
                                    stop_url = f"{srs_api_url}{stream_id}"
                                    stop_response = requests.delete(stop_url, timeout=3)
                                    if stop_response.status_code in [200, 204]:
                                        logger.info(f"✅ 已清理流: {stream_path}")
                                        time.sleep(1)
                                        return
                                except Exception as e:
                                    logger.warning(f"   清理流异常: {str(e)}")
                        except requests.exceptions.RequestException as e:
                            # 无法连接到客户端API，可能连接已断开，尝试清理流
                            logger.warning(f"   无法连接到客户端API: {str(e)}，尝试清理流...")
                            try:
                                stop_url = f"{srs_api_url}{stream_id}"
                                stop_response = requests.delete(stop_url, timeout=3)
                                if stop_response.status_code in [200, 204]:
                                    logger.info(f"✅ 已清理流: {stream_path}")
                                    time.sleep(1)
                                    return
                            except Exception as e2:
                                logger.warning(f"   清理流异常: {str(e2)}")

                    # 方法2: 尝试通过流ID停止（某些SRS版本支持）
                    logger.info(f"   尝试通过流ID停止: {stream_id}")
                    stop_url = f"{srs_api_url}{stream_id}"
                    try:
                        stop_response = requests.delete(stop_url, timeout=3)
                        if stop_response.status_code in [200, 204]:
                            logger.info(f"✅ 已停止现有流: {stream_path}")
                            time.sleep(2)  # 等待流完全停止
                            return
                        else:
                            logger.warning(f"   停止流失败 (状态码: {stop_response.status_code})")
                    except Exception as e:
                        logger.warning(f"   停止流异常: {str(e)}")

                    # 方法3: 如果API都失败，尝试查找并杀死占用该流的ffmpeg进程
                    logger.warning(f"⚠️  API方法失败，尝试查找占用该流的进程...")
                    try:
                        # 查找推流到该地址的ffmpeg进程
                        result = subprocess.run(
                            ["pgrep", "-f", f"rtmp://.*{stream_path.split('/')[-1]}"],
                            capture_output=True,
                            text=True,
                            timeout=3
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            pids = result.stdout.strip().split('\n')
                            for pid in pids:
                                if pid.strip():
                                    logger.info(f"   发现进程 PID: {pid.strip()}，正在终止...")
                                    try:
                                        subprocess.run(["kill", "-TERM", pid.strip()], timeout=2)
                                        time.sleep(1)
                                        logger.info(f"✅ 已终止进程: {pid.strip()}")
                                    except:
                                        pass
                            time.sleep(2)  # 等待进程完全退出
                            return
                    except Exception as e:
                        logger.warning(f"   查找进程失败: {str(e)}")

                    logger.warning(f"⚠️  无法停止现有流，但将继续尝试推流...")
                else:
                    logger.info(f"✅ 未发现现有流: {stream_path}")
            else:
                logger.warning(f"⚠️  无法获取流列表 (状态码: {response.status_code})，继续尝试推流...")

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️  无法连接到 SRS API: {str(e)}，继续尝试推流...")

    except Exception as e:
        logger.warning(f"⚠️  检查现有流时出错: {str(e)}，继续尝试推流...")


def _is_likely_rtsp_flat_corrupt_frame(
    frame,
    std_max: float = 4.0,
    mean_lo: float = 80.0,
    mean_hi: float = 180.0,
) -> bool:
    """
    典型解码「中灰塌缩」屏；仅中灰且极低方差判定，避免夜景误杀。
    """
    if frame is None or frame.size == 0:
        return True
    try:
        if len(frame.shape) == 2:
            gray = frame
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _mean, _std = cv2.meanStdDev(gray)
        m, s = float(_mean[0][0]), float(_std[0][0])
        return bool(mean_lo <= m <= mean_hi and s < std_max)
    except Exception:
        return False


def buffer_streamer_worker(device_id: str):
    """缓流器工作线程：为指定摄像头缓冲源流，接收推帧器插入的帧，输出到目标流"""
    logger.info(f"💾 缓流器线程启动 [设备: {device_id}]")

    if not task_config or not hasattr(task_config, 'device_streams'):
        logger.error(f"任务配置未加载，设备 {device_id} 缓流器退出")
        return

    device_stream_info = task_config.device_streams.get(device_id)
    if not device_stream_info:
        logger.error(f"设备 {device_id} 流信息不存在，缓流器退出")
        return

    rtsp_url = device_stream_info.get('rtsp_url')
    device_name = device_stream_info.get('device_name', device_id)

    # 打印输入流地址信息
    logger.info(f"📺 设备 {device_id} 流地址配置:")
    input_stream_type = "RTSP" if rtsp_url and rtsp_url.startswith(
        'rtsp://') else "RTMP" if rtsp_url and rtsp_url.startswith('rtmp://') else "输入流"
    logger.info(f"   {input_stream_type}输入流: {rtsp_url}")

    if not rtsp_url:
        logger.error(f"设备 {device_id} 输入流地址不存在，缓流器退出")
        return

    # 兼容 RTSP 和 RTMP 两种格式的输入流
    stream_type = "RTSP" if rtsp_url.startswith('rtsp://') else "RTMP" if rtsp_url.startswith('rtmp://') else "未知"
    logger.info(f"📡 设备 {device_id} 输入流类型: {stream_type}")

    cap = None
    frame_width = None
    frame_height = None
    next_output_frame = 1
    retry_count = 0
    max_retries = 5
    rtsp_open_timeout_msec = int(os.getenv("RTSP_OPEN_TIMEOUT_MSEC", "5000"))
    rtsp_read_timeout_msec = int(os.getenv("RTSP_READ_TIMEOUT_MSEC", "2500"))
    rtsp_retry_delay_sec = max(0.1, float(os.getenv("RTSP_RETRY_DELAY_SEC", "1")))
    rtsp_retry_cooldown_sec = max(1.0, float(os.getenv("RTSP_RETRY_COOLDOWN_SEC", "8")))
    rtsp_read_fail_delay_sec = max(0.1, float(os.getenv("RTSP_READ_FAIL_DELAY_SEC", "0.3")))
    pending_frames = set()

    # 流畅度优化：基于时间戳的帧率控制
    frame_interval = 1.0 / SOURCE_FPS
    last_frame_time = time.time()
    max_push_process_per_cycle = 20

    # 灰屏重连（默认开启；与实时算法服务一致，见 AI_RTSP_GRAY_*）
    _gray_reconnect = (os.getenv("AI_RTSP_GRAY_RECONNECT", "1").strip().lower() not in ("0", "false", "no", "off"))
    try:
        _gray_streak_need = max(1, int((os.getenv("AI_RTSP_GRAY_STREAK", "20").strip() or "20")))
    except Exception:
        _gray_streak_need = 20

    def _gray_float(name: str, default: float) -> float:
        try:
            return float((os.getenv(name) or "").strip() or default)
        except Exception:
            return default

    _gray_std_max = _gray_float("AI_RTSP_GRAY_STD_MAX", 4.0)
    _gray_mean_lo = _gray_float("AI_RTSP_GRAY_MEAN_LO", 80.0)
    _gray_mean_hi = _gray_float("AI_RTSP_GRAY_MEAN_HI", 180.0)
    _gray_warmup_sec = _gray_float("AI_RTSP_GRAY_WARMUP_SEC", 15.0)
    _gray_reconnect_delay = _gray_float("AI_RTSP_GRAY_RECONNECT_DELAY_SEC", 2.0)
    gray_bad_streak = 0
    last_rtsp_connect_time = 0.0

    def process_detection_results_and_cleanup():
        """异步消费检测结果并清理超时帧，避免检测慢导致延迟累积。"""
        processed_count = 0
        while processed_count < max_push_process_per_cycle:
            try:
                push_data = push_queues[device_id].get_nowait()
                processed_frame = push_data['frame']
                fn = push_data['frame_number']
                detections = push_data.get('detections', [])

                frame_data = None
                with buffer_locks[device_id]:
                    frame_buffer = frame_buffers[device_id]
                    if fn in frame_buffer:
                        frame_buffer[fn]['frame'] = processed_frame
                        frame_buffer[fn]['processed'] = True
                        frame_buffer[fn]['detections'] = detections
                        frame_data = frame_buffer[fn]
                    pending_frames.discard(fn)

                # 帧可能已超时清理；若仍有检测结果，仍需发告警（否则检测完成即丢事件）
                if not frame_data:
                    if detections and task_config and task_config.alert_event_enabled:
                        frame_ts = push_data.get('timestamp', time.time())
                        logger.info(
                            f"🚨 设备 {device_id} 抽帧帧 {fn}（缓冲区已释放）补发告警：检测到 {len(detections)} 个目标"
                        )
                        for det in detections:
                            try:
                                image_path = save_alert_image(
                                    processed_frame,
                                    device_id,
                                    fn,
                                    det
                                )
                                algorithm_name = task_config.task_name if task_config and hasattr(
                                    task_config, 'task_name') else 'detection'
                                alert_data = {
                                    'object': det.get('class_name', 'unknown'),
                                    'event': algorithm_name,
                                    'device_id': device_id,
                                    'device_name': device_name,
                                    'face_detection_enabled': bool(
                                        getattr(task_config, 'face_detection_enabled', False)
                                    ),
                                    'plate_detection_enabled': bool(
                                        getattr(task_config, 'plate_detection_enabled', False)
                                    ),
                                    'time': datetime.fromtimestamp(frame_ts).strftime('%Y-%m-%d %H:%M:%S'),
                                    'information': json.dumps({
                                        'track_id': det.get('track_id', 0),
                                        'confidence': det.get('confidence', 0),
                                        'bbox': det.get('bbox', []),
                                        'frame_number': fn,
                                        'first_seen_time': datetime.fromtimestamp(
                                            det.get('first_seen_time', frame_ts)
                                        ).isoformat() if det.get('first_seen_time') else None,
                                        'duration': det.get('duration', 0)
                                    }),
                                    'image_path': image_path if image_path else None,
                                }
                                logger.info(
                                    f"📤 设备 {device_id} 抽帧帧 {fn}（补发）异步发送告警: object={alert_data['object']}"
                                )
                                send_alert_event_async(alert_data)
                            except Exception as e:
                                logger.error(f"发送告警失败: {str(e)}", exc_info=True)
                    processed_count += 1
                    continue

                output_frame = frame_data['frame']
                frame_timestamp = frame_data.get('timestamp', time.time())

                # 只在抽帧的帧上发送告警
                if detections and task_config and task_config.alert_event_enabled:
                    logger.info(f"🚨 设备 {device_id} 抽帧帧 {fn} 开始发送告警：检测到 {len(detections)} 个目标")
                    # 发送告警（每个检测结果发送一次）
                    for det in detections:
                        try:
                            # 保存告警图片到本地
                            image_path = save_alert_image(
                                output_frame,
                                device_id,
                                fn,
                                det
                            )

                            # 构建告警数据（参照告警表字段）
                            # 获取算法名称（任务名称）
                            algorithm_name = task_config.task_name if task_config and hasattr(
                                task_config, 'task_name') else 'detection'

                            alert_data = {
                                'object': det.get('class_name', 'unknown'),
                                'event': algorithm_name,  # 使用算法名称作为事件类型
                                'device_id': device_id,
                                'device_name': device_name,
                                'face_detection_enabled': bool(
                                    getattr(task_config, 'face_detection_enabled', False)
                                ),
                                'plate_detection_enabled': bool(
                                    getattr(task_config, 'plate_detection_enabled', False)
                                ),
                                'time': datetime.fromtimestamp(frame_timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                                'information': json.dumps({
                                    'track_id': det.get('track_id', 0),
                                    'confidence': det.get('confidence', 0),
                                    'bbox': det.get('bbox', []),
                                    'frame_number': fn,
                                    'first_seen_time': datetime.fromtimestamp(
                                        det.get('first_seen_time', frame_timestamp)
                                    ).isoformat() if det.get('first_seen_time') else None,
                                    'duration': det.get('duration', 0)
                                }),
                                # 不直接传输图片，而是传输图片所在磁盘路径
                                'image_path': image_path if image_path else None,
                            }

                            # 异步发送告警事件
                            logger.info(
                                f"📤 设备 {device_id} 抽帧帧 {fn} 异步发送告警事件: object={alert_data['object']}, event={alert_data['event']}")
                            send_alert_event_async(alert_data)
                        except Exception as e:
                            logger.error(f"发送告警失败: {str(e)}", exc_info=True)

                # 告警发送（或无告警）后清理该帧
                with buffer_locks[device_id]:
                    frame_buffer = frame_buffers[device_id]
                    frame_buffer.pop(fn, None)
                logger.info(f"✅ 设备 {device_id} 抽帧帧 {fn} 处理完成，已清理")
                processed_count += 1
            except queue.Empty:
                break

        # 超时清理：异步模式下定期回收过期未完成帧，防止延迟累积
        now_ts = time.time()
        timed_out_frames = []
        with buffer_locks[device_id]:
            frame_buffer = frame_buffers[device_id]
            for fn, frame_data in list(frame_buffer.items()):
                frame_ts = frame_data.get('timestamp', now_ts)
                if now_ts - frame_ts > SNAPSHOT_RESULT_MAX_WAIT_SEC:
                    timed_out_frames.append(fn)

            for fn in timed_out_frames:
                frame_buffer.pop(fn, None)
                pending_frames.discard(fn)

        if timed_out_frames:
            logger.warning(
                f"⚠️  设备 {device_id} 超时清理抓拍帧 {len(timed_out_frames)} 个: {timed_out_frames[:5]}"
                f"{'...' if len(timed_out_frames) > 5 else ''}"
            )

    while not stop_event.is_set():
        try:
            # 打开源流（支持 RTSP 和 RTMP）
            if cap is None or not cap.isOpened():
                stream_type = "RTSP" if rtsp_url.startswith('rtsp://') else "RTMP" if rtsp_url.startswith(
                    'rtmp://') else "流"

                logger.info(f"正在连接设备 {device_id} 的 {stream_type} 流: {rtsp_url} (重试次数: {retry_count})")

                # 强制使用 FFmpeg 后端，避免 OpenCV 尝试其他后端导致错误
                try:
                    # 对于 RTMP/RTSP 流，使用 FFmpeg 后端
                    if rtsp_url.startswith('rtmp://') or rtsp_url.startswith('rtsp://'):
                        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                    else:
                        cap = cv2.VideoCapture(rtsp_url)

                    # 设置缓冲区大小为1，减少延迟
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                    # 设置超时参数（毫秒）- 对于 RTMP/RTSP 流设置合理的超时
                    # 注意：这些属性可能在某些 OpenCV 版本中不可用，使用 try-except 处理
                    if rtsp_url.startswith('rtmp://') or rtsp_url.startswith('rtsp://'):
                        try:
                            # 设置连接超时（毫秒）
                            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, rtsp_open_timeout_msec)
                        except (AttributeError, cv2.error):
                            # 如果属性不存在，忽略错误
                            pass
                        try:
                            # 设置读取超时（毫秒）
                            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, rtsp_read_timeout_msec)
                        except (AttributeError, cv2.error):
                            # 如果属性不存在，忽略错误
                            pass

                except Exception as e:
                    logger.error(f"设备 {device_id} 创建 VideoCapture 时出错: {str(e)}")
                    # 确保释放资源
                    if cap is not None:
                        try:
                            cap.release()
                        except:
                            pass
                        cap = None
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"❌ 设备 {device_id} 连接 {stream_type} 流失败，已达到最大重试次数 {max_retries}")
                        logger.info(f"等待{rtsp_retry_cooldown_sec:.1f}秒后重新尝试...")
                        time.sleep(rtsp_retry_cooldown_sec)
                        retry_count = 0
                    else:
                        logger.warning(
                            f"设备 {device_id} 无法打开 {stream_type} 流，等待重试... ({retry_count}/{max_retries})")
                        time.sleep(rtsp_retry_delay_sec)
                    continue

                if not cap.isOpened():
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"❌ 设备 {device_id} 连接 {stream_type} 流失败，已达到最大重试次数 {max_retries}")
                        logger.info(f"等待{rtsp_retry_cooldown_sec:.1f}秒后重新尝试...")
                        time.sleep(rtsp_retry_cooldown_sec)
                        retry_count = 0
                    else:
                        logger.warning(
                            f"设备 {device_id} 无法打开 {stream_type} 流，等待重试... ({retry_count}/{max_retries})")
                        time.sleep(rtsp_retry_delay_sec)
                    # 确保释放资源
                    if cap is not None:
                        try:
                            cap.release()
                        except:
                            pass
                        cap = None
                    continue

                retry_count = 0
                device_caps[device_id] = cap
                logger.info(f"✅ 设备 {device_id} {stream_type} 流连接成功")
                if rtsp_url.startswith("rtsp://"):
                    last_rtsp_connect_time = time.time()

            # 从源流读取帧
            ret, frame = cap.read()

            if not ret or frame is None:
                logger.warning(f"设备 {device_id} 读取源流帧失败，重新连接...")
                if cap is not None:
                    cap.release()
                    cap = None
                    device_caps.pop(device_id, None)
                gray_bad_streak = 0
                time.sleep(rtsp_read_fail_delay_sec)
                continue

            if (
                rtsp_url.startswith("rtsp://")
                and _gray_reconnect
                and (time.time() - last_rtsp_connect_time) >= _gray_warmup_sec
                and _is_likely_rtsp_flat_corrupt_frame(
                    frame, _gray_std_max, _gray_mean_lo, _gray_mean_hi
                )
            ):
                gray_bad_streak += 1
                if gray_bad_streak >= _gray_streak_need:
                    logger.warning(
                        f"设备 {device_id} 连续 {gray_bad_streak} 帧疑似解码灰屏/塌缩，释放并重连 RTSP"
                    )
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap = None
                        device_caps.pop(device_id, None)
                    gray_bad_streak = 0
                    process_detection_results_and_cleanup()
                    time.sleep(max(0.5, _gray_reconnect_delay))
                    continue
                process_detection_results_and_cleanup()
                continue
            gray_bad_streak = 0

            # 抓拍算法任务：只在cron时间点处理1帧，其他帧完全跳过
            current_timestamp = time.time()

            # 检查cron表达式，如果不在cron时间点，直接跳过这帧
            if not should_extract_frame_by_cron(device_id, current_timestamp):
                # 不在cron时间点也要消费检测结果，避免结果堆积到下一次cron才处理
                process_detection_results_and_cleanup()
                continue

            # 到了cron时间点，处理这1帧
            # 更新该设备的帧计数（仅用于日志）
            frame_counts[device_id] += 1
            frame_count = frame_counts[device_id]

            # 缩放到目标分辨率（与 stream_forward 的 FFmpeg lanczos 思路一致，使用 OpenCV Lanczos）
            original_height, original_width = frame.shape[:2]
            if (original_width, original_height) != TARGET_RESOLUTION:
                frame = cv2.resize(frame, TARGET_RESOLUTION, interpolation=cv2.INTER_LANCZOS4)

            # 将帧发送到抽帧队列进行分析（队列容量为1，新帧会顶掉旧帧）
            pending_frames.add(frame_count)
            frame_sent = False
            try:
                # 尝试直接放入
                extract_queues[device_id].put_nowait({
                    'frame': frame,
                    'frame_number': frame_count,
                    'timestamp': current_timestamp,
                    'device_id': device_id
                })
                frame_sent = True
                logger.info(
                    f"📸 设备 {device_id} 在cron时间点抽帧: 帧号={frame_count}, 时间={datetime.fromtimestamp(current_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
            except queue.Full:
                # 队列已满，取出旧的帧（顶一个），再放入新的
                try:
                    old_frame_data = extract_queues[device_id].get_nowait()
                    logger.debug(
                        f"🔄 设备 {device_id} 抽帧队列已满，丢弃旧帧 {old_frame_data.get('frame_number')}，放入新帧 {frame_count}")
                except queue.Empty:
                    pass
                # 再次尝试放入新帧
                try:
                    extract_queues[device_id].put_nowait({
                        'frame': frame,
                        'frame_number': frame_count,
                        'timestamp': current_timestamp,
                        'device_id': device_id
                    })
                    frame_sent = True
                    logger.info(
                        f"📸 设备 {device_id} 在cron时间点抽帧: 帧号={frame_count}, 时间={datetime.fromtimestamp(current_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
                except queue.Full:
                    logger.warning(f"⚠️  设备 {device_id} 抽帧队列放入失败，帧 {frame_count} 被丢弃")

            # 将帧存入缓冲区（仅用于等待检测结果和发送告警）
            with buffer_locks[device_id]:
                frame_buffer = frame_buffers[device_id]
                frame_buffer[frame_count] = {
                    'frame': frame,
                    'frame_number': frame_count,
                    'timestamp': current_timestamp,
                    'processed': False,
                    'is_extracted': True  # 标记为抽帧的帧
                }

            # 低延迟模式：抽帧后不阻塞等待检测结果，继续读取最新流帧。
            # 检测结果在下方异步消费并发送告警，避免单帧慢检测拖慢整体。

            process_detection_results_and_cleanup()

            # 优化CPU占用：短暂休眠，避免频繁读取帧
            time.sleep(0.1)  # 100ms

        except Exception as e:
            logger.error(f"❌ 设备 {device_id} 缓流器异常: {str(e)}", exc_info=True)
            time.sleep(2)

    # 清理资源
    if cap is not None:
        cap.release()
        device_caps.pop(device_id, None)

    logger.info(f"💾 设备 {device_id} 缓流器线程停止")


def extractor_worker():
    """抽帧器工作线程：从多个摄像头的缓流器获取帧，抽帧并标记位置"""
    logger.info("📹 抽帧器线程启动（多摄像头并行）")

    while not stop_event.is_set():
        try:
            has_work = False
            # 遍历所有设备的抽帧队列
            for device_id, extract_queue in extract_queues.items():
                try:
                    frame_data = extract_queue.get_nowait()
                    frame = frame_data['frame']
                    frame_number = frame_data['frame_number']
                    timestamp = frame_data['timestamp']
                    device_id_from_data = frame_data.get('device_id', device_id)
                    frame_id = f"{device_id_from_data}_frame_{frame_number}_{int(timestamp)}"

                    has_work = True

                    # 将帧发送给YOLO检测（带设备ID和位置信息）
                    detection_queue = detection_queues.get(device_id_from_data)
                    if detection_queue:
                        frame_sent = False
                        retry_count = 0
                        max_retries = 20  # 增加重试次数
                        while not frame_sent and retry_count < max_retries:
                            try:
                                detection_queue.put_nowait({
                                    'frame_id': frame_id,
                                    'frame': frame,
                                    'frame_number': frame_number,
                                    'timestamp': timestamp,
                                    'device_id': device_id_from_data
                                })
                                frame_sent = True
                                if frame_number % 10 == 0:
                                    logger.info(f"✅ 抽帧器 [{device_id_from_data}]: {frame_id} (帧号: {frame_number})")
                            except queue.Full:
                                retry_count += 1
                                if retry_count < max_retries:
                                    # 如果队列持续满，尝试丢弃最旧的帧（仅在重试多次后）
                                    if retry_count >= 15:
                                        try:
                                            # 尝试获取并丢弃一个旧帧
                                            detection_queue.get_nowait()
                                            logger.debug(
                                                f"🔄 设备 {device_id_from_data} 检测队列满，丢弃最旧帧以腾出空间")
                                        except queue.Empty:
                                            pass
                                    time.sleep(0.01)
                                else:
                                    logger.warning(
                                        f"⚠️  设备 {device_id_from_data} 检测队列已满，帧 {frame_id} 多次重试失败（队列大小: {DETECTION_QUEUE_SIZE}, 当前队列长度: {detection_queue.qsize()}）")
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"❌ 设备 {device_id} 抽帧器异常: {str(e)}", exc_info=True)

            # 优化CPU占用：如果本轮没有工作，增加sleep时间
            if not has_work:
                time.sleep(0.05)  # 50ms，减少空轮询
            else:
                time.sleep(0.01)  # 10ms，有工作时短暂休眠

        except Exception as e:
            logger.error(f"❌ 抽帧器异常: {str(e)}", exc_info=True)
            time.sleep(1)

    logger.info("📹 抽帧器线程停止")


def draw_detections(frame, tracked_detections, frame_number=None, tracking_enabled=False):
    """在帧上绘制检测结果

    Args:
        frame: 输入帧
        tracked_detections: 检测结果列表
        frame_number: 帧号
        tracking_enabled: 是否启用追踪
            - False: 画框 + 显示类别名（text）
            - True: 画框 + 显示类别名 + ID（text），不画卡片
    """
    import cv2
    from datetime import datetime

    if not tracked_detections:
        return frame

    annotated_frame = frame.copy()

    for tracked_det in tracked_detections:
        bbox = tracked_det.get('bbox', [])
        if not bbox or len(bbox) != 4:
            continue

        x1, y1, x2, y2 = bbox
        # 确保坐标在有效范围内
        h, w = annotated_frame.shape[:2]
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))

        class_name = tracked_det.get('class_name', 'unknown')
        confidence = tracked_det.get('confidence', 0.0)
        track_id = tracked_det.get('track_id', 0)
        is_cached = tracked_det.get('is_cached', False)
        first_seen_time = tracked_det.get('first_seen_time', time.time())
        duration = tracked_det.get('duration', 0.0)

        # 根据是否为缓存框选择颜色和样式
        if is_cached:
            color = (0, 200, 0)  # 稍暗的亮绿色
            thickness = 2
            alpha = 0.7
        else:
            color = (0, 255, 0)  # 亮绿色 (BGR格式)
            thickness = 2
            alpha = 1.0

        # 画框
        if is_cached:
            overlay = annotated_frame.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, thickness)
            cv2.addWeighted(overlay, alpha, annotated_frame, 1 - alpha, 0, annotated_frame)
        else:
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, thickness)

        # 绘制文字标签（根据是否启用追踪显示不同内容）
        font_scale = 0.8  # 增大字体
        font_thickness = 2  # 加粗字体

        # 根据是否启用追踪决定显示内容
        if tracking_enabled:
            # 启用追踪：显示类别名 + ID
            text = f"ID:{track_id} {class_name}"
        else:
            # 未启用追踪：只显示类别名
            text = class_name

        # 计算文字大小
        (text_width, text_height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                                                              font_thickness)

        # 在框的上方显示文字（不画背景卡片）
        text_x = x1
        text_y = max(text_height + 5, y1 - 5)

        # 只绘制文字，不绘制背景卡片
        cv2.putText(annotated_frame, text, (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, font_thickness)

    return annotated_frame


def yolo_detection_worker(worker_id: int):
    """YOLO检测工作线程：使用YOLO模型进行识别和画框（多摄像头并行）"""
    logger.info(f"🤖 YOLO检测线程 {worker_id} 启动（多摄像头并行）")

    consecutive_errors = 0
    max_consecutive_errors = 10

    while not stop_event.is_set():
        try:
            has_work = False
            # 遍历所有设备的检测队列
            for device_id, detection_queue in detection_queues.items():
                try:
                    detection_data = detection_queue.get_nowait()
                    frame = detection_data['frame']
                    frame_number = detection_data['frame_number']
                    timestamp = detection_data['timestamp']
                    device_id_from_data = detection_data.get('device_id', device_id)
                    frame_id = detection_data.get('frame_id', f"{device_id_from_data}_frame_{frame_number}")

                    has_work = True
                    consecutive_errors = 0  # 重置错误计数

                    # 减少日志输出
                    if frame_number % 10 == 0:
                        logger.info(f"🔍 [Worker {worker_id}] 开始检测: {frame_id}")

                    # 使用所有YOLO模型进行检测（合并结果，优化参数以降低CPU占用）
                    all_detections = []
                    try:
                        for model_id, yolo_model in yolo_models.items():
                            try:
                                # 优化检测参数以降低CPU占用：
                                # - imgsz: 降低检测分辨率（默认416，原640）
                                # - conf: 保持默认置信度阈值
                                # - iou: 保持默认IOU阈值
                                # - device: 使用CPU（如果支持GPU可改为'cuda'）
                                results = yolo_model(
                                    frame,
                                    conf=0.25,
                                    iou=0.45,
                                    imgsz=YOLO_IMG_SIZE,  # 使用配置的检测分辨率（默认416，原640）
                                    verbose=False,
                                    half=False,
                                    device=get_infer_device(device_id_from_data)
                                )
                                result = results[0]

                                if result.boxes is not None and len(result.boxes) > 0:
                                    boxes = result.boxes.xyxy.cpu().numpy()
                                    confidences = result.boxes.conf.cpu().numpy()
                                    class_ids = result.boxes.cls.cpu().numpy().astype(int)

                                    for box, conf, cls_id in zip(boxes, confidences, class_ids):
                                        x1, y1, x2, y2 = map(int, box)
                                        class_name = yolo_model.names[cls_id]
                                        if not _should_keep_detection(class_name):
                                            continue
                                        all_detections.append({
                                            'class_id': int(cls_id),
                                            'class_name': class_name,
                                            'confidence': float(conf),
                                            'bbox': [int(x1), int(y1), int(x2), int(y2)]
                                        })
                            except Exception as e:
                                logger.error(f"❌ 模型 {model_id} 检测异常: {str(e)}", exc_info=True)
                                continue
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(f"❌ YOLO检测异常: {str(e)} (连续错误: {consecutive_errors})", exc_info=True)
                        if consecutive_errors >= max_consecutive_errors:
                            logger.error(f"❌ 连续错误过多，等待10秒后继续...")
                            time.sleep(10)
                            consecutive_errors = 0
                        continue

                    # 如果启用追踪，进行目标追踪
                    tracked_detections = []
                    if task_config and task_config.tracking_enabled:
                        tracker = trackers.get(device_id_from_data)
                        if tracker:
                            tracked_detections = tracker.update(all_detections, frame_number, current_time=timestamp)
                        else:
                            tracked_detections = [
                                dict(det, track_id=0, is_cached=False, first_seen_time=timestamp, duration=0.0) for det
                                in all_detections]
                    else:
                        tracked_detections = [
                            dict(det, track_id=0, is_cached=False, first_seen_time=timestamp, duration=0.0) for det in
                            all_detections]

                    # 在帧上绘制检测结果
                    if tracked_detections:
                        processed_frame = draw_detections(
                            frame,
                            tracked_detections,
                            frame_number,
                            tracking_enabled=task_config.tracking_enabled if task_config else False
                        )
                        if frame_number % 10 == 0:
                            logger.info(
                                f"🎨 [Worker {worker_id}] 帧 {frame_number} 绘制了 {len(tracked_detections)} 个检测框")
                    else:
                        processed_frame = frame

                    # 构建检测结果列表（用于后续处理）
                    detections = []
                    for tracked_det in tracked_detections:
                        detections.append({
                            'track_id': tracked_det.get('track_id', 0),
                            'class_id': tracked_det.get('class_id', 0),
                            'class_name': tracked_det.get('class_name', 'unknown'),
                            'confidence': tracked_det.get('confidence', 0.0),
                            'bbox': tracked_det.get('bbox', []),
                            'timestamp': timestamp,
                            'frame_id': frame_id,
                            'frame_number': frame_number,
                            'is_cached': tracked_det.get('is_cached', False),
                            'first_seen_time': tracked_det.get('first_seen_time', timestamp),
                            'duration': tracked_det.get('duration', 0.0)
                        })

                    # 将处理后的帧发送到推帧队列
                    push_queue = push_queues.get(device_id_from_data)
                    if push_queue:
                        frame_sent = False
                        retry_count = 0
                        max_retries = 20  # 增加重试次数
                        while not frame_sent and retry_count < max_retries:
                            try:
                                push_queue.put_nowait({
                                    'frame': processed_frame,
                                    'frame_number': frame_number,
                                    'detections': detections,
                                    'device_id': device_id_from_data,
                                    'timestamp': timestamp
                                })
                                frame_sent = True
                                if frame_number % 10 == 0:
                                    logger.info(
                                        f"✅ [Worker {worker_id}] 检测完成: {frame_id} (帧号: {frame_number}), 检测到 {len(detections)} 个目标")
                            except queue.Full:
                                retry_count += 1
                                if retry_count < max_retries:
                                    # 如果队列持续满，尝试丢弃最旧的帧（仅在重试多次后）
                                    if retry_count >= 15:
                                        try:
                                            # 尝试获取并丢弃一个旧帧
                                            push_queue.get_nowait()
                                            logger.debug(
                                                f"🔄 设备 {device_id_from_data} 推帧队列满，丢弃最旧帧以腾出空间")
                                        except queue.Empty:
                                            pass
                                    time.sleep(0.01)
                                else:
                                    logger.warning(
                                        f"⚠️  设备 {device_id_from_data} 推帧队列已满，帧 {frame_id} 多次重试失败（队列大小: {PUSH_QUEUE_SIZE}, 当前队列长度: {push_queue.qsize()}）")
                except queue.Empty:
                    continue
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(f"❌ 设备 {device_id} YOLO检测异常: {str(e)} (连续错误: {consecutive_errors})",
                                 exc_info=True)
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(f"❌ 连续错误过多，等待10秒后继续...")
                        time.sleep(10)
                        consecutive_errors = 0
                    else:
                        time.sleep(1)

            # 优化CPU占用：如果本轮没有工作，增加sleep时间
            if not has_work:
                time.sleep(0.05)  # 50ms，减少空轮询
            else:
                time.sleep(0.01)  # 10ms，有工作时短暂休眠

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"❌ YOLO检测异常: {str(e)} (连续错误: {consecutive_errors})", exc_info=True)
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"❌ 连续错误过多，等待10秒后继续...")
                time.sleep(10)
                consecutive_errors = 0
            else:
                time.sleep(1)

    logger.info(f"🤖 YOLO检测线程 {worker_id} 停止")


def cleanup_all_resources():
    """清理所有资源（VideoCapture等）"""
    logger.info("🧹 开始清理所有资源...")

    # 注意：抓拍算法任务不推流，不需要清理FFmpeg推送进程

    # 清理所有VideoCapture对象
    for device_id, cap in list(device_caps.items()):
        if cap is not None:
            try:
                logger.info(f"🛑 释放设备 {device_id} 的VideoCapture")
                cap.release()
            except Exception as e:
                logger.error(f"❌ 释放设备 {device_id} 的VideoCapture失败: {str(e)}")
        device_caps.pop(device_id, None)

    logger.info("✅ 所有资源已清理")


def signal_handler(sig, frame):
    """信号处理器"""
    logger.info("\n🛑 收到停止信号，正在关闭所有服务...")
    stop_event.set()

    # 清理所有资源（FFmpeg进程、VideoCapture等）
    cleanup_all_resources()

    # 等待所有线程结束（增加等待时间）
    logger.info("⏳ 等待所有线程结束...")
    time.sleep(3)

    logger.info("✅ 所有服务已停止")
    sys.exit(0)


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🚀 抓拍算法任务服务启动")
    logger.info("=" * 60)
    logger.info("📊 优化配置参数:")
    logger.info(f"   视频分辨率: {TARGET_WIDTH}x{TARGET_HEIGHT} (原1280x720)")
    logger.info(f"   视频帧率: {SOURCE_FPS}fps (原25fps)")
    logger.info(f"   YOLO检测分辨率: {YOLO_IMG_SIZE} (原640)")
    logger.info(f"   检测队列大小: {DETECTION_QUEUE_SIZE} (原50)")
    logger.info(f"   推帧队列大小: {PUSH_QUEUE_SIZE} (原50)")
    logger.info(f"   YOLO检测线程数: {YOLO_WORKER_THREADS} (原1)")
    logger.info("=" * 60)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 加载任务配置（失败不退出：定时重试，避免守护进程重启风暴）
    retry_interval = int(os.getenv('TASK_CONFIG_RETRY_INTERVAL', '10'))
    while not stop_event.is_set():
        ok = load_task_config()
        if ok:
            break
        logger.error(f"❌ 任务配置加载失败，将在 {retry_interval}s 后重试（不会退出进程）")
        for _ in range(retry_interval):
            if stop_event.is_set():
                break
            time.sleep(1)
    if stop_event.is_set():
        logger.info("收到停止信号，退出启动流程")
        return

    # 为每个摄像头启动独立的缓流器线程
    buffer_threads = []
    if hasattr(task_config, 'device_streams'):
        for device_id in task_config.device_streams.keys():
            logger.info(f"💾 启动设备 {device_id} 的缓流器线程...")
            buffer_thread = threading.Thread(target=buffer_streamer_worker, args=(device_id,), daemon=True)
            buffer_thread.start()
            buffer_threads.append(buffer_thread)

    # 启动共享的抽帧器线程（处理所有摄像头）
    logger.info("📹 启动抽帧器线程（多摄像头并行）...")
    extractor_thread = threading.Thread(target=extractor_worker, daemon=True)
    extractor_thread.start()

    # 启动YOLO检测线程（处理所有摄像头，支持多线程）
    logger.info(f"🤖 启动 {YOLO_WORKER_THREADS} 个YOLO检测线程（多摄像头并行）...")
    yolo_threads = []
    for worker_id in range(1, YOLO_WORKER_THREADS + 1):
        yolo_thread = threading.Thread(target=yolo_detection_worker, args=(worker_id,), daemon=True)
        yolo_thread.start()
        yolo_threads.append(yolo_thread)
        logger.info(f"   ✅ YOLO检测线程 {worker_id} 已启动")

    # 启动心跳上报线程
    logger.info("💓 启动心跳上报线程...")
    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat_thread.start()

    # 启动SRS录像清理线程
    logger.info("🧹 启动SRS录像清理线程...")
    srs_cleanup_thread = threading.Thread(target=srs_recording_cleanup_worker, daemon=True)
    srs_cleanup_thread.start()

    # 启动追踪目标保存线程（如果启用追踪）
    if task_config and task_config.tracking_enabled:
        logger.info("💾 启动追踪目标保存线程...")
        tracking_save_thread = threading.Thread(target=save_tracking_targets_periodically, daemon=True)
        tracking_save_thread.start()

    logger.info("=" * 60)
    logger.info("✅ 所有服务已启动")
    logger.info("=" * 60)
    logger.info("按 Ctrl+C 停止所有服务")
    logger.info("=" * 60)

    # 主循环
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)
    except Exception as e:
        logger.error(f"❌ 主循环异常: {str(e)}", exc_info=True)
        signal_handler(None, None)


if __name__ == "__main__":
    main()
