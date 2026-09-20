export interface EvaluatorModelRef {
  provider_id: string;
  model_id: string;
  credential_ref?: string;
}
export function readModelRef(value: string): EvaluatorModelRef | null {
  try {
    const m = JSON.parse(value);
    if (!m || typeof m.provider_id !== 'string' || typeof m.model_id !== 'string') return null;
    return {
      provider_id: m.provider_id,
      model_id: m.model_id,
      ...(typeof m.credential_ref === 'string' ? { credential_ref: m.credential_ref } : {}),
    };
  } catch {
    return null;
  }
}
export function modelRefError(value: string) {
  const m = readModelRef(value);
  if (!m?.provider_id.trim() || !m.model_id.trim())
    return '请选择评审模型，或填写提供商 ID 与模型 ID。';
  if (
    [m.provider_id, m.model_id, m.credential_ref ?? ''].some((v) =>
      /^(sk-|Bearer\s)/i.test(v.trim()),
    )
  )
    return '这里只填写模型或凭据引用，不能填写 API Key。';
  return '';
}
export function modelRefLabel(value: string) {
  const m = readModelRef(value);
  return m?.model_id?.trim() ? m.model_id + ' · ' + m.provider_id : '未选择评审模型';
}
