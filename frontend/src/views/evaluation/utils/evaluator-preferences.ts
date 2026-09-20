const key = 'agentgate:builtin-evaluator-disabled:v1';
function disabledIds(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? '[]');
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [];
  } catch {
    return [];
  }
}
export function applyEvaluatorPreference<
  T extends { id: string; source: string; enabled: boolean },
>(item: T): T {
  return item.source === 'builtin' && disabledIds().includes(item.id)
    ? { ...item, enabled: false }
    : item;
}
export function setBuiltinEnabled(id: string, enabled: boolean) {
  const ids = new Set(disabledIds());
  if (enabled) ids.delete(id);
  else ids.add(id);
  localStorage.setItem(key, JSON.stringify([...ids]));
  window.dispatchEvent(new Event('evaluator-preferences-changed'));
}
export function assertLocallyEnabled(ids: string[]) {
  const blocked = ids.filter((id) => disabledIds().includes(id));
  if (blocked.length)
    throw Error('所选评估器已在当前浏览器禁用：' + blocked.join('、') + '。请重新选择或先启用。');
}
