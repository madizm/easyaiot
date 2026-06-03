/** 摄像头位置信息（WGS84），供表单校验与地图场景复用 */

export interface DeviceLocationFields {
  longitude?: number | null;
  latitude?: number | null;
  altitude?: number | null;
  address?: string | null;
  location_source?: string | null;
  location_updated_at?: string | null;
  has_location?: boolean;
}

export const LOCATION_SOURCE_LABEL: Record<string, string> = {
  manual: '手动填写',
  gb28181: '国标同步',
  import: '批量导入',
};

export function hasDeviceLocation(loc: Pick<DeviceLocationFields, 'longitude' | 'latitude' | 'has_location'>) {
  if (loc.has_location) return true;
  return loc.longitude != null && loc.latitude != null;
}

export function formatLocationSummary(loc: DeviceLocationFields): string {
  if (!hasDeviceLocation(loc)) return '未设置';
  const lng = Number(loc.longitude).toFixed(6);
  const lat = Number(loc.latitude).toFixed(6);
  return `${lng}, ${lat}`;
}

export function validateLongitude(_rule: unknown, value: unknown) {
  if (value === undefined || value === null || value === '') {
    return Promise.resolve();
  }
  const num = Number(value);
  if (Number.isNaN(num) || num < -180 || num > 180) {
    return Promise.reject('经度范围应在 -180 至 180 之间');
  }
  return Promise.resolve();
}

export function validateLatitude(_rule: unknown, value: unknown) {
  if (value === undefined || value === null || value === '') {
    return Promise.resolve();
  }
  const num = Number(value);
  if (Number.isNaN(num) || num < -90 || num > 90) {
    return Promise.reject('纬度范围应在 -90 至 90 之间');
  }
  return Promise.resolve();
}

export function validateLocationPair(longitude: unknown, latitude: unknown) {
  const hasLng = longitude !== undefined && longitude !== null && longitude !== '';
  const hasLat = latitude !== undefined && latitude !== null && latitude !== '';
  if (hasLng !== hasLat) {
    return Promise.reject('经纬度需同时填写或同时留空');
  }
  return Promise.resolve();
}

export function validateAltitude(_rule: unknown, value: unknown) {
  if (value === undefined || value === null || value === '') {
    return Promise.resolve();
  }
  const num = Number(value);
  if (Number.isNaN(num) || num < -500 || num > 9000) {
    return Promise.reject('海拔高度应在 -500 至 9000 米之间');
  }
  return Promise.resolve();
}
