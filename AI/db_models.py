"""
@author 翱翔的雄库鲁
@email andywebjava@163.com
@wechat EasyAIoT2025
"""
import json
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz

db = SQLAlchemy()

# 时区设置
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

def beijing_now():
    """获取当前北京时间（无时区信息的datetime对象，用于数据库存储）"""
    beijing_dt = datetime.now(BEIJING_TZ)
    # 返回无时区信息的datetime对象，因为数据库字段不支持时区
    return beijing_dt.replace(tzinfo=None)

class Model(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    model_path = db.Column(db.String(500), nullable=True)
    image_url = db.Column(db.String(500))
    version = db.Column(db.String(20), default="V1.0.0")
    # 0=未部署 1=已部署 2=训练中 3=已下线（与前端模型管理一致）
    status = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 导出模型路径字段
    onnx_model_path = db.Column(db.String(500))
    torchscript_model_path = db.Column(db.String(500))
    tensorrt_model_path = db.Column(db.String(500))
    openvino_model_path = db.Column(db.String(500))

    export_records = db.relationship('ExportRecord', back_populates='model', cascade='all, delete-orphan')

class TrainTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=True)
    model_id = db.Column(db.Integer, nullable=True)  # 已废弃，保留列兼容历史数据
    progress = db.Column(db.Integer, default=0)
    dataset_path = db.Column(db.String(200), nullable=False)
    dataset_name = db.Column(db.String(100), nullable=True)
    dataset_version = db.Column(db.String(100), nullable=True)
    hyperparameters = db.Column(db.Text)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='running')
    train_log = db.Column(db.Text, nullable=False)
    checkpoint_dir = db.Column(db.String(500), nullable=False)
    metrics_path = db.Column(db.Text)
    minio_model_path = db.Column(db.String(500))
    train_results_path = db.Column(db.String(500))

class ExportRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.Integer, db.ForeignKey('model.id'), nullable=False)
    model_name = db.Column(db.String(100))  # 模型名称
    format = db.Column(db.String(50), nullable=False)
    minio_path = db.Column(db.String(500))
    local_path = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=beijing_now)  # 使用北京时间
    status = db.Column(db.String(20), default='PENDING')  # 新增状态字段
    message = db.Column(db.Text)  # 新增错误信息字段
    model = db.relationship('Model', back_populates='export_records')

class InferenceTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.Integer, db.ForeignKey('model.id'), nullable=True)
    inference_type = db.Column(db.String(20), nullable=False)  # image/video/rtsp
    input_source = db.Column(db.String(500))  # 原始文件路径或RTSP地址
    output_path = db.Column(db.String(500))  # 处理后文件在Minio的路径
    processed_frames = db.Column(db.Integer)  # 视频/流处理帧数
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='PROCESSING')  # PROCESSING/COMPLETED/FAILED
    error_message = db.Column(db.Text)
    processing_time = db.Column(db.Float)  # 单位：秒
    stream_output_url = db.Column(db.String(500))


