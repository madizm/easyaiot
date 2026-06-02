<template>
  <BasicModal
    @register="registerModal"
    title="训练参数配置"
    @cancel="handleCancel"
    :width="700"
    :canFullscreen="false"
    :showOkBtn="false"
    :showCancelBtn="false"
    :minHeight="200"
    wrapClassName="train-task-config-modal"
    :bodyStyle="{ padding: 0 }"
    destroyOnClose
    :footerOffset="0"
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
        <div class="basic-params-row">
          <div class="basic-param-item">
            <label>迭代次数 (epochs)</label>
            <input type="number" v-model="params.epochs" min="10" max="1000" class="param-input"/>
            <span class="hint">推荐 100-300</span>
          </div>
          <div class="basic-param-item">
            <label>批量大小 (batch_size)</label>
            <input type="number" v-model="params.batch_size" min="1" :max="maxBatchSize" class="param-input"/>
            <span class="hint">按显存调整</span>
          </div>
          <div class="basic-param-item">
            <label>图像尺寸 (imgsz)</label>
            <input type="number" v-model="params.imgsz" class="param-input"/>
            <span class="hint">默认 640</span>
          </div>
        </div>
      </div>

      <div class="param-section">
        <h4 class="section-title">GPU 配置</h4>
        <div class="param-group gpu-toggle-row">
          <label>使用 GPU 训练</label>
          <div class="gpu-toggle-inline">
            <a-switch v-model:checked="useGpu"/>
            <span class="hint" v-if="gpuLoading">正在探测 GPU...</span>
            <span class="hint" v-else-if="!useGpu">将使用 CPU 训练</span>
            <span class="hint" v-else-if="gpuStatus.multi_gpu">
              已探测 {{ gpuStatus.visible_gpu_ids.length }} 张 GPU，将自动多卡并行 (DDP)
            </span>
            <span class="hint" v-else-if="gpuStatus.visible_gpu_ids.length === 1">
              单卡: {{ gpuDeviceLabel }}
            </span>
            <span class="hint warn" v-else>未检测到可用 GPU，将回退 CPU</span>
          </div>
        </div>
        <ul v-if="gpuStatus.devices?.length" class="gpu-device-list">
          <li v-for="dev in gpuStatus.devices" :key="dev.index">
            GPU {{ dev.index }}: {{ dev.name }} ({{ dev.total_memory_gb }} GB)
          </li>
        </ul>
      </div>

      <div class="param-section">
        <h4 class="section-title">资源选择</h4>

        <div class="param-group">
          <label>预训练权重</label>
          <select v-model="selectedModel" class="resource-select">
            <option v-for="preset in presetModels" :key="preset" :value="preset">
              {{ preset }}
            </option>
          </select>
          <span class="hint hint-placeholder" aria-hidden="true">&nbsp;</span>
        </div>

      </div>

      <div class="param-section dataset-section">
        <h4 class="section-title">数据集配置</h4>
        <Tabs
          v-model:activeKey="datasetSourceTab"
          type="card"
          class="dataset-tabs"
          :destroyInactiveTabPane="false"
          @change="onDatasetTabChange"
        >
          <TabPane key="local" tab="本地上传">
            <div class="dataset-tab-pane">
              <Alert
                type="info"
                show-icon
                banner
                class="dataset-alert"
                message="上传 YOLO 格式数据集 ZIP 压缩包，单文件最大 5GB，无需在云端预先创建数据集"
              />
              <Upload
                accept=".zip"
                :file-list="localFileList"
                :show-upload-list="true"
                :max-count="1"
                :before-upload="beforeLocalDatasetUpload"
                @remove="handleLocalFileRemove"
              >
                <a-button type="primary">
                  {{ localFileList?.length ? '重新选择压缩包' : '上传数据集压缩包' }}
                </a-button>
              </Upload>
              <span class="dataset-upload-tip">仅支持 .zip 格式，单文件最大 5GB</span>
            </div>
          </TabPane>
          <TabPane key="cloud" tab="云端数据集">
            <div class="dataset-tab-pane">
              <Alert
                type="info"
                show-icon
                banner
                class="dataset-alert"
                message="请先在数据集管理中完成：标注 → 划分用途 → 同步到 Minio，方可用于训练"
              />
              <Select
                v-model:value="selectedDatasetId"
                class="dataset-select"
                placeholder="请选择已同步到 Minio 的云端数据集"
                :loading="cloudDatasetLoading"
                :options="cloudDatasetOptions"
                allow-clear
                show-search
                :filter-option="filterCloudDataset"
              />
              <p v-if="selectedCloudDataset && !selectedCloudDataset.zipUrl" class="dataset-hint-warn">
                该数据集尚未同步到 Minio：请进入数据集详情，先「划分用途」再「一键同步到 Minio」。
              </p>
              <Empty
                v-if="!cloudDatasetLoading && !cloudDatasetOptions.length"
                class="dataset-empty"
                description="暂无云端数据集，请先在数据集管理中创建"
              />
            </div>
          </TabPane>
        </Tabs>
      </div>
    </div>
    <template #footer>
      <div class="modal-footer">
        <a-button @click="handleCancel">取消</a-button>
        <a-button type="primary" :loading="uploading" @click="startTrain">开始训练</a-button>
      </div>
    </template>
  </BasicModal>
