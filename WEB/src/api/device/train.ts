import {defHttp} from '@/utils/http/axios';

const Api = {
  TrainTask: '/model/train_task',
};

const commonApi = (
  method: 'get' | 'post' | 'delete' | 'put',
  url: string,
  params: Record<string, unknown> = {},
  headers: Record<string, string> = {},
  isTransformResponse = true,
) => {
  const authHeader = {'X-Authorization': 'Bearer ' + localStorage.getItem('jwt_token')};

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
