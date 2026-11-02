import { noInfiniteMotion } from './scripts/motion-rules.js'
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'src/shared/api/types.ts'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'attention': { rules: { 'no-infinite-motion': noInfiniteMotion } }, 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      'attention/no-infinite-motion': 'error',
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'no-console': ['error', { allow: ['warn', 'error'] }],
    },
  },
  { files: ['**/*.test.{ts,tsx}', '**/__tests__/**'], rules: { 'attention/no-infinite-motion': 'off' } },
)
