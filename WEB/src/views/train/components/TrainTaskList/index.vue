<template>
  <div id="train-task-list" class="train-container bg-white p-6 rounded-xl shadow-lg transition-all duration-300">
    <!-- 表格模式 -->
    <BasicTable
      v-if="viewMode === 'table'"
      @register="registerTable"
      class="rounded-xl overflow-hidden border border-gray-100 shadow-sm"
    >
      <template #toolbar>
        <div class="toolbar-buttons">
          <a-button type="primary" @click="openAddModal(true, {isEdit: false, isView: false})">
            <Icon icon="ant-design:plus-circle-outlined"/>
            启动新训练
          </a-button>
          <a-button type="default" @click="handleToggleViewMode">
            <template #icon>
              <SwapOutlined />
            </template>
            切换视图
          </a-button>
        </div>
      </template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.dataIndex === 'action'">
          <TableAction
            :actions="getTableActions(record)"
            :action-style="{
              display: 'flex',
              flexWrap: 'nowrap',
              gap: '4px',
              alignItems: 'center',
              marginRight: '0'
            }"
          />
        </template>
      </template>
    </BasicTable>

    <!-- 卡片模式 -->
    <div v-else>
      <TrainTaskCardList
        :params="params"
        :api="getTrainTaskListApi"
        @get-method="getMethod"
        @view-logs="handleOpenTrainLogsModal"
        @view-results="handleViewTrainResults"
        @download="handleDownloadWeights"
        @delete="handleCardDelete"
      >
        <template #header>
          <a-button type="primary" @click="openAddModal(true, {isEdit: false, isView: false})">
            <Icon icon="ant-design:plus-circle-outlined"/>
            启动新训练
          </a-button>
          <a-button type="default" @click="handleToggleViewMode">
            <template #icon>
              <SwapOutlined />
            </template>
            切换视图
          </a-button>
        </template>
      </TrainTaskCardList>
    </div>

    <StartTrainModal @register="registerAddModel" @success="handleStartTrain"/>
    <TrainLogsModal
      v-if="showLogsModal"
      @register="registerTrainLogsModal"
      @success="handleSuccess"
      @close="handleLogsModalClose"
    />

    <a-modal
      v-model:visible="showResultsModal"
      title="训练结果"
      :footer="null"
      width="80%"
    >
      <img :src="currentImageUrl" style="width: 100%" v-if="currentImageUrl"/>
      <div v-else class="text-center py-8">
        <a-empty description="暂无训练结果图片"/>
      </div>
    </a-modal>
  </div>
</template>

<script lang="ts" setup>
import {nextTick, ref} from 'vue';
import {SwapOutlined} from '@ant-design/icons-vue';
import {BasicTable, TableAction, useTable} from '@/components/Table';
import {useMessage} from '@/hooks/web/useMessage';
import {useModal} from '@/components/Modal';
import {deleteTrainTask, getTrainTaskPage, startTrain} from '@/api/device/train';
import {getDatasetPage} from '@/api/device/dataset';
import StartTrainModal from '@/views/train/components/StartTrainTaskModal/index.vue';
import TrainLogsModal from '@/views/train/components/TrainTaskLogsModal/index.vue';
import TrainTaskCardList from '@/views/train/components/TrainTaskCardList/index.vue';
import {getBasicColumns, getFormConfig} from './Data';
import {Empty as AEmpty, Modal as AModal} from 'ant-design-vue';
import {Icon} from '@/components/Icon';

defineOptions({name: 'TrainTaskList'});

const {createMessage} = useMessage();

const viewMode = ref<'table' | 'card'>('card');
const params = {};
let cardListReload = () => {};

const showLogsModal = ref(false);
const showResultsModal = ref(false);
const currentImageUrl = ref('');

const [registerAddModel, {openModal: openAddModal}] = useModal();
const [registerTrainLogsModal, {openModal: openTrainLogsModal}] = useModal();

function getMethod(m: () => void) {
  cardListReload = m;
}

function handleToggleViewMode() {
  viewMode.value = viewMode.value === 'table' ? 'card' : 'table';
  if (viewMode.value === 'card') {
    cardListReload();
  }
}

function handleSuccess() {
  if (viewMode.value === 'table') {
    reload({page: 0});
  } else {
    cardListReload();
  }
}

let datasetUrlMap: Record<string, { name: string; version: string }> | null = null;

async function ensureDatasetUrlMap() {
  if (datasetUrlMap) return;
  try {
    const res = await getDatasetPage({page: 1, size: 500});
    const list = res?.data?.list || res?.data || [];
    datasetUrlMap = {};
    for (const item of list) {
      if (item.zipUrl) {
        datasetUrlMap[item.zipUrl] = {
          name: item.name || '',
          version: item.version || '',
        };
      }
    }
  } catch {
    datasetUrlMap = {};
  }
}

function enrichDatasetDisplay(records: Record<string, unknown>[]) {
  if (!records?.length) return;
  for (const record of records) {
    if (record.dataset_name) continue;
    const matched = datasetUrlMap?.[record.dataset_path as string];
    if (matched?.name) {
      record.dataset_name = matched.name;
      record.dataset_version = matched.version;
    }
  }
}

