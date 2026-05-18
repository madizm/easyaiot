"""
@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import json
import os
import shutil
import threading
import traceback
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import torch
from flask import current_app, jsonify, Blueprint, request
from ultralytics import YOLO

from app.services.minio_service import ModelService
from db_models import db, TrainTask

train_bp = Blueprint('train', __name__)

# 全局训练状态和进程
train_status = {}
train_processes = {}

@train_bp.route('/start', methods=['POST'])
def api_start_train():
    train_task = None
    is_new_record = False  # 标记是否是新创建的记录
    try:
        # 获取训练参数
        data = request.get_json() or {}

        record_id = data.get('taskId')
        task_name = (data.get('taskName') or data.get('task_name') or '').strip()
        epochs = data.get('epochs', 20)
        batch_size = data.get('batch_size', 16)
        img_size = data.get('imgsz', 640)
        model_arch = data.get('modelPath', 'yolov8n.pt')
        dataset_url = data.get('datasetPath')
        dataset_zip_path = dataset_url
        dataset_name = (data.get('datasetName') or data.get('dataset_name') or '').strip() or None
        dataset_version = (data.get('datasetVersion') or data.get('dataset_version') or '').strip() or None
        use_gpu = data.get('use_gpu', True)

        if not dataset_zip_path:
            return jsonify({'success': False, 'code': 400, 'msg': '缺少数据集路径'}), 400

        if record_id:
            train_task = TrainTask.query.get(record_id)
            if train_task:
                if train_task.id in train_status and train_status[train_task.id]['status'] in ['preparing', 'train']:
                    return jsonify({'success': False, 'code': 0, 'msg': '该训练任务已在进行中'}), 200
                if task_name:
                    train_task.name = task_name
                train_task.dataset_path = dataset_zip_path
                if dataset_name:
                    train_task.dataset_name = dataset_name
                if dataset_version is not None:
                    train_task.dataset_version = dataset_version
                train_task.start_time = datetime.utcnow()
                train_task.status = 'preparing'
                train_task.train_log = ''
                train_task.progress = 0
                train_task.hyperparameters = json.dumps({
                    'epochs': epochs,
                    'model_arch': model_arch,
                    'img_size': img_size,
                    'batch_size': batch_size,
                    'use_gpu': use_gpu
                })
                db.session.commit()
                is_new_record = False

        if not train_task:
            if not task_name:
                task_name = f'训练任务_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            train_task = TrainTask(
                name=task_name,
                dataset_path=dataset_zip_path,
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                hyperparameters=json.dumps({
                    'epochs': epochs,
                    'model_arch': model_arch,
                    'img_size': img_size,
                    'batch_size': batch_size,
                    'use_gpu': use_gpu
                }),
                start_time=datetime.utcnow(),
                status='preparing',
                train_log='',
                checkpoint_dir=''
            )
            db.session.add(train_task)
            db.session.commit()
            is_new_record = True

        task_id = train_task.id
        if task_id in train_status and train_status[task_id]['status'] in ['preparing', 'train']:
            return jsonify({'success': False, 'code': 0, 'msg': '训练已在进行中'}), 200

        train_status[task_id] = {
            'status': 'preparing',
            'message': '准备训练数据...',
            'progress': 0,
            'log': '',
            'stop_requested': False
        }

        train_thread = threading.Thread(
            target=train_model,
            args=(task_id, epochs, model_arch, img_size, batch_size,
                  use_gpu, dataset_zip_path, train_task.id)
        )
        train_thread.daemon = True
        train_thread.start()

        return jsonify({
            'success': True,
            'code': 0,
            'msg': '训练已启动',
            'record_id': train_task.id  # 返回记录ID给前端
        }), 200
    except Exception as e:
        # 如果创建了训练记录但在启动线程前失败，需要回滚或删除记录
        if train_task:
            try:
                if is_new_record:
                    # 如果是新创建的记录，删除它
                    db.session.delete(train_task)
                    db.session.commit()
                else:
                    # 如果是更新的记录，标记为错误状态
                    train_task.status = 'error'
                    train_task.error_log = f'启动训练失败: {str(e)}'
                    db.session.commit()
            except Exception as rollback_error:
                print(f'回滚训练记录失败: {str(rollback_error)}')
                db.session.rollback()
        
        return jsonify({'success': False, 'code': 400, 'msg': f'启动训练失败: {str(e)}'}), 400


def get_project_root():
    """获取项目根目录"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))


