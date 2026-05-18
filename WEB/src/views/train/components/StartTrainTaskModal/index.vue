<template>
  <BasicModal
    @register="registerModal"
    title="训练参数配置"
    @cancel="handleCancel"
    :width="700"
    :canFullscreen="false"
  >
    <div class="modal-content">
      <div class="param-section">
        <h4 class="section-title">任务信息</h4>
        <div class="param-group">
          <label>任务名称</label>
          <input
            type="text"
            v-model="taskName"
            class="param-input"
            placeholder="请输入训练任务名称"
          />
        </div>
      </div>

      <div class="param-section">
        <h4 class="section-title">基础参数配置</h4>
        <div class="param-group">
          <label>迭代次数 (epochs)</label>
          <input type="number" v-model="params.epochs" min="10" max="1000" class="param-input"/>
          <span class="hint">推荐值: 100-300</span>
        </div>

        <div class="param-group">
          <label>批量大小 (batch_size)</label>
          <input type="number" v-model="params.batch_size" min="1" :max="maxBatchSize" class="param-input"/>
          <span class="hint">根据显存调整</span>
        </div>

        <div class="param-group">
          <label>图像尺寸 (imgsz)</label>
          <input type="number" v-model="params.imgsz" class="param-input"/>
          <span class="hint">默认640px</span>
        </div>
      </div>

      <div class="resource-selector">
        <h4 class="section-title">资源选择</h4>

        <div class="param-group">
          <label>预训练权重</label>
          <select v-model="selectedModel" class="resource-select">
            <option v-for="preset in presetModels" :key="preset" :value="preset">
              {{ preset }}
            </option>
          </select>
        </div>
        <div class="param-group">
          <label>数据集配置</label>
          <select v-model="selectedDatasetId" class="resource-select">
            <option v-for="dataset in datasetList" :key="dataset.id" :value="dataset.id">
              {{ dataset.name }}（{{ dataset.version || '—' }}）
            </option>
          </select>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="modal-footer">
        <a-button @click="handleCancel">取消</a-button>
        <a-button type="primary" @click="startTrain">开始训练</a-button>
      </div>
    </template>
  </BasicModal>
</template>

<script lang="ts" setup>
import {reactive, ref} from 'vue';
import {BasicModal, useModalInner} from '@/components/Modal';
import {getDatasetPage} from '@/api/device/dataset';
import {useMessage} from '@/hooks/web/useMessage';

interface DatasetItem {
  id: string | number;
  name: string;
  version: string;
  zipUrl: string;
}

const presetModels = [
  'yolov8n.pt',
  'yolov8s.pt',
  'yolov8m.pt',
  'yolov8l.pt',
  'yolov8x.pt',
  'yolo11n.pt',
  'yolo11s.pt',
];

const {createMessage} = useMessage();

const [registerModal, {closeModal}] = useModalInner(() => {
  loadDatasets();
  taskName.value = '';
  selectedModel.value = presetModels[0];
});

const params = reactive({
  epochs: 100,
  batch_size: 16,
  imgsz: 640,
});

const taskName = ref('');
const datasetList = ref<DatasetItem[]>([]);
const selectedModel = ref(presetModels[0]);
const selectedDatasetId = ref<string | number>('');
const maxBatchSize = ref(64);

const emit = defineEmits(['success']);

const loadDatasets = async () => {
  try {
    const res = await getDatasetPage({page: 1, size: 100});
    datasetList.value = res.data?.list || res.data || [];
    if (datasetList.value.length) {
      selectedDatasetId.value = datasetList.value[0].id;
    }
  } catch (e) {
    createMessage.error('加载数据集失败');
    console.error(e);
  }
};

const startTrain = () => {
  if (!taskName.value.trim()) {
    createMessage.warn('请输入训练任务名称');
    return;
  }
  const dataset = datasetList.value.find((item) => item.id === selectedDatasetId.value);
  if (!dataset?.zipUrl) {
    createMessage.warn('请先选择数据集');
    return;
  }
  emit('success', {
    ...params,
    taskName: taskName.value.trim(),
    modelPath: selectedModel.value,
    datasetPath: dataset.zipUrl,
    datasetName: dataset.name,
    datasetVersion: dataset.version || '',
  });
  closeModal();
};

const handleCancel = () => closeModal();
</script>

<style scoped>
.modal-content {
  padding: 25px;
  background: #ffffff;
}

.section-title {
  font-size: 1.2rem;
  font-weight: 600;
  color: #2c3e50;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(to right, #3498db, #2c3e50) 1;
}

.param-group {
  display: grid;
  grid-template-columns: 160px 1fr auto;
  align-items: center;
  margin-bottom: 15px;
  gap: 12px;
}

.param-input,
.resource-select {
  padding: 10px 14px;
  border: 1px solid #dce1e6;
  border-radius: 8px;
  background: #f8fafc;
}

.param-input:focus,
.resource-select:focus {
  border-color: #3498db;
  background: white;
}

@media (max-width: 768px) {
  .param-group {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}
</style>
