import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests

_logger = logging.getLogger(__name__)


GB28181_SOURCE_PREFIX = 'gb28181://'


def is_gb28181_source(source: Optional[str]) -> bool:
    return bool(source and source.strip().lower().startswith(GB28181_SOURCE_PREFIX))


def parse_gb28181_source(source: Optional[str]) -> Optional[Tuple[str, str]]:
    if not is_gb28181_source(source):
        return None

    parsed = urlparse(source.strip())
    device_id = (parsed.netloc or '').strip()
    channel_id = (parsed.path or '').strip('/ ')
    if not device_id or not channel_id:
        return None
    return device_id, channel_id


def _candidate_bases() -> Iterable[str]:
    configured_base = (os.getenv('GB28181_SERVICE_URL') or '').strip().rstrip('/')
    if configured_base:
        yield configured_base

    gateway_url = (os.getenv('GATEWAY_URL') or '').strip().rstrip('/')
    if gateway_url:
        if gateway_url.endswith('/admin-api'):
            yield f'{gateway_url}/gb28181'
        else:
            yield f'{gateway_url}/admin-api/gb28181'

    yield 'http://localhost:48088/api'


def _build_play_url(base_url: str, device_id: str, channel_id: str) -> str:
    base = base_url.rstrip('/')
    if base.endswith('/api'):
        return f'{base}/play/start/{device_id}/{channel_id}'
    return f'{base}/play/start/{device_id}/{channel_id}'


def _body_suggests_hevc_rtmp(body: dict) -> bool:
    """播放接口返回的 RTMP 地址若标明 HEVC/H.265，OpenCV 内置 FFmpeg 拉 RTMP(FLV) 常失败 (codec_id=0)。"""
    if not isinstance(body, dict):
        return False
    for key in ('rtmp', 'rtmps'):
        u = body.get(key)
        if not isinstance(u, str) or not u.strip():
            continue
        lu = u.lower()
        if 'h265' in lu or 'hevc' in lu:
            return True
    return False


def _gb28181_play_candidates(body: dict) -> Tuple[List[Optional[str]], Dict[str, Any]]:
    """
    按协议顺序返回候选播放地址，并附带策略元数据（用于日志与排障）。

    默认 (GB28181_PLAY_PROTOCOL=rtmp_first) 将 RTMP 置于 RTSP 之前：
    ZLMediaKit 在「RTMP 协议无读者」时会触发 on_stream_none_reader；WVP/iot-gb28181
    在 streamOnDemand=true 时会对国标 rtp 流返回 close。若仅使用 RTSP 拉流，则
    RTMP 侧始终无读者，约 streamNoneReaderDelayMS（常配 20s）后整路流被释放，
    实时算法仍用 OpenCV/FFmpeg 拉流会表现为灰屏/断流。以 RTMP 作为输入时，拉流端
    会占用 RTMP 读者，可保持流存活。

    若环境仅通 RTSP 或拉 RTMP 失败，可设 GB28181_PLAY_PROTOCOL=rtsp_first 恢复旧顺序。

    GB28181_HEVC_RTSP_FIRST（默认 1）：当播放接口返回的 RTMP 地址含 HEVC/H.265 线索时，
    在仍为 rtmp_first 策略的前提下自动改为「先 RTSP」——用于规避 OpenCV VideoCapture 对
    RTMP+HEVC 无法建解码器的问题。若因此出现 ZLM「无 RTMP 读者断流」，可调大
    streamNoneReaderDelayMS，或设 GB28181_HEVC_RTSP_FIRST=0 并改用带 libx265 的 FFmpeg 构建 OpenCV。
    """
    flv_block = [
        body.get('flv'),
        body.get('https_flv'),
        body.get('ws_flv'),
    ]
    other = [
        body.get('fmp4'),
        body.get('hls'),
        body.get('rtc'),
        body.get('rtcs'),
    ]
    mode = (os.getenv('GB28181_PLAY_PROTOCOL') or 'rtmp_first').strip().lower()
    hevc_rtsp_first = (os.getenv('GB28181_HEVC_RTSP_FIRST', '1').strip().lower() not in (
        '0', 'false', 'no', 'off',
    ))
    hevc_hint = _body_suggests_hevc_rtmp(body if isinstance(body, dict) else {})

    meta: Dict[str, Any] = {
        'play_protocol': mode,
        'hevc_rtsp_first_env_on': hevc_rtsp_first,
        'hevc_hint': hevc_hint,
        'branch': 'rtmp_first',
    }

    if mode in ('rtsp_first', 'rtsp', 'legacy'):
        meta['branch'] = 'rtsp_first'
        candidates = [
            body.get('rtsp'),
            body.get('rtsps'),
            body.get('rtmp'),
            body.get('rtmps'),
            *flv_block,
            *other,
        ]
        return candidates, meta

    if hevc_rtsp_first and hevc_hint:
        meta['branch'] = 'hevc_rtsp_first'
        candidates = [
            body.get('rtsp'),
            body.get('rtsps'),
            body.get('rtmp'),
            body.get('rtmps'),
            *flv_block,
            *other,
        ]
        return candidates, meta

    meta['branch'] = 'rtmp_first'
    candidates = [
        body.get('rtmp'),
        body.get('rtmps'),
        body.get('rtsp'),
        body.get('rtsps'),
        *flv_block,
        *other,
    ]
    return candidates, meta


