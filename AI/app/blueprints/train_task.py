"""
@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import json
import logging
import os
import re
import shutil
from urllib.parse import parse_qs, urlparse

import requests
from flask import Blueprint, request, jsonify
from sqlalchemy import desc, or_

from db_models import db, TrainTask

train_task_bp = Blueprint('train_task', __name__)
logger = logging.getLogger(__name__)

TASK_NAME_MAX_LEN = 200
DEFAULT_TASK_BASE_NAME = 'train'
LEGACY_TIMESTAMP_BASE = re.compile(r'^train_task_\d{8}_\d{6}$')


def _strip_task_id_suffix(name: str, task_id: int | None) -> str:
    if not name or task_id is None:
        return (name or '').strip()
    suffix = f'_{task_id}'
    if name.endswith(suffix):
        return name[:-len(suffix)].strip()
    return name.strip()


def resolve_task_base_name(task: TrainTask) -> str:
    """解析用户填写的任务名前缀，避免把整段历史拼接名当作 base。"""
    if task.hyperparameters:
        try:
            hp = json.loads(task.hyperparameters)
            for key in ('task_base_name', 'taskName', 'task_name'):
                val = (hp.get(key) or '').strip()
                if val:
                    return val
        except (json.JSONDecodeError, TypeError):
            pass

    stored = _strip_task_id_suffix((task.name or '').strip(), task.id)
    ds = (task.dataset_name or '').strip()
    dv = (task.dataset_version or '').strip()
    for extra in (dv, ds):
        if extra and stored.endswith(f'_{extra}'):
            stored = stored[: -(len(extra) + 1)]

    if LEGACY_TIMESTAMP_BASE.match(stored) or stored.startswith('train_task_'):
        return DEFAULT_TASK_BASE_NAME

    return stored or DEFAULT_TASK_BASE_NAME


def build_train_task_name(
    base_name=None,
    dataset_name=None,
    dataset_version=None,
    task_id=None,
) -> str:
    """格式: {用户任务名}_{数据集名}_{版本}_{任务ID}，例如 train_人_v1.0.0_19"""
    base = _strip_task_id_suffix((base_name or '').strip(), task_id)
    if LEGACY_TIMESTAMP_BASE.match(base) or base.startswith('train_task_'):
        base = DEFAULT_TASK_BASE_NAME
    if not base:
        base = DEFAULT_TASK_BASE_NAME

    ds = (dataset_name or '').strip()
    dv = (dataset_version or '').strip()
    for extra in (dv, ds):
        if extra and base.endswith(f'_{extra}'):
            base = base[: -(len(extra) + 1)]

    parts = [base]
    if ds:
        parts.append(ds)
    if dv:
        parts.append(dv)
    if task_id is not None:
        parts.append(str(task_id))

    return '_'.join(parts)[:TASK_NAME_MAX_LEN]


def _dataset_path_key(dataset_path: str) -> str:
    if not dataset_path:
        return ''
    parsed = urlparse(dataset_path)
    prefix_list = parse_qs(parsed.query).get('prefix')
    if prefix_list and prefix_list[0]:
        return prefix_list[0]
    return dataset_path.rstrip('/').split('/')[-1]


def _build_dataset_zip_map(items) -> dict:
    """zipUrl / 路径前缀 -> {name, version}"""
    dataset_map = {}
    for item in items or []:
        name = (item.get('name') or '').strip()
        version = (item.get('version') or '').strip()
        zip_url = (item.get('zipUrl') or '').strip()
        if not zip_url:
            continue
        info = {'name': name, 'version': version}
        dataset_map[zip_url] = info
        path_key = _dataset_path_key(zip_url)
        if path_key:
            dataset_map[path_key] = info
    return dataset_map


def _load_dataset_zip_map() -> dict:
    java_url = os.getenv('JAVA_BACKEND_URL', 'http://localhost:8080').rstrip('/')
    headers = {}
    auth = request.headers.get('Authorization') or request.headers.get('X-Authorization')
    if auth:
        headers['Authorization'] = auth

    try:
        resp = requests.get(
            f'{java_url}/admin-api/dataset/page',
            params={'pageNo': 1, 'pageSize': 500, 'page': 1, 'size': 500},
            headers=headers,
            timeout=8,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get('data')
        if isinstance(data, dict):
            items = data.get('list') or data.get('records') or []
        elif isinstance(data, list):
            items = data
        else:
            items = body.get('list') or []
        return _build_dataset_zip_map(items)
    except Exception as e:
        logger.warning('加载数据集列表失败，训练任务名将无法补全数据集信息: %s', e)
        return {}


def _lookup_dataset_info(dataset_map: dict, dataset_path: str):
    if not dataset_path or not dataset_map:
        return None
    if dataset_path in dataset_map:
        return dataset_map[dataset_path]
    path_key = _dataset_path_key(dataset_path)
    if path_key and path_key in dataset_map:
        return dataset_map[path_key]
    return None


def _is_local_filesystem_dataset_path(dataset_path: str) -> bool:
    """已落盘的本地 zip/目录，不应再用云端数据集映射覆盖名称。"""
    if not dataset_path:
        return False
    if dataset_path.startswith('/api/v1/buckets/'):
        return False
    if '://' in dataset_path and not dataset_path.startswith('file://'):
        return False
    return os.path.exists(dataset_path)


def _enrich_task_metadata(task: TrainTask, dataset_map: dict) -> bool:
    """补全缺失的数据集字段与任务名，返回是否有字段变更。"""
    changed = False
    info = None
    if not _is_local_filesystem_dataset_path(task.dataset_path):
        info = _lookup_dataset_info(dataset_map, task.dataset_path)
    if info:
        if not task.dataset_name and info.get('name'):
            task.dataset_name = info['name']
            changed = True
        if task.dataset_version in (None, '') and info.get('version'):
            task.dataset_version = info['version']
            changed = True

    new_name = build_train_task_name(
        resolve_task_base_name(task),
        task.dataset_name,
        task.dataset_version,
        task.id,
    )
    if (task.name or '') != new_name:
        task.name = new_name
        changed = True
    return changed


def _task_display_name(task: TrainTask) -> str:
    if (task.name or '').strip():
        return task.name.strip()
    return build_train_task_name(
        resolve_task_base_name(task),
        task.dataset_name,
        task.dataset_version,
        task.id,
    )


def _apply_task_name_filter(query, keyword: str):
    """按任务名、数据集名称、版本及数据集路径模糊搜索。"""
    pattern = f'%{keyword}%'
    return query.filter(
        or_(
            TrainTask.name.ilike(pattern),
            TrainTask.dataset_name.ilike(pattern),
            TrainTask.dataset_version.ilike(pattern),
            TrainTask.dataset_path.ilike(pattern),
        )
    )


def _apply_progress_filter(query, progress_filter: str):
    if progress_filter == 'not_started':
        return query.filter(or_(TrainTask.progress.is_(None), TrainTask.progress <= 0))
    if progress_filter == 'in_progress':
        return query.filter(TrainTask.progress > 0, TrainTask.progress < 100)
    if progress_filter == 'completed':
        return query.filter(TrainTask.progress >= 100)
    return query


def _serialize_task(task: TrainTask) -> dict:
    return {
        'id': task.id,
        'name': _task_display_name(task),
        'task_name': task.name,
        'dataset_path': task.dataset_path,
        'dataset_name': task.dataset_name,
        'dataset_version': task.dataset_version,
        'hyperparameters': task.hyperparameters,
        'start_time': task.start_time.isoformat() if task.start_time else None,
        'progress': task.progress,
        'end_time': task.end_time.isoformat() if task.end_time else None,
        'status': task.status,
        'metrics_path': task.metrics_path,
        'train_results_path': task.train_results_path,
        'minio_model_path': task.minio_model_path,
    }


@train_task_bp.route('/list', methods=['GET'])
def train_tasks():
    try:
        page_no = int(request.args.get('pageNo', 1))
        page_size = int(request.args.get('pageSize', 10))
        task_name = (
            request.args.get('task_name')
            or request.args.get('taskName')
            or request.args.get('model_name')
            or ''
        ).strip()
        progress_filter = (
            request.args.get('progress_filter')
            or request.args.get('progressFilter')
            or ''
        ).strip()

        if page_no < 1 or page_size < 1:
            return jsonify({
                'code': 400,
                'msg': '参数错误：pageNo和pageSize必须为正整数'
            }), 400

        query = TrainTask.query
        if task_name:
            query = _apply_task_name_filter(query, task_name)

        if progress_filter:
            query = _apply_progress_filter(query, progress_filter)

        query = query.order_by(desc(TrainTask.start_time))
        pagination = query.paginate(page=page_no, per_page=page_size, error_out=False)

        dataset_map = _load_dataset_zip_map()
        records = []
        dirty_tasks = []
        for task in pagination.items:
            if _enrich_task_metadata(task, dataset_map):
                dirty_tasks.append(task)
            records.append(_serialize_task(task))

        if dirty_tasks:
            try:
                db.session.commit()
            except Exception as e:
                logger.warning('补全训练任务元数据失败: %s', e)
                db.session.rollback()

        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': records,
            'total': pagination.total
        })

    except ValueError:
        return jsonify({
            'code': 400,
            'msg': '参数类型错误：pageNo和pageSize需为整数'
        }), 400
    except Exception as e:
        logger.error(f'训练记录查询失败: {str(e)}')
        return jsonify({
            'code': 500,
            'msg': '服务器内部错误'
        }), 500


@train_task_bp.route('/<int:record_id>')
def train_detail(record_id):
    try:
        record = TrainTask.query.get(record_id)
        if not record:
            return jsonify({
                'code': 404,
                'msg': f'训练记录ID {record_id} 不存在'
            }), 404

        data = _serialize_task(record)
        data['train_log'] = record.train_log
        data['checkpoint_dir'] = record.checkpoint_dir

        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': data
        })

    except Exception as e:
        logger.error(f'获取训练记录详情失败: {str(e)}')
        return jsonify({
            'code': 500,
            'msg': '服务器内部错误'
        }), 500


@train_task_bp.route('/delete/<int:record_id>', methods=['DELETE'])
def delete_train(record_id):
    try:
        record = TrainTask.query.get_or_404(record_id)

        if record.train_log and os.path.exists(record.train_log):
            os.remove(record.train_log)

        if record.checkpoint_dir and os.path.exists(record.checkpoint_dir):
            shutil.rmtree(record.checkpoint_dir)

        if record.metrics_path and os.path.exists(record.metrics_path):
            os.remove(record.metrics_path)

        db.session.delete(record)
        db.session.commit()

        return jsonify({
            'code': 0,
            'msg': '训练记录删除成功'
        })

    except Exception as e:
        logger.error(f'删除训练记录失败: {str(e)}')
        db.session.rollback()
        return jsonify({
            'code': 500,
            'msg': '服务器内部错误'
        }), 500
