<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElButton, ElDialog, ElMessage, ElOption, ElSelect } from 'element-plus';
import { useAuthStore } from '../../stores/modules/auth';
import { agentDirectory } from '../../api/agent-platform';
import type { PlatformTeam } from './components/AgentTargetPicker.vue';

const router = useRouter();
const auth = useAuthStore();
const tokenDraft = ref('');
const loginError = ref('');
const loading = ref(false);
const spaceVisible = ref(false);
const teams = ref<readonly PlatformTeam[]>([]);
const space = ref('personal');

const tokenValid = computed(() => {
  const token = tokenDraft.value;
  return !!token.trim() && token.length <= 512 && !/\s/.test(token) && !/^Bearer\b/i.test(token);
});

function enterMain() {
  void router.push('/overview');
}

async function bankLogin() {
  loginError.value = '';
  if (!tokenDraft.value.trim()) {
    loginError.value = '请先输入行内用户token。';
    return;
  }
  if (!tokenValid.value) {
    loginError.value = '请填写不含空白、换行或 Bearer 前缀的原始 token，最多 512 个字符。';
    return;
  }
  loading.value = true;
  try {
    const items = await agentDirectory.getTeams({ token: tokenDraft.value });
    teams.value = items;
    space.value = 'personal';
    spaceVisible.value = true;
  } catch (error) {
    const status = (error as { status?: unknown } | null)?.status;
    loginError.value =
      status === 401 || status === 403
        ? 'token 无效或已过期，请重新输入。'
        : '行内平台目录查询失败，请稍后重试。';
  } finally {
    loading.value = false;
  }
}

function confirmSpace() {
  const team = teams.value.find((item) => item.teamId === space.value);
  auth.loginBank(
    tokenDraft.value,
    space.value === 'personal' ? '' : space.value,
    space.value === 'personal' ? '个人空间' : (team?.teamName ?? ''),
  );
  spaceVisible.value = false;
  tokenDraft.value = '';
  ElMessage.success('登录成功');
  enterMain();
}

function externalLogin() {
  auth.loginExternal();
  enterMain();
}
</script>

<template>
  <div class="welcome">
    <div class="welcome-card">
      <div class="welcome-brand">
        <b>智能体评测中心</b><small>AgentGate · 评测工作台</small>
      </div>
      <h1 class="welcome-title">欢迎页面</h1>
      <p class="welcome-hint">请输入行内用户token</p>
      <div class="token-row">
        <input
          v-model="tokenDraft"
          class="token-input"
          type="text"
          maxlength="512"
          autocomplete="off"
          spellcheck="false"
          placeholder="粘贴行内平台签发的 token"
          aria-label="请输入行内用户token"
          :disabled="loading"
          @input="loginError = ''"
          @keyup.enter="bankLogin"
        />
        <ElButton type="primary" :loading="loading" :disabled="loading" @click="bankLogin">
          行内Login
        </ElButton>
      </div>
      <div class="token-meta">
        <span v-if="loginError" role="alert" class="token-error">{{ loginError }}</span>
        <span class="token-count">{{ tokenDraft.length }} / 512</span>
      </div>
      <div class="external-row">
        <ElButton :disabled="loading" @click="externalLogin">行外Login</ElButton>
      </div>
      <p class="welcome-note">
        行内 Login：访问行内智能体平台真实目录（需有效 token，登录后选择个人/团队空间）。<br />
        行外 Login：直接进入本地环境，智能体目录来自本地虚拟地址。
      </p>
    </div>
    <ElDialog v-model="spaceVisible" title="选择个人/团队空间" width="440px" :close-on-click-modal="false">
      <div class="space-field">
        <label for="welcome-space">个人/团队空间</label>
        <ElSelect id="welcome-space" v-model="space" style="width: 100%">
          <ElOption value="personal" label="个人空间" />
          <ElOption
            v-for="team in teams"
            :key="team.teamId"
            :value="team.teamId"
            :label="`${team.teamName} · ${team.teamId}`"
          />
        </ElSelect>
        <p v-if="!teams.length" class="space-note">当前 token 名下没有团队，将以个人空间进入。</p>
      </div>
      <template #footer>
        <ElButton @click="spaceVisible = false">取消</ElButton>
        <ElButton type="primary" @click="confirmSpace">确认</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.welcome {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, #f3f4f6 0%, #eef5f3 100%);
}
.welcome-card {
  width: 560px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 48px 44px;
}
.welcome-brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.welcome-brand b {
  font-size: 22px;
}
.welcome-brand small {
  color: #6b7280;
  font-size: 13px;
}
.welcome-title {
  font-size: 28px;
  font-weight: 700;
  margin: 18px 0 4px;
}
.welcome-hint {
  font-size: 14px;
  color: #374151;
  margin: 0 0 22px;
}
.token-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.token-input {
  flex: 1;
  height: 40px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 0 12px;
  font: inherit;
  outline: none;
}
.token-input:focus {
  border-color: #07ac8e;
  box-shadow: 0 0 0 3px #07ac8e22;
}
.token-meta {
  display: flex;
  justify-content: space-between;
  min-height: 20px;
  margin-top: 6px;
  gap: 12px;
}
.token-error {
  color: #dc2626;
  font-size: 12px;
}
.token-count {
  color: #6b7280;
  font-size: 12px;
  margin-left: auto;
}
.external-row {
  margin-top: 18px;
}
.welcome-note {
  margin: 26px 0 0;
  padding-top: 16px;
  border-top: 1px dashed #e5e7eb;
  color: #6b7280;
  font-size: 13px;
  line-height: 1.7;
}
.space-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.space-field label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}
.space-note {
  margin: 0;
  color: #6b7280;
  font-size: 13px;
}
</style>
