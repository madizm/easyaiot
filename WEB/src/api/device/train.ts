import {defHttp} from '@/utils/http/axios';

const Api = {
  TrainTask: '/model/train_task',
};

const buildAuthHeader = () => ({
  'X-Authorization': 'Bearer ' + localStorage.getItem('jwt_token'),
});

const commonApi = (
  method: 'get' | 'post' | 'delete' | 'put',
  url: string,
  params: Record<string, unknown> = {},
  headers: Record<string, string> = {},
  isTransformResponse = true,
) => {
  const authHeader = buildAuthHeader();

  return defHttp[method](
    {
      url,
      headers: {
        ...authHeader,
        ...headers,
      },
      ...params,
    },
    {
      isTransformResponse,
    },
  );
};

export const getTrainTaskPage = (params: Record<string, unknown>) => {
  return commonApi('get', `${Api.TrainTask}/list`, {params});
};

export const getTrainTaskDetail = (recordId: number) => {
  return commonApi('get', `${Api.TrainTask}/${recordId}`);
};

export const deleteTrainTask = (recordId: number) => {
  return commonApi('delete', `${Api.TrainTask}/delete/${recordId}`);
};

export const startTrain = (config: Record<string, unknown>) => {
  return commonApi('post', `${Api.TrainTask}/start`, {data: config});
};

export const stopTrain = (taskId: number) => {
  return commonApi('post', `${Api.TrainTask}/${taskId}/stop`);
};

export const getTrainStatus = (taskId: number) => {
  return commonApi('get', `${Api.TrainTask}/${taskId}/status`);
};

export const getTrainLogs = (taskId: number) => {
  return commonApi('get', `${Api.TrainTask}/${taskId}/logs`);
};

export const getTrainGpuStatus = () => {
  return commonApi('get', `${Api.TrainTask}/gpu/status`);
};

/** 上传本地 YOLO 数据集 zip，返回服务端路径供训练使用 */
export const uploadTrainDataset = (formData: FormData) => {
  return defHttp.post(
    {
      url: `${Api.TrainTask}/dataset/upload`,
      data: formData,
      timeout: 60 * 60 * 1000,
      headers: buildAuthHeader(),
    },
    {
      isTransformResponse: true,
      successMessageMode: 'none',
    },
  );
};