</template>

<script lang="ts" setup>
import {computed, nextTick, reactive, ref} from 'vue';
import type {UploadProps} from 'ant-design-vue';
import {Alert, Empty, Select, TabPane, Tabs, Upload} from 'ant-design-vue';
import {BasicModal, useModalInner} from '@/components/Modal';
import {getDatasetPage} from '@/api/device/dataset';
import {getTrainGpuStatus, uploadTrainDataset} from '@/api/device/train';
import {useMessage} from '@/hooks/web/useMessage';

interface GpuDeviceInfo {
  index: number;
  name: string;
  total_memory_gb: number;
}

interface GpuStatusData {
  cuda_available: boolean;
  visible_gpu_ids: number[];
  multi_gpu: boolean;
  devices: GpuDeviceInfo[];
}

interface DatasetItem {
  id: string | number;
  name: string;
  version: string;
  zipUrl?: string;
  isAllocated?: number;
  isSyncMinio?: number;
  totalImages?: number;
  annotatedImages?: number;
}

type DatasetSourceTab = 'local' | 'cloud';

const presetModels = [
  'yolov8n.pt',
  'yolov8s.pt',
  'yolov8m.pt',
  'yolov8l.pt',
  'yolov8x.pt',
  'yolo11n.pt',
  'yolo11s.pt',
  'yolo26n.pt',
  'yolo26s.pt',
];

const {createMessage} = useMessage();

const defaultGpuStatus = (): GpuStatusData => ({
  cuda_available: false,
  visible_gpu_ids: [],
  multi_gpu: false,
  devices: [],
});

const useGpu = ref(true);
const gpuLoading = ref(false);
const gpuStatus = ref<GpuStatusData>(defaultGpuStatus());
const uploading = ref(false);

const datasetSourceTab = ref<DatasetSourceTab>('local');
const cloudDatasetsLoaded = ref(false);
const cloudDatasetLoading = ref(false);
const localDatasetFile = ref<File | null>(null);
const localDatasetPath = ref('');
const localDatasetDisplayName = ref('');
const localFileList = ref<UploadProps['fileList']>([]);

const gpuDeviceLabel = computed(() => {
  const dev = gpuStatus.value.devices?.[0];
  if (!dev) return 'GPU 0';
  return `${dev.name} (${dev.total_memory_gb} GB)`;
});

const loadGpuStatus = async () => {
  gpuLoading.value = true;
  try {
    const res = await getTrainGpuStatus();
    const data = (res?.data ?? res) as GpuStatusData;
    gpuStatus.value = {
      cuda_available: !!data?.cuda_available,
      visible_gpu_ids: data?.visible_gpu_ids ?? [],
      multi_gpu: !!data?.multi_gpu,
      devices: data?.devices ?? [],
    };
    useGpu.value = gpuStatus.value.visible_gpu_ids.length > 0;
  } catch (e) {
    gpuStatus.value = defaultGpuStatus();
    useGpu.value = false;
    console.error(e);
  } finally {
    gpuLoading.value = false;
  }
};

const resetDatasetSelection = () => {
  localDatasetFile.value = null;
  localDatasetPath.value = '';
  localDatasetDisplayName.value = '';
  localFileList.value = [];
  selectedDatasetId.value = undefined;
};

