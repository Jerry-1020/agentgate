<script setup lang="ts">
defineProps<{ page: string; online: boolean | null }>();
defineEmits<{ logout: [] }>();
const navigation = [
  ['overview', '测评总览'],
  ['evaluators', '评估器'],
  ['datasets', '测评集'],
  ['tasks', '测评任务'],
  ['annotations', '标注'],
];
</script>
<template>
  <div
    class="app revision-app"
    :class="{ 'review-layout': ['annotations', 'evaluators'].includes(page) }"
  >
    <header class="topbar">
      <div class="brand">智能体测评中心</div>
      <div class="topbar-right">
        <button type="button" class="logout-btn" @click="$emit('logout')">登出 Logout</button>
      </div>
    </header>
    <div class="shell">
      <aside class="sidebar">
        <RouterLink
          v-for="item in navigation"
          :key="item[0]"
          :to="'/' + item[0]"
          class="nav-item"
          :class="{ active: page === item[0] || (page === 'stability' && item[0] === 'tasks') }"
          >{{ item[1] }}</RouterLink
        >
        <div class="nav-group sidebar-status">
          连接状态：{{
            online === null ? '正在连接服务…' : online ? '测评后端已连接' : '服务未连接'
          }}
        </div>
      </aside>
      <main class="content"><slot /></main>
    </div>
    <slot name="dialogs" />
  </div>
</template>

<style scoped>
.topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.logout-btn {
  background: #fff;
  color: #076b5d;
  border: none;
  border-radius: 6px;
  height: 34px;
  padding: 0 14px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}
.logout-btn:hover {
  background: #eafffb;
}
.sidebar-status {
  margin-top: auto;
  color: #9ca3af;
}
</style>
