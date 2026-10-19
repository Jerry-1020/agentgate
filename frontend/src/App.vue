<script setup lang="ts">
import { computed } from 'vue';
import { useAuthStore } from './stores/modules/auth';
import {
  embeddedMode,
  initializeUrlIdentity,
} from './integration/platform-url-context';

const auth = useAuthStore();
initializeUrlIdentity();
const unavailable = computed(() => embeddedMode && !auth.platformReady);
</script>

<template>
  <main v-if="unavailable" class="platform-entry" aria-live="polite">
    <p>平台会话已退出，请从创新工厂重新打开智能体测评</p>
  </main>
  <RouterView v-else />
</template>

<style scoped>
.platform-entry {
  min-height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  font-size: 14px;
  color: #606266;
}
</style>