const onDatasetTabChange = (key: string | number) => {
  resetDatasetSelection();
  if (key === 'cloud' && !cloudDatasetsLoaded.value) {
    loadDatasets().finally(() => {
      cloudDatasetsLoaded.value = true;
      nextTick(() => redoModalHeight());
    });
    return;
  }
  nextTick(() => redoModalHeight());
};

const [registerModal, {closeModal, redoModalHeight}] = useModalInner(() => {
  taskName.value = '';
  selectedModel.value = presetModels[0];
  datasetSourceTab.value = 'local';
  cloudDatasetsLoaded.value = false;
  datasetList.value = [];
  resetDatasetSelection();
  loadGpuStatus().finally(() => {
    nextTick(() => redoModalHeight());
  });
});

const params = reactive({
  epochs: 100,
  batch_size: 16,
  imgsz: 640,
});

const taskName = ref('');
const datasetList = ref<DatasetItem[]>([]);
const selectedModel = ref(presetModels[0]);
const selectedDatasetId = ref<string | number | undefined>(undefined);
const maxBatchSize = ref(64);

const selectedCloudDataset = computed(() =>
  datasetList.value.find((item) => item.id === selectedDatasetId.value),
);

const cloudDatasetOptions = computed(() =>
  datasetList.value.map((item) => {
    const trainable = !!item.zipUrl;
    const statusHint = trainable
      ? '可用于训练'
      : item.isAllocated === 1
        ? '待同步 Minio'
        : (item.annotatedImages ?? 0) >= (item.totalImages ?? 0) && (item.totalImages ?? 0) > 0
          ? '待划分用途'
          : '未完成标注/同步';
    return {
      label: `${item.name}（${item.version || '—'}）— ${statusHint}`,
      value: item.id,
      disabled: !trainable,
    };
  }),
);

const filterCloudDataset = (input: string, option?: { label?: string }) =>
  (option?.label ?? '').toLowerCase().includes(input.toLowerCase());

const emit = defineEmits(['success']);

const loadDatasets = async () => {
  cloudDatasetLoading.value = true;
  try {
    const res = await getDatasetPage({page: 1, size: 100});
    datasetList.value = res.data?.list || res.data || [];
  } catch (e) {
    createMessage.error('加载云端数据集失败');
    console.error(e);
  } finally {
    cloudDatasetLoading.value = false;
  }
};

const beforeLocalDatasetUpload: UploadProps['beforeUpload'] = (file) => {
  const isZip = file.name.toLowerCase().endsWith('.zip');
  if (!isZip) {
    createMessage.warn('请选择 ZIP 格式的数据集压缩包');
    return false;
  }
  const maxSize = 5 * 1024 * 1024 * 1024;
  if (file.size > maxSize) {
    createMessage.warn('数据集压缩包不能超过 5GB');
    return false;
  }
  localDatasetFile.value = file;
  localDatasetPath.value = '';
  localDatasetDisplayName.value = file.name;
  localFileList.value = [{uid: '-1', name: file.name, status: 'done'}];
  return false;
};

const handleLocalFileRemove = () => {
  localDatasetFile.value = null;
  localDatasetPath.value = '';
  localDatasetDisplayName.value = '';
  localFileList.value = [];
};

const uploadLocalDatasetIfNeeded = async (): Promise<string | null> => {
  if (localDatasetPath.value) {
    return localDatasetPath.value;
  }
  if (!localDatasetFile.value) {
    return null;
  }
  const formData = new FormData();
  formData.append('file', localDatasetFile.value);
  const res = await uploadTrainDataset(formData);
  const payload = (res as { path?: string; fileName?: string; data?: { path?: string; fileName?: string } }) ?? {};
  const path = payload.path ?? payload.data?.path;
  if (!path) {
    throw new Error('数据集上传失败');
  }
  localDatasetPath.value = path;
  const fileName = payload.fileName ?? payload.data?.fileName;
  if (fileName) {
    localDatasetDisplayName.value = fileName;
  }
  return path;
};

