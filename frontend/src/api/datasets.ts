import { request } from './client';
import type {
  CaseTurn,
  Condition,
  DatasetDetail,
  DatasetExport,
  DatasetMutation,
  DatasetRecord,
  DatasetSummary,
  DatasetVersion,
  EvaluationCase,
  Expectation,
  SerializedExpectation,
} from '../views/datasets/types/index';

const headers = { 'Content-Type': 'application/json' };
const id = encodeURIComponent;

interface ApiExpectationBase {
  id: string;
  name: string | null;
}

type ApiExpectation =
  | Expectation
  | (ApiExpectationBase & { kind: 'skill_route'; condition: Condition })
  | (ApiExpectationBase & {
      kind: 'tool_call';
      tool: string;
      mode: 'required' | 'forbidden';
    })
  | (ApiExpectationBase & { kind: 'policy'; policy_id: string });

type ApiCaseTurn = Omit<
  CaseTurn,
  | 'expected_skill'
  | 'expectations'
  | 'required_tools'
  | 'forbidden_tools'
  | 'policy_rules'
  | 'preserved_skill_routes'
  | 'original_expectations'
> & { expectations: ApiExpectation[] };
type ApiEvaluationCase = Omit<EvaluationCase, 'turns'> & { turns: ApiCaseTurn[] };
type ApiDatasetVersion = Omit<DatasetVersion, 'cases'> & { cases: ApiEvaluationCase[] };
type ApiDatasetDetail = Omit<DatasetDetail, 'versions'> & { versions: ApiDatasetVersion[] };
type ApiDatasetMutation = Omit<DatasetMutation, 'draft'> & { draft: ApiDatasetVersion };

const editableExpectationKinds = new Set(['state', 'tool_argument', 'output']);

export function toEditorCase(item: ApiEvaluationCase): EvaluationCase {
  return {
    ...item,
    turns: item.turns.map((turn) => {
      const skill = turn.expectations.find((item) => item.kind === 'skill_route');
      return {
        ...turn,
        original_expectations: structuredClone(turn.expectations),
        preserved_skill_routes: turn.expectations.filter(
          (item): item is ApiExpectationBase & { kind: 'skill_route'; condition: Condition } =>
            item.kind === 'skill_route' &&
            (item !== skill ||
              item.condition.kind !== 'equals' ||
              typeof item.condition.expected !== 'string'),
        ),
        expected_skill:
          skill?.kind === 'skill_route' &&
          skill.condition.kind === 'equals' &&
          typeof skill.condition.expected === 'string'
            ? skill.condition.expected
            : null,
        expectations: turn.expectations.filter((item): item is Expectation =>
          editableExpectationKinds.has(item.kind),
        ),
        required_tools: turn.expectations
          .filter((item) => item.kind === 'tool_call' && item.mode === 'required')
          .map((item) => (item.kind === 'tool_call' ? item.tool : '')),
        forbidden_tools: turn.expectations
          .filter((item) => item.kind === 'tool_call' && item.mode === 'forbidden')
          .map((item) => (item.kind === 'tool_call' ? item.tool : '')),
        policy_rules: turn.expectations
          .filter((item) => item.kind === 'policy')
          .map((item) => (item.kind === 'policy' ? item.policy_id : '')),
      };
    }),
  };
}

function toEditorVersion(version: ApiDatasetVersion): DatasetVersion {
  return { ...version, cases: version.cases.map(toEditorCase) };
}

