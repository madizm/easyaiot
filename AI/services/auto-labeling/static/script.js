/** 解析 API 路径（支持 WEB iframe 通过 <base> 嵌套时的子路径前缀） */
function apiUrl(path) {
    return new URL(path.replace(/^\//, ''), document.baseURI).href;
}

let currentImage = null;
let currentAnnotations = [];
let classes = [];
let isDrawing = false;
let startPoint = null;
let currentPoint = null;
let currentTool = 'rect'; // 默认工具
let imageCache = new Map(); // 图片缓存
let selectedAnnotationId = null; // 当前选中的标注ID
let isResizing = false; // 是否正在调整大小
let isMoving = false; // 是否正在移动标注
let resizeHandle = null; // 当前调整大小的控制点
let lastMousePos = null; // 上次鼠标位置
let polygonPoints = []; // 多边形绘制时的顶点数组
let isPolygonDrawing = false; // 是否正在绘制多边形
let updateAnnotationListDebounced = debounce(updateAnnotationList, 100); // 防抖后的标注列表更新函数

/** API 路径中的图片键（可含子目录）需编码 */
function imageKeyForApiUrl(name) {
    return encodeURIComponent(name);
}

/**
 * 导入的标注（LabelMe/YOLO/COCO 等）可能没有 id 或 id 重复，会导致
 * selectedAnnotationId 与多条标注同时相等。为每条补全唯一数字 id。
 * @returns {boolean} 是否修改了数据（需持久化）
 */
function normalizeAnnotationIds(annotations) {
    if (!Array.isArray(annotations) || annotations.length === 0) return false;
    let changed = false;
    const seen = new Set();
    let seq = Date.now();
    for (const ann of annotations) {
        let id = ann.id;
        if (typeof id === 'string' && /^-?\d+$/.test(id.trim())) {
            const n = parseInt(id.trim(), 10);
            if (ann.id !== n) changed = true;
            ann.id = n;
            id = n;
        }
        if (typeof ann.id !== 'number' || !Number.isFinite(ann.id) || seen.has(ann.id)) {
            ann.id = seq++;
            changed = true;
        }
        seen.add(ann.id);
    }
    return changed;
}

// AI标注相关状态
let aiAnnotateEnabled = false; // AI标注是否开启
let aiAnnotateModel = ''; // 当前选择的AI模型
let aiAnnotateConfidence = 0.5; // AI标注置信度阈值
let aiAutoNext = false; // 保存后是否自动切换下一张（默认关闭）
let aiAnnotating = false; // 是否正在进行AI标注

// 快捷键设置
let shortcutSettings = {
    deleteSelected: 'Q',
    save: 'Ctrl+S',
    prevImage: 'A',
    nextImage: 'D',
    autoNextAfterSave: false
};

// 从localStorage加载快捷键设置
function loadShortcutSettings() {
    const saved = localStorage.getItem('auto-labeling_shortcuts');
    if (saved) {
        try {
            shortcutSettings = JSON.parse(saved);
        } catch (e) {
            console.error('加载快捷键设置失败:', e);
        }
    }
}

// 防抖函数
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// DOM加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

// 初始化应用
function initializeApp() {
    loadShortcutSettings();
    setupDatasetSwitcher();
    setupEventListeners();
    refreshActiveDatasetSelect().then(() => {
        loadClasses();
        loadImages();
    });
}

// 设置事件监听器
function setupEventListeners() {
    // 导航按钮
    document.getElementById('openFolderBtn').addEventListener('click', showDatasetModal);
    document.getElementById('exportBtn').addEventListener('click', showExportModal);
    document.getElementById('settingsBtn').addEventListener('click', showSettingsModal);
    document.getElementById('clearAnnotationBtn').addEventListener('click', clearCurrentAnnotations);
    document.getElementById('saveAnnotationBtn').addEventListener('click', saveAnnotations);
    
    // AI标注按钮
    document.getElementById('aiAnnotateToggle').addEventListener('click', toggleAiAnnotate);
    
    // 搜索框
    document.getElementById('imageSearch').addEventListener('input', filterImages);
    
    // 工具按钮
    document.getElementById('rectTool').addEventListener('click', () => switchTool('rect'));
    document.getElementById('polygonTool').addEventListener('click', () => switchTool('polygon'));
    document.getElementById('moveTool').addEventListener('click', () => switchTool('move'));
    
    // 类别管理
    document.getElementById('addClassBtn').addEventListener('click', addClass);
    document.getElementById('newClassInput').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') addClass();
    });
    
    // 画布事件
    const canvas = document.getElementById('imageCanvas');
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseLeave);
    canvas.addEventListener('dblclick', handleDoubleClick);
    
    // 模态框关闭事件
    setupModalCloseEvents();
    
    // 数据集上传事件
    setupDatasetUploadEvents();
    
    // 导出表单事件
    document.getElementById('exportForm').addEventListener('submit', handleExport);
    const cloudExportBtn = document.getElementById('cloudExportBtn');
    if (cloudExportBtn) {
        cloudExportBtn.addEventListener('click', handleCloudExport);
    }

    // 设置表单事件
    document.getElementById('settingsForm').addEventListener('submit', handleSettingsSave);
    
    // 编辑类别表单事件
    document.getElementById('editClassForm').addEventListener('submit', handleEditClass);
    
    // YOLO11模型管理按钮事件
    document.getElementById('downloadModelsBtn').addEventListener('click', downloadModels);
    document.getElementById('refreshModelsBtn').addEventListener('click', refreshModels);
    
    // YOLO11模型拖放事件
    setupModelDropZoneEvents();
    
    // AI标注模态框事件
    setupAiAnnotateEvents();
    
    // 快捷键
    document.addEventListener('keydown', handleKeyDown);
    
    // 全选和删除按钮
    document.getElementById('selectAllBtn').addEventListener('click', selectAllImages);
    document.getElementById('deleteSelectedBtn').addEventListener('click', deleteSelectedImages);
}