const startTrain = async () => {
  if (!taskName.value.trim()) {
    createMessage.warn('请输入训练任务名称');
    return;
  }

  let datasetPath = '';
  let datasetName = '';
  let datasetVersion = '';
  const datasetSource = datasetSourceTab.value;

  if (datasetSource === 'local') {
    if (!localDatasetFile.value && !localDatasetPath.value) {
      createMessage.warn('请选择本地数据集 ZIP 压缩包');
      return;
    }
    uploading.value = true;
    try {
      const path = await uploadLocalDatasetIfNeeded();
      if (!path) {
        createMessage.warn('本地数据集上传失败，请重试');
        return;
      }
      datasetPath = path;
      datasetName = (localDatasetDisplayName.value || '本地数据集').replace(/\.zip$/i, '');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '本地数据集上传失败';
      createMessage.error(msg);
      return;
    } finally {
      uploading.value = false;
    }
  } else {
    if (!selectedDatasetId.value) {
      createMessage.warn('请选择云端数据集');
      return;
    }
    const dataset = datasetList.value.find((item) => item.id === selectedDatasetId.value);
    if (!dataset) {
      createMessage.warn('请选择云端数据集');
      return;
    }
    if (!dataset.zipUrl) {
      if (dataset.isAllocated !== 1) {
        createMessage.warn('该数据集尚未划分用途，请先在数据集管理中点击「按比例划分数据集用途」');
      } else if (dataset.isSyncMinio !== 1) {
        createMessage.warn('该数据集尚未同步到 Minio，请先在数据集管理中点击「一键同步到 Minio」');
      } else {
        createMessage.warn('该数据集训练包尚未就绪，请完成划分用途并同步到 Minio 后再训练');
      }
      return;
    }
    datasetPath = dataset.zipUrl;
    datasetName = dataset.name;
    datasetVersion = dataset.version || '';
  }

  emit('success', {
    ...params,
    taskName: taskName.value.trim(),
    modelPath: selectedModel.value,
    datasetSource,
    datasetPath,
    datasetName,
    datasetVersion,
    use_gpu: useGpu.value,
    gpu_ids: useGpu.value && gpuStatus.value.visible_gpu_ids.length
      ? gpuStatus.value.visible_gpu_ids
      : undefined,
  });
  closeModal();
};

const handleCancel = () => closeModal();
</script>

<style lang="less" scoped>
.modal-content {
  padding: 20px 25px 8px;
  background: #ffffff;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.section-title {
  font-size: 1.2rem;
  font-weight: 600;
  color: #2c3e50;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #e8eef3;
}

.hint-placeholder {
  visibility: hidden;
}

.param-group {
  display: grid;
  grid-template-columns: 160px 1fr auto;
  align-items: start;
  margin-bottom: 15px;
  gap: 12px;
}

.basic-params-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.basic-param-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;

  label {
    font-size: 13px;
    font-weight: 500;
    color: #5a6c7d;
    line-height: 1.4;
  }

  .param-input {
    width: 100%;
    box-sizing: border-box;
  }

  .hint {
    font-size: 12px;
    color: #8a9aaa;
    line-height: 1.3;
  }
}

.dataset-section .section-title {
  margin-bottom: 12px;
}

.dataset-tabs {
  :deep(.ant-tabs-nav) {
    margin-bottom: 0;
  }

  :deep(.ant-tabs-content-holder) {
    border: 1px solid #f0f0f0;
    border-top: none;
    border-radius: 0 0 8px 8px;
    background: #fafafa;
  }
}

.dataset-tab-pane {
  padding: 12px 16px 16px;
}

.dataset-alert {
  margin-bottom: 12px;
}

.dataset-upload-tip {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: #8a9aaa;
  line-height: 1.4;
}

.dataset-select {
  width: 100%;
}

.dataset-empty {
  margin-top: 24px;
}

.dataset-hint-warn {
  margin: 8px 0 0;
  font-size: 12px;
  color: #e67e22;
  line-height: 1.5;
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

.gpu-toggle-row {
  grid-template-columns: 160px 1fr;
  align-items: center;
}

.gpu-toggle-inline {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
  min-width: 0;
}

.gpu-toggle-inline .hint {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
  color: #5a6c7d;
  font-size: 13px;
}

.gpu-device-list {
  margin: 0 0 16px 172px;
  padding: 0;
  list-style: none;
  font-size: 13px;
  color: #5a6c7d;
}

.gpu-device-list li {
  padding: 4px 0;
}

.hint.warn {
  color: #e67e22;
}

@media (max-width: 768px) {
  .param-group {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .basic-params-row {
    grid-template-columns: 1fr;
  }
}
</style>

<style lang="less">
.train-task-config-modal {
  .scroll-container .scrollbar__wrap {
    margin-bottom: 0 !important;
  }

  .ant-modal-body {
    padding: 0;
    background: #fff;
  }
}
</style>
