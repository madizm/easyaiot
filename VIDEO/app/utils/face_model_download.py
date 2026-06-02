"""人脸特征提取模型 face_rec.onnx 下载与状态查询"""
import os
import threading
import tempfile
import urllib.request
import zipfile
from typing import Any, Dict

from app.utils.face_model_paths import FACE_MATCH_MODEL_PATH

FACE_REC_DOWNLOAD_URL = os.getenv(
    'FACE_REC_MODEL_DOWNLOAD_URL',
    'https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip',
)
# GitHub v0.7 发行包为根目录 w600k_r50.onnx；部分镜像/旧包为 buffalo_l/ 前缀
ONNX_ZIP_CANDIDATES = ('w600k_r50.onnx', 'buffalo_l/w600k_r50.onnx')
# 完整模型约 167MB，低于此阈值视为未下载或损坏
MIN_MODEL_SIZE_BYTES = 10 * 1024 * 1024
# buffalo_l.zip 约 280MB，用于 Content-Length 缺失时的进度估算
ESTIMATED_ZIP_SIZE_BYTES = 280 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 256 * 1024
DOWNLOAD_USER_AGENT = 'EasyAIoT-VIDEO/1.0'

_lock = threading.Lock()
_state: Dict[str, Any] = {
    'status': 'idle',  # idle | downloading | done | error
    'stage': 'idle',  # idle | downloading | extracting | done | error
    'progress': 0,
    'downloaded_bytes': 0,
    'total_bytes': 0,
    'error': None,
}


def _reset_error_if_idle() -> None:
    if _state['status'] == 'idle':
        _state['error'] = None


def is_face_rec_model_available() -> bool:
    if not os.path.isfile(FACE_MATCH_MODEL_PATH):
        return False
    try:
        return os.path.getsize(FACE_MATCH_MODEL_PATH) >= MIN_MODEL_SIZE_BYTES
    except OSError:
        return False


def _build_status_locked() -> Dict[str, Any]:
    exists = is_face_rec_model_available()
    size_bytes = os.path.getsize(FACE_MATCH_MODEL_PATH) if exists else 0
    _reset_error_if_idle()
    downloading = _state['status'] == 'downloading'
    stage = _state['stage']
    if exists:
        stage = 'done'
    elif not downloading and _state['status'] == 'error':
        stage = 'error'
    elif not downloading:
        stage = 'idle'
    return {
        'exists': exists,
        'filename': os.path.basename(FACE_MATCH_MODEL_PATH),
        'path': FACE_MATCH_MODEL_PATH,
        'size_bytes': size_bytes,
        'downloading': downloading,
        'stage': stage,
        'progress': int(_state['progress']) if downloading or exists else 0,
        'downloaded_bytes': int(_state['downloaded_bytes']),
        'total_bytes': int(_state['total_bytes']),
        'error': _state['error'],
    }


def get_face_rec_model_status() -> Dict[str, Any]:
    with _lock:
        return _build_status_locked()


def _set_progress(stage: str, progress: int, downloaded: int = 0, total: int = 0) -> None:
    with _lock:
        _state['stage'] = stage
        _state['downloaded_bytes'] = downloaded
        if total > 0:
            _state['total_bytes'] = total
        _state['progress'] = max(int(_state['progress']), int(progress))


def _download_with_progress(url: str, dest_path: str) -> None:
    req = urllib.request.Request(url, headers={'User-Agent': DOWNLOAD_USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        content_length = int(resp.headers.get('Content-Length', 0) or 0)
        total = content_length or ESTIMATED_ZIP_SIZE_BYTES
        _set_progress('downloading', 1, downloaded=0, total=total)

        downloaded = 0
        with open(dest_path, 'wb') as out_file:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                progress = min(85, int(downloaded * 85 / total)) if total else 0
                _set_progress('downloading', progress, downloaded=downloaded, total=total)


def _resolve_onnx_member(zf: zipfile.ZipFile) -> str:
    names = set(zf.namelist())
    for candidate in ONNX_ZIP_CANDIDATES:
        if candidate in names:
            return candidate
    for name in zf.namelist():
        if name.rstrip('/').endswith('w600k_r50.onnx'):
            return name
    onnx_entries = [n for n in zf.namelist() if n.lower().endswith('.onnx')]
    raise KeyError(
        'archive 中未找到 w600k_r50.onnx '
        f'(已尝试 {ONNX_ZIP_CANDIDATES})，当前 onnx 条目: {onnx_entries}'
    )


def _extract_onnx(zip_path: str, target_path: str) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        member = _resolve_onnx_member(zf)
        info = zf.getinfo(member)
        total = info.file_size or MIN_MODEL_SIZE_BYTES
        written = 0
        _set_progress('extracting', 86, downloaded=0, total=total)

        with zf.open(member) as src, open(target_path, 'wb') as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                written += len(chunk)
                progress = 86 + min(13, int(written * 13 / total))
                _set_progress('extracting', progress, downloaded=written, total=total)


def _do_download() -> None:
    tmp_dir = tempfile.mkdtemp(prefix='face_rec_model_')
    zip_path = os.path.join(tmp_dir, 'buffalo_l.zip')
    partial_path = f'{FACE_MATCH_MODEL_PATH}.downloading'
    try:
        with _lock:
            _state['status'] = 'downloading'
            _state['stage'] = 'downloading'
            _state['progress'] = 0
            _state['downloaded_bytes'] = 0
            _state['total_bytes'] = ESTIMATED_ZIP_SIZE_BYTES
            _state['error'] = None

        _download_with_progress(FACE_REC_DOWNLOAD_URL, zip_path)

        with _lock:
            _state['progress'] = max(int(_state['progress']), 85)

        _extract_onnx(zip_path, partial_path)
        os.replace(partial_path, FACE_MATCH_MODEL_PATH)

        with _lock:
            _state['status'] = 'done'
            _state['stage'] = 'done'
            _state['progress'] = 100
            _state['downloaded_bytes'] = os.path.getsize(FACE_MATCH_MODEL_PATH)
            _state['total_bytes'] = _state['downloaded_bytes']
            _state['error'] = None
    except Exception as exc:
        for path in (partial_path, FACE_MATCH_MODEL_PATH):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        with _lock:
            _state['status'] = 'error'
            _state['stage'] = 'error'
            _state['error'] = str(exc)
    finally:
        try:
            if os.path.isfile(zip_path):
                os.remove(zip_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass


def start_face_rec_model_download() -> Dict[str, Any]:
    with _lock:
        if is_face_rec_model_available():
            _state['status'] = 'done'
            _state['stage'] = 'done'
            _state['progress'] = 100
            _state['error'] = None
            return {'started': False, 'message': '模型已存在', **_build_status_locked()}

        if _state['status'] == 'downloading':
            return {'started': False, 'message': '模型正在下载中', **_build_status_locked()}

        _state['status'] = 'downloading'
        _state['stage'] = 'downloading'
        _state['progress'] = 0
        _state['downloaded_bytes'] = 0
        _state['total_bytes'] = ESTIMATED_ZIP_SIZE_BYTES
        _state['error'] = None
        status = _build_status_locked()

    thread = threading.Thread(target=_do_download, name='face-rec-model-download', daemon=True)
    thread.start()
    return {'started': True, 'message': '已开始下载', **status}
