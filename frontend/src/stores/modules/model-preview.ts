import { reactive } from 'vue';
import { defineStore } from 'pinia';
import { pinia } from '../index';

export type PreviewTeam = { id: string; name: string };
export type PreviewCredential = {
  id: string;
  name: string;
  provider: string;
  ownerTeamId: string;
  allowedTeamIds: string[];
  enabled: boolean;
  revision: number;
};
export type PreviewConnection = {
  id: string;
  name: string;
  provider: string;
  baseUrl: string;
  modelId: string;
  credentialId: string;
  ownerTeamId: string;
  allowedTeamIds: string[];
  enabled: boolean;
};
export type PreviewCatalog = {
  teams: PreviewTeam[];
  credentials: PreviewCredential[];
  connections: PreviewConnection[];
};
export const settingsCapability = {
  persistentModelManagement: false,
  teamAuthorization: false,
  connectionTest: false,
} as const;

export function seedSettings(): PreviewCatalog {
  return {
    teams: [
      { id: 'demo-research', name: '研发团队（演示）' },
      { id: 'demo-quality', name: '质量评测团队（演示）' },
    ],
    credentials: [
      {
        id: 'demo-key-shared',
        name: '评测服务凭据（示例）',
        provider: 'openai-compatible',
        ownerTeamId: 'demo-research',
        allowedTeamIds: ['demo-quality'],
        enabled: true,
        revision: 1,
      },
      {
        id: 'demo-key-quality',
        name: '质量团队凭据（示例）',
        provider: 'openai-compatible',
        ownerTeamId: 'demo-quality',
        allowedTeamIds: [],
        enabled: true,
        revision: 1,
      },
    ],
    connections: [
      {
        id: 'demo-model-quality',
        name: '通用质量评分（示例）',
        provider: 'openai-compatible',
        baseUrl: 'https://model.example.com/v1',
        modelId: 'example-judge',
        credentialId: 'demo-key-shared',
        ownerTeamId: 'demo-research',
        allowedTeamIds: ['demo-quality'],
        enabled: true,
      },
      {
        id: 'demo-model-reason',
        name: '推理评分备选（示例）',
        provider: 'openai-compatible',
        baseUrl: 'https://model.example.com/v1',
        modelId: 'example-reasoner',
        credentialId: 'demo-key-quality',
        ownerTeamId: 'demo-quality',
        allowedTeamIds: [],
        enabled: false,
      },
    ],
  };
}
// Shared only within this browser page lifecycle; no storage, secret value or real API writes.
export const useSettingsPreviewStore = defineStore('settings-preview', () => ({
  catalog: reactive<PreviewCatalog>(seedSettings()),
}));
export const settingsPreview = useSettingsPreviewStore(pinia).catalog;
export function permittedTeams(item: { ownerTeamId: string; allowedTeamIds: string[] }): string[] {
  return [...new Set([item.ownerTeamId, ...item.allowedTeamIds])];
}
export function connectionState(
  connection: PreviewConnection,
  catalog: PreviewCatalog,
): 'disabled' | 'credential_disabled' | 'invalid' | 'available' {
  if (!connection.enabled) return 'disabled';
  const key = catalog.credentials.find((k) => k.id === connection.credentialId);
  if (
    !key ||
    key.provider !== connection.provider ||
    permittedTeams(connection).some((t) => !permittedTeams(key).includes(t))
  )
    return 'invalid';
  return key.enabled ? 'available' : 'credential_disabled';
}
export function visibleConnections(catalog: PreviewCatalog, teamId: string): PreviewConnection[] {
  return catalog.connections.filter(
    (c) => permittedTeams(c).includes(teamId) && connectionState(c, catalog) === 'available',
  );
}
export function validateConnection(value: PreviewConnection, catalog: PreviewCatalog): string {
  if (!value.name.trim() || !value.modelId.trim()) return '请填写连接名称和模型 ID。';
  if (!catalog.teams.some((t) => t.id === value.ownerTeamId)) return '请选择所属团队。';
  if (
    catalog.connections.some(
      (c) =>
        c.id !== value.id &&
        c.ownerTeamId === value.ownerTeamId &&
        c.name.trim().toLowerCase() === value.name.trim().toLowerCase(),
    )
  )
    return '该团队已存在同名模型连接。';
  try {
    const url = new URL(value.baseUrl);
    if (
      url.protocol !== 'https:' ||
      !url.hostname ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    )
      throw Error();
    if (url.pathname.replace(/\/$/, '').endsWith('/chat/completions'))
      return '请填写 BaseURL，不要包含 /chat/completions。';
  } catch {
    return '请填写 HTTPS BaseURL，不能包含账号、密钥、查询参数或片段。';
  }
  const key = catalog.credentials.find((k) => k.id === value.credentialId);
  if (!key || key.provider !== value.provider) return '请选择与接口协议匹配的 API Key。';
  if (!key.enabled) return '所选 API Key 已停用，请更换凭据。';
  if (
    permittedTeams(value).some(
      (id) => !catalog.teams.some((t) => t.id === id) || !permittedTeams(key).includes(id),
    )
  )
    return '模型使用团队必须在所选 API Key 的授权范围内。';
  return '';
}
export function validateCredential(value: PreviewCredential, catalog: PreviewCatalog): string {
  if (!value.name.trim()) return '请填写凭据名称。';
  if (permittedTeams(value).some((id) => !catalog.teams.some((t) => t.id === id)))
    return '请选择有效团队。';
  if (
    catalog.credentials.some(
      (k) =>
        k.id !== value.id &&
        k.ownerTeamId === value.ownerTeamId &&
        k.name.trim().toLowerCase() === value.name.trim().toLowerCase(),
    )
  )
    return '该团队已存在同名凭据。';
  if (
    catalog.connections.some(
      (c) =>
        c.credentialId === value.id &&
        (c.provider !== value.provider ||
          permittedTeams(c).some((t) => !permittedTeams(value).includes(t))),
    )
  )
    return '仍有模型连接使用被移除的授权，请先调整对应模型的使用团队或更换凭据。';
  return '';
}
