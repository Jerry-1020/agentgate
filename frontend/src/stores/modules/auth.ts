import { defineStore } from 'pinia';

export type LoginMode = 'bank' | 'external';

export interface AuthSession {
  loginMode: LoginMode;
  token: string;
  teamId: string;
  teamName: string;
}

// 纯内存会话：token 不进 localStorage/sessionStorage（与平台安全约定一致），
// 刷新页面回到欢迎页重新登录。
export const useAuthStore = defineStore('agentgate-auth', {
  state: (): AuthSession => ({
    loginMode: 'bank',
    token: '',
    teamId: 'personal',
    teamName: '个人空间',
  }),
  getters: {
    authenticated: (state) => state.loginMode === 'bank' ? !!state.token : true,
    isBank: (state) => state.loginMode === 'bank',
    modeLabel: (state) =>
      state.loginMode === 'bank'
        ? `行内 · ${state.teamId === 'personal' ? '个人空间' : state.teamName || state.teamId}`
        : '行外模式 · 本地环境',
  },
  actions: {
    loginBank(token: string, teamId: string, teamName: string) {
      this.loginMode = 'bank';
      this.token = token;
      this.teamId = teamId;
      this.teamName = teamName;
    },
    loginExternal() {
      this.loginMode = 'external';
      this.token = '';
      this.teamId = '';
      this.teamName = '';
    },
    logout() {
      this.$reset();
    },
  },
});
