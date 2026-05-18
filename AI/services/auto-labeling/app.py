import argparse
import os
import re
import json
import math
import shutil
import hashlib
import uuid
import time
import atexit
import socket
import threading
import logging
from collections import defaultdict
import numpy as np
import base64
import traceback
import cv2
import sys
import requests
import netifaces
from urllib.parse import urlparse, parse_qs, unquote
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from PIL import Image


def _load_env_file(env_name=''):
    """与 /projects/easyaiot/VIDEO/run.py 一致：先加载 .env 再读 Nacos 等变量。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if env_name:
        env_file = f'.env.{env_name}'
        if os.path.exists(env_file):
            load_dotenv(env_file)
            print(f'已加载配置文件: {env_file}')
        else:
            print(f'配置文件 {env_file} 不存在，尝试加载默认 .env')
            if os.path.exists('.env'):
                load_dotenv('.env')
                print('已加载默认配置文件: .env')
            else:
                print('默认配置文件 .env 也不存在')
    else:
        if os.path.exists('.env'):
            load_dotenv('.env')
            print('已加载默认配置文件: .env')


def _parse_env_arg_and_load_dotenv():
    """支持 python app.py --env=prod；与 gunicorn 等共存时用 parse_known_args。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--env', type=str, default='', help='加载 .env.<name>')
    args, _ = parser.parse_known_args()
    _load_env_file(args.env)


_parse_env_arg_and_load_dotenv()

logging.getLogger('nacos').setLevel(logging.WARNING)

app = Flask(__name__)
CORS(app)

_URL_PREFIX = os.getenv('URL_PREFIX', '').rstrip('/')


class _ScriptNameMiddleware:
    """WEB iframe 嵌套时由代理注入 X-Forwarded-Prefix；直连 8000 端口时不设前缀。"""

    def __init__(self, wsgi_app, fallback_prefix: str = ''):
        self.wsgi_app = wsgi_app
        self.fallback_prefix = fallback_prefix.rstrip('/')

    def __call__(self, environ, start_response):
        prefix = (
            environ.get('HTTP_X_FORWARDED_PREFIX', '').strip()
            or self.fallback_prefix
        ).rstrip('/')
        if prefix:
            environ['SCRIPT_NAME'] = prefix
        return self.wsgi_app(environ, start_response)


app.wsgi_app = _ScriptNameMiddleware(app.wsgi_app, _URL_PREFIX)


def get_local_ip():
    """与 easyaiot/VIDEO/run.py 中 get_local_ip 一致。"""
    if ip := os.getenv('POD_IP'):
        return ip
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
        for addr in addrs:
            ip = addr['addr']
            if ip != '127.0.0.1' and not ip.startswith('169.254.'):
                return ip
    if not (os.getenv('HTTP_PROXY') or os.getenv('HTTPS_PROXY')):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        finally:
            s.close()
    raise RuntimeError('无法确定本地IP，请配置POD_IP环境变量')


def send_heartbeat(client, ip, port, stop_event):
    """与 easyaiot/VIDEO/run.py 中 send_heartbeat 一致。"""
    service_name = os.getenv('SERVICE_NAME', 'auto-labeling-server')
    while not stop_event.is_set():
        try:
            client.send_heartbeat(service_name=service_name, ip=ip, port=port)
        except Exception as e:
            print(f'心跳异常: {e}')
        time.sleep(5)


def _deregister_nacos_service(flask_app):
    """进程退出时注销 Nacos（与 VIDEO run.py 中 deregister_service 的 Nacos 部分一致）。"""
    if not getattr(flask_app, 'nacos_registered', False):
        return
    try:
        if hasattr(flask_app, 'heartbeat_stop_event'):
            flask_app.heartbeat_stop_event.set()
            if hasattr(flask_app, 'heartbeat_thread') and flask_app.heartbeat_thread:
                flask_app.heartbeat_thread.join(timeout=3.0)
                print('心跳线程已停止')
        service_name = os.getenv('SERVICE_NAME', 'auto-labeling-server')
        port = int(os.getenv('FLASK_RUN_PORT', os.getenv('PORT', '8000')))
        if getattr(flask_app, 'nacos_client', None) and getattr(flask_app, 'registered_ip', None):
            flask_app.nacos_client.remove_naming_instance(
                service_name=service_name,
                ip=flask_app.registered_ip,
                port=port,
            )
            print(f'全局注销成功: {service_name}@{flask_app.registered_ip}:{port}')
    except Exception as e:
        print(f'注销异常: {e}')


def _init_nacos_registration(flask_app):
    """Nacos 注册与心跳；与 easyaiot/VIDEO/run.py create_app 内逻辑一致。失败不影响 Web 启动。"""
    flask_app.nacos_registered = False
    flask_app.nacos_client = None
    if os.getenv('NACOS_REGISTER', 'true').lower() in ('0', 'false', 'no', 'off'):
        return
    try:
        from nacos import NacosClient
    except ImportError:
        print('未安装 nacos-sdk-python，跳过 Nacos 注册')
        return
    try:
        # 默认值与 VIDEO/.env 一致：宿主机直连用 localhost；Docker 内请设 NACOS_SERVER=Nacos:8848
        nacos_server = os.getenv('NACOS_SERVER', 'localhost:8848')
        namespace = os.getenv('NACOS_NAMESPACE', '')
        service_name = os.getenv('SERVICE_NAME', 'auto-labeling-server')
        port = int(os.getenv('FLASK_RUN_PORT', os.getenv('PORT', '8000')))
        username = os.getenv('NACOS_USERNAME', 'nacos')
        password = os.getenv('NACOS_PASSWORD', 'basiclab@iot78475418754')
        ip = os.getenv('POD_IP') or get_local_ip()
        flask_app.nacos_client = NacosClient(
            server_addresses=nacos_server,
            namespace=namespace,
            username=username,
            password=password,
        )
        flask_app.nacos_client.add_naming_instance(
            service_name=service_name,
            ip=ip,
            port=port,
            cluster_name='DEFAULT',
            healthy=True,
            ephemeral=True,
        )
        print(f'服务注册成功: {service_name}@{ip}:{port}')
        flask_app.registered_ip = ip
        flask_app.nacos_registered = True
        flask_app.heartbeat_stop_event = threading.Event()
        flask_app.heartbeat_thread = threading.Thread(
            target=send_heartbeat,
            args=(flask_app.nacos_client, ip, port, flask_app.heartbeat_stop_event),
            daemon=True,
        )
        flask_app.heartbeat_thread.start()
    except Exception as e:
        print(f'Nacos注册失败: {e}')
        flask_app.nacos_client = None
        flask_app.nacos_registered = False


_init_nacos_registration(app)

_has_setup_nacos = False


@app.before_request
def setup_nacos_once():
    """与 VIDEO 一致：首请求时标记（供退出逻辑参考）。"""
    global _has_setup_nacos
    if not _has_setup_nacos:
        app.nacos_registered = bool(getattr(app, 'nacos_client', None))
        _has_setup_nacos = True


atexit.register(lambda: _deregister_nacos_service(app))

# 配置
UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
ANNOTATIONS_FOLDER = os.path.join(STATIC_FOLDER, 'annotations')

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['STATIC_FOLDER'] = STATIC_FOLDER
app.config['ANNOTATIONS_FOLDER'] = ANNOTATIONS_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 最大上传2GB

# 创建必要的目录
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)
os.makedirs(ANNOTATIONS_FOLDER, exist_ok=True)

# ---------- 多数据集存储（按导入目录「文件夹名称」分槽，互不覆盖）----------
DATASETS_SUBDIR = 'datasets'
ACTIVE_DATASET_FILE = os.path.join(ANNOTATIONS_FOLDER, 'active.json')
RESERVED_UPLOAD_SLUG = '__uploads__'


def _datasets_root():
    return os.path.join(ANNOTATIONS_FOLDER, DATASETS_SUBDIR)


def _dataset_slot_dir(slug):
    return os.path.join(_datasets_root(), slug)


def _slug_from_import_root(dataset_root):
    """用数据集根路径的最后一段目录名作为存储槽名；与系统保留槽冲突时加前缀。"""
    root = os.path.realpath(os.path.expanduser(str(dataset_root).strip()))
    base = os.path.basename(root.rstrip(os.sep))
    if not base or base in ('.', '..'):
        h = hashlib.sha256(root.encode('utf-8')).hexdigest()[:12]
        base = 'dataset_' + h
    if base == RESERVED_UPLOAD_SLUG or base.startswith('__'):
        base = 'ds_' + base
    return base


def _annotations_file_for_slug(slug):
    return os.path.join(_dataset_slot_dir(slug), 'annotations.json')


def _classes_file_for_slug(slug):
    return os.path.join(_dataset_slot_dir(slug), 'classes.json')


def _dataset_config_file_for_slug(slug):
    return os.path.join(_dataset_slot_dir(slug), 'dataset_config.json')


def _write_active_file(slug):
    with open(ACTIVE_DATASET_FILE, 'w', encoding='utf-8') as f:
        json.dump({'slug': slug}, f, indent=2, ensure_ascii=False)


def _default_classes():
    return [
        {'name': 'person', 'color': '#3aa757'},
        {'name': 'car', 'color': '#4c9ffd'},
        {'name': 'animal', 'color': '#ff9d00'},
    ]


