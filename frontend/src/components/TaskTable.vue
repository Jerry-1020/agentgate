<template>
  <div class="table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>任务</th>
          <th>测评对象 / 版本</th>
          <th>测评集 / 评估器</th>
          <th>状态</th>
          <th>通过率</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.id">
          <td>
            <b>{{ task.name }}</b>
            <div class="muted">{{ task.id }}</div>
          </td>
          <td>
            {{ task.target.name }}
            <div class="muted">{{ task.target.type }} · {{ task.target.version }}</div>
          </td>
          <td>
            {{ task.dataset.name }}
            <div class="muted">{{ task.dataset.version }} · {{ task.evaluator.version }}</div>
          </td>
          <td>
            <span :class="['badge', statusClass(task.status)]">{{ task.status }}</span>
          </td>
          <td>{{ task.passRate === null ? '—' : task.passRate + '%' }}</td>
          <td>{{ task.createdAt }}</td>
          <td><button class="link" @click="$emit('open', task)">查看</button></td>
        </tr>
        <tr v-if="!tasks.length">
          <td colspan="7" class="empty">暂无符合条件的测评任务</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<script setup lang="ts">
import type { EvalTask, TaskStatus } from '../domain/evaluation';
defineProps<{ tasks: EvalTask[] }>();
defineEmits<{ open: [task: EvalTask] }>();
function statusClass(status: TaskStatus) {
  return status === '已完成'
    ? 'success'
    : status === '已失败'
      ? 'error'
      : status === '运行中'
        ? 'warn'
        : 'info';
}
</script>