class PlateAlgorithmVersion(db.Model):
    """车牌算法版本表（独立于通用模型管理）"""
    __tablename__ = 'plate_algorithm_version'

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(50), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    base_model = db.Column(db.String(100), nullable=False, default='yolo11n.pt')
    model_path = db.Column(db.String(500), nullable=True)  # MinIO下载URL
    metrics_path = db.Column(db.String(500), nullable=True)  # 训练曲线CSV
    train_results_path = db.Column(db.String(500), nullable=True)  # 训练结果图
    status = db.Column(db.String(20), nullable=False, default='draft')  # draft/active/archived
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=beijing_now)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now)

    train_tasks = db.relationship(
        'PlateTrainTask',
        backref=db.backref('version_obj', lazy=True),
        lazy='dynamic'
    )
    inference_tasks = db.relationship(
        'PlateInferenceTask',
        backref=db.backref('version_obj', lazy=True),
        lazy='dynamic'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'version': self.version,
            'description': self.description,
            'base_model': self.base_model,
            'model_path': self.model_path,
            'metrics_path': self.metrics_path,
            'train_results_path': self.train_results_path,
            'status': self.status,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PlateDataset(db.Model):
    """车牌训练数据集表（独立管理）"""
    __tablename__ = 'plate_dataset'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    dataset_source = db.Column(db.String(1000), nullable=False)  # 本地目录/zip 或 MinIO下载URL
    source_type = db.Column(db.String(20), nullable=False, default='custom')  # custom/merged
    status = db.Column(db.String(20), nullable=False, default='ready')  # ready/archived
    merged_from = db.Column(db.Text, nullable=True)  # JSON字符串，记录合并来源数据集ID列表
    created_at = db.Column(db.DateTime, default=beijing_now)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now)

    def to_dict(self):
        merged_from = []
        if self.merged_from:
            try:
                merged_from = json.loads(self.merged_from)
            except Exception:
                merged_from = []

        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'dataset_source': self.dataset_source,
            'source_type': self.source_type,
            'status': self.status,
            'merged_from': merged_from,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PlateTrainTask(db.Model):
    """车牌算法训练任务表"""
    __tablename__ = 'plate_train_task'

    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('plate_algorithm_version.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='preparing')  # preparing/running/completed/stopped/failed
    progress = db.Column(db.Integer, nullable=False, default=0)
    dataset_source = db.Column(db.String(1000), nullable=False)
    dataset_local_path = db.Column(db.String(1000), nullable=True)
    normalized_data_yaml = db.Column(db.String(1000), nullable=True)
    hyperparameters = db.Column(db.Text, nullable=True)
    train_log = db.Column(db.Text, nullable=False, default='')
    error_message = db.Column(db.Text, nullable=True)
    minio_model_path = db.Column(db.String(500), nullable=True)
    metrics_path = db.Column(db.String(500), nullable=True)
    train_results_path = db.Column(db.String(500), nullable=True)
    start_time = db.Column(db.DateTime, default=beijing_now)
    end_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=beijing_now)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now)

    def to_dict(self):
        dataset_id = None
        dataset_name = None
        if self.hyperparameters:
            try:
                hp = json.loads(self.hyperparameters)
                dataset_id = hp.get('dataset_id')
                dataset_name = hp.get('dataset_name')
            except Exception:
                dataset_id = None
                dataset_name = None

        return {
            'id': self.id,
            'version_id': self.version_id,
            'status': self.status,
            'progress': self.progress,
            'dataset_id': dataset_id,
            'dataset_name': dataset_name,
            'dataset_source': self.dataset_source,
            'dataset_local_path': self.dataset_local_path,
            'normalized_data_yaml': self.normalized_data_yaml,
            'hyperparameters': self.hyperparameters,
            'train_log': self.train_log,
            'error_message': self.error_message,
            'minio_model_path': self.minio_model_path,
            'metrics_path': self.metrics_path,
            'train_results_path': self.train_results_path,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PlateInferenceTask(db.Model):
    """车牌算法推理任务表"""
    __tablename__ = 'plate_inference_task'

    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('plate_algorithm_version.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='processing')  # processing/completed/failed
    input_source = db.Column(db.String(1000), nullable=True)
    output_image_path = db.Column(db.String(500), nullable=True)
    output_json_path = db.Column(db.String(500), nullable=True)
    detection_count = db.Column(db.Integer, nullable=False, default=0)
    result_preview = db.Column(db.Text, nullable=True)  # JSON字符串，保存部分检测结果
    error_message = db.Column(db.Text, nullable=True)
    processing_time = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=beijing_now)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now)

    def to_dict(self):
        return {
            'id': self.id,
            'version_id': self.version_id,
            'status': self.status,
            'input_source': self.input_source,
            'output_image_path': self.output_image_path,
            'output_json_path': self.output_json_path,
            'detection_count': self.detection_count,
            'result_preview': self.result_preview,
            'error_message': self.error_message,
            'processing_time': self.processing_time,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class LLMModel(db.Model):
    """大模型配置表（简化版）"""
    __tablename__ = 'llm_config'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True, comment='模型名称')
    service_type = db.Column(db.String(20), default='online', nullable=False, comment='服务类型[online:线上服务,local:本地服务]')
    vendor = db.Column(db.String(50), nullable=False, comment='供应商[aliyun:阿里云,openai:OpenAI,anthropic:Anthropic,local:本地服务]')
    model_type = db.Column(db.String(50), default='vision', nullable=False, comment='模型类型[text:文本,vision:视觉,multimodal:多模态]')
    model_name = db.Column(db.String(100), nullable=False, comment='模型标识（如qwen-vl-max）')
    base_url = db.Column(db.String(500), nullable=False, comment='API基础URL')
    api_key = db.Column(db.String(200), nullable=True, comment='API密钥（线上服务必填，本地服务可选）')
    api_version = db.Column(db.String(50), nullable=True, comment='API版本')
    
    # 基础配置
    temperature = db.Column(db.Float, default=0.7, nullable=False, comment='温度参数')
    max_tokens = db.Column(db.Integer, default=2000, nullable=False, comment='最大输出token数')
    timeout = db.Column(db.Integer, default=60, nullable=False, comment='请求超时时间（秒）')
    
    # 状态管理
    is_active = db.Column(db.Boolean, default=False, nullable=False, comment='是否激活')
    status = db.Column(db.String(20), default='inactive', nullable=False, comment='状态[active:激活,inactive:未激活,error:错误]')
    last_test_time = db.Column(db.DateTime, nullable=True, comment='最后测试时间')
    last_test_result = db.Column(db.Text, nullable=True, comment='最后测试结果')
    
    # 描述信息
    description = db.Column(db.Text, nullable=True, comment='模型描述')
    icon_url = db.Column(db.String(500), nullable=True, comment='图标URL')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'service_type': self.service_type,
            'vendor': self.vendor,
            'model_type': self.model_type,
            'model_name': self.model_name,
            'base_url': self.base_url,
            'api_key': self.api_key[:10] + '***' if self.api_key else None,  # 只显示前10位
            'api_version': self.api_version,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'timeout': self.timeout,
            'is_active': self.is_active,
            'status': self.status,
            'last_test_time': self.last_test_time.isoformat() if self.last_test_time else None,
            'last_test_result': self.last_test_result,
            'description': self.description,
            'icon_url': self.icon_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class OCRResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)  # 识别出的文本
    confidence = db.Column(db.Float)  # 置信度
    bbox = db.Column(db.JSON)  # 边界框坐标 [x1, y1, x2, y2]
    polygon = db.Column(db.JSON)  # 多边形坐标 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    page_num = db.Column(db.Integer, default=1)  # 页码
    line_num = db.Column(db.Integer)  # 行号
    word_num = db.Column(db.Integer)  # 单词序号
    image_url = db.Column(db.String(500))  # 新增：图片在OSS中的URL
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'text': self.text,
            'confidence': self.confidence,
            'bbox': self.bbox,
            'polygon': self.polygon,
            'page_num': self.page_num,
            'line_num': self.line_num,
            'word_num': self.word_num,
            'image_url': self.image_url,  # 新增
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class SpeechRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(100), unique=True, nullable=False)  # 订单ID
    audio_file_path = db.Column(db.String(500))  # 音频文件在Minio的路径
    filename = db.Column(db.String(255), nullable=False)  # 原始文件名
    file_size = db.Column(db.Integer, nullable=False)  # 文件大小(字节)
    duration = db.Column(db.Integer, nullable=False)  # 音频时长(秒)
    recognized_text = db.Column(db.Text)  # 识别出的文本
    confidence = db.Column(db.Float)  # 整体置信度
    status = db.Column(db.String(20), default='UPLOADED')  # 状态: UPLOADED/PROCESSING/COMPLETED/FAILED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 创建时间
    completed_at = db.Column(db.DateTime)  # 完成时间
    error_message = db.Column(db.Text)

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'order_id': self.order_id,
            'filename': self.filename,
            'file_size': self.file_size,
            'duration': self.duration,
            'recognized_text': self.recognized_text,
            'confidence': self.confidence,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'error_message': self.error_message
        }

    def __repr__(self):
        return f'<SpeechRecord {self.filename} ({self.status})>'


