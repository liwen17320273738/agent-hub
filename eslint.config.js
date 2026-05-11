import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default tseslint.config(
  { ignores: ['dist/', 'node_modules/', 'server/', 'playwright-report/', 'test-results/'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    rules: {
      // Allow any in Vue SFCs (common for template refs and complex component props)
      '@typescript-eslint/no-explicit-any': 'warn',
      // Allow unused vars with _ prefix (conventional "intentionally unused")
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      // Vue-specific
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'warn',
    },
  },
)