// 切换工具
function switchTool(tool) {
    // 更新UI状态
    document.querySelectorAll('.tool-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(tool + 'Tool').classList.add('active');
    
    // 重置所有绘制状态
    isDrawing = false;
    isPolygonDrawing = false;
    startPoint = null;
    currentPoint = null;
    polygonPoints = [];
    
    // 设置当前工具
    currentTool = tool;
    
    // 更新鼠标样式
    const canvas = document.getElementById('imageCanvas');
    canvas.style.cursor = 'crosshair';
    
    redrawCanvas();
}

// 处理鼠标按下事件
function handleMouseDown(e) {
    if (!currentImage) return;
    
    const rect = e.target.getBoundingClientRect();
    const canvas = e.target;
    
    // 获取图片的实际尺寸和位置
    const img = imageCache.get(currentImage);
    if (!img) return;
    
    // 计算图片在画布上的显示尺寸和位置（自适应居中）
    const container = document.getElementById('imageCanvasContainer');
    const maxWidth = container.clientWidth - 20;
    const maxHeight = container.clientHeight - 20;
    const ratio = Math.min(maxWidth / img.width, maxHeight / img.height);
    const scaledWidth = img.width * ratio;
    const scaledHeight = img.height * ratio;
    const imgX = (container.clientWidth - scaledWidth) / 2;
    const imgY = (container.clientHeight - scaledHeight) / 2;
    
    // 计算鼠标在画布上的坐标
    const canvasX = e.clientX - rect.left;
    const canvasY = e.clientY - rect.top;
    
    // 计算鼠标在图片上的实际坐标
    const x = (canvasX - imgX) / ratio;
    const y = (canvasY - imgY) / ratio;
    
    // 检查是否点击了某个标注的控制点
    const resizeResult = checkResizeHandleClick(canvasX, canvasY, ratio, imgX, imgY);
    if (resizeResult) {
        isResizing = true;
        resizeHandle = resizeResult.handle;
        selectedAnnotationId = resizeResult.annotationId;
        lastMousePos = {x: e.clientX, y: e.clientY};
        updateAnnotationListDebounced();
        redrawCanvas();
        return;
    }
    
    // 检查是否点击了某个标注
    const annotationResult = checkAnnotationClick(canvasX, canvasY, ratio, imgX, imgY);
    if (annotationResult) {
        selectedAnnotationId = annotationResult.id;
        isMoving = true;
        lastMousePos = {x: e.clientX, y: e.clientY};
        updateAnnotationListDebounced();
        redrawCanvas();
        return;
    }
    
    // 如果点击了空白区域，取消选择
    selectedAnnotationId = null;
    updateAnnotationListDebounced();
    redrawCanvas();
    // 处理多边形绘制
    if (currentTool === 'polygon') {
        // 如果还没有开始绘制多边形，初始化
        if (!isPolygonDrawing) {
            isPolygonDrawing = true;
            polygonPoints = [];
        }
        
        // 添加当前点到多边形顶点数组
        polygonPoints.push({x: x, y: y});
        
        // 更新当前点用于绘制
        currentPoint = {x: x, y: y};
        
        redrawCanvas();
        return;
    }
    
    // 处理矩形绘制
    if (currentTool === 'rect') {
        // 绘制工具 - 开始绘制
        isDrawing = true;
        startPoint = {x: x, y: y};
        currentPoint = {x: x, y: y};
        redrawCanvas();
    }
}

// 检查是否点击了调整大小的控制点
function checkResizeHandleClick(canvasX, canvasY, ratio, imgX, imgY) {
    for (const annotation of currentAnnotations) {
        if (annotation.type !== 'rectangle' || annotation.points.length < 4) continue;
        
        // 计算矩形的四个角点
        const points = annotation.points;
        const x1 = points[0][0] * ratio + imgX;
        const y1 = points[0][1] * ratio + imgY;
        const x2 = points[2][0] * ratio + imgX;
        const y2 = points[2][1] * ratio + imgY;
        
        // 控制点位置
        const handles = [
            { x: x1, y: y1, type: 'nw' },
            { x: (x1 + x2) / 2, y: y1, type: 'n' },
            { x: x2, y: y1, type: 'ne' },
            { x: x2, y: (y1 + y2) / 2, type: 'e' },
            { x: x2, y: y2, type: 'se' },
            { x: (x1 + x2) / 2, y: y2, type: 's' },
            { x: x1, y: y2, type: 'sw' },
            { x: x1, y: (y1 + y2) / 2, type: 'w' }
        ];
        
        // 检查是否点击了某个控制点
        for (const handle of handles) {
            const distance = Math.sqrt(
                Math.pow(canvasX - handle.x, 2) + Math.pow(canvasY - handle.y, 2)
            );
            if (distance <= 8) {
                return { annotationId: annotation.id, handle: handle.type };
            }
        }
    }
    return null;
}

// 检查是否点击了某个标注
function checkAnnotationClick(canvasX, canvasY, ratio, imgX, imgY) {
    for (const annotation of currentAnnotations) {
        if (annotation.type !== 'rectangle' || annotation.points.length < 4) continue;
        
        // 计算矩形的边界
        const points = annotation.points;
        const x1 = points[0][0] * ratio + imgX;
        const y1 = points[0][1] * ratio + imgY;
        const x2 = points[2][0] * ratio + imgX;
        const y2 = points[2][1] * ratio + imgY;
        
        // 检查鼠标是否在矩形内部
        if (canvasX >= x1 && canvasX <= x2 && canvasY >= y1 && canvasY <= y2) {
            return annotation;
        }
    }
    return null;
}

// 处理鼠标移动事件
function handleMouseMove(e) {
    if (!currentImage) return;
    
    const rect = e.target.getBoundingClientRect();
    const canvas = e.target;
    
    // 获取图片的实际尺寸和位置
    const img = imageCache.get(currentImage);
    if (!img) return;
    
    // 计算图片在画布上的显示尺寸和位置（自适应居中）
    const container = document.getElementById('imageCanvasContainer');
    const maxWidth = container.clientWidth - 20;
    const maxHeight = container.clientHeight - 20;
    const ratio = Math.min(maxWidth / img.width, maxHeight / img.height);
    const scaledWidth = img.width * ratio;
    const scaledHeight = img.height * ratio;
    const imgX = (container.clientWidth - scaledWidth) / 2;
    const imgY = (container.clientHeight - scaledHeight) / 2;
    
    // 计算鼠标在画布上的坐标
    const canvasX = e.clientX - rect.left;
    const canvasY = e.clientY - rect.top;
    
    // 计算鼠标在图片上的实际坐标
    const x = (canvasX - imgX) / ratio;
    const y = (canvasY - imgY) / ratio;
    
    // 处理调整大小
    if (isResizing && selectedAnnotationId && resizeHandle) {
        if (!lastMousePos) return;
        
        const dx = (e.clientX - lastMousePos.x) / ratio;
        const dy = (e.clientY - lastMousePos.y) / ratio;
        
        resizeAnnotation(selectedAnnotationId, resizeHandle, dx, dy);
        lastMousePos = {x: e.clientX, y: e.clientY};
        redrawCanvas();
        return;
    }
    
    // 处理移动标注
    if (isMoving && selectedAnnotationId) {
        if (!lastMousePos) return;
        
        const dx = (e.clientX - lastMousePos.x) / ratio;
        const dy = (e.clientY - lastMousePos.y) / ratio;
        
        moveAnnotation(selectedAnnotationId, dx, dy);
        lastMousePos = {x: e.clientX, y: e.clientY};
        redrawCanvas();
        return;
    }
    
    // 处理多边形绘制过程中的鼠标移动
    if (isPolygonDrawing) {
        // 更新当前鼠标位置，用于绘制从最后一个顶点到当前鼠标位置的连线
        currentPoint = {x: x, y: y};
        redrawCanvas();
        return;
    }
    
    // 处理矩形绘制过程中的鼠标移动
    if (isDrawing) {
        // 更新当前点
        currentPoint = {x: x, y: y};
        redrawCanvas();
    } else if (currentTool === 'rect' || currentTool === 'polygon') {
        // 绘制十字引导线，但不重绘画布以避免闪烁
        drawCrosshair(e);
    }
}

// 调整标注大小
function resizeAnnotation(annotationId, handle, dx, dy) {
    const annotation = currentAnnotations.find(a => a.id === annotationId);
    if (!annotation || annotation.type !== 'rectangle') return;
    
    const points = annotation.points;
    if (points.length < 4) return;
    
    // 计算当前矩形的边界
    let x1 = points[0][0];
    let y1 = points[0][1];
    let x2 = points[2][0];
    let y2 = points[2][1];
    
    // 根据不同的控制点调整矩形大小
    switch (handle) {
        case 'nw': // 左上
            x1 += dx;
            y1 += dy;
            break;
        case 'n': // 上中
            y1 += dy;
            break;
        case 'ne': // 右上
            x2 += dx;
            y1 += dy;
            break;
        case 'e': // 右中
            x2 += dx;
            break;
        case 'se': // 右下
            x2 += dx;
            y2 += dy;
            break;
        case 's': // 下中
            y2 += dy;
            break;
        case 'sw': // 左下
            x1 += dx;
            y2 += dy;
            break;
        case 'w': // 左中
            x1 += dx;
            break;
    }
    
    // 确保矩形的宽高为正
    if (x2 < x1) [x1, x2] = [x2, x1];
    if (y2 < y1) [y1, y2] = [y2, y1];
    
    // 更新矩形的四个角点
    annotation.points = [
        [x1, y1],
        [x2, y1],
        [x2, y2],
        [x1, y2]
    ];
}

// 移动标注
function moveAnnotation(annotationId, dx, dy) {
    const annotation = currentAnnotations.find(a => a.id === annotationId);
    if (!annotation) return;
    
    // 更新所有点的坐标
    annotation.points = annotation.points.map(point => [
        point[0] + dx,
        point[1] + dy
    ]);
}

// 处理鼠标抬起事件
function handleMouseUp(e) {
    if (!currentImage) return;
    
    // 结束调整大小
    if (isResizing) {
        isResizing = false;
        resizeHandle = null;
        saveAnnotationsSilent();
        return;
    }
    
    // 结束移动标注
    if (isMoving) {
        isMoving = false;
        saveAnnotationsSilent();
        return;
    }
    
    // 处理矩形绘制完成
    if (isDrawing && startPoint && currentPoint && currentTool === 'rect') {
        // 矩形工具 - 创建矩形标注
        const width = Math.abs(currentPoint.x - startPoint.x);
        const height = Math.abs(currentPoint.y - startPoint.y);
        const minX = Math.min(startPoint.x, currentPoint.x);
        const minY = Math.min(startPoint.y, currentPoint.y);
        
        if (width > 5 && height > 5) { // 避免误触创建太小的矩形
            const selectedClass = getSelectedClass();
            if (selectedClass) {
                const annotation = {
                    id: Date.now(),
                    class: selectedClass.name,
                    points: [
                        [minX, minY],
                        [minX + width, minY],
                        [minX + width, minY + height],
                        [minX, minY + height]
                    ],
                    type: 'rectangle'
                };
                currentAnnotations.push(annotation);
                saveAnnotationsSilent();
                updateAnnotationList();
            }
        }
        isDrawing = false;
        startPoint = null;
        currentPoint = null;
        redrawCanvas();
    }
}

// 处理双击事件，完成多边形绘制
function handleDoubleClick(e) {
    if (!currentImage || currentTool !== 'polygon' || !isPolygonDrawing || polygonPoints.length < 3) return;
    
    // 完成多边形绘制
    const selectedClass = getSelectedClass();
    if (selectedClass) {
        // 将多边形顶点转换为所需格式
        const points = polygonPoints.map(point => [point.x, point.y]);
        
        const annotation = {
            id: Date.now(),
            class: selectedClass.name,
            points: points,
            type: 'polygon'
        };
        
        currentAnnotations.push(annotation);
        saveAnnotationsSilent();
        updateAnnotationListDebounced();
    }
    
    // 重置多边形绘制状态
    isPolygonDrawing = false;
    polygonPoints = [];
    currentPoint = null;
    
    redrawCanvas();
}

// 处理鼠标离开画布事件
function handleMouseLeave() {
    if (isDrawing) {
        isDrawing = false;
        startPoint = null;
        currentPoint = null;
        redrawCanvas();
    }
    
    // 如果正在绘制多边形，重置绘制状态
    if (isPolygonDrawing) {
        isPolygonDrawing = false;
        polygonPoints = [];
        currentPoint = null;
        redrawCanvas();
    }
}

// 获取选中的类别
function getSelectedClass() {
    const selectedElement = document.querySelector('.class-item.selected');
    if (!selectedElement) return null;
    
    const className = selectedElement.querySelector('.class-name').textContent;
    return classes.find(c => c.name === className);
}

// 重绘画布
function redrawCanvas() {
    const canvas = document.getElementById('imageCanvas');
    const ctx = canvas.getContext('2d');
    const container = document.getElementById('imageCanvasContainer');
    
    // 设置画布尺寸为容器大小
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
    
    // 清空画布
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (!currentImage) return;
    
    // 使用图像缓存避免重复加载
    if (!imageCache.has(currentImage)) {
        const img = new Image();
        img.onload = function() {
            imageCache.set(currentImage, img);
            drawImageAndAnnotations(ctx, img, container);
        };
        img.src = apiUrl(`/api/image/${imageKeyForApiUrl(currentImage)}`);
    } else {
        const img = imageCache.get(currentImage);
        drawImageAndAnnotations(ctx, img, container);
    }
}

function drawImageAndAnnotations(ctx, img, container) {
    // 计算图片在画布上的显示尺寸和位置（自适应居中）
    const maxWidth = container.clientWidth - 20;
    const maxHeight = container.clientHeight - 20;
    const ratio = Math.min(maxWidth / img.width, maxHeight / img.height);
    const scaledWidth = img.width * ratio;
    const scaledHeight = img.height * ratio;
    const imgX = (container.clientWidth - scaledWidth) / 2;
    const imgY = (container.clientHeight - scaledHeight) / 2;
    
    // 绘制图片
    ctx.drawImage(img, imgX, imgY, scaledWidth, scaledHeight);
    
    // 绘制所有标注
    currentAnnotations.forEach(annotation => {
        drawAnnotation(ctx, annotation, ratio, ratio, imgX, imgY);
    });
    
    // 绘制当前正在绘制的形状
    if (isDrawing && startPoint && currentPoint && currentTool === 'rect') {
        // 设置绘制样式为实线
        ctx.strokeStyle = '#ff0000';
        ctx.lineWidth = 2;
        ctx.setLineDash([]); // 使用实线而不是虚线
        
        // 计算实际绘制的矩形坐标（考虑缩放和偏移）
        const rectX = startPoint.x * ratio + imgX;
        const rectY = startPoint.y * ratio + imgY;
        const rectWidth = (currentPoint.x - startPoint.x) * ratio;
        const rectHeight = (currentPoint.y - startPoint.y) * ratio;
        
        ctx.strokeRect(rectX, rectY, rectWidth, rectHeight);
        
        // 绘制控制点
        drawControlPoints(ctx, 
            {x: startPoint.x * ratio + imgX, y: startPoint.y * ratio + imgY}, 
            {x: currentPoint.x * ratio + imgX, y: currentPoint.y * ratio + imgY}
        );
    }
    
    // 绘制多边形
    if (isPolygonDrawing && polygonPoints.length > 0) {
        ctx.save();
        ctx.strokeStyle = '#ff0000';
        ctx.lineWidth = 2;
        ctx.setLineDash([]);
        
        // 1. 绘制连线（从第一个点到当前鼠标位置）
        ctx.beginPath();
        
        // 绘制已添加的顶点之间的连线
        for (let i = 0; i < polygonPoints.length; i++) {
            const point = polygonPoints[i];
            const canvasX = point.x * ratio + imgX;
            const canvasY = point.y * ratio + imgY;
            
            if (i === 0) {
                ctx.moveTo(canvasX, canvasY);
            } else {
                ctx.lineTo(canvasX, canvasY);
            }
        }
        
        // 绘制从最后一个点到当前鼠标位置的连线
        if (currentPoint && polygonPoints.length > 0) {
            const lastPoint = polygonPoints[polygonPoints.length - 1];
            const lastCanvasX = lastPoint.x * ratio + imgX;
            const lastCanvasY = lastPoint.y * ratio + imgY;
            const currentCanvasX = currentPoint.x * ratio + imgX;
            const currentCanvasY = currentPoint.y * ratio + imgY;
            
            ctx.moveTo(lastCanvasX, lastCanvasY);
            ctx.lineTo(currentCanvasX, currentCanvasY);
        }
        
        ctx.stroke();
        
        // 2. 绘制已添加的顶点
        ctx.fillStyle = '#ff0000';
        for (const point of polygonPoints) {
            const canvasX = point.x * ratio + imgX;
            const canvasY = point.y * ratio + imgY;
            
            ctx.beginPath();
            ctx.arc(canvasX, canvasY, 4, 0, Math.PI * 2);
            ctx.fill();
        }
        
        ctx.restore();
    }
}

// 绘制控制点
function drawControlPoints(ctx, startPoint, currentPoint) {
    if (!startPoint || !currentPoint) return;
    
    const pointRadius = 4;
    ctx.fillStyle = '#ff0000';
    
    // 起始点
    ctx.beginPath();
    ctx.arc(startPoint.x, startPoint.y, pointRadius, 0, Math.PI * 2);
    ctx.fill();
    
    // 当前点
    ctx.beginPath();
    ctx.arc(currentPoint.x, currentPoint.y, pointRadius, 0, Math.PI * 2);
    ctx.fill();
}

// 绘制所有标注
function drawAnnotations(ctx, scaleX = 1, scaleY = 1, offsetX = 0, offsetY = 0) {
    currentAnnotations.forEach(annotation => {
        drawAnnotation(ctx, annotation, scaleX, scaleY, offsetX, offsetY);
    });
}

// 绘制单个标注
function drawAnnotation(ctx, annotation, scaleX = 1, scaleY = 1, offsetX = 0, offsetY = 0) {
    if (!annotation.points || annotation.points.length === 0) return;
    
    const classInfo = classes.find(c => c.name === annotation.class);
    const color = classInfo ? classInfo.color : '#ff0000';
    
    // 检查是否为选中状态
    const isSelected = annotation.id === selectedAnnotationId;
    
    ctx.beginPath();
    ctx.moveTo(annotation.points[0][0] * scaleX + offsetX, annotation.points[0][1] * scaleY + offsetY);
    
    for (let i = 1; i < annotation.points.length; i++) {
        ctx.lineTo(annotation.points[i][0] * scaleX + offsetX, annotation.points[i][1] * scaleY + offsetY);
    }
    
    if (annotation.type === 'rectangle' || annotation.points.length > 2) {
        ctx.closePath();
        ctx.fillStyle = color + '40'; // 半透明填充
        ctx.fill();
    }
    
    // 绘制边框
    ctx.strokeStyle = isSelected ? '#ff0000' : color;
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.stroke();
    
    // 绘制标签名
    if (annotation.points.length > 0) {
        const textX = annotation.points[0][0] * scaleX + offsetX;
        const textY = annotation.points[0][1] * scaleY + offsetY - 5;
        
        ctx.fillStyle = isSelected ? '#ff0000' : color;
        ctx.font = '14px Arial';
        ctx.fillText(annotation.class, textX, textY);
    }
    
    // 如果是选中状态，绘制控制点
    if (isSelected && annotation.type === 'rectangle') {
        drawResizeHandles(ctx, annotation, scaleX, scaleY, offsetX, offsetY);
    }
}

// 绘制调整大小的控制点
function drawResizeHandles(ctx, annotation, scaleX, scaleY, offsetX, offsetY) {
    const points = annotation.points;
    if (points.length < 4) return;
    
    // 计算矩形的四个角点
    const x1 = points[0][0] * scaleX + offsetX;
    const y1 = points[0][1] * scaleY + offsetY;
    const x2 = points[2][0] * scaleX + offsetX;
    const y2 = points[2][1] * scaleY + offsetY;
    
    // 控制点位置
    const handles = [
        { x: x1, y: y1, type: 'nw' }, // 左上
        { x: (x1 + x2) / 2, y: y1, type: 'n' }, // 上中
        { x: x2, y: y1, type: 'ne' }, // 右上
        { x: x2, y: (y1 + y2) / 2, type: 'e' }, // 右中
        { x: x2, y: y2, type: 'se' }, // 右下
        { x: (x1 + x2) / 2, y: y2, type: 's' }, // 下中
        { x: x1, y: y2, type: 'sw' }, // 左下
        { x: x1, y: (y1 + y2) / 2, type: 'w' }  // 左中
    ];
    
    // 绘制控制点
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#ff0000';
    ctx.lineWidth = 1;
    
    handles.forEach(handle => {
        ctx.beginPath();
        ctx.arc(handle.x, handle.y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
    });
}

// 刷新顶部「当前数据集」下拉框（与 /api/datasets 同步）
function refreshActiveDatasetSelect() {
    const sel = document.getElementById('activeDatasetSelect');
    if (!sel) {
        return Promise.resolve();
    }
    return fetch(apiUrl('/api/datasets'))
        .then(response => response.json())
        .then(data => {
            const cur = data.active || '';
            sel.innerHTML = '';
            (data.datasets || []).forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.slug;
                let label = d.slug;
                if (d.slug === '__uploads__') {
                    label = '本地上传';
                }
                if (d.mode === 'external' && d.root) {
                    label += ' — ' + d.root;
                }
                opt.textContent = label;
                sel.appendChild(opt);
            });
            if ([...sel.options].some(o => o.value === cur)) {
                sel.value = cur;
            } else if (sel.options.length) {
                sel.selectedIndex = 0;
            }
        })
        .catch(err => console.error('加载数据集列表失败:', err));
}

