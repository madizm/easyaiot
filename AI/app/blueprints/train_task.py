"""
@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import logging
import os
import shutil
from datetime import datetime

from flask import Blueprint, request, jsonify
from sqlalchemy import desc

from db_models import db, TrainTask

train_task_bp = Blueprint('train_task', __name__)
logger = logging.getLogger(__name__)


def _task_display_name(task: TrainTask) -> str:
    if task.name:
        return task.name
    return f'训练任务 #{task.id}'


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
        status_filter = request.args.get('status')

        if page_no < 1 or page_size < 1:
            return jsonify({
                'code': 400,
                'msg': '参数错误：pageNo和pageSize必须为正整数'
            }), 400

        query = TrainTask.query
        if task_name:
            query = query.filter(TrainTask.name.ilike(f'%{task_name}%'))

        if status_filter in ['running', 'completed', 'failed', 'preparing', 'stopped', 'error']:
            query = query.filter(TrainTask.status == status_filter)

        query = query.order_by(desc(TrainTask.start_time))
        pagination = query.paginate(page=page_no, per_page=page_size, error_out=False)

        records = [_serialize_task(task) for task in pagination.items]

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
