import { test, expect } from '@playwright/test';
import { createPinia } from 'pinia';
import { http } from '../src/utils/request';
import { useTaskLinksStore } from '../src/stores/modules/task-links';
import { useSettingsPreviewStore } from '../src/stores/modules/model-preview';

test('shared task links are owned by Pinia and remain isolated between app instances', async () => {
  const previous = http.defaults.adapter;
  try {
    http.defaults.adapter = async config => ({
      data: [{ id: 'task-a', kind: 'single', run_ids: ['run-a'], static_report_ids: [] }],
      status: 200, statusText: 'OK', headers: {}, config,
    });
    const first = useTaskLinksStore(createPinia());
    const second = useTaskLinksStore(createPinia());
    await first.refreshTaskLinks();
    expect(first.readTaskLinks()[0].runIds).toEqual(['run-a']);
    expect(second.readTaskLinks()).toEqual([]);
  } finally { http.defaults.adapter = previous; }
});

test('model preview state uses Pinia without sharing mutable seed data across apps', () => {
  const first = useSettingsPreviewStore(createPinia());
  const second = useSettingsPreviewStore(createPinia());
  first.catalog.teams[0].name = 'changed';
  expect(second.catalog.teams[0].name).not.toBe('changed');
});