// Editor convenience fields must not recreate the identities or order of unchanged checks.
export function toApiCase(item: EvaluationCase): ApiEvaluationCase {
  return {
    ...item,
    turns: item.turns.map(
      ({
        expected_skill,
        required_tools,
        forbidden_tools,
        policy_rules,
        preserved_skill_routes,
        original_expectations,
        ...turn
      }) => {
        const original = original_expectations ?? [],
          used = new Set<string>();
        function reuse(
          candidate: SerializedExpectation,
          predicate: (e: SerializedExpectation) => boolean,
        ): SerializedExpectation {
          const found = original.find((e) => !used.has(e.id) && predicate(e));
          if (!found) return candidate;
          used.add(found.id);
          return { ...candidate, id: found.id, name: found.name };
        }
        const expectations: SerializedExpectation[] = [
          ...(preserved_skill_routes ?? []),
          ...(expected_skill
            ? [
                reuse(
                  {
                    id: crypto.randomUUID(),
                    kind: 'skill_route',
                    name: null,
                    condition: { kind: 'equals', expected: expected_skill },
                  },
                  (e) =>
                    e.kind === 'skill_route' &&
                    e.condition.kind === 'equals' &&
                    typeof e.condition.expected === 'string' &&
                    !preserved_skill_routes?.some((p) => p.id === e.id),
                ),
              ]
            : []),
          ...required_tools.map((tool) =>
            reuse(
              { id: crypto.randomUUID(), kind: 'tool_call', name: null, tool, mode: 'required' },
              (e) => e.kind === 'tool_call' && e.mode === 'required' && e.tool === tool,
            ),
          ),
          ...forbidden_tools.map((tool) =>
            reuse(
              { id: crypto.randomUUID(), kind: 'tool_call', name: null, tool, mode: 'forbidden' },
              (e) => e.kind === 'tool_call' && e.mode === 'forbidden' && e.tool === tool,
            ),
          ),
          ...policy_rules.map((policy_id) =>
            reuse(
              { id: crypto.randomUUID(), kind: 'policy', name: null, policy_id },
              (e) => e.kind === 'policy' && e.policy_id === policy_id,
            ),
          ),
          ...turn.expectations,
        ];
        const order = new Map(original.map((e, i) => [e.id, i]));
        expectations.sort(
          (a, b) =>
            (order.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
            (order.get(b.id) ?? Number.MAX_SAFE_INTEGER),
        );
        return { ...turn, expectations };
      },
    ),
  };
}

export const datasetApi = {
  list: () => request<DatasetSummary[]>('/api/datasets'),
  create: (name: string, description = '') =>
    request<ApiDatasetMutation>('/api/datasets', {
      method: 'POST',
      headers,
      body: JSON.stringify({ name, description }),
    }).then((result) => ({ ...result, draft: toEditorVersion(result.draft) })),
  detail: (datasetId: string) =>
    request<ApiDatasetDetail>(`/api/datasets/${id(datasetId)}`).then((result) => ({
      ...result,
      versions: result.versions.map(toEditorVersion),
    })),
  update: (
    datasetId: string,
    changes: Partial<Pick<DatasetRecord, 'name' | 'description' | 'archived'>>,
  ) =>
    request<DatasetRecord>(`/api/datasets/${id(datasetId)}`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify(changes),
    }),
  archive: (datasetId: string) =>
    request<DatasetRecord>(`/api/datasets/${id(datasetId)}`, { method: 'DELETE' }),
  copy: (datasetId: string, name: string, sourceVersion?: number | null) =>
    request<ApiDatasetMutation>(`/api/datasets/${id(datasetId)}/copy`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ name, source_version: sourceVersion ?? null }),
    }).then((result) => ({ ...result, draft: toEditorVersion(result.draft) })),
  versions: (datasetId: string) =>
    request<ApiDatasetVersion[]>(`/api/datasets/${id(datasetId)}/versions`).then((versions) =>
      versions.map(toEditorVersion),
    ),
  version: (datasetId: string, version: number) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/versions/${version}`).then(
      toEditorVersion,
    ),
  currentDraft: (datasetId: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/current`).then(
      toEditorVersion,
    ),
  createDraft: (datasetId: string, basedOnVersion?: number | null) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ based_on_version: basedOnVersion ?? null }),
    }).then(toEditorVersion),
  discardDraft: (datasetId: string) =>
    request<void>(`/api/datasets/${id(datasetId)}/drafts/current`, {
      method: 'DELETE',
    }),
  publish: (datasetId: string, expectedHash: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/publish`, {
      method: 'POST',
      headers,
    }).then(toEditorVersion),
  addCase: (datasetId: string, item: EvaluationCase, expectedHash: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/cases`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(toApiCase(item)),
    }).then(toEditorVersion),
  updateCase: (datasetId: string, item: EvaluationCase, expectedHash: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/cases/${id(item.id)}`, {
      method: 'PUT',
      headers: { ...headers, 'If-Match': expectedHash },
      body: JSON.stringify(toApiCase(item)),
    }).then(toEditorVersion),
  removeCase: (datasetId: string, caseId: string, expectedHash: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/cases/${id(caseId)}`, {
      method: 'DELETE',
      headers: { 'If-Match': expectedHash },
    }).then(toEditorVersion),
  copyCase: (datasetId: string, caseId: string, expectedHash: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/cases/${id(caseId)}/copy`, {
      method: 'POST',
      headers: { 'If-Match': expectedHash },
    }).then(toEditorVersion),
  reorderCases: (datasetId: string, caseIds: string[], expectedHash: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/case-order`, {
      method: 'PUT',
      headers: { ...headers, 'If-Match': expectedHash },
      body: JSON.stringify({ case_ids: caseIds }),
    }).then(toEditorVersion),
  exportVersion: (datasetId: string, version: number) =>
    request<DatasetExport>(`/api/datasets/${id(datasetId)}/versions/${version}/export`),
  importDataset: (payload: DatasetExport) =>
    request<{ dataset: DatasetRecord; version: DatasetVersion }>('/api/datasets/import', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    }),
};