class AIService(db.Model):
    """AI服务表，用于维护所有部署的AI服务"""
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.Integer, db.ForeignKey('model.id'), nullable=True)  # 关联的模型ID（可空，支持心跳自动创建）
    service_name = db.Column(db.String(100), nullable=False)  # 服务名称（允许重复，支持同一服务名称的多个实例）
    server_ip = db.Column(db.String(50))  # 部署的服务器IP
    port = db.Column(db.Integer)  # 服务端口
    inference_endpoint = db.Column(db.String(200))  # 推理接口地址
    status = db.Column(db.String(20), default='stopped')  # 状态: running/stopped/error
    mac_address = db.Column(db.String(50))  # MAC地址
    deploy_time = db.Column(db.DateTime, default=beijing_now)  # 部署时间
    last_heartbeat = db.Column(db.DateTime)  # 最后上报时间
    process_id = db.Column(db.Integer)  # 进程ID
    log_path = db.Column(db.String(500))  # 日志文件路径
    model_version = db.Column(db.String(20))  # 模型版本号
    format = db.Column(db.String(50))  # 模型格式 (onnx, openvino, pytorch等)
    created_at = db.Column(db.DateTime, default=beijing_now)
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now)
    
    # 关系定义
    model = db.relationship('Model', backref=db.backref('ai_services', lazy='dynamic'))
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'model_id': self.model_id,
            'service_name': self.service_name,
            'server_ip': self.server_ip,
            'port': self.port,
            'inference_endpoint': self.inference_endpoint,
            'status': self.status,
            'mac_address': self.mac_address,
            'deploy_time': self.deploy_time.isoformat() if self.deploy_time else None,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'process_id': self.process_id,
            'log_path': self.log_path,
            'model_version': self.model_version,
            'format': self.format,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<AIService {self.service_name} ({self.status})>'


