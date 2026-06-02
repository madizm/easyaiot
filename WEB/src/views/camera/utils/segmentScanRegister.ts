import type { CredentialPair, SegmentScanDeviceRow } from '@/api/device/camera';

/** 按品牌拼装 IPC 主码流 RTSP（与 VideoModal 海康/大华规则一致） */
export function buildSegmentScanRtspUrl(
  record: SegmentScanDeviceRow,
  cred: CredentialPair,
  stream = 0,
): string | undefined {
  const ip = record.ip?.trim();
  if (!ip || !cred.username?.trim()) return undefined;
  const user = encodeURIComponent(cred.username.trim());
  const pw = encodeURIComponent(cred.password || '');
  const port = 554;
  const vendor = record.vendor;
  if (vendor === 'hikvision' || vendor === 'ezviz') {
    const subtype = stream === 0 ? 1 : 2;
    return `rtsp://${user}:${pw}@${ip}:${port}/Streaming/Channels/10${subtype}`;
  }
  if (vendor === 'dahua') {
    const subtype = stream === 0 ? 0 : 1;
    return `rtsp://${user}:${pw}@${ip}:${port}/cam/realmonitor?channel=1&subtype=${subtype}`;
  }
  return undefined;
}

export function resolveSegmentScanRtsp(
  record: SegmentScanDeviceRow,
  cred: CredentialPair,
): string | undefined {
  const fromScan = record.rtsp_url?.trim();
  if (fromScan) return fromScan;
  return buildSegmentScanRtspUrl(record, cred);
}

export function isSegmentScanRecognized(record: SegmentScanDeviceRow): boolean {
  return !!(record.is_nvr || record.is_recognized || record.vendor);
}

/** 扫描带回 auth_username，或已识别设备且表单有凭证 */
export function isSegmentScanCredentialAccessible(
  record: SegmentScanDeviceRow,
  mode: 'camera' | 'nvr',
  hasFormCredentials: boolean,
): boolean {
  if (record.auth_username && String(record.auth_username).trim()) return true;
  if (!hasFormCredentials || !isSegmentScanRecognized(record)) return false;
  if (mode === 'nvr') return true;
  return !record.is_nvr;
}

export function hasSegmentScanRegisterPayload(
  record: SegmentScanDeviceRow,
  mode: 'camera' | 'nvr',
  cred: CredentialPair,
  credentialAccessible: boolean,
): boolean {
  if (mode === 'nvr') return credentialAccessible;
  if (!credentialAccessible) return false;
  return !!resolveSegmentScanRtsp(record, cred);
}
