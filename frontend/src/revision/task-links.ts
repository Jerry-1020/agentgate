// UI associations only. Runs and reports always come from the backend.
export interface TaskLink {
  id: string
  kind: 'single' | 'ab'
  mockSelection?: {branch:string;credentialScope:string;credentialLabel:string}
  runIds: string[]
  staticReports: { version: string; reportId?: string; error?: string }[]
}
const key = 'agentgate:task-links:v1'
export function readTaskLinks(): TaskLink[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(value) ? value.filter(x => x && typeof x.id === 'string'
      && ['single', 'ab'].includes(x.kind) && Array.isArray(x.runIds)
      && x.runIds.every((id: unknown) => typeof id === 'string') && Array.isArray(x.staticReports)) : []
  } catch { return [] }
}
export function saveTaskLink(link: TaskLink) {
  const links = readTaskLinks().filter(x => x.id !== link.id)
  localStorage.setItem(key, JSON.stringify([link, ...links]))
  window.dispatchEvent(new Event('task-links-updated'))
}
