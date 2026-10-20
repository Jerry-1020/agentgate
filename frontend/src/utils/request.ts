import axios, { type AxiosRequestConfig } from 'axios';
import { pinia } from '../stores';
import { useAuthStore } from '../stores/modules/auth';
import { embeddedMode } from '../integration/platform-url-context';

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(
      Array.isArray(detail)
        ? detail.map((item) => item?.message ?? JSON.stringify(item)).join('；')
        : typeof detail === 'object' && detail !== null
          ? JSON.stringify(detail)
          : String(detail ?? `HTTP ${status}`),
    );
    this.name = 'ApiError';
  }
}
export const http = axios.create({
  baseURL: import.meta.env?.VITE_API_BASE_URL || '/api',
  timeout: 30000,
});
http.interceptors.request.use((config) => {
  const auth = useAuthStore(pinia);
  if (!embeddedMode && auth.loginMode === 'external') return config;
  if (embeddedMode && (!auth.isIntegrated || !auth.platformReady)) {
    throw new ApiError(0, '尚未收到平台登录信息，请等待初始化');
  }

  // This client is reserved for the configured evaluation backend.
  // Reject attempts to override the destination and leak identity headers.
  const pageUrl = typeof window === 'undefined' ? 'http://localhost/' : window.location?.href ?? 'http://localhost/';
  const base = new URL(String(http.defaults.baseURL || '/api'), pageUrl);
  const destination = new URL(http.getUri(config), pageUrl);
  const prefix = base.pathname.replace(/\/+$/, '');
  if (destination.origin !== base.origin ||
      (destination.pathname !== prefix && !destination.pathname.startsWith(`${prefix}/`))) {
    throw new ApiError(0, '拒绝向非测评服务发送身份信息');
  }

  config.headers = {
    ...config.headers,
    token: auth.token ?? '',
    user_team_id: auth.teamId ?? '',
    user_team_name: encodeURIComponent(auth.teamName ?? ''),
    user_id: auth.userId ?? '',
    user_name: encodeURIComponent(auth.userName ?? ''),
  };
  return config;
});

http.interceptors.response.use(
  (response) => {
    const payload = response.data;
    // Both the current raw API and the platform ResponseBase envelope are supported.
    if (
      payload &&
      typeof payload === 'object' &&
      'code' in payload &&
      'data' in payload &&
      'message' in payload
    ) {
      if (String(payload.code) !== '0') throw new ApiError(response.status, payload.message);
      response.data = payload.data;
    }
    return response;
  },
  (error) => {
    if (axios.isAxiosError(error)) {
      if (error.code === 'ECONNABORTED')
        return Promise.reject(new ApiError(0, '请求超时，请先查询保存或运行状态，避免重复提交。'));
      return Promise.reject(
        new ApiError(
          error.response?.status ?? 0,
          error.response?.data?.detail ?? error.response?.data?.message ?? error.message,
        ),
      );
    }
    return Promise.reject(error);
  },
);
export async function httpRequest<T>(url: string, config: AxiosRequestConfig = {}): Promise<T> {
  // Legacy /api callers share the same configurable baseURL without doubling the prefix.
  const path = url.replace(/^\/api(?=\/|$)/, '');
  const response = await http.request<T>({ ...config, url: path });
  return response.data;
}
export default http;
