module.exports = {
  root: true,
  env: {
    browser: true,
    es2020: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: {
      jsx: true,
    },
  },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended', 'plugin:react-hooks/recommended'],
  ignorePatterns: ['dist/', 'node_modules/', '*.config.*'],
  rules: {
    // 历史页面中存在较多演进中的未用参数，第一阶段只作为 TypeScript 构建风险处理。
    '@typescript-eslint/no-unused-vars': 'off',
    // 后台 API 与第三方组件数据形态较多，后续按模块逐步收窄 any。
    '@typescript-eslint/no-explicit-any': 'off',
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
  },
};
