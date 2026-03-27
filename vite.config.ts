import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const apiProxy = {
  '/api/proxy/dashscope': {
    target: 'https://dashscope.aliyuncs.com',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/proxy\/dashscope/, '/compatible-mode/v1'),
  },
  '/api/proxy/deepseek': {
    target: 'https://api.deepseek.com',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/proxy\/deepseek/, '/v1'),
  },
  '/api/proxy/openai': {
    target: 'https://api.openai.com',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/proxy\/openai/, '/v1'),
  },
}

/**
 * GitHub Pages 项目页地址为 https://<user>.github.io/<repo>/
 * 时需在构建环境设置 VITE_BASE_PATH=/<repo>/（工作流已按仓库名自动设置）。
 * 用户主页仓库 (<user>.github.io) 请在仓库 Variables 中将 VITE_BASE_PATH 设为 /
 */
const base = process.env.VITE_BASE_PATH || '/'

export default defineConfig({
  base,
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5200,
    proxy: {
      /** 企业模式 API（见 server/index.mjs）；与下方 LLM 反向代理路径互不覆盖 */
      '/api/hub': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api\/hub/, ''),
      },
      ...apiProxy,
    },
  },
  preview: {
    port: 5200,
    proxy: {
      '/api/hub': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api\/hub/, ''),
      },
      ...apiProxy,
    },
  },
})
