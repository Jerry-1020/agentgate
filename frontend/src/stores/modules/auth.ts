import { defineStore } from 'pinia';

export type LoginMode = 'bank' | 'external' | 'integrated';

export interface PlatformIdentity {
  token: string;
  teamId: string;
  teamName: string;
  userId: string;
  userName: string;
}

export interface AuthSession extends PlatformIdentity {
  loginMode: LoginMode;
  platformReady: boolean;
}

// Memory-only identity. Do not enable persistence for this store.
export const useAuthStore = defineStore('agentgate-auth', {
  state: (): AuthSession => ({
    loginMode: 'bank',
    token: '',
    teamId: '',
    teamName: '个人空间',
    userId: '',
    userName: '',
    platformReady: false,
  }),
  getters: {
    authenticated: (state) => state.loginMode === 'external'
      ? true
      : state.loginMode === 'integrated'
        ? state.platformReady
        : !!state.token,
    isBank: (state) => state.loginMode === 'bank',
    isIntegrated: (state) => state.loginMode === 'integrated',
    usesPlatformDirectory: (state) => state.loginMode !== 'external',
    modeLabel: (state) =>
      state.loginMode === 'integrated'
        ? '集成模式'
        : state.loginMode === 'bank'
        ? state.teamId
          ? `行内 · ${state.teamName || state.teamId}`
          : '行内 · 个人空间'
        : '行外模式 · 本地环境',
  },
  actions: {
    initializePlatform(identity: PlatformIdentity) {
      this.$patch({ ...identity, loginMode: 'integrated', platformReady: true });
    },
    loginBank(token: string, teamId: string, teamName: string) {
      this.$reset();
      this.$patch({ loginMode: 'bank', token, teamId, teamName });
    },
    loginExternal() {
      this.$reset();
      this.$patch({ loginMode: 'external', teamName: '' });
    },
    logout() {
      this.$reset();
    },
  },
});
