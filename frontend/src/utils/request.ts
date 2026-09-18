import axios from 'axios'

const request = axios.create({ baseURL: '/race-api', timeout: 15_000 })

request.interceptors.response.use((response) => {
  const payload = response.data
  if (payload?.code !== '0') return Promise.reject(new Error(payload?.message || '平台接口调用失败'))
  return payload.data
})

export default request