let datasetSwitcherChangeBound = false;

function setupDatasetSwitcher() {
    const sel = document.getElementById('activeDatasetSelect');
    if (!sel || datasetSwitcherChangeBound) {
        return;
    }
    datasetSwitcherChangeBound = true;
    sel.addEventListener('change', function() {
        const slug = sel.value;
        if (!slug) {
            return;
        }
        fetch(apiUrl('/api/datasets/active'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ slug: slug })
        })
        .then(response => response.json().then(j => ({ ok: response.ok, j: j })))
        .then(({ ok, j }) => {
            if (!ok) {
                showToast(j.error || '切换数据集失败');
                refreshActiveDatasetSelect();
                return;
            }
            currentImage = null;
            currentAnnotations = [];
            selectedAnnotationId = null;
            loadClasses();
            loadImages();
            showToast('已切换数据集');
        })
        .catch(() => {
            showToast('切换数据集失败');
            refreshActiveDatasetSelect();
        });
    });
}

// 加载类别
function loadClasses() {
    fetch(apiUrl('/api/classes'))
        .then(response => response.json())
        .then(data => {
            classes = data;
            updateClassList();
        })
        .catch(error => console.error('加载类别失败:', error));
}

// 更新类别列表
function updateClassList() {
    const classList = document.getElementById('classList');
    classList.innerHTML = '';
    
    classes.forEach((cls, index) => {
        const li = document.createElement('li');
        li.className = 'class-item';
        // 设置CSS变量，用于背景色
        li.style.setProperty('--class-color', cls.color);
        // 显示数字序号（1-9显示数字，超过9显示-）
        const shortcutKey = index < 9 ? (index + 1) : '-';
        li.innerHTML = `
            <span class="class-shortcut">${shortcutKey}</span>
            <span class="class-name">${cls.name}</span>
            <div class="class-actions">
                <button class="class-edit-btn" data-index="${index}">
                    <i class="fas fa-pencil-alt"></i>
                </button>
            </div>
            <button class="class-delete-btn" data-index="${index}">
                <i class="fas fa-times"></i>
            </button>
        `;
        classList.appendChild(li);
    });
    
    // 添加事件监听器
    document.querySelectorAll('.class-item').forEach((item, index) => {
        // 点击选中类别
        item.addEventListener('click', function() {
            document.querySelectorAll('.class-item').forEach(i => i.classList.remove('selected'));
            this.classList.add('selected');
        });
        
        // 编辑按钮事件
        const editBtn = item.querySelector('.class-edit-btn');
        if (editBtn) {
            editBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                editClass(index);
            });
        }
        
        // 删除按钮事件
        const deleteBtn = item.querySelector('.class-delete-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                deleteClass(index);
            });
        }
    });
    
    // 默认选中第一个类别
    const firstClassItem = document.querySelector('.class-item');
    if (firstClassItem) {
        firstClassItem.classList.add('selected');
    }
}

// 添加类别
function addClass() {
    const nameInput = document.getElementById('newClassInput');
    const colorInput = document.getElementById('newClassColor');
    const name = nameInput.value.trim();
    
    if (!name) {
        showToast('请输入标签名称');
        return;
    }
    
    // 检查是否已存在同名类别
    if (classes.some(cls => cls.name === name)) {
        showToast('类别名称已存在');
        return;
    }
    
    const newClass = {
        name: name,
        color: colorInput.value
    };
    
    classes.push(newClass);
    updateClassList();
    saveClasses();
    
    // 清空输入框
    nameInput.value = '';
}

// 编辑类别
function editClass(index) {
    const cls = classes[index];
    document.getElementById('editClassIndex').value = index;
    document.getElementById('editClassName').value = cls.name;
    document.getElementById('editClassColor').value = cls.color;
    
    const modal = document.getElementById('editClassModal');
    modal.style.display = 'block';
}

// 处理类别编辑表单提交
function handleEditClass(e) {
    e.preventDefault();
    
    const index = document.getElementById('editClassIndex').value;
    const name = document.getElementById('editClassName').value.trim();
    const color = document.getElementById('editClassColor').value;
    
    if (!name) {
        showToast('请输入类别名称');
        return;
    }
    
    // 检查是否与其他类别重名
    if (classes.some((cls, i) => i != index && cls.name === name)) {
        showToast('类别名称已存在');
        return;
    }
    
    classes[index] = {
        name: name,
        color: color
    };
    
    updateClassList();
    saveClasses();
    
    // 关闭模态框
    document.getElementById('editClassModal').style.display = 'none';
}

// 删除类别
function deleteClass(index) {
    if (confirm(`确定要删除类别 "${classes[index].name}" 吗？`)) {
        classes.splice(index, 1);
        updateClassList();
        saveClasses();
    }
}

// 保存类别
function saveClasses() {
    fetch(apiUrl('/api/classes'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(classes)
    }).catch(error => console.error('保存类别失败:', error));
}

// 加载图片列表
function loadImages() {
    fetch(apiUrl('/api/images'))
        .then(response => response.json())
        .then(data => {
            window.allImages = data.images;
            updateImageList(data.images);
            updateImageCount(data.images.length);
            updateAnnotationProgress(data.images);
            
            // 检查URL参数，看是否需要直接打开某个图片
            const urlParams = new URLSearchParams(window.location.search);
            const imageName = urlParams.get('image');
            
            if (imageName) {
                // 如果URL参数指定了图片，检查该图片是否存在
                const imageExists = data.images.some(img => img.name === imageName);
                if (imageExists) {
                    selectImage(imageName);
                    return;
                }
            }
            
            // 如果URL参数无效或未指定，默认选中第一张图片（如果有）
            if (data.images.length > 0) {
                selectImage(data.images[0].name);
            } else {
                // 如果没有图片，显示无图片提示
                document.getElementById('noImageMessage').style.display = 'block';
                document.getElementById('imageCanvasContainer').style.display = 'none';
                currentImage = null;
            }
        })
        .catch(error => {
            console.error('加载图片列表失败:', error);
            showToast('加载图片列表失败');
        });
}

// 更新图片列表
function updateImageList(images) {
    const imageList = document.getElementById('imageList');
    imageList.innerHTML = '';
    
    // 调试：检查当前图片的标注数量
    const currentImageData = images.find(img => img.name === currentImage);
    if (currentImageData) {
        console.log('当前图片标注数量:', currentImageData.name, currentImageData.annotation_count);
    }
    
    images.forEach((image, index) => {
        const li = document.createElement('li');
        li.className = 'image-item';
        li.dataset.image = image.name;
        
        // 检查是否有标注
        const hasAnnotations = image.annotation_count > 0;
        
        li.innerHTML = `
            <div class="image-checkbox">
                <input type="checkbox" class="image-checkbox-input">
            </div>
            <div class="annotation-status">
                ${hasAnnotations ? 
                  '<i class="fas fa-check-circle annotated" title="已标注"></i>' : 
                  '<i class="far fa-circle unannotated" title="未标注"></i>'}
            </div>
            <div class="image-index">${index + 1}</div>
            <div class="image-name" title="${image.name}">${image.name}</div>
        `;
        imageList.appendChild(li);
    });
    
    // 添加点击事件
    document.querySelectorAll('.image-item').forEach(item => {
        item.addEventListener('click', function(e) {
            if (e.target.type !== 'checkbox') {
                const imageName = this.dataset.image;
                selectImage(imageName);
            }
        });
    });
    
    // 添加复选框事件
    document.querySelectorAll('.image-checkbox-input').forEach(checkbox => {
        checkbox.addEventListener('change', updateDeleteButtonState);
    });
    
    // 不再需要删除按钮事件监听器
}

// 更新图片计数
function updateImageCount(count) {
    document.getElementById('imageCount').textContent = `共 ${count} 张图片`;
}

// 更新标注进度
function updateAnnotationProgress(images) {
    const total = images ? images.length : (window.allImages ? window.allImages.length : 0);
    const annotated = images ? images.filter(img => img.annotation_count > 0).length : 
                      (window.allImages ? window.allImages.filter(img => img.annotation_count > 0).length : 0);
    
    document.getElementById('annotatedCount').textContent = annotated;
    document.getElementById('totalImageCount').textContent = total;
}

// 筛选图片
function filterImages() {
    const searchTerm = document.getElementById('imageSearch').value.toLowerCase();
    const filteredImages = window.allImages.filter(image => 
        image.name.toLowerCase().includes(searchTerm)
    );
    updateImageList(filteredImages);
}

// 选择图片
function selectImage(imageName, skipLoadAnnotations = false) {
    // 更新UI选中状态
    document.querySelectorAll('.image-item').forEach(item => {
        item.classList.remove('selected');
        if (item.dataset.image === imageName) {
            item.classList.add('selected');
        }
    });
    
    currentImage = imageName;
    
    // 隐藏无图片提示
    document.getElementById('noImageMessage').style.display = 'none';
    
    // 显示画布容器
    document.getElementById('imageCanvasContainer').style.display = 'block';
    
    // 加载标注，除非跳过
    if (!skipLoadAnnotations) {
        loadAnnotations(imageName);
    }
    
    // 如果AI标注已开启，自动进行AI标注
    if (aiAnnotateEnabled && !skipLoadAnnotations) {
        performAiAnnotate();
    }
}

// 加载标注
function loadAnnotations(imageName) {
    fetch(apiUrl(`/api/annotations/${imageKeyForApiUrl(imageName)}`))
        .then(response => response.json())
        .then(data => {
            currentAnnotations = data || [];
            if (normalizeAnnotationIds(currentAnnotations)) {
                saveAnnotationsSilent();
            }
            updateAnnotationListDebounced();
            redrawCanvas();
        })
        .catch(error => {
            console.error('加载标注失败:', error);
            currentAnnotations = [];
            updateAnnotationListDebounced();
            redrawCanvas();
        });
}

