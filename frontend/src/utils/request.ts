import axios, { type AxiosRequestConfig } from 'axios';

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