def _format_gb28181_choice_log(chosen_url: str, meta: Dict[str, Any]) -> str:
    """单行说明：最终选用协议与选路原因（便于对照 ZLM / OpenCV 灰屏问题）。"""
    scheme = urlparse(chosen_url).scheme.lower() if chosen_url else ''
    branch = meta.get('branch', '')
    branch_tip = {
        'rtsp_first': '接口顺序优先RTSP',
        'rtmp_first': '接口顺序优先RTMP(占读者保活)',
        'hevc_rtsp_first': 'HEVC+RTMP线索则优先RTSP(OpenCV兼容)',
    }.get(branch, branch)
    hevc_on = '开启' if meta.get('hevc_rtsp_first_env_on') else '关闭'
    hint = '是' if meta.get('hevc_hint') else '否'
    zlm_tip = ''
    if branch == 'hevc_rtsp_first':
        zlm_tip = '；若仅RTSP读者导致ZLM断流可调大streamNoneReaderDelayMS或子码流改H.264'
    elif branch == 'rtsp_first':
        zlm_tip = '；若RTMP长期无读者可能被ZLM回收，可调streamNoneReaderDelayMS或改用rtmp_first'
    return (
        f'选用={scheme or "?"} | {branch_tip} | PLAY_PROTOCOL={meta.get("play_protocol")} | '
        f'HEVC线索={hint} | HEVC_RTSP_FIRST={hevc_on}{zlm_tip}'
    )


def _extract_stream_url_and_meta(payload: dict) -> Tuple[Optional[str], Dict[str, Any]]:
    body = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    if not isinstance(body, dict):
        return None, {}
    candidates, meta = _gb28181_play_candidates(body)
    chosen = next((url for url in candidates if isinstance(url, str) and url.strip()), None)
    return chosen, meta


def _extract_stream_url(payload: dict) -> Optional[str]:
    url, _ = _extract_stream_url_and_meta(payload)
    return url


def resolve_gb28181_source(
    source: Optional[str],
    *,
    timeout: int = 15,
    logger=None,
) -> Optional[str]:
    parsed = parse_gb28181_source(source)
    if not parsed:
        return source

    device_id, channel_id = parsed
    headers = {}
    jwt_token = (os.getenv('JWT_TOKEN') or '').strip()
    if jwt_token:
        headers['X-Authorization'] = f'Bearer {jwt_token}'

    errors = []
    for base_url in _candidate_bases():
        play_url = _build_play_url(base_url, device_id, channel_id)
        try:
            response = requests.get(play_url, headers=headers, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            stream_url, meta = _extract_stream_url_and_meta(payload if isinstance(payload, dict) else {})
            if stream_url:
                detail = _format_gb28181_choice_log(stream_url, meta)
                log_fn = logger.info if logger else _logger.info
                log_fn(
                    f'GB28181源解析成功: {device_id}/{channel_id} -> {stream_url} | {detail} (via {base_url})'
                )
                return stream_url
            errors.append(f'{base_url}: 未返回可播放流地址')
        except Exception as exc:
            errors.append(f'{base_url}: {exc}')

    if logger:
        logger.error(
            f'GB28181源解析失败: {device_id}/{channel_id}, errors={"; ".join(errors)}'
        )
    return None
