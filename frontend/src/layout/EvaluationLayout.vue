<script setup lang="ts">
defineProps<{ page: string; online: boolean | null }>();
const navigation = [
  ['overview', '评测总览'],
  ['datasets', '评测集'],
  ['evaluators', '评估器'],
  ['tasks', '评测任务'],
  ['annotations', '人工标注'],
];
</script>
<template>
  <div
    class="app revision-app"
    :class="{ 'review-layout': ['annotations', 'evaluators'].includes(page) }"
  >
    <header class="topbar">
      <div class="brand">智能体评测中心</div>
      <span class="badge" :class="online ? 'success' : 'warn'">{{
        online === null ? '正在连接服务…' : online ? '评测后端已连接' : '服务未连接'
      }}</span>
    </header>
    <div class="shell">
      <aside class="sidebar">
        <div class="nav-group">评测与资产</div>
        <RouterLink
          v-for="item in navigation"
          :key="item[0]"
          :to="'/' + item[0]"
          class="nav-item"
          :class="{ active: page === item[0] || (page === 'stability' && item[0] === 'tasks') }"
          >{{ item[1] }}</RouterLink
        >
      </aside>
      <main class="content"><slot /></main>
    </div>
    <slot name="dialogs" />
  </div>
</template>
