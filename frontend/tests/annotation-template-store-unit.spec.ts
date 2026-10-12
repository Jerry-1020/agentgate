import { expect, test } from '@playwright/test';
import { createPinia } from 'pinia';
import { useReviewStore, type AnnotationTask } from '../src/stores/modules/review';

const storageKey = 'agentgate-ux-5198-annotations-v1';

function annotationTask(): AnnotationTask {
  return {
    id: 'task-v2',
    name: 'V2 模板',
    description: '',
    app: {
      source_id: 'platform',
      target_type: 'agent',
      external_target_id: 'agent-1',
      external_version_id: 'v2',
      name: 'Agent',
    },
    target: {
      loginMode: 'external',
      teamId: 'team-1',
      agentId: 'agent-1',
      agentName: 'Agent',
      typeGroup: 'base/workflow',
      branchId: 'main',
      agentVersion: 'v2',
    },
    template: {
      id: 'template-v2',
      name: 'V2 模板',
      description: '',
      message: [],
      tools: [],
      messageTags: [],
      toolTags: [],
      min: 0,
      max: 100,
      v2: {
        dataset: { enabled: true, criteria: [{ key: 'accuracy', text: '准确' }], tags: [] },
        evaluator: { enabled: false, criteria: [], tags: [] },
        agent: { enabled: false, criteria: [], tags: [] },
      },
    },
    annotations: {},
  };
}

test('V2 template is restored from the persisted task snapshot', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    },
  });
  try {
    const task = annotationTask();
    const first = useReviewStore(createPinia());
    first.saveAnnotationTask(task);
    expect(JSON.parse(values.get(storageKey) ?? '[]')[0].template.v2).toEqual(task.template.v2);
    const restored = useReviewStore(createPinia());
    expect(restored.annotationTemplates.find((template) => template.id === 'template-v2')?.v2).toEqual(
      task.template.v2,
    );
    expect(restored.annotationTasks[0].target?.agentVersion).toBe('v2');
  } finally {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});

test('failed browser write leaves the previous annotation task unchanged', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const original = annotationTask();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: () => JSON.stringify([original]),
      setItem: () => {
        throw Error('storage full');
      },
    },
  });
  try {
    const store = useReviewStore(createPinia());
    const changed = annotationTask();
    changed.name = 'unsaved';
    expect(() => store.saveAnnotationTask(changed)).toThrow('标注未保存');
    expect(store.annotationTasks[0].name).toBe('V2 模板');
  } finally {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  }
});