def _parse_minio_download_url(url: str):
    """解析 MinIO 下载 URL，返回 (bucket_name, object_key)。"""
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.split('/')
        if len(path_parts) >= 5 and path_parts[3] == 'buckets':
            bucket_name = path_parts[4]
        else:
            return None, None
        query_params = parse_qs(parsed.query)
        object_key = query_params.get('prefix', [None])[0]
        return bucket_name, object_key
    except Exception:
        return None, None


def _resolve_pretrained_model_path(model_arch: str, task_id: int):
    """
    将 model_arch 解析为 YOLO 可用的本地路径或标准权重名。
    返回 (resolved_path, error_message)，成功时 error_message 为 None。
    """
    model_arch = (model_arch or 'yolov8n.pt').strip()
    ai_root = get_project_root()

    if model_arch.startswith('/api/v1/buckets/'):
        bucket_name, object_key = _parse_minio_download_url(model_arch)
        if not bucket_name or not object_key:
            return None, f'预训练模型 URL 格式无效: {model_arch}'

        storage_dir = os.path.join(ai_root, 'data', 'pretrained', f'train_{task_id}')
        os.makedirs(storage_dir, exist_ok=True)
        filename = os.path.basename(object_key) or 'pretrained.pt'
        local_path = os.path.join(storage_dir, filename)

        if os.path.exists(local_path):
            return local_path, None

        success, error_msg = ModelService.download_from_minio(
            bucket_name=bucket_name,
            object_name=object_key,
            destination_path=local_path,
        )
        if success:
            return local_path, None
        return None, f'从 MinIO 下载预训练模型失败: {error_msg or "未知错误"}'

    if os.path.isabs(model_arch) and os.path.exists(model_arch):
        return model_arch, None

    for candidate in (
        os.path.join(ai_root, model_arch),
        os.path.join(ai_root, 'model', model_arch),
    ):
        if os.path.exists(candidate):
            return os.path.abspath(candidate), None

    # 标准 ultralytics 权重名（如 yolov8n.pt），由 YOLO 自行解析
    if '://' not in model_arch and not model_arch.startswith('/'):
        return model_arch, None

    return None, f'预训练模型路径不可用: {model_arch}'


@train_bp.route('/<int:task_id>/stop', methods=['POST'])
def api_stop_train(task_id):
    update_log(f"收到停止训练请求，任务ID: {task_id}", task_id)

    if task_id in train_status:
        train_status[task_id]['stop_requested'] = True
        train_status[task_id]['status'] = 'stopping'
        train_status[task_id]['message'] = '正在停止训练...'
        update_log("设置停止请求标志", task_id)

        if task_id in train_processes:
            pass

        return jsonify({'success': True, 'code': 0, 'msg': '停止请求已发送'}), 200
    else:
        update_log("没有找到训练状态", task_id)
        return jsonify({'success': False, 'code': 0, 'msg': '没有正在进行的训练'}), 200


@train_bp.route('/<int:task_id>/status')
def api_train_status(task_id):
    status = train_status.get(task_id, {
        'status': 'idle',
        'message': '等待开始',
        'progress': 0
    })
    return jsonify({'status': status, 'code': 0, 'msg': 'success'}), 200


@train_bp.route('/<int:task_id>/logs')
def api_train_log(task_id):
    """训练日志轮询接口，先返回内存中的日志数据，如果为空则查询数据库"""
    log_content = train_status.get(task_id, {}).get('log', '') if train_status.get(task_id) else ''

    # 如果缓存中日志为空，则从数据库查询最新训练记录
    if not log_content:
        try:
            train_task = TrainTask.query.filter_by(id=task_id).first()
            if train_task:
                log_content = train_task.train_log or ''

        except Exception as e:
            current_app.logger.error(f"查询训练记录失败: {str(e)}")

    # 返回日志数据
    return jsonify({
        'success': True,
        'code': 0,
        'data': log_content
    }), 200