class AutoLabelTask(db.Model):
    """自动化标注任务表"""
    __tablename__ = 'auto_label_task'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dataset_id = db.Column(db.BigInteger, nullable=False, comment='数据集ID')
    model_service_id = db.Column(db.Integer, db.ForeignKey('ai_service.id'), nullable=True, comment='AI服务ID')
    status = db.Column(db.String(20), default='PENDING', nullable=False, comment='状态[PENDING:待处理,PROCESSING:处理中,COMPLETED:已完成,FAILED:失败]')
    total_images = db.Column(db.Integer, default=0, comment='总图片数')
    processed_images = db.Column(db.Integer, default=0, comment='已处理图片数')
    success_count = db.Column(db.Integer, default=0, comment='成功标注数')
    failed_count = db.Column(db.Integer, default=0, comment='失败数')
    confidence_threshold = db.Column(db.Float, default=0.5, comment='置信度阈值')
    created_at = db.Column(db.DateTime, default=beijing_now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=beijing_now, onupdate=beijing_now, comment='更新时间')
    started_at = db.Column(db.DateTime, nullable=True, comment='开始时间')
    completed_at = db.Column(db.DateTime, nullable=True, comment='完成时间')
    error_message = db.Column(db.Text, nullable=True, comment='错误信息')
    
    # 关系定义
    model_service = db.relationship('AIService', backref=db.backref('auto_label_tasks', lazy='dynamic'))
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'dataset_id': self.dataset_id,
            'model_service_id': self.model_service_id,
            'status': self.status,
            'total_images': self.total_images,
            'processed_images': self.processed_images,
            'success_count': self.success_count,
            'failed_count': self.failed_count,
            'confidence_threshold': self.confidence_threshold,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'error_message': self.error_message
        }
    
    def __repr__(self):
        return f'<AutoLabelTask {self.id} ({self.status})>'


class AutoLabelResult(db.Model):
    """自动化标注结果表"""
    __tablename__ = 'auto_label_result'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.Integer, db.ForeignKey('auto_label_task.id'), nullable=False, comment='任务ID')
    dataset_image_id = db.Column(db.BigInteger, nullable=False, comment='数据集图片ID')
    annotations = db.Column(db.Text, nullable=True, comment='标注结果JSON')
    status = db.Column(db.String(20), default='SUCCESS', nullable=False, comment='状态[SUCCESS:成功,FAILED:失败]')
    error_message = db.Column(db.Text, nullable=True, comment='错误信息')
    created_at = db.Column(db.DateTime, default=beijing_now, comment='创建时间')
    
    # 关系定义
    task = db.relationship('AutoLabelTask', backref=db.backref('results', lazy='dynamic'))
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'dataset_image_id': self.dataset_image_id,
            'annotations': self.annotations,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<AutoLabelResult {self.id} ({self.status})>'


def ensure_train_task_name_column(engine):
    """老库 train_task 表无 name 列时补列。"""
    import logging
    from sqlalchemy import inspect, text

    log = logging.getLogger(__name__)
    try:
        inspector = inspect(engine)
        if 'train_task' not in inspector.get_table_names():
            return
        col_names = {c['name'] for c in inspector.get_columns('train_task')}
        if 'name' not in col_names:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE train_task ADD COLUMN name VARCHAR(100)'))
            log.info('已为 train_task 表添加 name 列')
    except Exception as e:
        log.warning('ensure_train_task_name_column: %s', e)


def ensure_train_task_dataset_columns(engine):
    """老库 train_task 表无 dataset_name / dataset_version 列时补列。"""
    import logging
    from sqlalchemy import inspect, text

    log = logging.getLogger(__name__)
    try:
        inspector = inspect(engine)
        if 'train_task' not in inspector.get_table_names():
            return
        col_names = {c['name'] for c in inspector.get_columns('train_task')}
        with engine.begin() as conn:
            if 'dataset_name' not in col_names:
                conn.execute(text('ALTER TABLE train_task ADD COLUMN dataset_name VARCHAR(100)'))
                log.info('已为 train_task 表添加 dataset_name 列')
            if 'dataset_version' not in col_names:
                conn.execute(text('ALTER TABLE train_task ADD COLUMN dataset_version VARCHAR(100)'))
                log.info('已为 train_task 表添加 dataset_version 列')
    except Exception as e:
        log.warning('ensure_train_task_dataset_columns: %s', e)


def ensure_model_table_status_column(engine):
    """
    老库仅有 model 表但无 status 列时补列。
    SQLAlchemy create_all() 不会为已存在的表追加新列。
    """
    import logging
    from sqlalchemy import inspect, text

    log = logging.getLogger(__name__)
    try:
        inspector = inspect(engine)
        if 'model' not in inspector.get_table_names():
            return
        col_names = {c['name'] for c in inspector.get_columns('model')}
        if 'status' in col_names:
            return
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE model ADD COLUMN status INTEGER DEFAULT 0'))
        log.info('已为 model 表添加 status 列')
    except Exception as e:
        log.warning('ensure_model_table_status_column: %s', e)
