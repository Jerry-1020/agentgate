module.exports = {
  root: true, env: { browser: true, es2022: true },
  extends: ['eslint:recommended', 'plugin:vue/vue3-essential'],
  parserOptions: { parser: '@typescript-eslint/parser', ecmaVersion: 'latest', sourceType: 'module', extraFileExtensions: ['.vue'] },
  plugins: ['@typescript-eslint'],
  rules: {
    'no-undef': 'off', 'no-unused-vars': 'off',
    'vue/multi-word-component-names': 'off',
    'no-empty': ['error', { allowEmptyCatch: true }],
  },
}