def _ensure_upload_slot(create_if_missing=True):
    """本地上传/抽帧使用固定槽位，与其它导入的数据集隔离。"""
    slot = _dataset_slot_dir(RESERVED_UPLOAD_SLUG)
    if not os.path.isdir(slot):
        if not create_if_missing:
            return
        os.makedirs(slot, exist_ok=True)
        with open(_annotations_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
            json.dump({}, f)
        with open(_classes_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
            json.dump(_default_classes(), f, indent=2, ensure_ascii=False)
        with open(_dataset_config_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'upload'}, f, indent=2, ensure_ascii=False)
        return
    if not os.path.isfile(_annotations_file_for_slug(RESERVED_UPLOAD_SLUG)):
        with open(_annotations_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
            json.dump({}, f)
    if not os.path.isfile(_classes_file_for_slug(RESERVED_UPLOAD_SLUG)):
        with open(_classes_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
            json.dump(_default_classes(), f, indent=2, ensure_ascii=False)
    if not os.path.isfile(_dataset_config_file_for_slug(RESERVED_UPLOAD_SLUG)):
        with open(_dataset_config_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'upload'}, f, indent=2, ensure_ascii=False)


def _prepare_dataset_import_slot(slug):
    """再次导入同名文件夹：清空该槽下所有文件后重建（由调用方写入新内容）。"""
    slot = _dataset_slot_dir(slug)
    if os.path.isdir(slot):
        shutil.rmtree(slot)
    os.makedirs(slot, exist_ok=True)


def _migrate_legacy_storage_if_needed():
    """将旧版 static/annotations/*.json 迁入 datasets/<槽名>/。"""
    os.makedirs(_datasets_root(), exist_ok=True)
    if os.path.isfile(ACTIVE_DATASET_FILE):
        return
    legacy_ann = os.path.join(ANNOTATIONS_FOLDER, 'annotations.json')
    legacy_classes = os.path.join(ANNOTATIONS_FOLDER, 'classes.json')
    legacy_cfg = os.path.join(ANNOTATIONS_FOLDER, 'dataset_config.json')
    has_legacy = (
        os.path.isfile(legacy_ann)
        or os.path.isfile(legacy_classes)
        or os.path.isfile(legacy_cfg)
    )
    if not has_legacy:
        _ensure_upload_slot(True)
        _write_active_file(RESERVED_UPLOAD_SLUG)
        return
    slug = RESERVED_UPLOAD_SLUG
    if os.path.isfile(legacy_cfg):
        try:
            with open(legacy_cfg, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if cfg.get('mode') == 'external' and (cfg.get('root') or '').strip():
                er = os.path.realpath(os.path.expanduser(cfg['root'].strip()))
                if os.path.isdir(er):
                    slug = _slug_from_import_root(er)
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            pass
    os.makedirs(_dataset_slot_dir(slug), exist_ok=True)
    if os.path.isfile(legacy_ann):
        shutil.copy2(legacy_ann, _annotations_file_for_slug(slug))
    else:
        with open(_annotations_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump({}, f)
    if os.path.isfile(legacy_classes):
        shutil.copy2(legacy_classes, _classes_file_for_slug(slug))
    else:
        with open(_classes_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(_default_classes(), f, indent=2, ensure_ascii=False)
    if os.path.isfile(legacy_cfg):
        shutil.copy2(legacy_cfg, _dataset_config_file_for_slug(slug))
    else:
        with open(_dataset_config_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'upload'}, f, indent=2, ensure_ascii=False)
    for p in (legacy_ann, legacy_classes, legacy_cfg):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
    for extra in (legacy_ann + '.bak', legacy_ann + '.lock', legacy_ann + '.tmp'):
        if os.path.isfile(extra):
            try:
                os.remove(extra)
            except OSError:
                pass
    _write_active_file(slug)


def _bootstrap_annotation_storage():
    _migrate_legacy_storage_if_needed()


def _active_dataset_slug():
    slug = None
    if os.path.isfile(ACTIVE_DATASET_FILE):
        try:
            with open(ACTIVE_DATASET_FILE, 'r', encoding='utf-8') as f:
                slug = (json.load(f).get('slug') or '').strip()
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            slug = None
    if slug and os.path.isdir(_dataset_slot_dir(slug)) and os.path.isfile(_dataset_config_file_for_slug(slug)):
        return slug
    dr = _datasets_root()
    if os.path.isdir(dr):
        for name in sorted(os.listdir(dr)):
            sub = os.path.join(dr, name)
            if os.path.isdir(sub) and os.path.isfile(_dataset_config_file_for_slug(name)):
                _write_active_file(name)
                return name
    _ensure_upload_slot(True)
    _write_active_file(RESERVED_UPLOAD_SLUG)
    return RESERVED_UPLOAD_SLUG


def _current_annotations_file():
    return _annotations_file_for_slug(_active_dataset_slug())


def _current_classes_file():
    return _classes_file_for_slug(_active_dataset_slug())


def _default_dataset_config():
    return {'mode': 'upload'}


def _load_dataset_config():
    slug = _active_dataset_slug()
    path = _dataset_config_file_for_slug(slug)
    if not os.path.exists(path):
        return _default_dataset_config()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        mode = cfg.get('mode', 'upload')
        if mode == 'external':
            root = (cfg.get('root') or '').strip()
            if not root:
                return _default_dataset_config()
            root = os.path.realpath(os.path.expanduser(root))
            if not os.path.isdir(root):
                return _default_dataset_config()
            return {'mode': 'external', 'root': root}
        return {'mode': 'upload'}
    except (json.JSONDecodeError, OSError, TypeError):
        return _default_dataset_config()


def _set_dataset_mode_upload():
    _ensure_upload_slot(True)
    with open(_dataset_config_file_for_slug(RESERVED_UPLOAD_SLUG), 'w', encoding='utf-8') as f:
        json.dump({'mode': 'upload'}, f, indent=2, ensure_ascii=False)
    _write_active_file(RESERVED_UPLOAD_SLUG)


_bootstrap_annotation_storage()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/classes')
def get_classes():
    """获取所有类别"""
    classes = []
    cf = _current_classes_file()
    if os.path.exists(cf):
        with open(cf, 'r') as f:
            classes = json.load(f)
    return jsonify(classes)


@app.route('/api/classes', methods=['POST'])
def save_classes():
    """保存所有类别"""
    data = request.json
    
    with open(_current_classes_file(), 'w') as f:
        json.dump(data, f, indent=2)
    
    return jsonify({'message': 'Classes saved successfully'})


@app.route('/api/images')
def get_images():
    """获取当前数据集中的所有图片（uploads 模式或外部根目录模式）。"""
    images = []

    annotations = {}
    ann_path = _current_annotations_file()
    if os.path.exists(ann_path):
        try:
            with open(ann_path, 'r', encoding='utf-8') as f:
                annotations = json.load(f)
            print(f"[DEBUG] 成功读取标注文件，共有 {len(annotations)} 张图片有标注")
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON解析失败: {e}")
            annotations = {}
        except Exception as e:
            print(f"[ERROR] 读取标注文件失败: {e}")
            annotations = {}
    else:
        print(f"[DEBUG] 标注文件不存在: {ann_path}")

    for abs_path, name in _iter_dataset_images():
        try:
            with Image.open(abs_path) as img:
                width, height = img.size
        except Exception:
            width, height = 0, 0
        annotation_count = len(annotations.get(name, []))
        images.append({
            'name': name,
            'width': width,
            'height': height,
            'annotation_count': annotation_count
        })

    images.sort(key=lambda x: x['name'])
    annotated_count = sum(1 for img in images if img['annotation_count'] > 0)
    print(f"[DEBUG] 返回 {len(images)} 张图片，其中 {annotated_count} 张有标注")

    cfg = _load_dataset_config()
    out = {
        'images': images,
        'dataset_mode': cfg.get('mode', 'upload'),
        'active_dataset': _active_dataset_slug(),
    }
    if cfg.get('mode') == 'external':
        out['dataset_root'] = cfg.get('root')
    else:
        out['dataset_root'] = None
    return jsonify(out)


@app.route('/api/datasets')
def list_datasets():
    """列出 static/annotations/datasets 下各数据集槽及当前活动槽。"""
    items = []
    root = _datasets_root()
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            cfg_path = _dataset_config_file_for_slug(name)
            if not os.path.isfile(cfg_path):
                continue
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                cfg = {}
            ann_path = _annotations_file_for_slug(name)
            n_ann = 0
            if os.path.isfile(ann_path):
                try:
                    with open(ann_path, 'r', encoding='utf-8') as f:
                        n_ann = len(json.load(f))
                except (json.JSONDecodeError, OSError, TypeError, UnicodeDecodeError):
                    n_ann = 0
            items.append({
                'slug': name,
                'mode': cfg.get('mode', 'upload'),
                'root': cfg.get('root'),
                'annotation_keys': n_ann,
            })
    return jsonify({'datasets': items, 'active': _active_dataset_slug()})


@app.route('/api/datasets/active', methods=['POST'])
def set_active_dataset():
    """切换当前编辑的数据集（仅改活动指针，不删数据）。"""
    data = request.get_json(silent=True) or {}
    slug = (data.get('slug') or '').strip()
    if not slug or not os.path.isfile(_dataset_config_file_for_slug(slug)):
        return jsonify({'error': '无效的数据集名称'}), 400
    _write_active_file(slug)
    return jsonify({'ok': True, 'active': slug})


@app.route('/api/images/delete', methods=['POST'])
def delete_images():
    """删除指定的图片"""
    data = request.json or {}
    image_names = data.get('images', [])
    
    deleted_count = 0
    errors = []
    
    for image_name in image_names:
        try:
            image_path = _safe_abs_path_for_image_key(image_name)
            if image_path and os.path.isfile(image_path):
                os.remove(image_path)
                sidecar = os.path.splitext(image_path)[0] + '.json'
                if os.path.isfile(sidecar):
                    try:
                        os.remove(sidecar)
                    except OSError:
                        pass
                deleted_count += 1

                annotations = {}
                ann_file = _current_annotations_file()
                if os.path.exists(ann_file):
                    with open(ann_file, 'r') as f:
                        annotations = json.load(f)

                    if image_name in annotations:
                        del annotations[image_name]
                        with open(ann_file, 'w') as f:
                            json.dump(annotations, f, indent=2)
            else:
                errors.append(f"图片 '{image_name}' 不存在")
        except Exception as e:
            errors.append(f"删除图片 '{image_name}' 失败: {str(e)}")
    
    if errors:
        return jsonify({
            'success': False,
            'deleted_count': deleted_count,
            'error': '; '.join(errors)
        }), 400
    
    return jsonify({
        'success': True,
        'deleted_count': deleted_count
    })


@app.route('/api/image/<path:image_key>')
def get_image(image_key):
    """获取指定图片（uploads 下扁平名，或外部数据集根下的相对路径）。"""
    abs_path = _safe_abs_path_for_image_key(image_key)
    if not abs_path or not os.path.isfile(abs_path):
        return jsonify({'error': '图片不存在'}), 404
    directory = os.path.dirname(abs_path)
    basename = os.path.basename(abs_path)
    return send_from_directory(directory, basename)


@app.route('/api/upload', methods=['POST'])
def upload_folder():
    """上传整个文件夹"""
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files[]')
    uploaded_files = []
    
    for file in files:
        if file.filename != '':
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename or '')
            file.save(filepath)
            uploaded_files.append(file.filename or '')

    if uploaded_files:
        _set_dataset_mode_upload()

    return jsonify({'message': 'Files uploaded successfully', 'files': uploaded_files})


_LABELME_IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')


def _labelme_json_to_annotations(json_content, classes, existing_class_names):
    """从 LabelMe JSON 内容解析为内部标注列表；会就地扩展 classes 与 existing_class_names。"""
    image_annotations = []
    for shape in json_content.get('shapes') or []:
        label = shape.get('label', '')
        points = shape.get('points', [])
        if label and label not in existing_class_names:
            new_color = '#{:06x}'.format(hash(label) % 0x1000000)
            classes.append({'name': label, 'color': new_color})
            existing_class_names.add(label)
        if not points or not label:
            continue
        color = '#000000'
        for cls in classes:
            if cls['name'] == label:
                color = cls['color']
                break
        shape_type = shape.get('shape_type', 'polygon')
        internal_points = points
        internal_type = shape_type
        if shape_type == 'rectangle' and len(points) == 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            internal_points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            internal_type = 'rectangle'
        elif shape_type == 'circle' and len(points) == 2:
            cx, cy = points[0]
            radius = ((points[1][0] - cx) ** 2 + (points[1][1] - cy) ** 2) ** 0.5
            internal_points = []
            for i in range(16):
                angle = (i / 16) * 2 * 3.14159
                internal_points.append([cx + radius * math.cos(angle), cy + radius * math.sin(angle)])
            internal_type = 'polygon'
        elif shape_type == 'line' and len(points) >= 2:
            internal_type = 'line'
        else:
            internal_type = 'polygon'
        image_annotations.append({
            'class': label,
            'color': color,
            'points': internal_points,
            'type': internal_type
        })
    return image_annotations


def _is_under_dataset_root(dataset_root, path):
    dataset_root = os.path.realpath(dataset_root)
    path = os.path.realpath(path)
    try:
        return os.path.commonpath([dataset_root, path]) == dataset_root
    except ValueError:
        return False


def _labelme_resolve_image_abs(json_path, json_content, dataset_root):
    """根据 LabelMe 的 imagePath 或 json 文件名，解析出对应的图片绝对路径。"""
    json_dir = os.path.dirname(os.path.realpath(json_path))
    dataset_root = os.path.realpath(dataset_root)
    candidates = []
    img_rel = (json_content.get('imagePath') or '').strip().replace('\\', '/')
    if img_rel:
        if os.path.isabs(img_rel):
            candidates.append(os.path.realpath(img_rel))
        else:
            candidates.append(os.path.realpath(os.path.join(json_dir, img_rel)))
    stem = os.path.splitext(os.path.basename(json_path))[0]
    for suf in _LABELME_IMAGE_SUFFIXES:
        candidates.append(os.path.realpath(os.path.join(json_dir, stem + suf)))
    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if os.path.isfile(cand) and _is_under_dataset_root(dataset_root, cand):
            return cand
    return None


def _collect_labelme_annotations_by_image(dataset_root, classes, existing_class_names):
    """
    遍历数据集下所有 .json，按 LabelMe 规范把标注挂到「图片绝对路径」上。
    支持 json 与图片分目录（依赖 imagePath 或 json 与图片同名同目录）。
    """
    image_to_ann = {}
    dataset_root = os.path.realpath(dataset_root)
    for current_root, dirnames, filenames in os.walk(dataset_root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
        for name in filenames:
            if not name.lower().endswith('.json'):
                continue
            json_path = os.path.join(current_root, name)
            if not _is_under_dataset_root(dataset_root, json_path):
                continue
            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    jc = json.load(jf)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue
            shapes = jc.get('shapes')
            if shapes is None:
                shapes = []
            if not isinstance(shapes, list):
                continue
            jc_use = dict(jc)
            jc_use['shapes'] = shapes
            img_abs = _labelme_resolve_image_abs(json_path, jc_use, dataset_root)
            if not img_abs:
                continue
            img_abs = os.path.realpath(img_abs)
            ann = _labelme_json_to_annotations(jc_use, classes, existing_class_names)
            image_to_ann.setdefault(img_abs, []).extend(ann)
    return image_to_ann


def _flatten_upload_relative_name(filename):
    """浏览器 webkitRelativePath 可能带子目录，压平为 uploads 下唯一文件名，与路径导入规则一致。"""
    if not filename:
        return ''
    norm = filename.replace('\\', '/').strip('/')
    if '/' not in norm:
        return os.path.basename(norm)
    return norm.replace('/', '__')


def _parse_data_yaml_names(path):
    """不依赖 PyYAML，从 data.yaml 中尽力解析 names 列表。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return []
    m = re.search(r'names:\s*\[(.*?)\]', text, re.DOTALL)
    if m:
        inner = m.group(1)
        items = re.findall(r"'([^']*)'|\"([^\"]*)\"", inner)
        names = [a or b for a, b in items if (a or b)]
        if names:
            return names
    m = re.search(r'names:\s*\n((?:\s*-\s*[^\n]+\n?)+)', text)
    if m:
        names = []
        for ln in m.group(1).splitlines():
            ln = ln.strip()
            if re.match(r'^-\s*', ln):
                v = re.sub(r'^-\s*', '', ln).strip().strip("'\"")
                names.append(v)
        if names:
            return names
    m = re.search(r'names:\s*\n((?:\s*\d+:\s*[^\n]+\n?)+)', text)
    if m:
        pairs = []
        for ln in m.group(1).splitlines():
            mm = re.match(r'^\s*(\d+):\s*(.+)$', ln.strip())
            if mm:
                pairs.append((int(mm.group(1)), mm.group(2).strip().strip("'\"")))
        pairs.sort(key=lambda x: x[0])
        return [p[1] for p in pairs]
    return []


def _load_yolo_class_names(dataset_root):
    for rel in ('classes.txt', os.path.join('labels', 'classes.txt')):
        p = os.path.join(dataset_root, rel)
        if os.path.isfile(p):
            with open(p, 'r', encoding='utf-8') as f:
                names = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith('#')]
            if names:
                return names
    for yaml_name in ('data.yaml', 'dataset.yaml'):
        p = os.path.join(dataset_root, yaml_name)
        if os.path.isfile(p):
            names = _parse_data_yaml_names(p)
            if names:
                return names
    return []


def _find_yolo_txt_for_image(dataset_root, image_abs):
    """在常见 YOLO 目录布局下查找与图片同名的 .txt 标签文件。"""
    dataset_root = os.path.realpath(dataset_root)
    image_abs = os.path.realpath(image_abs)
    try:
        rel = os.path.relpath(image_abs, dataset_root)
    except ValueError:
        return None
    parts = rel.split(os.sep)
    stem, _ = os.path.splitext(parts[-1])
    dir_parts = parts[:-1]
    cand_dirs = []
    if dir_parts:
        cand_dirs.append(os.path.join(dataset_root, *dir_parts))
    else:
        cand_dirs.append(dataset_root)
    for i, seg in enumerate(dir_parts):
        low = seg.lower()
        if low in ('images', 'jpegimages'):
            alt = list(dir_parts[:i]) + ['labels'] + list(dir_parts[i + 1:])
            cand_dirs.append(os.path.join(dataset_root, *alt))
    if any(p.lower() in ('images', 'jpegimages') for p in dir_parts):
        alt2 = ['labels' if p.lower() in ('images', 'jpegimages') else p for p in dir_parts]
        cand_dirs.append(os.path.join(dataset_root, *alt2))
    seen = set()
    for d in cand_dirs:
        p = os.path.join(d, f'{stem}.txt')
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        if os.path.isfile(rp) and _is_under_dataset_root(dataset_root, rp):
            return rp
    return None


def _yolo_txt_to_annotations(txt_path, image_abs, class_names, classes, existing_class_names):
    """将单张 YOLO 检测 txt（归一化 cxcywh）转为内部矩形标注。"""
    try:
        with Image.open(image_abs) as im:
            iw, ih = im.size
    except Exception:
        return []
    if iw <= 0 or ih <= 0:
        return []
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cid = int(float(parts[0]))
        except ValueError:
            continue
        if class_names and 0 <= cid < len(class_names):
            label = class_names[cid]
        else:
            label = f'class_{cid}'
        if label not in existing_class_names:
            new_color = '#{:06x}'.format(hash(label) % 0x1000000)
            classes.append({'name': label, 'color': new_color})
            existing_class_names.add(label)
        try:
            fx, fy, fw, fh = map(float, parts[1:5])
        except ValueError:
            continue
        x_min = (fx - fw / 2) * iw
        x_max = (fx + fw / 2) * iw
        y_min = (fy - fh / 2) * ih
        y_max = (fy + fh / 2) * ih
        color = '#000000'
        for cls in classes:
            if cls['name'] == label:
                color = cls['color']
                break
        out.append({
            'class': label,
            'color': color,
            'points': [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]],
            'type': 'rectangle',
        })
    return out


def _looks_like_coco_instances(obj):
    """COCO Object Detection / Instance Segmentation 的 instances JSON（非 LabelMe）。"""
    if not isinstance(obj, dict):
        return False
    if 'shapes' in obj or 'imagePath' in obj:
        return False
    if not isinstance(obj.get('images'), list) or len(obj['images']) == 0:
        return False
    if not isinstance(obj.get('annotations'), list):
        return False
    if not isinstance(obj.get('categories'), list):
        return False
    return True


def _ensure_class_named(label, classes, existing_class_names):
    """确保 classes 中存在该标签名，返回其颜色。"""
    if not label:
        label = 'unknown'
    if label not in existing_class_names:
        new_color = '#{:06x}'.format(hash(label) % 0x1000000)
        classes.append({'name': label, 'color': new_color})
        existing_class_names.add(label)
    for cls in classes:
        if cls['name'] == label:
            return cls['color']
    return '#000000'


def _search_roots_for_coco_json(coco_json_path, dataset_root):
    """解析 COCO file_name 时常用的若干图片根目录候选。"""
    coco_json_path = os.path.realpath(coco_json_path)
    coco_dir = os.path.dirname(coco_json_path)
    dr = os.path.realpath(dataset_root)
    roots = [
        dr,
        os.path.join(dr, 'images'),
        os.path.join(dr, 'JPEGImages'),
        os.path.realpath(os.path.join(coco_dir, '..')),
        os.path.realpath(os.path.join(coco_dir, '..', 'images')),
        os.path.realpath(os.path.join(coco_dir, '..', 'JPEGImages')),
        coco_dir,
    ]
    out, seen = [], set()
    for r in roots:
        rp = os.path.realpath(r)
        if rp in seen:
            continue
        seen.add(rp)
        if os.path.isdir(rp):
            out.append(rp)
    return out


def _resolve_coco_image_under_dataset(search_roots, dataset_root, file_name):
    """根据 COCO 的 file_name 在若干根目录下定位图片；必须在 dataset_root 之下。"""
    fn = (file_name or '').replace('\\', '/').lstrip('/')
    if not fn:
        return None
    dr = os.path.realpath(dataset_root)
    for root in search_roots:
        cand = os.path.realpath(os.path.join(root, fn))
        if os.path.isfile(cand) and _is_under_dataset_root(dr, cand):
            return cand
    bn = os.path.basename(fn)
    if bn != fn:
        for root in search_roots:
            cand = os.path.realpath(os.path.join(root, bn))
            if os.path.isfile(cand) and _is_under_dataset_root(dr, cand):
                return cand
    return None


def _coco_ann_to_shapes(ann, label, color):
    """单条 COCO annotation 转为 0..N 个内部标注 dict（矩形或多边形）。"""
    out = []
    try:
        iscrowd = int(ann.get('iscrowd', 0) or 0)
    except (TypeError, ValueError):
        iscrowd = 0
    if iscrowd:
        return out
    bbox = ann.get('bbox')
    seg = ann.get('segmentation')
    if bbox and isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            x, y, w, h = map(float, bbox[:4])
        except (TypeError, ValueError):
            x, y, w, h = 0.0, 0.0, 0.0, 0.0
        if w > 0 and h > 0:
            out.append({
                'class': label,
                'color': color,
                'points': [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                'type': 'rectangle',
            })
            return out
    if isinstance(seg, list) and seg:
        for poly in seg:
            if not isinstance(poly, (list, tuple)) or len(poly) < 6:
                continue
            try:
                pts = [[float(poly[i]), float(poly[i + 1])] for i in range(0, len(poly), 2)]
            except (TypeError, ValueError, IndexError):
                continue
            if len(pts) >= 3:
                out.append({
                    'class': label,
                    'color': color,
                    'points': pts,
                    'type': 'polygon',
                })
    return out


def _coco_instances_obj_to_image_ann_map(obj, search_roots, dataset_root, classes, existing_class_names):
    """
    将单个 COCO instances 对象解析为 image_realpath -> 内部标注列表。
    含在 json 中列出且能解析到文件的图片；无标注的图片对应空列表。
    """
    dr = os.path.realpath(dataset_root)
    cat_id_to_name = {}
    for c in obj.get('categories') or []:
        try:
            cid = int(c['id'])
        except (KeyError, ValueError, TypeError):
            continue
        name = c.get('name', '') or f'category_{cid}'
        cat_id_to_name[cid] = str(name)

    id_to_image = {}
    for im in obj.get('images') or []:
        try:
            iid = int(im['id'])
        except (KeyError, ValueError, TypeError):
            continue
        id_to_image[iid] = im

    anns_by_img = defaultdict(list)
    for ann in obj.get('annotations') or []:
        try:
            iid = int(ann['image_id'])
        except (KeyError, ValueError, TypeError):
            continue
        if iid not in id_to_image:
            continue
        anns_by_img[iid].append(ann)

    result = {}
    for iid, im in id_to_image.items():
        fname = im.get('file_name') or ''
        img_abs = _resolve_coco_image_under_dataset(search_roots, dr, fname)
        if not img_abs:
            continue
        img_abs = os.path.realpath(img_abs)
        internal = []
        for ann in anns_by_img.get(iid, []):
            try:
                cat_id = int(ann.get('category_id', -1))
            except (TypeError, ValueError):
                continue
            label = cat_id_to_name.get(cat_id, f'class_{cat_id}')
            color = _ensure_class_named(label, classes, existing_class_names)
            internal.extend(_coco_ann_to_shapes(ann, label, color))
        result[img_abs] = internal
    return result


def _collect_coco_by_image(dataset_root, classes, existing_class_names):
    """在 dataset_root 下扫描 instances 类 COCO JSON，合并得到 图片绝对路径 -> 标注。"""
    merged = {}
    dr = os.path.realpath(dataset_root)
    for current_root, dirnames, filenames in os.walk(dr):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
        for name in filenames:
            if not name.lower().endswith('.json'):
                continue
            jpath = os.path.join(current_root, name)
            jp = os.path.realpath(jpath)
            if not _is_under_dataset_root(dr, jp):
                continue
            try:
                with open(jpath, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue
            if not _looks_like_coco_instances(obj):
                continue
            roots = _search_roots_for_coco_json(jpath, dr)
            part = _coco_instances_obj_to_image_ann_map(obj, roots, dr, classes, existing_class_names)
            for k, v in part.items():
                merged.setdefault(k, []).extend(v)
    return merged


def _unique_name_in_upload_folder(desired_basename, upload_folder):
    """若 uploads 下已存在同名文件，则在扩展名前插入 _1、_2… 直至唯一。"""
    base, ext = os.path.splitext(desired_basename)
    candidate = desired_basename
    n = 0
    while os.path.exists(os.path.join(upload_folder, candidate)):
        n += 1
        candidate = f'{base}_{n}{ext}'
    return candidate


def _flatten_import_basename(dataset_root, src_abs_path):
    """
    将数据集根目录下的相对路径压平为单一文件名，避免不同子文件夹下同名图片冲突。
    例如：正面/img1.jpg -> 正面__img1.jpg
    """
    rel = os.path.relpath(src_abs_path, dataset_root)
    parent, fname = os.path.split(rel)
    if not parent or parent == '.':
        return fname
    return parent.replace(os.sep, '__') + '__' + fname


def _external_dataset_root():
    cfg = _load_dataset_config()
    if cfg.get('mode') == 'external':
        return cfg.get('root')
    return None


def _posix_relpath_under_root(dataset_root, abs_path):
    dataset_root = os.path.realpath(dataset_root)
    abs_path = os.path.realpath(abs_path)
    try:
        rel = os.path.relpath(abs_path, dataset_root)
    except ValueError:
        return None
    if rel.startswith('..' + os.sep) or rel == '..':
        return None
    return rel.replace(os.sep, '/')


def _safe_abs_path_for_image_key(image_key):
    """将 API 中的图片键解析为绝对路径；非法或越界则返回 None。"""
    if not image_key:
        return None
    root = _external_dataset_root()
    if root:
        nk = image_key.replace('\\', '/').strip('/')
        if '..' in nk.split('/') or nk.startswith('/'):
            return None
        candidate = os.path.realpath(os.path.join(root, *nk.split('/')))
        if not os.path.isfile(candidate):
            return None
        if not _is_under_dataset_root(root, candidate):
            return None
        return candidate
    if '/' in image_key or '\\' in image_key or '..' in image_key:
        return None
    upload = os.path.realpath(app.config['UPLOAD_FOLDER'])
    candidate = os.path.realpath(os.path.join(upload, image_key))
    if not os.path.isfile(candidate):
        return None
    if not _is_under_dataset_root(upload, candidate):
        return None
    return candidate


def _iter_dataset_images():
    """遍历当前数据集下所有图片，产出 (绝对路径, API 键)。"""
    root = _external_dataset_root()
    if root:
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
            for name in filenames:
                lower = name.lower()
                if not lower.endswith(_LABELME_IMAGE_SUFFIXES):
                    continue
                src_abs = os.path.realpath(os.path.join(current_root, name))
                try:
                    if os.path.commonpath([root, src_abs]) != root:
                        continue
                except ValueError:
                    continue
                key = _posix_relpath_under_root(root, src_abs)
                if key:
                    yield src_abs, key
        return
    upload = app.config['UPLOAD_FOLDER']
    for filename in os.listdir(upload):
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
            continue
        abs_path = os.path.realpath(os.path.join(upload, filename))
        yield abs_path, filename


def _internal_ann_to_labelme_shapes(internal_anns):
    shapes = []
    for ann in internal_anns or []:
        label = ann.get('class') or ''
        if not label:
            continue
        typ = ann.get('type', 'polygon')
        pts = ann.get('points') or []
        if not pts:
            continue
        if typ == 'rectangle' and isinstance(pts, list):
            if len(pts) == 4 and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in pts):
                xs = [float(p[0]) for p in pts]
                ys = [float(p[1]) for p in pts]
                shapes.append({
                    'label': label,
                    'points': [[min(xs), min(ys)], [max(xs), max(ys)]],
                    'group_id': None,
                    'shape_type': 'rectangle',
                    'flags': {},
                })
            elif len(pts) == 2 and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in pts):
                shapes.append({
                    'label': label,
                    'points': [[float(pts[0][0]), float(pts[0][1])], [float(pts[1][0]), float(pts[1][1])]],
                    'group_id': None,
                    'shape_type': 'rectangle',
                    'flags': {},
                })
        elif typ == 'line':
            line_pts = [[float(p[0]), float(p[1])] for p in pts
                        if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(line_pts) >= 2:
                shapes.append({
                    'label': label,
                    'points': line_pts,
                    'group_id': None,
                    'shape_type': 'line',
                    'flags': {},
                })
        else:
            poly_pts = [[float(p[0]), float(p[1])] for p in pts
                        if isinstance(p, (list, tuple)) and len(p) >= 2]
            if poly_pts:
                shapes.append({
                    'label': label,
                    'points': poly_pts,
                    'group_id': None,
                    'shape_type': 'polygon',
                    'flags': {},
                })
    return shapes


def _xyxy_from_internal_ann(ann):
    """
    从内部标注得到轴对齐包围盒 [x_min, y_min, x_max, y_max]（像素）。
    与导出 YOLO 时的 points / x,y,width,height 解析逻辑一致。
    """
    if 'x' in ann and 'y' in ann and 'width' in ann and 'height' in ann:
        try:
            x = float(ann['x'])
            y = float(ann['y'])
            w = float(ann['width'])
            h = float(ann['height'])
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return [x, y, x + w, y + h]
    points = ann.get('points', [])
    if not isinstance(points, list) or len(points) == 0:
        return None
    valid_points = []
    if isinstance(points[0], dict):
        for point in points:
            if 'x' in point and 'y' in point and point['x'] is not None and point['y'] is not None:
                valid_points.append([float(point['x']), float(point['y'])])
    else:
        for point in points:
            if isinstance(point, (list, tuple)) and len(point) >= 2 and point[0] is not None and point[1] is not None:
                valid_points.append([float(point[0]), float(point[1])])
    if len(valid_points) < 2:
        return None
    arr = np.array(valid_points)
    x_min = float(np.min(arr[:, 0]))
    y_min = float(np.min(arr[:, 1]))
    x_max = float(np.max(arr[:, 0]))
    y_max = float(np.max(arr[:, 1]))
    if x_max <= x_min or y_max <= y_min:
        return None
    return [x_min, y_min, x_max, y_max]


def _coco_bbox_segmentation_from_ann(ann):
    """
    返回 (bbox [x,y,w,h], area, segmentation)。
    segmentation 为 COCO 的 list of list；纯框检测时可为 []。
    """
    typ = str(ann.get('type') or 'polygon').lower()
    xyxy = _xyxy_from_internal_ann(ann)
    if not xyxy:
        return None
    x_min, y_min, x_max, y_max = xyxy
    bw = x_max - x_min
    bh = y_max - y_min
    if bw <= 0 or bh <= 0:
        return None
    bbox = [x_min, y_min, bw, bh]
    area = float(bw * bh)
    seg = []
    if typ == 'polygon':
        points = ann.get('points') or []
        poly_pts = []
        if isinstance(points, list):
            if points and isinstance(points[0], dict):
                for point in points:
                    if 'x' in point and 'y' in point and point['x'] is not None and point['y'] is not None:
                        poly_pts.extend([float(point['x']), float(point['y'])])
            else:
                for point in points:
                    if isinstance(point, (list, tuple)) and len(point) >= 2 and point[0] is not None and point[1] is not None:
                        poly_pts.extend([float(point[0]), float(point[1])])
        if len(poly_pts) >= 6:
            seg = [poly_pts]
    return bbox, area, seg


def _should_write_labelme_sidecar(dataset_root, image_abs):
    side = os.path.splitext(image_abs)[0] + '.json'
    if os.path.isfile(side):
        return True
    ytxt = _find_yolo_txt_for_image(dataset_root, image_abs)
    return ytxt is None


def _write_labelme_sidecar_for_external_image(dataset_root, image_abs, internal_anns):
    if not _should_write_labelme_sidecar(dataset_root, image_abs):
        return
    json_path = os.path.splitext(image_abs)[0] + '.json'
    base_obj = {
        'version': '5.0.1',
        'flags': {},
        'shapes': _internal_ann_to_labelme_shapes(internal_anns),
        'imagePath': os.path.basename(image_abs),
        'imageData': None,
    }
    try:
        with Image.open(image_abs) as im:
            base_obj['imageHeight'] = im.height
            base_obj['imageWidth'] = im.width
    except Exception:
        base_obj['imageHeight'] = 0
        base_obj['imageWidth'] = 0
    if os.path.isfile(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                old = json.load(f)
            for k in ('version', 'flags'):
                if k in old:
                    base_obj[k] = old[k]
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(base_obj, f, indent=2, ensure_ascii=False)


def _import_local_dataset_from_path(dataset_root, source_mode):
    """
    将服务器本地目录扫描为当前外部数据集（不复制图片）。
    source_mode:
      'imagefolder' — LabelMe（索引 JSON + 侧车 .json）、COCO instances；若某张图仍无标注，则回退读取同布局下的 YOLO .txt（与独立「YOLO」导入一致）。
      'yolo' — 仅 YOLO 检测 .txt（与 classes.txt / data.yaml 类别顺序对应），不读取 LabelMe / COCO。
    返回 dict：成功时含 classes, annotations, image_keys, 各类计数；失败时含 'error'。
    """
    assert source_mode in ('imagefolder', 'yolo')
    classes = []
    annotations = {}
    existing_class_names = {cls['name'] for cls in classes}

    yolo_names = []
    labelme_by_image = {}
    coco_by_image = {}
    if source_mode == 'imagefolder':
        labelme_by_image = _collect_labelme_annotations_by_image(dataset_root, classes, existing_class_names)
        coco_by_image = _collect_coco_by_image(dataset_root, classes, existing_class_names)
        yolo_names = _load_yolo_class_names(dataset_root)
    else:
        yolo_names = _load_yolo_class_names(dataset_root)

    image_keys = []
    labelme_from_index = 0
    sidecar_labelme = 0
    coco_images = 0
    yolo_images = 0

    for current_root, dirnames, filenames in os.walk(dataset_root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
        for name in filenames:
            lower = name.lower()
            if not lower.endswith(_LABELME_IMAGE_SUFFIXES):
                continue
            src_abs = os.path.join(current_root, name)
            src_abs = os.path.realpath(src_abs)
            try:
                if os.path.commonpath([dataset_root, src_abs]) != dataset_root:
                    continue
            except ValueError:
                continue

            rel_key = _posix_relpath_under_root(dataset_root, src_abs)
            if not rel_key:
                continue
            image_keys.append(rel_key)

            ann_list = None

            if source_mode == 'imagefolder':
                if src_abs in labelme_by_image:
                    ann_list = list(labelme_by_image[src_abs])
                    labelme_from_index += 1
                else:
                    json_sidecar = os.path.splitext(src_abs)[0] + '.json'
                    if os.path.isfile(json_sidecar):
                        try:
                            with open(json_sidecar, 'r', encoding='utf-8') as jf:
                                jc = json.load(jf)
                            shapes = jc.get('shapes')
                            if shapes is None:
                                shapes = []
                            if isinstance(shapes, list):
                                jc_use = dict(jc)
                                jc_use['shapes'] = shapes
                                ann_list = _labelme_json_to_annotations(jc_use, classes, existing_class_names)
                                sidecar_labelme += 1
                        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                            ann_list = None

                if ann_list is None and src_abs in coco_by_image:
                    ann_list = list(coco_by_image[src_abs])
                    coco_images += 1
                if not ann_list:
                    ytxt = _find_yolo_txt_for_image(dataset_root, src_abs)
                    if ytxt:
                        ann_list = _yolo_txt_to_annotations(ytxt, src_abs, yolo_names, classes, existing_class_names)
                        yolo_images += 1
            else:
                ytxt = _find_yolo_txt_for_image(dataset_root, src_abs)
                if ytxt:
                    ann_list = _yolo_txt_to_annotations(ytxt, src_abs, yolo_names, classes, existing_class_names)
                    yolo_images += 1

            if ann_list is None:
                ann_list = []

            annotations[rel_key] = ann_list

    if not image_keys:
        return {'error': '该目录下未发现支持的图片（png/jpg/jpeg/bmp/gif）'}

    if source_mode == 'yolo' and yolo_images == 0:
        return {
            'error': '未找到与图片匹配的 YOLO 标签（.txt）。请确认目录为 YOLO 检测布局（如 train/images 与 train/labels 下同名 .txt），或改用「ImageFolder」导入含 LabelMe / COCO 的工程。',
        }

    return {
        'classes': classes,
        'annotations': annotations,
        'image_keys': image_keys,
        'labelme_from_index': labelme_from_index,
        'labelme_from_sidecar': sidecar_labelme,
        'labelme_images': labelme_from_index + sidecar_labelme,
        'coco_images': coco_images,
        'yolo_images': yolo_images,
    }


@app.route('/api/import-dataset-path', methods=['POST'])
def import_dataset_from_path():
    """
    ImageFolder：将服务器本地目录设为数据集根（不复制图片）。
    解析 LabelMe、COCO instances；若某张图仍无标注，则尝试 YOLO 布局下的同名 .txt（与「仅 YOLO」导入一致）。
    """
    try:
        data = request.get_json(silent=True) or {}
        raw = (data.get('path') or '').strip()
        if not raw:
            return jsonify({'error': '请填写数据集目录的绝对路径'}), 400

        dataset_root = os.path.realpath(os.path.expanduser(raw))
        if not os.path.isdir(dataset_root):
            return jsonify({'error': f'路径不存在或不是目录: {dataset_root}'}), 400

        out = _import_local_dataset_from_path(dataset_root, 'imagefolder')
        if out.get('error'):
            return jsonify({'error': out['error']}), 400

        slug = _slug_from_import_root(dataset_root)
        _prepare_dataset_import_slot(slug)
        with open(_dataset_config_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'external', 'root': dataset_root}, f, indent=2, ensure_ascii=False)
        with open(_classes_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(out['classes'], f, indent=2, ensure_ascii=False)
        with open(_annotations_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(out['annotations'], f, indent=2, ensure_ascii=False)
        _write_active_file(slug)

        hint = None
        if out['labelme_images'] == 0 and out['coco_images'] == 0 and out['yolo_images'] == 0:
            hint = '未发现 LabelMe、COCO 或 YOLO .txt 标注。请确认图片与标签路径（如 images 与 labels 对应、data.yaml / classes.txt）。'

        return jsonify({
            'message': '已将本地目录设为数据集根目录（ImageFolder：LabelMe / COCO，未复制图片）',
            'path': dataset_root,
            'dataset_slug': slug,
            'images_copied': len(out['image_keys']),
            'labelme_images': out['labelme_images'],
            'labelme_from_index': out['labelme_from_index'],
            'labelme_from_sidecar': out['labelme_from_sidecar'],
            'coco_images': out['coco_images'],
            'yolo_images': out['yolo_images'],
            'files': out['image_keys'],
            'hint': hint,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'导入失败: {str(e)}'}), 500


@app.route('/api/import-yolo-path', methods=['POST'])
def import_yolo_dataset_from_path():
    """
    YOLO：将服务器本地目录设为数据集根（不复制图片）。
    仅解析与图片同名的 .txt（归一化 cx cy w h）及 classes.txt / data.yaml 类别名。
    """
    try:
        data = request.get_json(silent=True) or {}
        raw = (data.get('path') or '').strip()
        if not raw:
            return jsonify({'error': '请填写 YOLO 数据集根目录的绝对路径'}), 400

        dataset_root = os.path.realpath(os.path.expanduser(raw))
        if not os.path.isdir(dataset_root):
            return jsonify({'error': f'路径不存在或不是目录: {dataset_root}'}), 400

        out = _import_local_dataset_from_path(dataset_root, 'yolo')
        if out.get('error'):
            return jsonify({'error': out['error']}), 400

        slug = _slug_from_import_root(dataset_root)
        _prepare_dataset_import_slot(slug)
        with open(_dataset_config_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'external', 'root': dataset_root}, f, indent=2, ensure_ascii=False)
        with open(_classes_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(out['classes'], f, indent=2, ensure_ascii=False)
        with open(_annotations_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(out['annotations'], f, indent=2, ensure_ascii=False)
        _write_active_file(slug)

        return jsonify({
            'message': '已将本地目录设为数据集根目录（YOLO .txt，未复制图片）',
            'path': dataset_root,
            'dataset_slug': slug,
            'images_copied': len(out['image_keys']),
            'labelme_images': 0,
            'labelme_from_index': 0,
            'labelme_from_sidecar': 0,
            'coco_images': 0,
            'yolo_images': out['yolo_images'],
            'files': out['image_keys'],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'导入失败: {str(e)}'}), 500


@app.route('/api/import-coco-path', methods=['POST'])
def import_coco_path():
    """
    从 COCO instances JSON 绑定数据集：将图片根目录设为当前数据集根目录（不复制图片）。
    请求 JSON：coco_json（必填），images_root（可选，默认同 annotations 的上一级目录）。
    仅把 JSON 中能解析到的图片的 bbox/segmentation 写入 annotations.json（键为相对根目录的路径）；
    再次导入会按当前 JSON 与磁盘解析结果重写标注表。
    """
    try:
        data = request.get_json(silent=True) or {}
        coco_json_raw = (data.get('coco_json') or '').strip()
        images_root_raw = (data.get('images_root') or '').strip()
        if not coco_json_raw:
            return jsonify({'error': '请填写 COCO 标注 JSON（如 instances_train2017.json）的绝对路径'}), 400

        coco_json = os.path.realpath(os.path.expanduser(coco_json_raw))
        if not os.path.isfile(coco_json):
            return jsonify({'error': f'标注文件不存在: {coco_json}'}), 400

        if images_root_raw:
            dr = os.path.realpath(os.path.expanduser(images_root_raw))
        else:
            dr = os.path.realpath(os.path.join(os.path.dirname(coco_json), '..'))
        if not os.path.isdir(dr):
            return jsonify({'error': f'图片根目录不存在: {dr}'}), 400

        try:
            with open(coco_json, 'r', encoding='utf-8') as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            return jsonify({'error': f'无法读取 JSON: {e}'}), 400

        if not _looks_like_coco_instances(obj):
            return jsonify({'error': '不是 COCO instances 格式（需含 images、annotations、categories 字段，且与 LabelMe JSON 区分）'}), 400

        classes = []
        existing_class_names = set()

        roots = _search_roots_for_coco_json(coco_json, dr)
        if images_root_raw:
            ur = os.path.realpath(os.path.expanduser(images_root_raw))
            extra = [ur, os.path.join(ur, 'images'), os.path.join(ur, 'JPEGImages')]
            merged_roots, seen = [], set()
            for r in extra + roots:
                rp = os.path.realpath(r)
                if rp not in seen and os.path.isdir(rp):
                    seen.add(rp)
                    merged_roots.append(rp)
            roots = merged_roots

        part = _coco_instances_obj_to_image_ann_map(obj, roots, dr, classes, existing_class_names)
        if not part:
            return jsonify({'error': '未解析到任何图片，请检查 images_root 与 JSON 中 file_name 是否一致'}), 400

        annotations = {}
        ann_instances = 0
        for img_abs, ann_list in part.items():
            rel_key = _posix_relpath_under_root(dr, img_abs)
            if not rel_key:
                continue
            annotations[rel_key] = list(ann_list)
            ann_instances += len(ann_list)

        if not annotations:
            return jsonify({'error': '解析到的图片均无法映射到图片根目录下的相对路径，请检查 images_root'}), 400

        slug = _slug_from_import_root(dr)
        _prepare_dataset_import_slot(slug)
        with open(_dataset_config_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'external', 'root': dr}, f, indent=2, ensure_ascii=False)
        with open(_classes_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(classes, f, indent=2, ensure_ascii=False)
        with open(_annotations_file_for_slug(slug), 'w', encoding='utf-8') as f:
            json.dump(annotations, f, indent=2, ensure_ascii=False)
        _write_active_file(slug)

        image_keys = sorted(annotations.keys())
        return jsonify({
            'message': '已从 COCO JSON 绑定数据集（未复制图片）',
            'coco_json': coco_json,
            'images_root': dr,
            'dataset_slug': slug,
            'images_copied': len(image_keys),
            'annotation_instances': ann_instances,
            'files': image_keys,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'导入失败: {str(e)}'}), 500


@app.route('/api/upload/video', methods=['POST'])
def upload_video():
    """上传视频文件并抽帧"""
    import uuid
    
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    
    video_file = request.files['video']
    frame_interval = int(request.form.get('frame_interval', 30))  # 默认每隔30帧保存一帧
    
    if video_file.filename == '':
        return jsonify({'error': 'No video file selected'}), 400
    
    try:
        # 保存原始文件名（用于生成帧图片名）
        original_filename = video_file.filename or 'video'
        original_name = os.path.splitext(original_filename)[0]
        video_ext = os.path.splitext(original_filename)[1] or '.mp4'
        
        # 使用UUID作为临时文件名（避免中文路径问题）
        temp_filename = f"temp_{uuid.uuid4().hex}{video_ext}"
        temp_video_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
        video_file.save(temp_video_path)
        
        # 抽帧处理，传入原始文件名用于命名帧图片
        extracted_frames = extract_frames(temp_video_path, frame_interval, original_name)
        
        # 删除临时视频文件
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)
        
        if extracted_frames:
            _set_dataset_mode_upload()
        return jsonify({
            'message': 'Video frames extracted successfully', 
            'frames': extracted_frames,
            'count': len(extracted_frames)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Failed to process video: {str(e)}'}), 500


def extract_frames(video_path, frame_interval, original_name=None):
    """从视频中抽帧并保存为图片"""
    
    # 打开视频文件
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        # 尝试使用绝对路径
        abs_path = os.path.abspath(video_path)
        cap = cv2.VideoCapture(abs_path)
        if not cap.isOpened():
            raise Exception(f"无法打开视频文件: {video_path}")
    
    frame_count = 0
    saved_frame_count = 0
    extracted_frames = []
    
    # 使用传入的原始文件名，如果没有则从路径提取
    if original_name is None:
        video_basename = os.path.basename(video_path)
        if video_basename.startswith('temp_'):
            video_basename = video_basename[5:]
        original_name = os.path.splitext(video_basename)[0]
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # 每隔frame_interval帧保存一帧
        if frame_count % frame_interval == 0:
            # 生成文件名
            frame_filename = f"{original_name}_frame_{saved_frame_count:06d}.jpg"
            frame_path = os.path.join(app.config['UPLOAD_FOLDER'], frame_filename)
            
            # Windows中文路径兼容：使用cv2.imencode + 文件写入
            success, encoded_img = cv2.imencode('.jpg', frame)
            if success:
                with open(frame_path, 'wb') as f:
                    f.write(encoded_img.tobytes())
                extracted_frames.append(frame_filename)
                saved_frame_count += 1
            
        frame_count += 1
    
    cap.release()
    return extracted_frames


@app.route('/api/annotations/<path:image_name>')
def get_annotations(image_name):
    """获取特定图片的标注"""
    annotations = {}
    if os.path.exists(_current_annotations_file()):
        try:
            with open(_current_annotations_file(), 'r', encoding='utf-8') as f:
                annotations = json.load(f)
        except json.JSONDecodeError:
            # 如果JSON文件无效或为空，使用空字典
            annotations = {}
        except Exception as e:
            # 处理其他可能的错误
            print(f"Error reading annotations file: {e}")
            annotations = {}
    
    image_annotations = annotations.get(image_name, [])
    return jsonify(image_annotations)


@app.route('/api/annotations/<path:image_name>', methods=['POST'])
def save_annotations(image_name):
    """保存特定图片的标注"""
    import shutil
    import filelock
    
    data = request.json
    if not _safe_abs_path_for_image_key(image_name):
        return jsonify({'error': '图片不存在或路径无效'}), 400
    
    # 使用文件锁防止并发写入
    lock_file = _current_annotations_file() + '.lock'
    lock = filelock.FileLock(lock_file, timeout=10)
    
    try:
        with lock:
            # 读取现有标注
            annotations = {}
            if os.path.exists(_current_annotations_file()):
                try:
                    with open(_current_annotations_file(), 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():  # 确保文件不为空
                            annotations = json.loads(content)
                except json.JSONDecodeError as e:
                    # JSON解析失败，不覆盖原文件，返回错误
                    print(f"JSON解析失败: {e}")
                    return jsonify({'error': f'标注文件格式错误，无法保存: {str(e)}'}), 500
                except Exception as e:
                    print(f"读取标注文件失败: {e}")
                    return jsonify({'error': f'读取标注文件失败: {str(e)}'}), 500
            
            # 保存前先备份（每次保存都备份，保留最近一次）
            if os.path.exists(_current_annotations_file()):
                backup_file = _current_annotations_file() + '.bak'
                try:
                    shutil.copy2(_current_annotations_file(), backup_file)
                except Exception as e:
                    print(f"备份失败: {e}")
            
            # 更新标注
            annotations[image_name] = data
            
            # 先写入临时文件，成功后再替换原文件
            temp_file = _current_annotations_file() + '.tmp'
            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(annotations, f, indent=2, ensure_ascii=False)
                
                # 验证写入的JSON是否有效
                with open(temp_file, 'r', encoding='utf-8') as f:
                    json.load(f)  # 验证JSON格式
                
                # 替换原文件
                if os.path.exists(_current_annotations_file()):
                    os.replace(temp_file, _current_annotations_file())
                else:
                    os.rename(temp_file, _current_annotations_file())

                ext_root = _external_dataset_root()
                if ext_root:
                    img_abs = _safe_abs_path_for_image_key(image_name)
                    if img_abs:
                        try:
                            _write_labelme_sidecar_for_external_image(ext_root, img_abs, data)
                        except Exception as e:
                            print(f"同步 LabelMe 侧车 JSON 失败: {e}")
                    
            except Exception as e:
                # 写入失败，删除临时文件
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                print(f"写入标注文件失败: {e}")
                return jsonify({'error': f'保存失败: {str(e)}'}), 500
            
            return jsonify({'message': 'Annotations saved successfully'})
            
    except filelock.Timeout:
        return jsonify({'error': '文件正在被其他操作使用，请稍后重试'}), 503


@app.route('/api/ai-annotate', methods=['POST'])
def ai_annotate():
    """执行AI自动标注"""
    try:
        data = request.json or {}
        image_name = data.get('image_name', '')
        model_name = data.get('model_name', '')
        confidence = float(data.get('confidence', 0.5))
        install_path = data.get('install_path', 'plugins/yolo11')
        
        if not image_name:
            return jsonify({'error': '未指定图片'}), 400
        if not model_name:
            return jsonify({'error': '未指定模型'}), 400
        
        # 构建路径
        if not os.path.isabs(install_path):
            install_path = os.path.join(app.root_path, install_path)
        
        image_path = _safe_abs_path_for_image_key(image_name)
        model_path = os.path.join(install_path, 'models', model_name)
        
        # 确保路径是绝对路径
        if image_path:
            image_path = os.path.abspath(image_path)
        model_path = os.path.abspath(model_path)
        
        # 检查文件是否存在
        if not image_path or not os.path.exists(image_path):
            return jsonify({'error': f'图片不存在: {image_name}'}), 400
        if not os.path.exists(model_path):
            return jsonify({'error': f'模型不存在: {model_name}'}), 400
        
        # 获取Python路径 - 优先使用插件虚拟环境，否则使用系统Python
        if os.name == 'nt':  # Windows
            venv_python = os.path.join(install_path, 'venv', 'Scripts', 'python.exe')
        else:  # Linux/macOS
            venv_python = os.path.join(install_path, 'venv', 'bin', 'python')
        
        # 如果插件虚拟环境存在则使用，否则使用当前Python环境
        if os.path.exists(venv_python):
            python_path = venv_python
        else:
            python_path = sys.executable  # 使用当前运行的Python
        
        # 构建推理脚本 - 使用特殊标记包裹JSON输出
        inference_script = f'''
import json
import sys
import os

# 禁用ultralytics的输出
os.environ['YOLO_VERBOSE'] = 'False'

from ultralytics import YOLO

model = YOLO(r"{model_path}")
results = model(r"{image_path}", conf={confidence}, verbose=False)

annotations = []
for result in results:
    if result.boxes is not None:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]
            conf = float(box.conf[0])
            
            annotations.append({{
                "class": cls_name,
                "confidence": conf,
                "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                "type": "rectangle",
                "auto": True
            }})

# 使用特殊标记包裹JSON，便于解析
print("###JSON_START###")
print(json.dumps(annotations))
print("###JSON_END###")
'''
        
        # 执行推理
        import subprocess
        result = subprocess.run(
            [python_path, '-c', inference_script],
            capture_output=True,
            text=True,
            cwd=install_path,
            timeout=60,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else '推理失败'
            return jsonify({'error': f'模型推理失败: {error_msg}'}), 500
        
        # 解析输出 - 使用特殊标记提取JSON
        output = result.stdout
        
        # 查找JSON标记
        start_marker = "###JSON_START###"
        end_marker = "###JSON_END###"
        
        json_start = output.find(start_marker)
        json_end = output.find(end_marker)
        
        if json_start == -1 or json_end == -1:
            # 回退到旧方法
            json_start = output.rfind('[')
            json_end = output.rfind(']')
            if json_start == -1 or json_end == -1:
                return jsonify({'error': '无法解析模型输出', 'output': output[:500]}), 500
            json_str = output[json_start:json_end+1]
        else:
            json_str = output[json_start + len(start_marker):json_end].strip()
        
        annotations = json.loads(json_str)
        
        # 读取现有类别
        existing_classes = []
        if os.path.exists(_current_classes_file()):
            with open(_current_classes_file(), 'r') as f:
                existing_classes = json.load(f)
        
        existing_class_names = {cls['name'] for cls in existing_classes}
        
        # 为标注添加颜色，并自动创建不存在的类别
        new_classes_added = False
        for ann in annotations:
            cls_name = ann['class']
            # 查找类别颜色
            color = None
            for cls in existing_classes:
                if cls['name'] == cls_name:
                    color = cls['color']
                    break
            
            if color is None:
                # 类别不存在，创建新类别
                new_color = '#{:06x}'.format(hash(cls_name) % 0x1000000)
                existing_classes.append({'name': cls_name, 'color': new_color})
                existing_class_names.add(cls_name)
                color = new_color
                new_classes_added = True
            
            ann['color'] = color
            ann['id'] = int(hash(f"{cls_name}_{ann['points'][0][0]}_{ann['points'][0][1]}") % 1000000000)
        
        # 保存新增的类别
        if new_classes_added:
            with open(_current_classes_file(), 'w') as f:
                json.dump(existing_classes, f, indent=2)
        
        return jsonify({
            'success': True,
            'annotations': annotations,
            'new_classes_added': new_classes_added
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': '模型推理超时'}), 500
    except json.JSONDecodeError as e:
        return jsonify({'error': f'解析模型输出失败: {str(e)}'}), 500
    except Exception as e:
        import traceback
        print(f"AI标注错误: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'AI标注失败: {str(e)}'}), 500


@app.route('/api/ai-annotate-batch', methods=['POST'])
def ai_annotate_batch():
    """批量执行AI自动标注 - 一次性处理多张图片，速度更快"""
    try:
        import subprocess
        data = request.json or {}
        image_names = data.get('image_names', [])
        model_name = data.get('model_name', '')
        confidence = float(data.get('confidence', 0.5))
        install_path = data.get('install_path', 'plugins/yolo11')
        
        if not image_names:
            return jsonify({'error': '未指定图片'}), 400
        if not model_name:
            return jsonify({'error': '未指定模型'}), 400
        
        # 构建路径
        if not os.path.isabs(install_path):
            install_path = os.path.join(app.root_path, install_path)
        
        model_path = os.path.join(install_path, 'models', model_name)
        model_path = os.path.abspath(model_path)
        
        if not os.path.exists(model_path):
            return jsonify({'error': f'模型不存在: {model_name}'}), 400
        
        # 获取Python路径 - 优先使用插件虚拟环境，否则使用系统Python
        if os.name == 'nt':  # Windows
            venv_python = os.path.join(install_path, 'venv', 'Scripts', 'python.exe')
        else:  # Linux/macOS
            venv_python = os.path.join(install_path, 'venv', 'bin', 'python')
        
        # 如果插件虚拟环境存在则使用，否则使用当前Python环境
        if os.path.exists(venv_python):
            python_path = venv_python
        else:
            python_path = sys.executable  # 使用当前运行的Python
        
        # 构建图片路径列表
        image_paths = []
        valid_image_names = []
        for img_name in image_names:
            img_path = _safe_abs_path_for_image_key(img_name)
            if img_path:
                img_path = os.path.abspath(img_path)
            if img_path and os.path.exists(img_path):
                image_paths.append(img_path)
                valid_image_names.append(img_name)
        
        if not image_paths:
            return jsonify({'error': '没有有效的图片'}), 400
        
        # 将图片路径列表转为JSON字符串
        image_paths_json = json.dumps(image_paths)
        
        # 构建批量推理脚本
        inference_script = f'''
import json
import sys
import os

# 禁用ultralytics的输出
os.environ['YOLO_VERBOSE'] = 'False'

from ultralytics import YOLO

model = YOLO(r"{model_path}")
image_paths = {image_paths_json}

all_results = {{}}

# 批量推理 - YOLO支持传入列表一次性处理多张图片
results = model(image_paths, conf={confidence}, verbose=False)

for i, result in enumerate(results):
    img_path = image_paths[i]
    annotations = []
    if result.boxes is not None:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]
            conf = float(box.conf[0])
            
            annotations.append({{
                "class": cls_name,
                "confidence": conf,
                "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                "type": "rectangle",
                "auto": True
            }})
    all_results[img_path] = annotations

print("###JSON_START###")
print(json.dumps(all_results))
print("###JSON_END###")
'''
        
        # 执行批量推理
        result = subprocess.run(
            [python_path, '-c', inference_script],
            capture_output=True,
            text=True,
            cwd=install_path,
            timeout=300,  # 批量处理给更长的超时时间
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else '推理失败'
            return jsonify({'error': f'模型推理失败: {error_msg}'}), 500
        
        # 解析输出
        output = result.stdout
        start_marker = "###JSON_START###"
        end_marker = "###JSON_END###"
        
        json_start = output.find(start_marker)
        json_end = output.find(end_marker)
        
        if json_start == -1 or json_end == -1:
            return jsonify({'error': '无法解析模型输出'}), 500
        
        json_str = output[json_start + len(start_marker):json_end].strip()
        all_annotations = json.loads(json_str)
        
        # 读取现有类别
        existing_classes = []
        if os.path.exists(_current_classes_file()):
            with open(_current_classes_file(), 'r') as f:
                existing_classes = json.load(f)
        
        existing_class_names = {cls['name'] for cls in existing_classes}
        new_classes_added = False
        
        # 读取现有标注
        all_saved_annotations = {}
        if os.path.exists(_current_annotations_file()):
            with open(_current_annotations_file(), 'r') as f:
                all_saved_annotations = json.load(f)
        
        # 处理每张图片的标注结果
        results_summary = []
        for i, img_path in enumerate(image_paths):
            img_name = valid_image_names[i]
            annotations = all_annotations.get(img_path, [])
            
            # 为标注添加颜色和ID
            for ann in annotations:
                cls_name = ann['class']
                color = None
                for cls in existing_classes:
                    if cls['name'] == cls_name:
                        color = cls['color']
                        break
                
                if color is None:
                    new_color = '#{:06x}'.format(hash(cls_name) % 0x1000000)
                    existing_classes.append({'name': cls_name, 'color': new_color})
                    existing_class_names.add(cls_name)
                    color = new_color
                    new_classes_added = True
                
                ann['color'] = color
                ann['id'] = int(hash(f"{cls_name}_{ann['points'][0][0]}_{ann['points'][0][1]}") % 1000000000)
            
            # 合并到现有标注
            existing_anns = all_saved_annotations.get(img_name, [])
            merged_anns = existing_anns + annotations
            all_saved_annotations[img_name] = merged_anns
            
            results_summary.append({
                'image_name': img_name,
                'count': len(annotations),
                'success': True
            })
        
        # 保存所有标注
        with open(_current_annotations_file(), 'w') as f:
            json.dump(all_saved_annotations, f, indent=2)
        
        # 保存新增的类别
        if new_classes_added:
            with open(_current_classes_file(), 'w') as f:
                json.dump(existing_classes, f, indent=2)
        
        return jsonify({
            'success': True,
            'results': results_summary,
            'total_processed': len(results_summary),
            'new_classes_added': new_classes_added
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': '批量推理超时'}), 500
    except json.JSONDecodeError as e:
        return jsonify({'error': f'解析模型输出失败: {str(e)}'}), 500
    except Exception as e:
        import traceback
        print(f"批量AI标注错误: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'批量AI标注失败: {str(e)}'}), 500


@app.route('/api/check-yolo11-install')
def check_yolo11_install():
    """检查YOLO11安装状态"""
    import os
    # 检查YOLO11安装路径是否存在
    yolo11_path = os.path.join(app.root_path, 'plugins', 'yolo11')
    is_installed = os.path.exists(yolo11_path) and os.path.isdir(yolo11_path)
    
    # 初始化安装信息
    install_info = {
        'is_installed': is_installed,
        'install_time': '',
        'has_cuda': False,
        'hardware': 'CPU'
    }
    
    # 如果已安装，读取详细的安装信息
    if is_installed:
        install_info_path = os.path.join(yolo11_path, 'install_info.json')
        if os.path.exists(install_info_path):
            try:
                with open(install_info_path, 'r', encoding='utf-8') as f:
                    saved_info = json.load(f)
                    # 更新安装信息
                    install_info.update(saved_info)
            except Exception as e:
                print(f"读取安装信息失败: {e}")
    
    return jsonify(install_info)


@app.route('/api/download-models')
def download_models():
    """下载YOLO11预训练模型"""
    import os
    import subprocess
    import time
    from flask import Response
    
    # 获取模型列表和安装路径
    models_str = request.args.get('models', '')
    models = models_str.split(',') if models_str else []
    install_path = request.args.get('install_path', 'plugins/yolo11')
    
    # 确保安装路径是相对于项目根目录的
    if not os.path.isabs(install_path):
        install_path = os.path.join(app.root_path, install_path)
    
    def generate():
        # 发送初始状态
        yield f"data: {json.dumps({'status': 'started', 'message': '开始下载模型...', 'progress': 0})}\n\n"
        time.sleep(0.5)
        
        try:
            # 检查YOLO11是否安装
            if not os.path.exists(install_path) or not os.path.isdir(install_path):
                yield f"data: {json.dumps({'status': 'error', 'message': 'YOLO11未安装', 'progress': 0})}\n\n"
                return
            
            # 获取虚拟环境中的python路径
            if os.name == 'nt':  # Windows
                python_path = os.path.join(install_path, 'venv', 'Scripts', 'python.exe')
            else:  # Linux/macOS
                python_path = os.path.join(install_path, 'venv', 'bin', 'python')
            
            # 检查python路径是否存在
            if not os.path.exists(python_path):
                yield f"data: {json.dumps({'status': 'error', 'message': '虚拟环境未找到', 'progress': 0})}\n\n"
                return
            
            # 创建models目录
            models_dir = os.path.join(install_path, 'models')
            os.makedirs(models_dir, exist_ok=True)
            
            # 下载每个模型
            total_models = len(models)
            for i, model in enumerate(models):
                yield f"data: {json.dumps({'message': f'正在下载模型: {model}...', 'progress': int((i / total_models) * 50) + 10})}\n\n"
                
                # 使用ultralytics的CLI下载模型
                result = subprocess.run(
                    [python_path, '-c', f'from ultralytics import YOLO; YOLO("{model}.pt")'],
                    capture_output=True,
                    text=True,
                    cwd=models_dir,
                    encoding='utf-8',
                    errors='ignore'
                )
                
                if result.returncode != 0:
                    yield f"data: {json.dumps({'status': 'error', 'message': f'下载模型 {model} 失败: {result.stderr}', 'progress': 0})}\n\n"
                    return
                
                time.sleep(0.5)
            
            # 下载完成
            yield f"data: {json.dumps({'message': '模型下载完成！', 'progress': 100, 'status': 'completed'})}\n\n"
            
        except Exception as e:
            import traceback
            yield f"data: {json.dumps({'status': 'error', 'message': f'下载失败: {str(e)}', 'progress': 0, 'traceback': traceback.format_exc()})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/list-models')
def list_models():
    """获取已安装的YOLO11模型列表"""
    import os
    
    # 获取安装路径
    install_path = request.args.get('install_path', 'plugins/yolo11')
    # 确保安装路径是相对于项目根目录的
    if not os.path.isabs(install_path):
        install_path = os.path.join(app.root_path, install_path)
    
    # 初始化模型列表
    models = []
    
    # 检查YOLO11是否安装
    if os.path.exists(install_path) and os.path.isdir(install_path):
        # 检查models目录是否存在
        models_dir = os.path.join(install_path, 'models')
        if os.path.exists(models_dir) and os.path.isdir(models_dir):
            # 列出models目录下的所有.pt文件
            for file in os.listdir(models_dir):
                if file.endswith('.pt'):
                    models.append(file)
    
    return jsonify({'models': models})


@app.route('/api/upload-model', methods=['POST'])
def upload_model():
    """上传YOLO11模型文件"""
    import os
    
    # 获取安装路径
    install_path = request.headers.get('X-Install-Path', 'plugins/yolo11')
    # 确保安装路径是相对于项目根目录的
    if not os.path.isabs(install_path):
        install_path = os.path.join(app.root_path, install_path)
    
    # 检查YOLO11是否安装
    if not os.path.exists(install_path) or not os.path.isdir(install_path):
        return jsonify({'success': False, 'error': 'YOLO11未安装'})
    
    # 检查是否有文件上传
    if 'files[]' not in request.files:
        return jsonify({'success': False, 'error': '未找到上传的文件'})
    
    # 创建models目录
    models_dir = os.path.join(install_path, 'models')
    os.makedirs(models_dir, exist_ok=True)
    
    # 保存上传的文件
    uploaded_files = []
    files = request.files.getlist('files[]')
    for file in files:
        if file.filename != '' and file.filename.endswith('.pt'):
            # 保存文件到models目录
            file_path = os.path.join(models_dir, file.filename)
            file.save(file_path)
            uploaded_files.append(file.filename)
    
    return jsonify({'success': True, 'uploaded_files': uploaded_files})


@app.route('/api/delete-model', methods=['POST'])
def delete_model():
    """删除YOLO11模型文件"""
    import os
    
    # 获取安装路径
    install_path = request.headers.get('X-Install-Path', 'plugins/yolo11')
    # 确保安装路径是相对于项目根目录的
    if not os.path.isabs(install_path):
        install_path = os.path.join(app.root_path, install_path)
    
    # 获取模型名称
    data = request.json or {}
    model_name = data.get('model_name', '')
    
    # 检查YOLO11是否安装
    if not os.path.exists(install_path) or not os.path.isdir(install_path):
        return jsonify({'success': False, 'error': 'YOLO11未安装'})
    
    # 检查模型名称是否为空
    if not model_name:
        return jsonify({'success': False, 'error': '模型名称不能为空'})
    
    # 构建模型文件路径
    models_dir = os.path.join(install_path, 'models')
    model_path = os.path.join(models_dir, model_name)
    
    # 检查模型文件是否存在
    if not os.path.exists(model_path):
        return jsonify({'success': False, 'error': '模型文件不存在'})
    
    try:
        # 删除模型文件
        os.remove(model_path)
        return jsonify({'success': True, 'message': f'模型 {model_name} 删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'删除模型失败: {str(e)}'})


def _dataset_api_base():
    return (os.getenv('DATASET_API_BASE') or 'http://127.0.0.1:48080/admin-api').strip().rstrip('/')


def _request_authorization():
    auth = (request.headers.get('Authorization') or request.headers.get('X-Authorization') or '').strip()
    if not auth:
        auth = (os.getenv('DATASET_API_TOKEN') or '').strip()
    if auth and not auth.lower().startswith('bearer '):
        auth = 'Bearer ' + auth
    return auth


def _cloud_verify_ssl():
    raw = os.getenv('DATASET_API_VERIFY_SSL', 'true').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def _cloud_minio_config():
    endpoint = (os.getenv('MINIO_ENDPOINT') or '').strip()
    access_key = (os.getenv('MINIO_ACCESS_KEY') or '').strip()
    secret_key = (os.getenv('MINIO_SECRET_KEY') or '').strip()
    secure = os.getenv('MINIO_SECURE', 'false')
    bucket = (os.getenv('MINIO_DATASETS_BUCKET') or 'datasets').strip()
    return {
        'endpoint': endpoint,
        'access_key': access_key,
        'secret_key': secret_key,
        'secure': secure,
        'bucket': bucket,
    }


def _cloud_auth_headers(authorization):
    h = {}
    if authorization:
        auth = str(authorization).strip()
        if auth and not auth.lower().startswith('bearer '):
            auth = 'Bearer ' + auth
        if auth:
            h['Authorization'] = auth
    return h


def _cloud_response_data(body):
    if not isinstance(body, dict):
        raise RuntimeError(f'云平台返回非 JSON 对象: {str(body)[:200]}')
    if 'code' in body:
        if body.get('code') != 0:
            msg = body.get('msg') or body.get('message') or str(body)
            raise RuntimeError(msg)
        return body.get('data')
    return body


def _cloud_api_json(api_base, method, rel_path, authorization, params=None, json_body=None, timeout=180, verify_ssl=True):
    base = (api_base or '').strip().rstrip('/')
    if not base:
        raise ValueError('api_base 不能为空')
    url = base + '/' + str(rel_path).lstrip('/')
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    headers.update(_cloud_auth_headers(authorization))
    kw = {'headers': headers, 'timeout': timeout, 'verify': verify_ssl}
    if params:
        kw['params'] = params
    if json_body is not None:
        kw['json'] = json_body
    m = method.upper()
    if m == 'GET':
        r = requests.get(url, **kw)
    elif m == 'POST':
        r = requests.post(url, **kw)
    elif m == 'PUT':
        r = requests.put(url, **kw)
    else:
        raise ValueError(method)
    try:
        body = r.json()
    except Exception:
        r.raise_for_status()
        raise RuntimeError(f'云平台返回非 JSON: HTTP {r.status_code} {r.text[:800]}')
    return _cloud_response_data(body)


def _parse_gateway_path_to_bucket_key(storage_path):
    """解析 iot-dataset-biz 中 MinIO 下载路径，得到 (bucket, object_key)。"""
    if not storage_path:
        return None, None
    s = str(storage_path).strip()
    if 'prefix=' not in s:
        if '/' in s and not s.startswith('http'):
            return None, s.lstrip('/')
        return None, None
    try:
        if s.startswith('http://') or s.startswith('https://'):
            u = urlparse(s)
            q = parse_qs(u.query)
            pref = (q.get('prefix') or [''])[0]
            pref = unquote(pref)
            m = re.search(r'/buckets/([^/]+)/objects', u.path or '')
            bucket = m.group(1) if m else None
            return bucket, pref
        qstart = s.index('prefix=') + 7
        rest = s[qstart:]
        if '&' in rest:
            rest = rest.split('&', 1)[0]
        pref = unquote(rest)
        m = re.search(r'/buckets/([^/]+)/objects', s)
        bucket = m.group(1) if m else None
        return bucket, pref
    except Exception:
        return None, None


def _cloud_fetch_all_pages(api_base, rel_path, authorization, fixed_params, page_size=100, verify_ssl=True):
    out = []
    page_no = 1
    max_pages = 5000
    while page_no <= max_pages:
        params = dict(fixed_params or {})
        params['pageNo'] = page_no
        params['pageSize'] = page_size
        data = _cloud_api_json(api_base, 'GET', rel_path, authorization, params=params, verify_ssl=verify_ssl) or {}
        lst = data.get('list') or []
        total = int(data.get('total') or 0)
        out.extend(lst)
        if len(lst) < page_size or (total and len(out) >= total):
            break
        page_no += 1
    return out


def _cloud_annotations_to_auto_labeling(ann_json, shortcut_to_tag, img_w, img_h):
    out = []
    if not ann_json or not str(ann_json).strip():
        return out
    try:
        items = json.loads(ann_json) if isinstance(ann_json, str) else ann_json
    except (json.JSONDecodeError, TypeError):
        return out
    if not isinstance(items, list):
        return out
    iw, ih = float(img_w or 1), float(img_h or 1)
    if ih <= 0 or iw <= 0:
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        lab = it.get('label')
        try:
            sc = int(lab)
        except (TypeError, ValueError):
            continue
        tag = shortcut_to_tag.get(sc)
        if not tag:
            continue
        name = tag.get('name')
        color = tag.get('color') or '#000000'
        pts = it.get('points')
        if not isinstance(pts, list) or len(pts) < 2:
            continue
        xs, ys = [], []
        for p in pts:
            if isinstance(p, dict) and 'x' in p and 'y' in p:
                xs.append(float(p['x']) * iw)
                ys.append(float(p['y']) * ih)
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                xs.append(float(p[0]) * iw)
                ys.append(float(p[1]) * ih)
        if not xs:
            continue
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        out.append({
            'class': name,
            'color': color,
            'points': [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]],
            'type': 'rectangle',
        })
    return out


def _auto_labeling_ann_list_to_cloud_json(ann_list, name_to_shortcut, iw, ih):
    cloud_list = []
    if iw <= 0 or ih <= 0:
        return json.dumps(cloud_list, ensure_ascii=False)
    for ann in ann_list or []:
        if ann.get('type') == 'line':
            continue
        cls_name = ann.get('class')
        if not cls_name:
            continue
        sc = name_to_shortcut.get(cls_name)
        if sc is None:
            continue
        pts_in = ann.get('points') or []
        xs, ys = [], []
        if isinstance(pts_in, list):
            for p in pts_in:
                if isinstance(p, dict) and 'x' in p and 'y' in p:
                    xs.append(float(p['x']))
                    ys.append(float(p['y']))
                elif isinstance(p, (list, tuple)) and len(p) >= 2:
                    xs.append(float(p[0]))
                    ys.append(float(p[1]))
        if len(xs) >= 2 and len(ys) >= 2:
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
        elif all(k in ann for k in ('x', 'y', 'width', 'height')):
            x_min = float(ann['x'])
            y_min = float(ann['y'])
            x_max = x_min + float(ann['width'])
            y_max = y_min + float(ann['height'])
        else:
            continue
        cloud_list.append({
            'label': sc,
            'points': [
                {'x': x_min / iw, 'y': y_min / ih},
                {'x': x_max / iw, 'y': y_min / ih},
                {'x': x_max / iw, 'y': y_max / ih},
                {'x': x_min / iw, 'y': y_max / ih},
            ],
        })
    return json.dumps(cloud_list, ensure_ascii=False)


def _sanitize_cloud_name(s, max_len=48):
    s = (s or '').strip() or 'dataset'
    s = re.sub(r'[^\w\u4e00-\u9fff.-]+', '_', s)
    return s[:max_len] or 'dataset'


def _cloud_sync_file_for_slug(slug):
    return os.path.join(_dataset_slot_dir(slug), 'cloud_sync.json')


CLOUD_DATASETS_ZIP_BUCKET = 'datasets'


def _resolve_extracted_dataset_root(extract_dir):
    """若 zip 内仅有一层目录，则以其为数据集根。"""
    extract_dir = os.path.realpath(extract_dir)
    if not os.path.isdir(extract_dir):
        return extract_dir
    entries = [e for e in os.listdir(extract_dir) if not e.startswith('.')]
    if len(entries) == 1:
        only = os.path.join(extract_dir, entries[0])
        if os.path.isdir(only):
            return only
    return extract_dir


def _ensure_cloud_dataset_zip_url(api_base, authorization, dataset_id, verify_ssl=True):
    ds = _cloud_api_json(
        api_base, 'GET', '/dataset/get', authorization,
        params={'id': dataset_id}, verify_ssl=verify_ssl,
    ) or {}
    zip_url = (ds.get('zipUrl') or '').strip()
    if zip_url:
        return ds, zip_url
    _cloud_api_json(
        api_base, 'POST', f'/dataset/image/{dataset_id}/sync-to-minio',
        authorization, verify_ssl=verify_ssl,
    )
    ds = _cloud_api_json(
        api_base, 'GET', '/dataset/get', authorization,
        params={'id': dataset_id}, verify_ssl=verify_ssl,
    ) or {}
    zip_url = (ds.get('zipUrl') or '').strip()
    if not zip_url:
        raise RuntimeError('云平台数据集尚未生成压缩包，请先在平台完成标注并同步到 MinIO')
    return ds, zip_url


def _download_cloud_zip_to_path(zip_url, dest_path, minio_cfg):
    from minio_utils import download_object_to_path, get_minio_client

    bucket, obj_key = _parse_gateway_path_to_bucket_key(zip_url)
    if not obj_key:
        raise RuntimeError(f'无法解析压缩包路径: {zip_url[:160]}')
    if not bucket:
        bucket = minio_cfg.get('bucket') or CLOUD_DATASETS_ZIP_BUCKET
    mc = get_minio_client(
        minio_cfg['endpoint'],
        minio_cfg['access_key'],
        minio_cfg['secret_key'],
        minio_cfg['secure'],
    )
    download_object_to_path(mc, bucket, obj_key, dest_path)


def _read_json_file(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return default


@app.route('/api/cloud/datasets', methods=['GET'])
def cloud_list_datasets():
    """列出 iot-dataset 平台数据集，供前端下拉选择。"""
    api_base = _dataset_api_base()
    authorization = _request_authorization()
    verify_ssl = _cloud_verify_ssl()
    try:
        page_no = 1
        page_size = 100
        items = []
        while page_no <= 50:
            data = _cloud_api_json(
                api_base, 'GET', '/dataset/page', authorization,
                params={'pageNo': page_no, 'pageSize': page_size, 'datasetType': 0},
                verify_ssl=verify_ssl,
            ) or {}
            if isinstance(data, list):
                lst = data
                total = len(lst)
            else:
                lst = data.get('list') or []
                total = int(data.get('total') or 0)
            for row in lst:
                if not isinstance(row, dict):
                    continue
                did = row.get('id')
                if did is None:
                    continue
                name = (row.get('name') or '').strip() or f'dataset_{did}'
                version = (row.get('version') or row.get('datasetCode') or '').strip()
                label = f'{name} (ID:{did})'
                if version:
                    label = f'{name} [{version}] (ID:{did})'
                items.append({
                    'id': int(did),
                    'name': name,
                    'version': version,
                    'label': label,
                    'zipUrl': row.get('zipUrl') or '',
                })
            if len(lst) < page_size or (total and len(items) >= total):
                break
            page_no += 1
        return jsonify({'datasets': items, 'api_base': api_base})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'获取云平台数据集列表失败: {e}'}), 400


@app.route('/api/cloud/import', methods=['POST'])
def cloud_import_dataset():
    """
    从 iot-dataset 下载数据集压缩包到 uploads/，解压后解析为外部数据集槽位（static/annotations）。
    """
    import zipfile

    data = request.get_json(silent=True) or {}
    dataset_id = data.get('dataset_id')
    api_base = (data.get('api_base') or '').strip() or _dataset_api_base()
    authorization = _request_authorization()
    verify_ssl = _cloud_verify_ssl()
    minio_cfg = _cloud_minio_config()

    try:
        dataset_id = int(dataset_id)
    except (TypeError, ValueError):
        return jsonify({'error': '请选择有效的云平台数据集'}), 400

    if not minio_cfg['endpoint'] or not minio_cfg['access_key'] or not minio_cfg['secret_key']:
        return jsonify({'error': '服务端未配置 MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY'}), 500

    try:
        ds, zip_url = _ensure_cloud_dataset_zip_url(api_base, authorization, dataset_id, verify_ssl=verify_ssl)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'获取云平台数据集压缩包失败: {e}'}), 400

    ds_name = (ds or {}).get('name') or f'dataset_{dataset_id}'
    safe = _sanitize_cloud_name(ds_name)
    import_base = os.path.realpath(os.path.join(app.config['UPLOAD_FOLDER'], 'cloud_import', f'ds_{dataset_id}_{safe}'))
    zip_path = os.path.join(import_base, f'dataset-{dataset_id}.zip')
    extract_dir = os.path.join(import_base, 'data')
    os.makedirs(import_base, exist_ok=True)
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)

    try:
        _download_cloud_zip_to_path(zip_url, zip_path, minio_cfg)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'下载压缩包失败: {e}'}), 400

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as e:
        return jsonify({'error': f'压缩包损坏或格式无效: {e}'}), 400

    dataset_root = _resolve_extracted_dataset_root(extract_dir)
    slug = _slug_from_import_root(dataset_root)

    out = _import_local_dataset_from_path(dataset_root, 'imagefolder')
    if out.get('error'):
        return jsonify({'error': out['error']}), 400

    _prepare_dataset_import_slot(slug)
    cfg = {
        'mode': 'external',
        'root': dataset_root,
        'cloud': {
            'api_base': api_base,
            'dataset_id': dataset_id,
            'source_zip': zip_path,
        },
    }
    with open(_dataset_config_file_for_slug(slug), 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    with open(_classes_file_for_slug(slug), 'w', encoding='utf-8') as f:
        json.dump(out['classes'], f, indent=2, ensure_ascii=False)
    with open(_annotations_file_for_slug(slug), 'w', encoding='utf-8') as f:
        json.dump(out['annotations'], f, indent=2, ensure_ascii=False)
    with open(_cloud_sync_file_for_slug(slug), 'w', encoding='utf-8') as f:
        json.dump({
            'cloud_dataset_id': dataset_id,
            'api_base': api_base,
            'zip_path': zip_path,
            'images': {},
        }, f, indent=2, ensure_ascii=False)
    _write_active_file(slug)

    hint = None
    if out['labelme_images'] == 0 and out['coco_images'] == 0 and out['yolo_images'] == 0:
        hint = '压缩包已解压，但未解析到 LabelMe / COCO / YOLO 标注，请确认 zip 内目录结构。'

    return jsonify({
        'message': '已从云平台下载压缩包并导入本地数据集',
        'dataset_slug': slug,
        'local_root': dataset_root,
        'zip_path': zip_path,
        'images_ok': len(out['image_keys']),
        'yolo_images': out['yolo_images'],
        'labelme_images': out['labelme_images'],
        'coco_images': out['coco_images'],
        'hint': hint,
    })


@app.route('/api/cloud/export', methods=['POST'])
def cloud_export_dataset():
    """
    在云平台新建数据集（名称 + 版本），并将当前槽位的标签、图片与标注同步上传。
    """
    try:
        from minio_utils import ensure_bucket, get_minio_client, image_content_type, upload_file_to_minio
    except ImportError as e:
        return jsonify({'error': f'缺少 minio 依赖或模块加载失败: {e}'}), 500

    slug = _active_dataset_slug()
    data = request.get_json(silent=True) or {}
    api_base = (data.get('api_base') or '').strip() or _dataset_api_base()
    authorization = _request_authorization()
    verify_ssl = _cloud_verify_ssl()
    minio_cfg = _cloud_minio_config()
    minio_endpoint = minio_cfg['endpoint']
    minio_access_key = minio_cfg['access_key']
    minio_secret_key = minio_cfg['secret_key']
    minio_secure = minio_cfg['secure']
    minio_bucket = (os.getenv('MINIO_BUCKET') or 'dataset').strip()

    ds_name = (data.get('name') or data.get('dataset_name') or '').strip()
    ds_version = (data.get('version') or data.get('dataset_code') or '').strip()
    if not ds_name:
        return jsonify({'error': '请填写数据集名称'}), 400
    if not ds_version:
        return jsonify({'error': '请填写版本'}), 400

    if not minio_endpoint or not minio_access_key or not minio_secret_key:
        return jsonify({'error': '服务端未配置 MinIO 连接信息'}), 500

    sync_path = _cloud_sync_file_for_slug(slug)
    sync = {}
    slot_cfg = _read_json_file(_dataset_config_file_for_slug(slug), {})
    cloud_hint = (slot_cfg.get('cloud') or {}) if isinstance(slot_cfg, dict) else {}

    try:
        new_id = _cloud_api_json(
            api_base, 'POST', '/dataset/create', authorization,
            json_body={
                'name': ds_name,
                'datasetCode': ds_version,
                'datasetType': 0,
                'description': f'自动标注平台导出（本地槽位: {slug}）',
            },
            verify_ssl=verify_ssl,
        )
        try:
            cloud_dataset_id = int(new_id)
        except (TypeError, ValueError):
            return jsonify({'error': f'创建数据集返回异常: {new_id}'}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'创建云平台数据集失败: {e}'}), 400

    classes = _read_json_file(_classes_file_for_slug(slug), [])
    if not isinstance(classes, list):
        classes = []
    ann_all = _read_json_file(_annotations_file_for_slug(slug), {})
    if not isinstance(ann_all, dict):
        ann_all = {}

    tag_rows = _cloud_fetch_all_pages(
        api_base, '/dataset/tag/page', authorization, {'datasetId': cloud_dataset_id}, verify_ssl=verify_ssl)
    by_name = {}
    max_sc = 0
    for t in tag_rows:
        nm = (t.get('name') or '').strip()
        if nm:
            by_name[nm] = t
        sc = t.get('shortcut')
        try:
            sc = int(sc)
            max_sc = max(max_sc, sc)
        except (TypeError, ValueError):
            pass

    for cls in classes:
        nm = (cls.get('name') or '').strip()
        if not nm:
            continue
        color = cls.get('color') or '#3aa757'
        if nm in by_name:
            tid = by_name[nm].get('id')
            if tid:
                try:
                    upd_body = {
                        'id': tid,
                        'name': nm,
                        'color': color,
                        'datasetId': cloud_dataset_id,
                        'shortcut': int(by_name[nm].get('shortcut') or 1),
                        'description': (by_name[nm].get('description') or ''),
                    }
                    wh = by_name[nm].get('warehouseId')
                    if wh is not None:
                        upd_body['warehouseId'] = wh
                    _cloud_api_json(
                        api_base, 'PUT', '/dataset/tag/update', authorization,
                        json_body=upd_body,
                        verify_ssl=verify_ssl,
                    )
                except Exception as e:
                    traceback.print_exc()
                    return jsonify({'error': f'更新标签失败 {nm}: {e}'}), 400
        else:
            max_sc += 1
            try:
                cre_body = {
                    'name': nm,
                    'color': color,
                    'datasetId': cloud_dataset_id,
                    'shortcut': max_sc,
                    'description': '',
                }
                wh0 = tag_rows[0].get('warehouseId') if tag_rows else None
                if wh0 is not None:
                    cre_body['warehouseId'] = wh0
                _cloud_api_json(
                    api_base, 'POST', '/dataset/tag/create', authorization,
                    json_body=cre_body,
                    verify_ssl=verify_ssl,
                )
            except Exception as e:
                traceback.print_exc()
                return jsonify({'error': f'创建标签失败 {nm}: {e}'}), 400

    tag_rows = _cloud_fetch_all_pages(
        api_base, '/dataset/tag/page', authorization, {'datasetId': cloud_dataset_id}, verify_ssl=verify_ssl)
    name_to_shortcut = {}
    for t in tag_rows:
        nm = (t.get('name') or '').strip()
        sc = t.get('shortcut')
        if not nm or sc is None:
            continue
        try:
            name_to_shortcut[nm] = int(sc)
        except (TypeError, ValueError):
            continue

    try:
        mc = get_minio_client(minio_endpoint, minio_access_key, minio_secret_key, minio_secure)
    except (RuntimeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400
    ensure_bucket(mc, minio_bucket)

    image_map = sync.get('images') if isinstance(sync.get('images'), dict) else {}
    updated = 0
    created = 0
    err = []

    for abs_path, key in _iter_dataset_images():
        try:
            with Image.open(abs_path) as im:
                iw, ih = im.size
        except Exception as e:
            err.append(f'{key}: 无法读取图片 {e}')
            continue
        size_b = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
        ann_str = _auto_labeling_ann_list_to_cloud_json(ann_all.get(key, []), name_to_shortcut, iw, ih)
        completed = 1 if (ann_all.get(key) and len(ann_all.get(key)) > 0) else 0
        base_nm = os.path.basename(key.replace('\\', '/'))
        meta = image_map.get(key) or {}

        if meta.get('id'):
            try:
                _cloud_api_json(
                    api_base, 'PUT', '/dataset/image/update', authorization,
                    json_body={
                        'id': int(meta['id']),
                        'datasetId': cloud_dataset_id,
                        'name': base_nm,
                        'path': meta.get('path') or '',
                        'annotations': ann_str,
                        'width': int(iw),
                        'heigh': int(ih),
                        'size': int(size_b),
                        'completed': completed,
                    },
                    verify_ssl=verify_ssl,
                )
                updated += 1
            except Exception as e:
                err.append(f'{key}: 更新失败 {e}')
        else:
            ext = os.path.splitext(base_nm)[1].lstrip('.') or 'jpg'
            obj = f'{cloud_dataset_id}/{uuid.uuid4().hex}.{ext}'
            try:
                upload_file_to_minio(
                    mc,
                    minio_bucket,
                    obj,
                    abs_path,
                    content_type=image_content_type(ext),
                    ensure_bucket_exists=False,
                )
            except Exception as e:
                err.append(f'{key}: MinIO 上传失败 {e}')
                continue
            gw_path = f'/api/v1/buckets/{minio_bucket}/objects/download?prefix={obj}'
            try:
                new_img_id = _cloud_api_json(
                    api_base, 'POST', '/dataset/image/create', authorization,
                    json_body={
                        'datasetId': cloud_dataset_id,
                        'name': base_nm,
                        'path': gw_path,
                        'annotations': ann_str,
                        'width': int(iw),
                        'heigh': int(ih),
                        'size': int(size_b),
                        'completed': completed,
                    },
                    verify_ssl=verify_ssl,
                )
                image_map[key] = {'id': int(new_img_id), 'path': gw_path}
                created += 1
            except Exception as e:
                err.append(f'{key}: 创建图片记录失败 {e}')

    sync_out = {
        'cloud_dataset_id': cloud_dataset_id,
        'api_base': api_base,
        'images': image_map,
        'updated_at': int(time.time()),
    }
    with open(sync_path, 'w', encoding='utf-8') as f:
        json.dump(sync_out, f, indent=2, ensure_ascii=False)

    cloud_cfg = dict(cloud_hint)
    cloud_cfg.update({
        'api_base': api_base,
        'dataset_id': cloud_dataset_id,
        'minio_endpoint': minio_endpoint,
        'minio_bucket': minio_bucket,
        'minio_secure': minio_secure,
    })
    if isinstance(slot_cfg, dict):
        slot_cfg['cloud'] = cloud_cfg
        try:
            with open(_dataset_config_file_for_slug(slug), 'w', encoding='utf-8') as f:
                json.dump(slot_cfg, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    return jsonify({
        'message': '已创建云平台数据集并同步标注',
        'cloud_dataset_id': cloud_dataset_id,
        'name': ds_name,
        'version': ds_version,
        'updated_images': updated,
        'created_images': created,
        'errors': err[:40],
    })


@app.route('/api/export', methods=['POST'])
def export_dataset():
    """导出数据集"""
    try:
        import datetime
        
        data = request.json or {}
        # 确保比例值是有效的数字，处理前端可能发送的null或undefined
        train_ratio = float(data.get('train_ratio', 0.7)) if data.get('train_ratio') is not None else 0.7
        val_ratio = float(data.get('val_ratio', 0.2)) if data.get('val_ratio') is not None else 0.2
        test_ratio = float(data.get('test_ratio', 0.1)) if data.get('test_ratio') is not None else 0.1
        selected_classes = data.get('selected_classes', [])
        sample_selection = data.get('sample_selection', 'all')  # 获取样本选择参数，默认为'all'
        export_prefix = data.get('export_prefix', '')  # 获取导出文件前缀，默认为空字符串

        if not isinstance(selected_classes, list):
            selected_classes = []
        selected_classes = [str(x) for x in selected_classes if x is not None and str(x).strip()]
        if not selected_classes:
            return jsonify({'error': '请至少选择一个导出类别'}), 400
        # 与导入 _yolo_txt_to_annotations 一致：标签文件中的 id 为 names/classes.txt 中的下标
        export_class_id = {name: i for i, name in enumerate(selected_classes)}
        
        # 前端已经检查了比例总和必须等于1，所以这里不需要再归一化
        # 直接使用前端传递的比例值
        
        # 创建临时目录用于生成数据集
        import tempfile
        import zipfile
        temp_dir = tempfile.mkdtemp()
        
        # 生成带时间戳的基础名称，格式：datasets_年月日时分秒
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        base_name = f"datasets_{timestamp}"
        
        # 不管有没有前缀，zip 内根目录名使用 datasets_年月日时分秒
        export_root = os.path.join(temp_dir, base_name)
        from shutil import copyfile

        for split in ('train', 'val', 'test'):
            os.makedirs(os.path.join(export_root, split, 'images'), exist_ok=True)
            os.makedirs(os.path.join(export_root, split, 'labels'), exist_ok=True)
        
        # 获取所有图片
        images = []
        for _abs, key in _iter_dataset_images():
            images.append(key)
        
        # 根据样本选择参数过滤图片
        annotations = {}
        if os.path.exists(_current_annotations_file()):
            with open(_current_annotations_file(), 'r') as f:
                annotations = json.load(f)
        
        # 根据用户选择过滤图片
        if sample_selection == 'annotated':
            # 只选择有标注的图片
            images = [img for img in images if img in annotations and annotations[img]]
        elif sample_selection == 'unannotated':
            # 只选择没有标注的图片
            images = [img for img in images if img not in annotations or not annotations[img]]
        # 如果是'all'则不进行过滤，使用所有图片
        
        # 分割数据集
        np.random.shuffle(images)
        
        total_images = len(images)
        
        # 彻底重写数据集分割逻辑，确保严格按照比例分割
        # 0比例的数据集绝对为空，多余的数据直接扔掉
        train_images = []
        val_images = []
        test_images = []
        
        # 只处理比例大于0的数据集
        if train_ratio > 0:
            # 计算训练集数量
            train_count = int(total_images * train_ratio)
            # 只分配计算出的数量的图片
            train_images = images[:train_count]
        
        # 验证集只在train_ratio > 0时才处理，否则从0开始
        val_start = len(train_images) if train_ratio > 0 else 0
        if val_ratio > 0:
            # 计算验证集数量
            val_count = int(total_images * val_ratio)
            # 只分配计算出的数量的图片
            val_images = images[val_start:val_start + val_count]
        
        # 测试集只在train_ratio > 0或val_ratio > 0时才处理，否则从0开始
        test_start = (len(train_images) + len(val_images)) if (train_ratio > 0 or val_ratio > 0) else 0
        if test_ratio > 0:
            # 计算测试集数量
            test_count = int(total_images * test_ratio)
            # 只分配计算出的数量的图片
            test_images = images[test_start:test_start + test_count]
        
        # 确保0比例的数据集绝对为空
        if train_ratio == 0:
            train_images = []
        if val_ratio == 0:
            val_images = []
        if test_ratio == 0:
            test_images = []
        
        # 处理每个分割的数据集
        splits = [
            ('train', train_images),
            ('val', val_images),
            ('test', test_images)
        ]
        
        names_yaml_lines = '\n'.join(
            '  - ' + json.dumps(name, ensure_ascii=False) for name in selected_classes
        )
        data_yaml = f"""path: .
train: train/images
val: val/images
test: test/images

nc: {len(selected_classes)}
names:
{names_yaml_lines}
"""
        with open(os.path.join(export_root, 'data.yaml'), 'w', encoding='utf-8') as f:
            f.write(data_yaml)
        with open(os.path.join(export_root, 'classes.txt'), 'w', encoding='utf-8') as f:
            for name in selected_classes:
                f.write(name + '\n')

        for split_name, split_images in splits:
            for image_name in split_images:
                src_img_path = _safe_abs_path_for_image_key(image_name)
                if not src_img_path:
                    continue
                flat_base = image_name.replace('\\', '/').replace('/', '__')
                if export_prefix:
                    dst_img_name = f"{export_prefix}_{flat_base}"
                else:
                    dst_img_name = flat_base
                dst_img_path = os.path.join(export_root, split_name, 'images', dst_img_name)

                try:
                    img = Image.open(src_img_path)
                    width, height = img.size
                except Exception as e:
                    print(f"无法读取图片 {src_img_path}: {str(e)}")
                    continue

                copyfile(src_img_path, dst_img_path)

                image_annotations = annotations.get(image_name, [])
                filtered = []
                if image_annotations and sample_selection != 'unannotated':
                    filtered = [a for a in image_annotations if a.get('class') in export_class_id]

                base_nm = os.path.splitext(flat_base)[0]
                if export_prefix:
                    label_name = f"{export_prefix}_{base_nm}.txt"
                else:
                    label_name = f"{base_nm}.txt"
                label_path = os.path.join(export_root, split_name, 'labels', label_name)
                with open(label_path, 'w') as f:
                    for ann in filtered:
                        class_id = export_class_id[ann['class']]
                        points = ann.get('points', [])
                        if isinstance(points, list) and len(points) > 0:
                            valid_points = []
                            if isinstance(points[0], dict):
                                for point in points:
                                    if 'x' in point and 'y' in point and point['x'] is not None and point['y'] is not None:
                                        valid_points.append([point['x'], point['y']])
                            else:
                                for point in points:
                                    if isinstance(point, (list, tuple)) and len(point) >= 2 and point[0] is not None and point[1] is not None:
                                        valid_points.append([point[0], point[1]])
                            if len(valid_points) > 0:
                                points = np.array(valid_points)
                                x_min = np.min(points[:, 0])
                                y_min = np.min(points[:, 1])
                                x_max = np.max(points[:, 0])
                                y_max = np.max(points[:, 1])
                                center_x = ((x_min + x_max) / 2) / width
                                center_y = ((y_min + y_max) / 2) / height
                                bbox_width = (x_max - x_min) / width
                                bbox_height = (y_max - y_min) / height
                                f.write(f"{class_id} {center_x:.6f} {center_y:.6f} {bbox_width:.6f} {bbox_height:.6f}\n")
                        elif 'x' in ann and 'y' in ann and 'width' in ann and 'height' in ann:
                            x = ann['x']
                            y = ann['y']
                            w = ann['width']
                            h = ann['height']
                            if x is not None and y is not None and w is not None and h is not None:
                                x_min = x
                                y_min = y
                                x_max = x + w
                                y_max = y + h
                                center_x = ((x_min + x_max) / 2) / width
                                center_y = ((y_min + y_max) / 2) / height
                                bbox_width = (x_max - x_min) / width
                                bbox_height = (y_max - y_min) / height
                                f.write(f"{class_id} {center_x:.6f} {center_y:.6f} {bbox_width:.6f} {bbox_height:.6f}\n")
                        else:
                            print(f"Invalid points data for annotation: {ann}")

        zip_filename = f"{base_name}.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for root, dirs, files in os.walk(export_root):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, export_root)
                    zipf.write(file_path, arc_name)
        
        # 返回zip文件
        return send_from_directory(temp_dir, zip_filename, as_attachment=True, download_name=zip_filename)
        
    except Exception as e:
        import traceback
        print(f"Export error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    _port = int(os.environ.get('FLASK_RUN_PORT', os.environ.get('PORT', '8000')))
    app.run(debug=True, host='0.0.0.0', port=_port)


def process_content_data(content_data, annotations):
    """处理内容数据并提取标注"""
    print(f"处理内容数据: {content_data}")
    # TODO: 在这里添加您的自定义处理代码

def process_list_data(data_list, annotations):
    """处理列表数据并提取标注"""
    print(f"处理列表数据: {data_list}")
    # TODO: 在这里添加您的自定义处理代码