def update_log(message, task_id=None, progress=None, train_task=None):
    """统一的日志记录函数"""
    log_message = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(log_message)

    if task_id is not None and task_id in train_status:
        train_status[task_id]['log'] += log_message + '\n'
        if progress is not None:
            train_status[task_id]['progress'] = progress

    # 如果提供了train_task，更新数据库记录
    if train_task is not None:
        train_task.train_log += log_message + '\n'
        if progress is not None:
            train_task.progress = progress
        try:
            db.session.commit()
        except Exception as e:
            print(f"数据库提交失败: {str(e)}")


def train_model(task_id, epochs=20, model_arch='yolov8n.pt',
                img_size=640, batch_size=16, use_gpu=True,
                dataset_zip_path=None, record_id=None):
    """增强版训练函数，集成数据集下载和解压功能"""
    update_log(f"训练函数被调用，任务ID: {task_id}", task_id)
    train_task = None

    try:
        from run import create_app
        application = create_app()

        with application.app_context():
            # 在函数内部通过record_id获取训练记录
            train_task = TrainTask.query.get(record_id)
            
            # 重新获取train_task以确保在当前会话中
            db.session.refresh(train_task)

            # 更新日志函数
            def update_log_local(message, progress=None):
                update_log(message, task_id, progress, train_task)

            task_label = train_task.name if train_task and train_task.name else f'任务{task_id}'
            update_log_local(f"开始准备训练数据，任务: {task_label}")

            if train_status.get(task_id, {}).get('stop_requested'):
                log_msg = '训练已停止'
                train_status[task_id] = {
                    'status': 'stopped',
                    'message': log_msg,
                    'progress': 0,
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                }
                update_log_local(log_msg)
                return

            # data/datasets/train_<id>/
            # ├── images /
            # │   ├── train /
            # │   └── val /
            # ├── labels /
            # │   ├── train /
            # │   └── val /
            # └── data.yaml
            # 检查数据集目录是否存在
            model_dir = os.path.join(get_project_root(), 'data/datasets', f'train_{task_id}')
            data_yaml_path = os.path.join(model_dir, 'data.yaml')

            # 检查数据集目录结构完整性
            required_dirs = ['images/train', 'images/val', 'images/test', 'labels/train', 'labels/val', 'labels/test']
            all_dirs_exist = all(os.path.exists(os.path.join(model_dir, d)) for d in required_dirs)

            if os.path.exists(data_yaml_path) and all_dirs_exist:
                # 不再更新训练记录中的数据集路径，保持原始URL
                update_log_local(f"数据集验证成功，使用原始路径: {dataset_zip_path}")

            update_log_local(f"项目目录: {model_dir}")
            update_log_local(f"数据配置文件路径: {data_yaml_path}")
            update_log_local("检查数据集配置文件...")

            # 数据集不存在处理逻辑
            dataset_downloaded = False
            if not os.path.exists(data_yaml_path):
                log_msg = '数据集配置文件不存在，正在尝试从Minio下载数据集...'
                train_status[task_id].update({
                    'message': '正在下载数据集...',
                    'progress': 5
                })
                update_log_local(log_msg, progress=5)

                # 确保数据集目录存在
                os.makedirs(model_dir, exist_ok=True)

                # 从Minio下载数据集
                if dataset_zip_path:
                    # 解析URL获取bucket和object信息
                    parsed_url = urlparse(dataset_zip_path)
                    query_params = parse_qs(parsed_url.query)
                    object_key = query_params.get('prefix', [None])[0]

                    # 从路径中提取bucket名称（关键修复）
                    path_parts = parsed_url.path.split('/')
                    if len(path_parts) >= 5 and path_parts[3] == 'buckets':
                        bucket_name = path_parts[4]  # /api/v1/buckets/<bucket_name>/objects...
                    else:
                        bucket_name = "datasets"  # 默认值

                    # 本地压缩包路径
                    local_zip_path = os.path.join(model_dir, 'dataset.zip')

                    # Minio下载（使用解析出的bucket和object）
                    update_log_local(f"从Minio下载数据集: bucket={bucket_name}, object={object_key}")
                    success, error_msg = ModelService.download_from_minio(
                            bucket_name=bucket_name,  # 使用解析出的bucket
                            object_name=object_key,  # 使用prefix参数值
                            destination_path=local_zip_path
                    )
                    if success:
                        update_log_local("数据集下载成功，开始解压...")

                        # 解压数据集
                        if ModelService.extract_zip(local_zip_path, model_dir):
                            update_log_local("数据集解压成功")
                            # 删除压缩包释放空间
                            os.remove(local_zip_path)
                            update_log_local("已清理临时压缩文件")
                        else:
                            update_log_local("数据集解压失败")
                    else:
                        update_log_local("数据集下载失败")
                else:
                    update_log_local("未提供数据集Minio路径，无法下载")

            # 检查是否应该停止训练
            if train_status.get(task_id, {}).get('stop_requested'):
                log_msg = '训练已停止'
                train_status[task_id] = {
                    'status': 'stopped',
                    'message': log_msg,
                    'progress': 0,
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                }
                update_log_local(log_msg)
                return

            # 检查data.yaml文件是否存在
            if not os.path.exists(data_yaml_path):
                error_msg = "数据集配置文件不存在"
                update_log_local(error_msg)
                train_task.status = 'error'
                train_task.error_log = error_msg
                db.session.commit()
                raise Exception(error_msg)

            # 更新状态：开始加载模型
            train_status[task_id].update({
                'message': '加载预训练模型...',
                'progress': 10
            })
            update_log_local("加载预训练YOLOv8模型...", progress=10)

            update_log_local(f"尝试加载预训练模型: {model_arch}")
            local_model_arch, resolve_error = _resolve_pretrained_model_path(model_arch, task_id)
            if resolve_error:
                update_log_local(resolve_error)
                train_task.status = 'error'
                train_task.error_log = resolve_error
                db.session.commit()
                raise Exception(resolve_error)
            if local_model_arch != model_arch:
                update_log_local(f"预训练模型已解析为本地路径: {local_model_arch}")

            try:
                yolo_model = YOLO(local_model_arch)
                update_log_local(f"预训练模型加载成功!")
            except Exception as e:
                error_msg = f"预训练模型加载失败: {str(e)}"
                update_log_local(error_msg)
                train_task.status = 'error'
                train_task.error_log = error_msg
                db.session.commit()
                raise Exception(error_msg)

            # 保存模型引用以便可能的停止操作
            train_processes[task_id] = yolo_model

            # 更新状态：开始训练
            train_status[task_id].update({
                'status': 'train',
                'message': '正在训练模型...',
                'progress': 15
            })
            update_log_local(f"开始训练模型，共{epochs}个epochs...", progress=15)

            # 训练模型
            update_log_local(
                f"开始训练模型，配置: 数据文件={data_yaml_path}, epochs={epochs}, 图像尺寸={img_size}x{img_size}, 批次大小={batch_size}")

            # 在训练函数开始处添加GPU状态检查
            gpu_status = check_gpu_status()
            update_log_local(f"GPU状态检查: {json.dumps(gpu_status, indent=2)}")

            # 确定训练设备
            if use_gpu:
                if torch.cuda.is_available():
                    device = 0
                    update_log_local(f"使用GPU进行训练: {torch.cuda.get_device_name(0)}")
                else:
                    device = 'cpu'
                    update_log_local("警告: 请求使用GPU，但CUDA不可用。使用CPU进行训练。")
                    # 记录详细原因
                    update_log_local(
                        f"可能的原因: PyTorch版本={torch.__version__}, CUDA编译版本={getattr(torch.version, 'cuda', '未知')}")
            else:
                device = 'cpu'
                update_log_local("使用CPU进行训练")

            # 设置检查点目录
            checkpoint_dir = os.path.join(model_dir, 'train_results', 'checkpoints')
            os.makedirs(checkpoint_dir, exist_ok=True)
            train_task.checkpoint_dir = checkpoint_dir
            db.session.commit()

            # 训练模型
            yolo_model.train(
                data=data_yaml_path,
                epochs=epochs,
                imgsz=img_size,
                batch=batch_size,
                project=model_dir,
                name='train_results',
                exist_ok=True,
                device=device,
                save_period=5
            )

            # 存储results.csv文件（上传Minio），然后路径存到数据库metrics_path
            results_csv_path = os.path.join(model_dir, 'train_results', 'results.csv')
            if os.path.exists(results_csv_path):
                # 上传results.csv到Minio
                minio_csv_path = f"train_tasks/train_{task_id}/results.csv"
                csv_success, csv_error = ModelService.upload_to_minio(
                    bucket_name="model-train",
                    object_name=minio_csv_path,
                    file_path=results_csv_path
                )
                
                if csv_success:
                    # 构建可访问的URL路径供后续使用，参照png的处理方式
                    accessible_csv_url = f"/api/v1/buckets/model-train/objects/download?prefix={minio_csv_path}"
                    update_log_local(f"训练结果CSV已上传至Minio: {accessible_csv_url}")
                    train_task.metrics_path = accessible_csv_url
                else:
                    update_log_local("训练结果CSV上传Minio失败，请检查日志")
            else:
                update_log_local("未找到训练结果CSV文件")

            # 存储results.png（上传Minio），然后路径存到数据库train_results_path
            results_png_path = os.path.join(model_dir, 'train_results', 'results.png')
            if os.path.exists(results_png_path):
                # 上传results.png到Minio，使用指定的bucket和object key格式
                minio_png_path = f"train_tasks/train_{task_id}/results.png"
                png_success, png_error = ModelService.upload_to_minio(
                    bucket_name="model-train",
                    object_name=minio_png_path,
                    file_path=results_png_path
                )
                
                if png_success:
                    # 构建可访问的URL路径供后续使用
                    accessible_url = f"/api/v1/buckets/model-train/objects/download?prefix={minio_png_path}"
                    update_log_local(f"训练结果图表已上传至Minio: {accessible_url}")
                    train_task.train_results_path = accessible_url
                else:
                    update_log_local("训练结果图表上传Minio失败，请检查日志")
            else:
                update_log_local("未找到训练结果图表文件")

            # 检查是否应该停止训练
            if train_status.get(task_id, {}).get('stop_requested'):
                log_msg = '训练已停止'
                train_status[task_id] = {
                    'status': 'stopped',
                    'message': log_msg,
                    'progress': 0,
                    'log': train_status[task_id].get('log', '') + log_msg + '\n'
                }
                update_log_local(log_msg)
                return

            # 更新训练状态 - 训练完成
            train_status[task_id].update({
                'status': 'completed',
                'message': '训练完成，正在保存结果...',
                'progress': 90
            })
            update_log_local("训练完成，正在保存结果...", progress=90)

            update_log_local("模型训练完成!")
            update_log_local(f"训练结果保存路径: {os.path.join(model_dir, 'train_results')}")

            # 保存最佳模型
            best_model_path = os.path.join(model_dir, 'train_results', 'weights', 'best.pt')
            update_log_local(f"检查最佳模型文件是否存在: {best_model_path}")

            if os.path.exists(best_model_path):
                update_log_local(f"找到最佳模型文件，开始复制到保存目录: {best_model_path}")

                # 将最佳模型复制到模型存储目录
                model_save_dir = os.path.join(current_app.root_path, 'static', 'train_tasks', str(task_id), 'weights')
                os.makedirs(model_save_dir, exist_ok=True)
                local_model_path = os.path.join(model_save_dir, 'best.pt')
                shutil.copy(best_model_path, local_model_path)

                update_log_local(f"模型文件已成功复制到保存目录: {model_save_dir}")

                # ================= Minio上传功能 =================
                update_log_local("开始上传最佳模型到Minio...", progress=95)

                # 上传最佳模型
                minio_model_path = f"train_tasks/train_{task_id}/best.pt"
                model_success, model_error = ModelService.upload_to_minio(
                    bucket_name="models",
                    object_name=minio_model_path,
                    file_path=local_model_path
                )

                if model_success:
                    accessible_model_url = f"/api/v1/buckets/models/objects/download?prefix={minio_model_path}"
                    update_log_local(f"模型已成功上传至Minio: {accessible_model_url}")
                    train_task.minio_model_path = accessible_model_url
                    db.session.commit()
                else:
                    update_log_local("模型上传Minio失败，请检查日志")
                    train_task.best_model_path = local_model_path
                    db.session.commit()

                # 上传训练日志，参照results.png的写法
                log_content = train_task.train_log
                log_path = os.path.join(model_save_dir, f"train_log_{train_task.id}.txt")
                with open(log_path, 'w') as f:
                    f.write(log_content)

                minio_log_path = f"logs/train_{task_id}/train_log.txt"
                log_success, log_error = ModelService.upload_to_minio(
                    bucket_name="log-bucket",
                    object_name=minio_log_path,
                    file_path=log_path
                )

                if log_success:
                    # 构建可访问的URL路径供后续使用，参照results.png的URL结构
                    accessible_log_url = f"/api/v1/buckets/log-bucket/objects/download?prefix={minio_log_path}"
                    update_log_local(f"训练日志已上传至Minio: {accessible_log_url}")
                    train_task.minio_log_path = accessible_log_url  # 保存URL而不是路径
                else:
                    update_log_local("训练日志上传Minio失败，请检查日志")
                # ================= Minio上传完成 =================

                # 更新训练记录中的本地模型路径
                train_task.best_model_path = local_model_path

            else:
                error_msg = "未找到训练完成的最佳模型文件"
                update_log_local(error_msg)
                train_task.status = 'error'
                train_task.error_log = error_msg
                db.session.commit()
                raise Exception(error_msg)

            # 更新训练状态 - 完成
            train_status[task_id].update({
                'status': 'completed',
                'message': '模型训练完成并已保存',
                'progress': 100
            })

            # 更新训练记录状态
            train_task.status = 'completed'
            train_task.end_time = datetime.utcnow()
            train_task.progress = 100
            db.session.commit()
            update_log_local("模型训练完成并已保存", progress=100)

    except Exception as e:
        from run import create_app
        application = create_app()
        with application.app_context():
            task = TrainTask.query.get(record_id) if record_id else None
            error_msg = f'训练出错: {str(e)}'
            log_msg = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {error_msg}'

            if task:
                task.status = 'error'
                task.end_time = datetime.utcnow()
                task.error_log = f"{str(e)}\n{traceback.format_exc()}"
                task.train_log = (task.train_log or '') + log_msg + '\n'
                db.session.commit()

            update_log(error_msg, task_id, train_task=task)
            traceback.print_exc()

            if task_id in train_status:
                train_status[task_id].update({
                    'status': 'error',
                    'message': error_msg,
                    'progress': 0,
                    'error_details': str(e),
                    'traceback': traceback.format_exc(),
                    'log': train_status[task_id].get('log', '') + log_msg + '\n' + traceback.format_exc()
                })
    finally:
        if task_id in train_processes:
            del train_processes[task_id]


def check_gpu_status():
    """检查并记录GPU状态"""
    import torch
    status = {
        'pytorch_version': torch.__version__,
        'cuda_available': torch.cuda.is_available(),
        'cuda_version': torch.version.cuda if hasattr(torch.version, 'cuda') else '未知',
        'device_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            status[f'device_{i}_name'] = torch.cuda.get_device_name(i)
            status[f'device_{i}_capability'] = torch.cuda.get_device_capability(i)

    return status