// 更新标注列表
function updateAnnotationList() {
    const annotationList = document.getElementById('currentAnnotations');
    annotationList.innerHTML = '';
    
    currentAnnotations.forEach((annotation, index) => {
        const li = document.createElement('li');
        li.className = `annotation-item ${annotation.id === selectedAnnotationId ? 'selected' : ''}`;
        li.dataset.annotationId = annotation.id;
        li.innerHTML = `
            <div class="annotation-color" style="background-color: ${getClassColor(annotation.class)};"></div>
            <span class="annotation-class">${annotation.class}</span>
            <div class="annotation-actions">
                <button class="btn btn-small btn-danger delete-annotation-btn" data-index="${index}">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
        annotationList.appendChild(li);
    });
    
    // 添加事件监听器
    document.querySelectorAll('.annotation-item').forEach((item, index) => {
        // 点击选中标注
        item.addEventListener('click', function() {
            const annotationId = parseInt(this.dataset.annotationId);
            selectedAnnotationId = annotationId;
            updateAnnotationList();
            redrawCanvas();
        });
        
        // 删除按钮事件
        const deleteBtn = item.querySelector('.delete-annotation-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                deleteAnnotation(index);
            });
        }
    });
}

// 获取类别颜色
function getClassColor(className) {
    const cls = classes.find(c => c.name === className);
    return cls ? cls.color : '#ff0000';
}

// 删除标注
function deleteAnnotation(index) {
    if (confirm('确定要删除这个标注吗？')) {
        const annotation = currentAnnotations[index];
        // 如果删除的是当前选中的标注，重置选中状态
        if (annotation.id === selectedAnnotationId) {
            selectedAnnotationId = null;
        }
        currentAnnotations.splice(index, 1);
        updateAnnotationListDebounced();
        saveAnnotationsSilent();
        redrawCanvas();
    }
}

// 清除当前标注
function clearCurrentAnnotations() {
    if (currentAnnotations.length === 0) {
        showToast('当前没有标注可清除');
        return;
    }
    
    if (confirm(`确定要清除当前图片的 ${currentAnnotations.length} 个标注吗？`)) {
        currentAnnotations = [];
        selectedAnnotationId = null; // 重置选中状态
        updateAnnotationListDebounced();
        
        // 保存空标注并刷新图片列表
        fetch(apiUrl(`/api/annotations/${imageKeyForApiUrl(currentImage)}`), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(currentAnnotations)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || '保存失败');
                });
            }
            // 刷新图片列表以更新标注状态
            return fetch(apiUrl('/api/images'))
        })
        .then(response => response.json())
        .then(data => {
            window.allImages = data.images;
            updateImageList(data.images);
            updateImageCount(data.images.length);
            updateAnnotationProgress(data.images);
        })
        .catch(error => {
            console.error('清除标注失败:', error);
            showToast('清除失败: ' + error.message, 'error');
        });
        
        redrawCanvas();
        showToast('标注已清除');
    }
}

// 保存标注 (静默保存，不显示提示，不跳转)
function saveAnnotationsSilent() {
    if (!currentImage) return;
    
    fetch(apiUrl(`/api/annotations/${imageKeyForApiUrl(currentImage)}`), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(currentAnnotations)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || '保存失败');
            });
        }
    })
    .catch(error => {
        console.error('静默保存失败:', error);
        showToast('保存失败: ' + error.message, 'error');
    });
}

// 保存标注 (手动保存，显示提示，可能跳转)
function saveAnnotations() {
    if (!currentImage) {
        showToast('请先选择一张图片', 'warning');
        return;
    }
    
    console.log('正在保存标注...', currentImage, currentAnnotations);
    
    fetch(apiUrl(`/api/annotations/${imageKeyForApiUrl(currentImage)}`), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(currentAnnotations)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || '保存失败');
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('保存成功，服务器返回:', data);
        showToast('标注已保存');
        // 重新获取图片列表，更新标注计数
        fetch(apiUrl('/api/images'))
            .then(response => response.json())
            .then(data => {
                window.allImages = data.images;
                updateImageList(data.images);
                updateImageCount(data.images.length);
                updateAnnotationProgress(data.images);
                
                // 如果设置了保存后自动跳转，切换到下一张
                if (shortcutSettings.autoNextAfterSave) {
                    goToNextImage();
                } else {
                    // 保持当前选中的图片不变，只更新UI选中状态，不重新加载标注
                    document.querySelectorAll('.image-item').forEach(item => {
                        item.classList.remove('selected');
                        if (item.dataset.image === currentImage) {
                            item.classList.add('selected');
                        }
                    });
                    // 重绘画布以显示当前标注
                    redrawCanvas();
                }
            })
            .catch(error => {
                console.error('更新图片列表失败:', error);
            });
    })
    .catch(error => {
        console.error('保存标注失败:', error);
        showToast('保存标注失败: ' + error.message, 'error');
    });
}

// 全选图片
function selectAllImages() {
    const checkboxes = document.querySelectorAll('.image-checkbox-input');
    const allSelected = Array.from(checkboxes).every(cb => cb.checked);
    
    checkboxes.forEach(cb => {
        cb.checked = !allSelected;
    });
    
    updateDeleteButtonState();
}

// 更新删除按钮状态
function updateDeleteButtonState() {
    const checkedCount = document.querySelectorAll('.image-checkbox-input:checked').length;
    const deleteBtn = document.getElementById('deleteSelectedBtn');
    
    if (checkedCount > 0) {
        deleteBtn.disabled = false;
        deleteBtn.title = `删除选中的 ${checkedCount} 张图片`;
    } else {
        deleteBtn.disabled = true;
        deleteBtn.title = '删除选中';
    }
}

// 删除选中图片
function deleteSelectedImages() {
    const checkedItems = document.querySelectorAll('.image-checkbox-input:checked');
    
    if (checkedItems.length === 0) {
        showToast('请先选择要删除的图片');
        return;
    }
    
    if (!confirm(`确定要删除选中的 ${checkedItems.length} 张图片吗？`)) {
        return;
    }
    
    const imageNames = Array.from(checkedItems).map(cb => {
        return cb.closest('.image-item').dataset.image;
    });
    
    fetch(apiUrl('/api/images/delete'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({images: imageNames})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(`成功删除 ${imageNames.length} 张图片`);
            // 重新加载图片列表
            loadImages();
            // 清除选中状态
            checkedItems.forEach(cb => cb.checked = false);
            updateDeleteButtonState();
        } else {
            throw new Error(data.error || '删除失败');
        }
    })
    .catch(error => {
        console.error('删除图片失败:', error);
        showToast('删除图片失败: ' + error.message);
    });
}

// 显示数据集模态框
function showDatasetModal() {
    document.getElementById('datasetModal').style.display = 'block';
}

// 显示导出模态框
function showExportModal() {
    // 加载类别到导出表单
    const container = document.getElementById('classCheckboxes');
    container.innerHTML = '';
    
    classes.forEach(cls => {
        const label = document.createElement('label');
        label.className = 'class-checkbox-label';
        label.innerHTML = `
            <input type="checkbox" name="exportClasses" value="${cls.name}" checked>
            <span class="class-color-inline" style="background-color: ${cls.color};"></span>
            ${cls.name}
        `;
        container.appendChild(label);
    });
    
    // 设置默认比例
    document.getElementById('trainRatio').value = 0.7;
    document.getElementById('valRatio').value = 0.2;
    document.getElementById('testRatio').value = 0.1;

    const exportModal = document.getElementById('exportModal');
    if (exportModal) {
        exportModal.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
        exportModal.querySelectorAll('.tab-pane').forEach((p) => p.classList.remove('active'));
        const localBtn = exportModal.querySelector('.tab-btn[data-tab="export-local"]');
        const localPane = document.getElementById('export-local-tab');
        if (localBtn) localBtn.classList.add('active');
        if (localPane) localPane.classList.add('active');
        const statusEl = document.getElementById('cloudExportStatus');
        if (statusEl) statusEl.textContent = '';
    }
    
    document.getElementById('exportModal').style.display = 'block';
}

// 检查YOLO11安装状态并更新UI
function checkYolo11InstallStatus() {
    // 发送请求检查YOLO11安装状态
    fetch(apiUrl('/api/check-yolo11-install'))
        .then(response => response.json())
        .then(data => {
            const isInstalled = data.is_installed;
            const modelsSection = document.querySelector('.yolo11-models-section');
            const downloadModelsBtn = document.getElementById('downloadModelsBtn');
            const refreshModelsBtn = document.getElementById('refreshModelsBtn');
            const modelDropZone = document.getElementById('modelDropZone');
            const modelsContainer = document.getElementById('modelsContainer');
            
            // 更新安装信息显示
            const installInfoElement = document.getElementById('yolo11InstallInfo');
            if (isInstalled) {
                if (installInfoElement) {
                    const installTime = data.install_time || '未知';
                    const hardware = data.has_cuda ? 'CUDA (GPU)' : 'CPU';
                    installInfoElement.innerHTML = `
                        <p style="margin: 5px 0;"><strong>安装时间:</strong> ${installTime}</p>
                        <p style="margin: 5px 0;"><strong>硬件支持:</strong> ${hardware}</p>
                    `;
                    installInfoElement.style.display = 'block';
                }
                
                // 更新按钮状态
                if (modelsSection) {
                    modelsSection.style.opacity = '1';
                    modelsSection.style.pointerEvents = 'auto';
                }
                if (downloadModelsBtn) downloadModelsBtn.disabled = false;
                if (refreshModelsBtn) refreshModelsBtn.disabled = false;
            } else {
                if (installInfoElement) {
                    installInfoElement.innerHTML = '';
                    installInfoElement.style.display = 'none';
                }
                
                // 更新按钮状态
                if (modelsSection) {
                    modelsSection.style.opacity = '0.5';
                    modelsSection.style.pointerEvents = 'none';
                }
                if (downloadModelsBtn) downloadModelsBtn.disabled = true;
                if (refreshModelsBtn) refreshModelsBtn.disabled = true;
            }
        })
        .catch(error => {
            console.error('检查YOLO11安装状态失败:', error);
        });
}

// 下载YOLO11预训练模型
function downloadModels() {
    // 获取选中的模型
    const selectedModels = Array.from(document.querySelectorAll('input[name="yolo11Models"]:checked'))
        .map(cb => cb.value);
    
    if (selectedModels.length === 0) {
        showToast('请至少选择一个模型');
        return;
    }
    
    // 获取安装路径
    const installPath = document.getElementById('yolo11InstallPath').value;
    
    // 显示状态
    const statusElement = document.getElementById('modelDownloadStatus');
    const statusText = document.getElementById('modelStatusText');
    statusElement.style.display = 'block';
    statusText.textContent = `正在下载模型: ${selectedModels.join(', ')}...`;
    
    // 禁用下载按钮
    const downloadBtn = document.getElementById('downloadModelsBtn');
    const refreshBtn = document.getElementById('refreshModelsBtn');
    downloadBtn.disabled = true;
    refreshBtn.disabled = true;
    
    // 使用EventSource实现服务器推送进度
    const eventSource = new EventSource(apiUrl(`/api/download-models?models=${selectedModels.join(',')}&install_path=${encodeURIComponent(installPath)}`));
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            // 更新状态文本
            statusText.textContent = data.message;
            
            // 检查是否下载完成
            if (data.status === 'completed') {
                eventSource.close();
                statusText.textContent = `模型下载完成: ${selectedModels.join(', ')}`;
                // 刷新模型列表
                refreshModels();
                // 恢复按钮状态
                downloadBtn.disabled = false;
                refreshBtn.disabled = false;
                // 5秒后隐藏状态
                setTimeout(() => {
                    statusElement.style.display = 'none';
                }, 5000);
            }
            
            // 检查是否下载失败
            if (data.status === 'error') {
                eventSource.close();
                statusText.textContent = `下载失败: ${data.error}`;
                // 恢复按钮状态
                downloadBtn.disabled = false;
                refreshBtn.disabled = false;
                // 5秒后隐藏状态
                setTimeout(() => {
                    statusElement.style.display = 'none';
                }, 5000);
            }
        } catch (error) {
            console.error('解析下载进度失败:', error);
        }
    };
    
    eventSource.onerror = function() {
        eventSource.close();
        statusText.textContent = '下载过程中发生错误';
        // 恢复按钮状态
        downloadBtn.disabled = false;
        refreshBtn.disabled = false;
        // 5秒后隐藏状态
        setTimeout(() => {
            statusElement.style.display = 'none';
        }, 5000);
    };
}

// 刷新模型列表
function refreshModels() {
    // 获取安装路径
    const installPath = document.getElementById('yolo11InstallPath').value;
    
    // 显示加载状态
    const modelsList = document.getElementById('modelsList');
    modelsList.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 正在加载模型列表...';
    
    // 发送请求获取模型列表
    fetch(apiUrl(`/api/list-models?install_path=${encodeURIComponent(installPath)}`))
        .then(response => response.json())
        .then(data => {
            // 更新模型列表
            if (data.models && data.models.length > 0) {
                modelsList.innerHTML = '';
                data.models.forEach(model => {
                    const modelItem = document.createElement('div');
                    modelItem.className = 'model-item';
                    modelItem.innerHTML = `
                        <i class="fas fa-file-code"></i>
                        <span class="model-name">${model}</span>
                        <button class="delete-model-btn" onclick="deleteModel('${model}')">
                            <i class="fas fa-times"></i>
                        </button>
                    `;
                    modelsList.appendChild(modelItem);
                });
            } else {
                modelsList.innerHTML = '<i class="fas fa-info-circle"></i> 暂无已安装的模型';
            }
        })
        .catch(error => {
            console.error('获取模型列表失败:', error);
            modelsList.innerHTML = '<i class="fas fa-exclamation-triangle"></i> 获取模型列表失败';
        });
}

// 删除模型
function deleteModel(modelName) {
    // 确认删除
    if (!confirm(`确定要删除模型 ${modelName} 吗？`)) {
        return;
    }
    
    // 获取安装路径
    const installPath = document.getElementById('yolo11InstallPath').value;
    
    // 显示状态
    const statusElement = document.getElementById('modelDownloadStatus');
    const statusText = document.getElementById('modelStatusText');
    statusElement.style.display = 'block';
    statusText.textContent = `正在删除模型: ${modelName}...`;
    
    // 发送删除请求
    fetch(apiUrl('/api/delete-model'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Install-Path': installPath
        },
        body: JSON.stringify({model_name: modelName})
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            statusText.textContent = `模型删除成功: ${modelName}`;
            // 刷新模型列表
            refreshModels();
        } else {
            statusText.textContent = `删除失败: ${data.error}`;
        }
        // 5秒后隐藏状态
        setTimeout(() => {
            statusElement.style.display = 'none';
        }, 5000);
    })
    .catch(error => {
        console.error('删除模型失败:', error);
        statusText.textContent = `删除失败: ${error.message}`;
        // 5秒后隐藏状态
        setTimeout(() => {
            statusElement.style.display = 'none';
        }, 5000);
    });
}

// 设置模型拖放区域事件
function setupModelDropZoneEvents() {
    const dropZone = document.getElementById('modelDropZone');
    
    // 阻止默认拖放行为
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });
    
    // 高亮拖放区域
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });
    
    // 取消高亮拖放区域
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });
    
    // 处理文件拖放
    dropZone.addEventListener('drop', handleDrop, false);
}

// 阻止默认拖放行为
function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

// 高亮拖放区域
function highlight(e) {
    const dropZone = document.getElementById('modelDropZone');
    dropZone.style.borderColor = '#266CFB';
    dropZone.style.backgroundColor = '#e8f0fe';
}

// 取消高亮拖放区域
function unhighlight(e) {
    const dropZone = document.getElementById('modelDropZone');
    dropZone.style.borderColor = '#ced4da';
    dropZone.style.backgroundColor = '#f8f9fa';
}

// 处理文件拖放
function handleDrop(e) {
    const files = e.dataTransfer.files;
    if (files.length === 0) return;
    
    // 显示状态
    const statusElement = document.getElementById('modelDownloadStatus');
    const statusText = document.getElementById('modelStatusText');
    statusElement.style.display = 'block';
    statusText.textContent = `正在上传模型文件...`;
    
    // 获取安装路径
    const installPath = document.getElementById('yolo11InstallPath').value;
    
    // 创建FormData对象
    const formData = new FormData();
    Array.from(files).forEach(file => {
        formData.append('files[]', file, file.name);
    });
    
    // 发送文件上传请求
    fetch(apiUrl('/api/upload-model'), {
        method: 'POST',
        body: formData,
        headers: {
            'X-Install-Path': installPath
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            statusText.textContent = `模型文件上传成功: ${data.uploaded_files.join(', ')}`;
            // 刷新模型列表
            refreshModels();
        } else {
            statusText.textContent = `上传失败: ${data.error}`;
        }
    })
    .catch(error => {
        console.error('上传模型文件失败:', error);
        statusText.textContent = `上传失败: ${error.message}`;
    })
    .finally(() => {
        // 5秒后隐藏状态
        setTimeout(() => {
            statusElement.style.display = 'none';
        }, 5000);
    });
}

// 显示设置模态框
function showSettingsModal() {
    document.getElementById('settingsModal').style.display = 'block';
    // 检查YOLO11安装状态并更新UI
    checkYolo11InstallStatus();
    // 刷新模型列表
    refreshModels();
    
    // 加载快捷键设置到表单
    document.getElementById('deleteSelectedShortcut').value = shortcutSettings.deleteSelected || 'Q';
    document.getElementById('saveShortcut').value = shortcutSettings.save || 'Ctrl+S';
    document.getElementById('prevImageShortcut').value = shortcutSettings.prevImage || 'A';
    document.getElementById('nextImageShortcut').value = shortcutSettings.nextImage || 'D';
    document.getElementById('autoNextAfterSave').checked = shortcutSettings.autoNextAfterSave || false;
}

// 处理导出表单提交
function handleExport(e) {
    e.preventDefault();
    
    // 获取表单数据
    const formData = new FormData(e.target);
    const trainRatio = parseFloat(formData.get('trainRatio'));
    const valRatio = parseFloat(formData.get('valRatio'));
    const testRatio = parseFloat(formData.get('testRatio'));

    console.log("trainRatio:", typeof trainRatio, trainRatio);
    console.log("valRatio:", typeof valRatio, valRatio);
    console.log("testRatio:", typeof testRatio,testRatio)


    // 获取选中的类别
    const selectedClasses = Array.from(document.querySelectorAll('input[name="exportClasses"]:checked'))
        .map(cb => cb.value);
    
    if (selectedClasses.length === 0) {
        showToast('请至少选择一个类别');
        return;
    }
    
    // 检查比例总和
    // const total = trainRatio + valRatio + testRatio;
    // if (Math.abs(total - 1.0) > 0.001) {
    //     showToast('训练集、验证集和测试集比例之和必须等于1');
    //     return;
    // }
    
    // 获取样本选择选项和文件前缀
    const sampleSelection = formData.get('sampleSelection');
    const exportPrefix = document.getElementById('exportPrefix').value;
    
    // 显示加载指示器
    document.getElementById('exportSubmitBtn').style.display = 'none';
    document.getElementById('exportLoadingIndicator').style.display = 'block';
    
    // 发送导出请求
    fetch(apiUrl('/api/export'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            train_ratio: trainRatio,
            val_ratio: valRatio,
            test_ratio: testRatio,
            selected_classes: selectedClasses,
            sample_selection: sampleSelection,
            export_prefix: exportPrefix
        })
    })
    .then(response => {
        if (response.ok) {
            return response.blob().then(blob => {
                // 生成带时间戳的文件名，格式：datasets_年月日时分秒.zip
                const now = new Date();
                const year = now.getFullYear();
                const month = String(now.getMonth() + 1).padStart(2, '0');
                const day = String(now.getDate()).padStart(2, '0');
                const hours = String(now.getHours()).padStart(2, '0');
                const minutes = String(now.getMinutes()).padStart(2, '0');
                const seconds = String(now.getSeconds()).padStart(2, '0');
                const filename = `datasets_${year}${month}${day}${hours}${minutes}${seconds}.zip`;
                
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                // 隐藏模态框
                document.getElementById('exportModal').style.display = 'none';
            });
        } else {
            return response.json().then(data => {
                throw new Error(data.error || '导出失败');
            });
        }
    })
    .catch(error => {
        console.error('导出失败:', error);
        showToast('导出失败: ' + error.message);
    })
    .finally(() => {
        // 隐藏加载指示器
        document.getElementById('exportSubmitBtn').style.display = 'block';
        document.getElementById('exportLoadingIndicator').style.display = 'none';
    });
}

function loadCloudDatasetOptions() {
    const sel = document.getElementById('cloudDatasetSelect');
    if (!sel) return Promise.resolve();
    sel.innerHTML = '<option value="">加载中…</option>';
    return fetch(apiUrl('/api/cloud/datasets'))
        .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
        .then(({ ok, j }) => {
            if (!ok || j.error) {
                throw new Error(j.error || '加载数据集列表失败');
            }
            const list = j.datasets || [];
            if (!list.length) {
                sel.innerHTML = '<option value="">（暂无图片数据集）</option>';
                return;
            }
            sel.innerHTML = '<option value="">请选择数据集</option>';
            list.forEach((d) => {
                const opt = document.createElement('option');
                opt.value = String(d.id);
                opt.textContent = d.label || d.name || `ID:${d.id}`;
                sel.appendChild(opt);
            });
        })
        .catch((err) => {
            console.error(err);
            sel.innerHTML = '<option value="">加载失败</option>';
            showToast(String(err.message || err));
        });
}

function handleCloudExport() {
    const statusEl = document.getElementById('cloudExportStatus');
    const setStatus = (t) => { if (statusEl) statusEl.textContent = t || ''; };
    const name = (document.getElementById('cloudExportName') || {}).value?.trim?.() || '';
    const version = (document.getElementById('cloudExportVersion') || {}).value?.trim?.() || '';
    if (!name) {
        showToast('请填写数据集名称');
        return;
    }
    if (!version) {
        showToast('请填写版本');
        return;
    }
    const btn = document.getElementById('cloudExportBtn');
    const prev = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 导出中...';
    }
    setStatus('正在创建云平台数据集并同步标注…');
    fetch(apiUrl('/api/cloud/export'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, version }),
    })
        .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
        .then(({ ok, j }) => {
            if (!ok || j.error) {
                throw new Error(j.error || '导出失败');
            }
            const extra = (j.errors && j.errors.length) ? `；部分错误：${j.errors.slice(0, 3).join('；')}` : '';
            showToast(j.message || '导出完成');
            setStatus(`新数据集 ID: ${j.cloud_dataset_id}；更新 ${j.updated_images} 张，新建 ${j.created_images} 张${extra}`);
        })
        .catch((err) => {
            console.error(err);
            showToast(String(err.message || err));
            setStatus('');
        })
        .finally(() => {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = prev;
            }
        });
}

// 处理设置保存
function handleSettingsSave(e) {
    e.preventDefault();
    
    // 读取快捷键设置
    shortcutSettings.deleteSelected = document.getElementById('deleteSelectedShortcut').value || 'Q';
    shortcutSettings.save = document.getElementById('saveShortcut').value || 'Ctrl+S';
    shortcutSettings.prevImage = document.getElementById('prevImageShortcut').value || 'A';
    shortcutSettings.nextImage = document.getElementById('nextImageShortcut').value || 'D';
    shortcutSettings.autoNextAfterSave = document.getElementById('autoNextAfterSave').checked;
    
    // 保存到localStorage
    localStorage.setItem('auto-labeling_shortcuts', JSON.stringify(shortcutSettings));
    
    showToast('设置已保存');
    document.getElementById('settingsModal').style.display = 'none';
}

// 处理键盘快捷键
function handleKeyDown(e) {
    // 如果正在输入框中，只处理Ctrl+S（防止浏览器默认保存），其他快捷键不处理
    const isInInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT';
    
    // 解析保存快捷键设置
    const saveKey = shortcutSettings.save || 'Ctrl+S';
    const saveKeyParts = saveKey.split('+');
    const saveRequiresCtrl = saveKeyParts.some(p => p.toLowerCase() === 'ctrl');
    const saveRequiresShift = saveKeyParts.some(p => p.toLowerCase() === 'shift');
    const saveRequiresAlt = saveKeyParts.some(p => p.toLowerCase() === 'alt');
    const saveMainKey = saveKeyParts.filter(p => !['ctrl', 'shift', 'alt'].includes(p.toLowerCase())).pop() || 's';
    
    // 检查是否匹配保存快捷键
    const isSaveShortcut = (
        e.key.toUpperCase() === saveMainKey.toUpperCase() &&
        e.ctrlKey === saveRequiresCtrl &&
        e.shiftKey === saveRequiresShift &&
        e.altKey === saveRequiresAlt
    );
    
    // 始终阻止浏览器默认的Ctrl+S行为
    if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
    }
    
    // 保存快捷键处理
    if (isSaveShortcut) {
        e.preventDefault();
        console.log('保存快捷键触发, isInInput:', isInInput);
        if (!isInInput) {
            saveAnnotations();
        }
        return;
    }
    
    // 如果在输入框中，不处理其他快捷键
    if (isInInput) {
        return;
    }
    
    // 删除选中框快捷键
    if (e.key.toUpperCase() === shortcutSettings.deleteSelected.toUpperCase() && !e.ctrlKey && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        deleteSelectedAnnotation();
        return;
    }
    
    // 上一张图片快捷键
    if (e.key.toUpperCase() === shortcutSettings.prevImage.toUpperCase() && !e.ctrlKey && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        goToPrevImage();
        return;
    }
    
    // 下一张图片快捷键
    if (e.key.toUpperCase() === shortcutSettings.nextImage.toUpperCase() && !e.ctrlKey && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        goToNextImage();
        return;
    }
    
    // 数字键1-9快速切换标签类别
    if (e.key >= '1' && e.key <= '9' && !e.ctrlKey && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        const index = parseInt(e.key) - 1;
        selectClassByIndex(index);
        return;
    }
}

// 通过索引选择标签类别
function selectClassByIndex(index) {
    if (index < 0 || index >= classes.length) {
        showToast(`标签 ${index + 1} 不存在`);
        return;
    }
    
    // 移除所有选中状态
    document.querySelectorAll('.class-item').forEach(item => {
        item.classList.remove('selected');
    });
    
    // 选中对应的标签
    const classItems = document.querySelectorAll('.class-item');
    if (classItems[index]) {
        classItems[index].classList.add('selected');
        showToast(`已切换到: ${classes[index].name}`);
    }
}

// 删除选中的标注框
function deleteSelectedAnnotation() {
    if (selectedAnnotationId === null) {
        showToast('请先选中一个标注框');
        return;
    }
    
    const index = currentAnnotations.findIndex(a => a.id === selectedAnnotationId);
    if (index !== -1) {
        currentAnnotations.splice(index, 1);
        selectedAnnotationId = null;
        updateAnnotationListDebounced();
        saveAnnotationsSilent();
        redrawCanvas();
        showToast('已删除选中的标注');
    }
}

// 切换到上一张图片
function goToPrevImage() {
    if (!window.allImages || window.allImages.length === 0) return;
    
    const currentIndex = window.allImages.findIndex(img => img.name === currentImage);
    if (currentIndex === -1) return;
    
    const prevIndex = currentIndex - 1;
    if (prevIndex >= 0) {
        selectImage(window.allImages[prevIndex].name);
    } else {
        showToast('已经是第一张图片');
    }
}

// 设置模态框关闭事件
function setupModalCloseEvents() {
    document.querySelectorAll('.modal .close').forEach(closeBtn => {
        closeBtn.addEventListener('click', function() {
            this.closest('.modal').style.display = 'none';
        });
    });
    
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    });
}

const IMAGE_UPLOAD_EXTENSIONS = /\.(jpe?g|png|gif|bmp|webp|tiff?)$/i;
/** 每批上传张数，避免单次 FormData 过大触发 413（直连 Flask 与 Nginx 代理均适用） */
const IMAGE_UPLOAD_BATCH_SIZE = 25;

/** 与后端 _flatten_upload_relative_name 一致：子目录压平为 uploads 下唯一文件名 */
function flattenUploadRelativeName(filename) {
    if (!filename) return '';
    const norm = filename.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (!norm.includes('/')) {
        const parts = norm.split('/');
        return parts[parts.length - 1];
    }
    return norm.replace(/\//g, '__');
}

function isImageUploadFile(file) {
    const name = (file.webkitRelativePath || file.name || '').toLowerCase();
    return IMAGE_UPLOAD_EXTENSIONS.test(name) || (file.type && file.type.startsWith('image/'));
}

function filterImageUploadFiles(files) {
    return Array.from(files).filter(isImageUploadFile);
}

function uploadFilenameForFile(file) {
    return flattenUploadRelativeName(file.webkitRelativePath || file.name);
}

async function uploadImageFilesInBatches(files, onProgress) {
    const total = files.length;
    let done = 0;
    for (let i = 0; i < total; i += IMAGE_UPLOAD_BATCH_SIZE) {
        const batch = files.slice(i, i + IMAGE_UPLOAD_BATCH_SIZE);
        const formData = new FormData();
        batch.forEach(file => {
            formData.append('files[]', file, uploadFilenameForFile(file));
        });
        const response = await fetch(apiUrl('/api/upload'), {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            if (response.status === 413) {
                throw new Error('REQUEST_ENTITY_TOO_LARGE');
            }
            let detail = `HTTP ${response.status}`;
            try {
                const body = await response.json();
                if (body && body.error) detail = body.error;
            } catch (_e) { /* ignore */ }
            throw new Error(detail);
        }
        await response.json();
        done += batch.length;
        if (typeof onProgress === 'function') {
            onProgress(done, total);
        }
    }
}

function readDirectoryEntryRecursive(entry, pathPrefix, files) {
    return new Promise((resolve) => {
        if (entry.isFile) {
            entry.file((file) => {
                const rel = pathPrefix + file.name;
                try {
                    Object.defineProperty(file, 'webkitRelativePath', {
                        value: rel,
                        configurable: true
                    });
                } catch (err) {
                    // 部分环境不可写，仍保留 basename
                }
                files.push(file);
                resolve();
            }, () => resolve());
            return;
        }
        if (entry.isDirectory) {
            const reader = entry.createReader();
            const readBatch = () => {
                reader.readEntries(async (entries) => {
                    if (!entries.length) {
                        resolve();
                        return;
                    }
                    await Promise.all(entries.map((child) =>
                        readDirectoryEntryRecursive(child, pathPrefix + entry.name + '/', files)
                    ));
                    readBatch();
                }, () => resolve());
            };
            readBatch();
            return;
        }
        resolve();
    });
}

async function collectFilesFromDataTransfer(dataTransfer) {
    const items = dataTransfer.items;
    if (!items || !items.length) {
        return Array.from(dataTransfer.files || []);
    }
    const files = [];
    const entryTasks = [];
    for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind !== 'file') continue;
        const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
        if (entry) {
            entryTasks.push(readDirectoryEntryRecursive(entry, '', files));
        } else {
            const file = item.getAsFile();
            if (file) files.push(file);
        }
    }
    if (entryTasks.length) {
        await Promise.all(entryTasks);
    }
    if (files.length) {
        return files;
    }
    return Array.from(dataTransfer.files || []);
}

function updateImageUploadSelection(selectedFiles) {
    const uploadArea = document.getElementById('imageUploadArea');
    const uploadImagesBtn = document.getElementById('uploadImagesBtn');
    if (!uploadArea || !uploadImagesBtn) return;

    const existingCount = uploadArea.querySelector('.file-count');
    if (existingCount) {
        existingCount.remove();
    }

    if (!selectedFiles.length) {
        uploadImagesBtn.disabled = true;
        return;
    }

    const fileCount = document.createElement('div');
    fileCount.className = 'file-count';
    fileCount.textContent = `已选择 ${selectedFiles.length} 张图片`;
    fileCount.style.marginTop = '10px';
    fileCount.style.fontSize = '0.9em';
    fileCount.style.color = '#666';
    uploadArea.appendChild(fileCount);
    uploadImagesBtn.disabled = false;
}

function setupImageUploadDropZone(uploadArea, onFilesSelected) {
    if (!uploadArea) return;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.add('drag-over');
        }, false);
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.remove('drag-over');
        }, false);
    });

    uploadArea.addEventListener('drop', async (e) => {
        const rawFiles = await collectFilesFromDataTransfer(e.dataTransfer);
        const imageFiles = filterImageUploadFiles(rawFiles);
        if (!imageFiles.length) {
            showToast('未找到可上传的图片文件，请拖拽包含图片的文件夹');
            return;
        }
        onFilesSelected(imageFiles);
    }, false);
}

// 设置数据集上传事件
function setupDatasetUploadEvents() {
    const datasetModal = document.getElementById('datasetModal');
    if (datasetModal) {
        ['dragenter', 'dragover', 'drop'].forEach((eventName) => {
            datasetModal.addEventListener(eventName, preventDefaults, false);
        });
    }

    // 图片文件夹上传
    const selectFolderBtn = document.getElementById('selectFolderBtn');
    const folderInput = document.getElementById('folderInput');
    const uploadImagesBtn = document.getElementById('uploadImagesBtn');
    const imageUploadArea = document.getElementById('imageUploadArea');
    let selectedImageFiles = [];

    const setSelectedImageFiles = (files) => {
        selectedImageFiles = filterImageUploadFiles(files);
        updateImageUploadSelection(selectedImageFiles);
    };

    if (selectFolderBtn && folderInput && uploadImagesBtn) {
        selectFolderBtn.addEventListener('click', function() {
            folderInput.click();
        });

        setupImageUploadDropZone(imageUploadArea, setSelectedImageFiles);
        
        folderInput.addEventListener('change', function(e) {
            const files = filterImageUploadFiles(e.target.files);
            if (files.length > 0) {
                setSelectedImageFiles(files);
            } else if (e.target.files && e.target.files.length > 0) {
                showToast('所选文件夹中未找到图片文件');
            }
        });
        
        // 上传图片按钮事件（分批上传，避免 413 REQUEST ENTITY TOO LARGE）
        uploadImagesBtn.addEventListener('click', async function() {
            if (selectedImageFiles.length === 0) {
                showToast('请先选择包含图片的文件夹');
                return;
            }

            const uploadCount = selectedImageFiles.length;
            uploadImagesBtn.disabled = true;

            const resetUploadBtn = () => {
                uploadImagesBtn.innerHTML = '<i class="fas fa-upload"></i> 上传图片到数据集';
                uploadImagesBtn.disabled = false;
            };

            try {
                await uploadImageFilesInBatches(selectedImageFiles, (done, total) => {
                    uploadImagesBtn.innerHTML =
                        `<i class="fas fa-spinner fa-spin"></i> 上传中 ${done}/${total}...`;
                });
                resetUploadBtn();
                showToast(`成功上传 ${uploadCount} 张图片`);
                document.getElementById('datasetModal').style.display = 'none';
                refreshActiveDatasetSelect().then(() => loadImages());
            } catch (error) {
                console.error('上传失败:', error);
                resetUploadBtn();
                const msg = error && error.message === 'REQUEST_ENTITY_TOO_LARGE'
                    ? '单批图片过大，请减少文件夹内图片体积或联系管理员调大上传限制'
                    : (error && error.message) || '上传失败，请重试';
                showToast(msg);
            }
        });
    }
    
    // 视频文件上传
    const selectVideoBtn = document.getElementById('selectVideoBtn');
    const videoInput = document.getElementById('videoInput');
    if (selectVideoBtn && videoInput) {
        selectVideoBtn.addEventListener('click', function() {
            videoInput.click();
        });
        
        videoInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const selectedVideoInfo = document.getElementById('selectedVideoInfo');
                const selectedVideoName = document.getElementById('selectedVideoName');
                selectedVideoName.textContent = file.name;
                selectedVideoInfo.style.display = 'block';
                
                // 启用抽帧按钮
                const extractFramesBtn = document.getElementById('extractFramesBtn');
                if (extractFramesBtn) {
                    extractFramesBtn.disabled = false;
                }
            }
        });
    }
    
    // 视频抽帧按钮
    const extractFramesBtn = document.getElementById('extractFramesBtn');
    const frameIntervalInput = document.getElementById('frameInterval');
    if (extractFramesBtn && videoInput && frameIntervalInput) {
        extractFramesBtn.addEventListener('click', function() {
            const files = videoInput.files;
            if (files.length === 0) {
                showToast('请先选择视频文件');
                return;
            }
            
            // 获取抽帧间隔
            const frameInterval = parseInt(frameIntervalInput.value) || 30;
            
            // 显示上传中状态
            extractFramesBtn.disabled = true;
            extractFramesBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 抽帧中...';
            
            // 创建FormData对象，用于发送视频文件和抽帧间隔
            const formData = new FormData();
            formData.append('video', files[0], files[0].name);
            formData.append('frame_interval', frameInterval);
            
            // 发送真实的视频抽帧请求
            fetch(apiUrl('/api/upload/video'), {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // 重置按钮状态
                extractFramesBtn.innerHTML = '<i class="fas fa-film"></i> 抽帧并添加到数据集';
                extractFramesBtn.disabled = false;
                
                if (data.error) {
                    // 显示错误提示
                    showToast(`抽帧失败: ${data.error}`);
                } else {
                    // 显示成功提示
                    showToast(`成功从视频中提取 ${data.count} 帧图片`);
                    
                    // 关闭模态框
                    document.getElementById('datasetModal').style.display = 'none';
                    
                    // 重新加载图片列表
                    refreshActiveDatasetSelect().then(() => loadImages());
                }
            })
            .catch(error => {
                console.error('抽帧失败:', error);
                
                // 重置按钮状态
                extractFramesBtn.innerHTML = '<i class="fas fa-film"></i> 抽帧并添加到数据集';
                extractFramesBtn.disabled = false;
                
                // 显示错误提示
                showToast('抽帧失败，请重试');
            });
        });
    }
    
    // ImageFolder：服务端数据集根目录绑定
    const importDatasetPathBtn = document.getElementById('importDatasetPathBtn');
    const datasetPathInput = document.getElementById('datasetPathInput');
    if (importDatasetPathBtn && datasetPathInput) {
        importDatasetPathBtn.addEventListener('click', function() {
            const path = (datasetPathInput.value || '').trim();
            if (!path) {
                showToast('请填写数据集目录的绝对路径');
                return;
            }
            importDatasetPathBtn.disabled = true;
            const prevHtml = importDatasetPathBtn.innerHTML;
            importDatasetPathBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 导入中...';
            fetch(apiUrl('/api/import-dataset-path'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path })
            })
            .then(function(response) {
                return response.json().then(function(data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function(result) {
                importDatasetPathBtn.innerHTML = prevHtml;
                importDatasetPathBtn.disabled = false;
                if (!result.ok || result.data.error) {
                    showToast(result.data.error || '导入失败');
                    return;
                }
                const d = result.data;
                const extra = [];
                if (d.images_copied != null) extra.push('图片 ' + d.images_copied + ' 张');
                if (d.labelme_images != null && d.labelme_images > 0) extra.push('LabelMe 标注 ' + d.labelme_images + ' 张');
                if (d.coco_images) extra.push('COCO 标注 ' + d.coco_images + ' 张');
                if (d.yolo_images != null && d.yolo_images > 0) extra.push('YOLO .txt 标注 ' + d.yolo_images + ' 张');
                let msg = 'ImageFolder 导入成功：' + extra.join('，');
                if (d.hint) msg += '（' + d.hint + '）';
                showToast(msg);
                document.getElementById('datasetModal').style.display = 'none';
                datasetPathInput.value = '';
                refreshActiveDatasetSelect().then(() => {
                    loadImages();
                    loadClasses();
                });
            })
            .catch(function(err) {
                console.error('路径导入失败:', err);
                importDatasetPathBtn.innerHTML = prevHtml;
                importDatasetPathBtn.disabled = false;
                showToast('导入失败，请重试');
            });
        });
    }

    const importYoloPathBtn = document.getElementById('importYoloPathBtn');
    const yoloDatasetPathInput = document.getElementById('yoloDatasetPathInput');
    if (importYoloPathBtn && yoloDatasetPathInput) {
        importYoloPathBtn.addEventListener('click', function() {
            const path = (yoloDatasetPathInput.value || '').trim();
            if (!path) {
                showToast('请填写 YOLO 数据集根目录的绝对路径');
                return;
            }
            importYoloPathBtn.disabled = true;
            const prevHtml = importYoloPathBtn.innerHTML;
            importYoloPathBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 导入中...';
            fetch(apiUrl('/api/import-yolo-path'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path })
            })
            .then(function(response) {
                return response.json().then(function(data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function(result) {
                importYoloPathBtn.innerHTML = prevHtml;
                importYoloPathBtn.disabled = false;
                if (!result.ok || result.data.error) {
                    showToast(result.data.error || '导入失败');
                    return;
                }
                const d = result.data;
                const extra = [];
                if (d.images_copied != null) extra.push('图片 ' + d.images_copied + ' 张');
                if (d.yolo_images != null && d.yolo_images > 0) extra.push('含 YOLO 标签的图片 ' + d.yolo_images + ' 张');
                showToast('YOLO 导入成功：' + extra.join('，'));
                document.getElementById('datasetModal').style.display = 'none';
                yoloDatasetPathInput.value = '';
                refreshActiveDatasetSelect().then(() => {
                    loadImages();
                    loadClasses();
                });
            })
            .catch(function(err) {
                console.error('YOLO 路径导入失败:', err);
                importYoloPathBtn.innerHTML = prevHtml;
                importYoloPathBtn.disabled = false;
                showToast('导入失败，请重试');
            });
        });
    }

    const importCocoBtn = document.getElementById('importCocoBtn');
    const cocoJsonPathInput = document.getElementById('cocoJsonPathInput');
    const cocoImagesRootInput = document.getElementById('cocoImagesRootInput');
    if (importCocoBtn && cocoJsonPathInput) {
        importCocoBtn.addEventListener('click', function() {
            const cocoJson = (cocoJsonPathInput.value || '').trim();
            if (!cocoJson) {
                showToast('请填写 COCO instances JSON 的绝对路径');
                return;
            }
            const imagesRoot = cocoImagesRootInput ? (cocoImagesRootInput.value || '').trim() : '';
            importCocoBtn.disabled = true;
            const prevHtml = importCocoBtn.innerHTML;
            importCocoBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 导入中...';
            const body = { coco_json: cocoJson };
            if (imagesRoot) {
                body.images_root = imagesRoot;
            }
            fetch(apiUrl('/api/import-coco-path'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            })
            .then(function(response) {
                return response.json().then(function(data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function(result) {
                importCocoBtn.innerHTML = prevHtml;
                importCocoBtn.disabled = false;
                if (!result.ok || result.data.error) {
                    showToast(result.data.error || '导入失败');
                    return;
                }
                const d = result.data;
                const parts = [];
                if (d.images_copied != null) parts.push('图片 ' + d.images_copied + ' 张');
                if (d.annotation_instances != null) parts.push('标注实例 ' + d.annotation_instances + ' 个');
                showToast('COCO 导入成功：' + parts.join('，'));
                document.getElementById('datasetModal').style.display = 'none';
                cocoJsonPathInput.value = '';
                if (cocoImagesRootInput) cocoImagesRootInput.value = '';
                refreshActiveDatasetSelect().then(() => {
                    loadImages();
                    loadClasses();
                });
            })
            .catch(function(err) {
                console.error('COCO 导入失败:', err);
                importCocoBtn.innerHTML = prevHtml;
                importCocoBtn.disabled = false;
                showToast('导入失败，请重试');
            });
        });
    }

    const cloudImportBtn = document.getElementById('cloudImportBtn');
    if (cloudImportBtn) {
        cloudImportBtn.addEventListener('click', function() {
            const dataset_id = parseInt((document.getElementById('cloudDatasetSelect') || {}).value, 10);
            if (Number.isNaN(dataset_id)) {
                showToast('请选择云平台数据集');
                return;
            }
            const prevHtml = cloudImportBtn.innerHTML;
            cloudImportBtn.disabled = true;
            cloudImportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 导入中...';
            fetch(apiUrl('/api/cloud/import'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ dataset_id }),
            })
                .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
                .then(({ ok, j }) => {
                    if (!ok || j.error) {
                        throw new Error(j.error || '导入失败');
                    }
                    showToast(j.message || '导入成功');
                    document.getElementById('datasetModal').style.display = 'none';
                    return refreshActiveDatasetSelect().then(() => {
                        loadImages();
                        loadClasses();
                    });
                })
                .catch((err) => {
                    console.error(err);
                    showToast(String(err.message || err));
                })
                .finally(() => {
                    cloudImportBtn.innerHTML = prevHtml;
                    cloudImportBtn.disabled = false;
                });
        });
    }

    initModalTabs('datasetModal', {
        onTabChange(tabId) {
            if (tabId === 'cloud') {
                loadCloudDatasetOptions();
            }
        },
    });
    initModalTabs('exportModal');
}

function initModalTabs(modalId, options) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    const tabBtns = modal.querySelectorAll('.tab-btn');
    tabBtns.forEach((btn) => {
        btn.addEventListener('click', function() {
            tabBtns.forEach((b) => b.classList.remove('active'));
            this.classList.add('active');
            modal.querySelectorAll('.tab-pane').forEach((pane) => pane.classList.remove('active'));
            const tabId = this.getAttribute('data-tab');
            const targetTab = document.getElementById(`${tabId}-tab`);
            if (targetTab) {
                targetTab.classList.add('active');
            }
            if (options && typeof options.onTabChange === 'function') {
                options.onTabChange(tabId);
            }
        });
    });
}

// 显示Toast提示
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.style.display = 'block';
    
    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

// 页面卸载前确认
window.addEventListener('beforeunload', function(e) {
    // 如果有未保存的更改，显示确认提示
    // 这里可以根据需要实现
});

// 绘制十字引导线 - 移除直接在主画布上绘制的逻辑，避免重影
function drawCrosshair(e) {
    // 不再直接在画布上绘制十字线，避免重影问题
    // 重绘画布时会清除所有临时绘制
    return;
}

// 切换手风琴折叠状态
function toggleAccordion(header) {
    const item = header.parentElement;
    item.classList.toggle('active');
    const body = item.querySelector('.accordion-body');
    if (item.classList.contains('active')) {
        body.style.display = 'block';
    } else {
        body.style.display = 'none';
    }
}

// ==================== AI标注功能 ====================

// 切换AI标注状态
function toggleAiAnnotate() {
    if (aiAnnotateEnabled) {
        // 关闭AI标注
        disableAiAnnotate();
    } else {
        // 显示AI标注设置模态框
        showAiAnnotateModal();
    }
}

// 显示AI标注模态框
function showAiAnnotateModal() {
    const modal = document.getElementById('aiAnnotateModal');
    modal.style.display = 'block';
    
    // 加载可用模型列表
    loadAiModels();
    
    // 更新批量标注范围信息
    updateBatchRangeInfo();
    
    // 设置默认范围为全部图片
    const totalImages = window.allImages ? window.allImages.length : 0;
    const endInput = document.getElementById('batchEndIndex');
    if (endInput && totalImages > 0) {
        endInput.value = totalImages;
    }
    updateBatchRangeInfo();
}

// 加载AI模型列表
function loadAiModels() {
    const installPath = document.getElementById('yolo11InstallPath')?.value || 'plugins/yolo11';
    const modelSelect = document.getElementById('aiModelSelect');
    
    modelSelect.innerHTML = '<option value="">-- 加载中... --</option>';
    
    fetch(apiUrl(`/api/list-models?install_path=${encodeURIComponent(installPath)}`))
        .then(response => response.json())
        .then(data => {
            modelSelect.innerHTML = '<option value="">-- 请选择模型 --</option>';
            if (data.models && data.models.length > 0) {
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.textContent = model;
                    modelSelect.appendChild(option);
                });
                
                // 如果之前选择过模型，恢复选择
                if (aiAnnotateModel) {
                    modelSelect.value = aiAnnotateModel;
                }
            } else {
                modelSelect.innerHTML = '<option value="">-- 无可用模型，请先安装 --</option>';
            }
        })
        .catch(error => {
            console.error('加载模型列表失败:', error);
            modelSelect.innerHTML = '<option value="">-- 加载失败 --</option>';
        });
}

// 设置AI标注事件
function setupAiAnnotateEvents() {
    // 置信度滑块
    const confidenceSlider = document.getElementById('aiConfidence');
    const confidenceValue = document.getElementById('aiConfidenceValue');
    if (confidenceSlider && confidenceValue) {
        confidenceSlider.addEventListener('input', function() {
            confidenceValue.textContent = this.value;
        });
    }
    
    // AI标注表单提交
    const aiForm = document.getElementById('aiAnnotateForm');
    if (aiForm) {
        aiForm.addEventListener('submit', function(e) {
            e.preventDefault();
            enableAiAnnotate();
        });
    }
    
    // 取消按钮
    const cancelBtn = document.getElementById('aiAnnotateCancelBtn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            document.getElementById('aiAnnotateModal').style.display = 'none';
        });
    }
    
    // 批量标注按钮
    const batchBtn = document.getElementById('aiBatchAnnotateBtn');
    if (batchBtn) {
        batchBtn.addEventListener('click', function() {
            startBatchAnnotate();
        });
    }
    
    // 批量标注取消按钮
    const batchCancelBtn = document.getElementById('batchCancelBtn');
    if (batchCancelBtn) {
        batchCancelBtn.addEventListener('click', function() {
            cancelBatchAnnotate();
        });
    }
    
    // 批量标注范围输入框事件
    const startIndexInput = document.getElementById('batchStartIndex');
    const endIndexInput = document.getElementById('batchEndIndex');
    if (startIndexInput) {
        startIndexInput.addEventListener('input', updateBatchRangeInfo);
    }
    if (endIndexInput) {
        endIndexInput.addEventListener('input', updateBatchRangeInfo);
    }
}

// 开启AI标注
function enableAiAnnotate() {
    const modelSelect = document.getElementById('aiModelSelect');
    const confidenceSlider = document.getElementById('aiConfidence');
    const autoNextCheckbox = document.getElementById('aiAutoNext');
    
    if (!modelSelect.value) {
        showToast('请选择一个模型');
        return;
    }
    
    // 保存设置
    aiAnnotateModel = modelSelect.value;
    aiAnnotateConfidence = parseFloat(confidenceSlider.value);
    aiAutoNext = autoNextCheckbox.checked;
    aiAnnotateEnabled = true;
    
    // 关闭模态框
    document.getElementById('aiAnnotateModal').style.display = 'none';
    
    // 更新按钮状态
    updateAiAnnotateButton();
    
    // 显示状态栏
    showAiStatusBar();
    
    showToast(`AI标注已开启，模型: ${aiAnnotateModel}`);
    
    // 如果当前有图片，立即进行AI标注
    if (currentImage) {
        performAiAnnotate();
    }
}

// 关闭AI标注
function disableAiAnnotate() {
    aiAnnotateEnabled = false;
    
    // 更新按钮状态
    updateAiAnnotateButton();
    
    // 隐藏状态栏
    hideAiStatusBar();
    
    showToast('AI标注已关闭');
}

// 更新AI标注按钮状态
function updateAiAnnotateButton() {
    const btn = document.getElementById('aiAnnotateToggle');
    if (aiAnnotateEnabled) {
        btn.classList.add('ai-active');
        btn.innerHTML = '<i class="fas fa-robot"></i> AI标注中';
        btn.style.backgroundColor = '#28a745';
        btn.style.borderColor = '#28a745';
    } else {
        btn.classList.remove('ai-active');
        btn.innerHTML = '<i class="fas fa-robot"></i> AI标注';
        btn.style.backgroundColor = '';
        btn.style.borderColor = '';
    }
}

// 显示AI状态栏 - 在导航栏内显示
function showAiStatusBar() {
    // 检查是否已存在状态信息
    let statusInfo = document.getElementById('aiStatusInfo');
    if (!statusInfo) {
        statusInfo = document.createElement('span');
        statusInfo.id = 'aiStatusInfo';
        statusInfo.className = 'ai-status-info';
        
        // 插入到导航栏logo后面
        const logo = document.querySelector('.logo');
        if (logo) {
            logo.parentNode.insertBefore(statusInfo, logo.nextSibling);
        }
    }
    
    statusInfo.innerHTML = `<i class="fas fa-robot"></i> ${aiAnnotateModel} | 阈值:${aiAnnotateConfidence}`;
    statusInfo.style.display = 'inline-flex';
}

// 隐藏AI状态栏
function hideAiStatusBar() {
    const statusInfo = document.getElementById('aiStatusInfo');
    if (statusInfo) {
        statusInfo.style.display = 'none';
    }
}

// 执行AI标注
function performAiAnnotate() {
    if (!aiAnnotateEnabled || !currentImage || aiAnnotating) {
        return;
    }
    
    aiAnnotating = true;
    showToast('正在进行AI标注...');
    
    const installPath = document.getElementById('yolo11InstallPath')?.value || 'plugins/yolo11';
    
    fetch(apiUrl('/api/ai-annotate'), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            image_name: currentImage,
            model_name: aiAnnotateModel,
            confidence: aiAnnotateConfidence,
            install_path: installPath
        })
    })
    .then(response => response.json())
    .then(data => {
        aiAnnotating = false;
        
        if (data.error) {
            showToast(`AI标注失败: ${data.error}`);
            return;
        }
        
        if (data.annotations && data.annotations.length > 0) {
            // 将AI标注结果添加到当前标注
            data.annotations.forEach(ann => {
                // 生成唯一ID
                ann.id = Date.now() + Math.floor(Math.random() * 1000);
                currentAnnotations.push(ann);
            });
            
            updateAnnotationListDebounced();
            redrawCanvas();
            
            showToast(`AI标注完成，检测到 ${data.annotations.length} 个目标`);
            
            // 如果有新类别被添加，刷新类别列表
            if (data.new_classes_added) {
                loadClasses();
            }
        } else {
            showToast('AI标注完成，未检测到目标');
        }
    })
    .catch(error => {
        aiAnnotating = false;
        console.error('AI标注失败:', error);
        showToast('AI标注失败: ' + error.message);
    });
}

// 切换到下一张图片
function goToNextImage() {
    if (!window.allImages || window.allImages.length === 0) return;
    
    const currentIndex = window.allImages.findIndex(img => img.name === currentImage);
    if (currentIndex === -1) return;
    
    const nextIndex = currentIndex + 1;
    if (nextIndex < window.allImages.length) {
        selectImage(window.allImages[nextIndex].name);
    } else {
        showToast('已经是最后一张图片');
    }
}


// ==================== 批量AI标注功能 ====================

// 批量标注状态
let batchAnnotateRunning = false;
let batchAnnotateCancelled = false;

// 更新批量标注范围信息
function updateBatchRangeInfo() {
    const totalImages = window.allImages ? window.allImages.length : 0;
    const startInput = document.getElementById('batchStartIndex');
    const endInput = document.getElementById('batchEndIndex');
    const infoText = document.getElementById('batchRangeInfo');
    
    if (startInput && endInput && infoText) {
        // 设置最大值
        startInput.max = totalImages;
        endInput.max = totalImages;
        
        // 如果结束值大于总数，调整为总数
        if (parseInt(endInput.value) > totalImages) {
            endInput.value = totalImages;
        }
        
        const start = parseInt(startInput.value) || 1;
        const end = parseInt(endInput.value) || totalImages;
        const rangeCount = Math.max(0, end - start + 1);
        
        infoText.textContent = `共 ${totalImages} 张图片，当前选择范围: ${start}-${end} (${rangeCount}张)`;
    }
}

// 开始批量标注 - 使用新的批量API
async function startBatchAnnotate() {
    const modelSelect = document.getElementById('aiModelSelect');
    const confidenceSlider = document.getElementById('aiConfidence');
    const skipAnnotatedCheckbox = document.getElementById('aiSkipAnnotated');
    const batchSizeSelect = document.getElementById('batchSize');
    const startIndexInput = document.getElementById('batchStartIndex');
    const endIndexInput = document.getElementById('batchEndIndex');
    
    if (!modelSelect.value) {
        showToast('请选择一个模型');
        return;
    }
    
    if (!window.allImages || window.allImages.length === 0) {
        showToast('没有图片可以标注');
        return;
    }
    
    // 获取设置
    const model = modelSelect.value;
    const confidence = parseFloat(confidenceSlider.value);
    const skipAnnotated = skipAnnotatedCheckbox ? skipAnnotatedCheckbox.checked : false;
    const batchSize = parseInt(batchSizeSelect?.value || '10');
    const installPath = document.getElementById('yolo11InstallPath')?.value || 'plugins/yolo11';
    
    // 获取区间范围
    const startIndex = Math.max(1, parseInt(startIndexInput?.value || '1'));
    const endIndex = Math.min(window.allImages.length, parseInt(endIndexInput?.value || window.allImages.length));
    
    if (startIndex > endIndex) {
        showToast('起始位置不能大于结束位置');
        return;
    }
    
    // 获取指定范围内的图片
    let imagesToAnnotate = window.allImages.slice(startIndex - 1, endIndex);
    
    // 过滤已标注的图片
    if (skipAnnotated) {
        imagesToAnnotate = imagesToAnnotate.filter(img => img.annotation_count === 0);
    }
    
    if (imagesToAnnotate.length === 0) {
        showToast('选定范围内没有需要标注的图片');
        return;
    }
    
    // 显示进度条
    const progressDiv = document.getElementById('batchAnnotateProgress');
    const progressText = document.getElementById('batchProgressText');
    const progressBar = document.getElementById('batchProgressBar');
    const resultText = document.getElementById('batchResultText');
    
    progressDiv.style.display = 'block';
    progressBar.style.width = '0%';
    resultText.innerHTML = '';
    
    // 禁用按钮
    document.getElementById('aiBatchAnnotateBtn').disabled = true;
    document.getElementById('aiAnnotateStartBtn').disabled = true;
    
    batchAnnotateRunning = true;
    batchAnnotateCancelled = false;
    
    let successCount = 0;
    let failCount = 0;
    let totalDetected = 0;
    const total = imagesToAnnotate.length;
    
    showToast(`开始批量标注 ${total} 张图片，每批 ${batchSize} 张...`);
    
    // 分批处理
    const batches = [];
    for (let i = 0; i < imagesToAnnotate.length; i += batchSize) {
        batches.push(imagesToAnnotate.slice(i, i + batchSize));
    }
    
    let processedCount = 0;
    
    for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
        if (batchAnnotateCancelled) {
            resultText.innerHTML += `<div style="color: orange;">已取消，共处理 ${processedCount} 张图片</div>`;
            break;
        }
        
        const batch = batches[batchIndex];
        const batchImageNames = batch.map(img => img.name);
        
        progressText.textContent = `正在处理第 ${batchIndex + 1}/${batches.length} 批 (${processedCount + 1}-${processedCount + batch.length}/${total})`;
        progressBar.style.width = `${((processedCount + batch.length) / total) * 100}%`;
        
        try {
            // 使用批量API
            const response = await fetch(apiUrl('/api/ai-annotate-batch'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    image_names: batchImageNames,
                    model_name: model,
                    confidence: confidence,
                    install_path: installPath
                })
            });
            
            const data = await response.json();
            
            if (data.error) {
                failCount += batch.length;
                resultText.innerHTML += `<div style="color: red;">✗ 批次 ${batchIndex + 1} 失败: ${data.error}</div>`;
            } else if (data.results) {
                // 处理每张图片的结果
                for (const result of data.results) {
                    if (result.success) {
                        if (result.count > 0) {
                            successCount++;
                            totalDetected += result.count;
                            resultText.innerHTML += `<div style="color: green;">✓ ${result.image_name}: ${result.count} 个目标</div>`;
                        } else {
                            resultText.innerHTML += `<div style="color: gray;">○ ${result.image_name}: 无目标</div>`;
                        }
                    } else {
                        failCount++;
                        resultText.innerHTML += `<div style="color: red;">✗ ${result.image_name}: 失败</div>`;
                    }
                }
            }
            
            // 滚动到底部
            resultText.scrollTop = resultText.scrollHeight;
            
        } catch (error) {
            failCount += batch.length;
            resultText.innerHTML += `<div style="color: red;">✗ 批次 ${batchIndex + 1} 错误: ${error.message}</div>`;
        }
        
        processedCount += batch.length;
    }
    
    // 完成
    batchAnnotateRunning = false;
    progressText.textContent = `完成: 处理 ${processedCount} 张，检测到 ${totalDetected} 个目标`;
    progressBar.style.width = '100%';
    
    // 恢复按钮
    document.getElementById('aiBatchAnnotateBtn').disabled = false;
    document.getElementById('aiAnnotateStartBtn').disabled = false;
    
    // 刷新图片列表和类别
    loadImages();
    loadClasses();
    
    showToast(`批量标注完成！处理 ${processedCount} 张图片，检测到 ${totalDetected} 个目标`);
}

// 取消批量标注
function cancelBatchAnnotate() {
    if (batchAnnotateRunning) {
        batchAnnotateCancelled = true;
        showToast('正在取消批量标注...');
    }
}