function buildRequestParams(params: Record<string, unknown>) {
  const requestParams = {...params};
  if (requestParams.timeRange && Array.isArray(requestParams.timeRange) && requestParams.timeRange.length === 2) {
    requestParams.startTimeFrom = requestParams.timeRange[0];
    requestParams.startTimeTo = requestParams.timeRange[1];
    delete requestParams.timeRange;
  }
  if (requestParams.model_name) {
    requestParams.task_name = requestParams.model_name;
    delete requestParams.model_name;
  }
  if (requestParams.task_name === '') {
    delete requestParams.task_name;
  }
  if (requestParams.status === '') {
    delete requestParams.status;
  }
  return requestParams;
}

async function fetchTrainTasks(params: Record<string, unknown>) {
  await ensureDatasetUrlMap();
  const result = await getTrainTaskPage(buildRequestParams(params));
  const records = result?.data ?? result?.list ?? [];
  if (Array.isArray(records)) {
    enrichDatasetDisplay(records);
  }
  return result;
}

const getTrainTaskListApi = async (queryParams: Record<string, unknown>) => {
  const result = await fetchTrainTasks(queryParams);
  return {
    data: result?.data ?? result?.list ?? [],
    total: result?.total ?? 0,
  };
};

const getTableActions = (record: Record<string, unknown>) => {
  const actions = [
    {
      icon: 'mdi:file-document-outline',
      tooltip: {title: '查看日志', placement: 'top'},
      onClick: () => handleOpenTrainLogsModal(record),
      style: 'color: #1890ff; padding: 0 8px; font-size: 16px;',
    },
    {
      icon: 'mdi:image-outline',
      tooltip: {title: '查看训练结果', placement: 'top'},
      onClick: () => handleViewTrainResults(record),
      style: 'color: #1890ff; padding: 0 8px; font-size: 16px;',
    },
  ];

  if (record.minio_model_path) {
    actions.push({
      icon: 'ant-design:download-outlined',
      tooltip: {title: '下载训练权重', placement: 'top'},
      onClick: () => handleDownloadWeights(record),
      style: 'color: #1890ff; padding: 0 8px; font-size: 16px;',
    });
  }

  actions.push({
    icon: 'mdi:delete-outline',
    tooltip: {title: '删除', placement: 'top'},
    popConfirm: {
      placement: 'topRight',
      title: '确定删除此训练任务?',
      confirm: () => handleDelete(record),
    },
    style: 'color: #ff4d4f; padding: 0 8px; font-size: 16px;',
  });

  return actions;
};

const handleStartTrain = async (config) => {
  try {
    const response = await startTrain(config);
    if (response && (response.code === 0 || response.success === true)) {
      createMessage.success(response.msg || '训练已启动');
      handleSuccess();
    } else {
      createMessage.error(response?.msg || '启动训练失败');
    }
  } catch (error) {
    const errorMsg = error?.response?.data?.msg || error?.message || '启动训练失败';
    createMessage.error(errorMsg);
  }
};

const handleViewTrainResults = (record) => {
  if (record.train_results_path) {
    currentImageUrl.value = record.train_results_path;
    showResultsModal.value = true;
  } else {
    createMessage.warning('此训练记录没有结果图片');
  }
};

const handleDownloadWeights = async (record) => {
  const url = record.minio_model_path;
  if (!url) {
    createMessage.warning('暂无可下载的训练权重');
    return;
  }
  try {
    const token = localStorage.getItem('jwt_token');
    const response = await fetch(url, {
      method: 'GET',
      headers: {'X-Authorization': 'Bearer ' + token},
    });
    if (!response.ok) {
      throw new Error('下载失败');
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.download = `${record.name || 'train'}_${record.id}.pt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(link.href);
    createMessage.success('下载成功');
  } catch {
    createMessage.error('下载训练权重失败');
  }
};

const handleDelete = async (record) => {
  try {
    const response = await deleteTrainTask(record.id);
    if (response && (response.code === 0 || response.success === true)) {
      createMessage.success(response.msg || '删除成功');
      handleSuccess();
    } else {
      createMessage.error(response?.msg || '删除失败');
    }
  } catch (error) {
    const errorMsg = error?.response?.data?.msg || error?.message || '删除失败，请稍后重试';
    createMessage.error(errorMsg);
  }
};

const handleCardDelete = async (record) => {
  await handleDelete(record);
};

const handleOpenTrainLogsModal = (record) => {
  showLogsModal.value = true;
  nextTick(() => {
    openTrainLogsModal(true, {record});
  });
};

const handleLogsModalClose = () => {
  showLogsModal.value = false;
};

const [registerTable, {reload}] = useTable({
  canResize: true,
  showIndexColumn: false,
  title: '模型训练',
  api: fetchTrainTasks,
  columns: getBasicColumns(),
  useSearchForm: true,
  showTableSetting: true,
  pagination: true,
  formConfig: getFormConfig(),
  fetchSetting: {
    listField: 'data',
    totalField: 'total',
  },
  rowKey: 'id',
});
</script>

<style lang="less" scoped>
#train-task-list {
  .toolbar-buttons {
    display: flex;
    align-items: center;
    gap: 10px;
  }
}
</style>
