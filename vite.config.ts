import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { DELIVERY_DOCS, ensureDeliveryTemplates, listDeliveryDocs, readDeliveryDoc, writeDeliveryDoc } from './server/deliveryDocs.mjs'

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
  '/api/proxy/anthropic': {
    target: 'https://api.anthropic.com',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/proxy\/anthropic/, ''),
  },
  '/api/proxy/gemini': {
    target: 'https://generativelanguage.googleapis.com',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/proxy\/gemini/, ''),
  },
  '/api/proxy/zhipu': {
    target: 'https://open.bigmodel.cn',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/proxy\/zhipu/, '/api/paas/v4'),
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
  plugins: [
    vue(),
    {
      name: 'wayne-delivery-docs-dev',
      configureServer(server) {
        server.middlewares.use('/api/hub/delivery-docs', async (req, res, next) => {
          try {
            await ensureDeliveryTemplates()

            if (req.method === 'GET' && req.url === '/') {
              const docs = await listDeliveryDocs()
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ docs }))
              return
            }

            if (req.method === 'POST' && req.url === '/init') {
              const docs = await listDeliveryDocs()
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ docs }))
              return
            }

            const pathname = req.url?.startsWith('/') ? req.url.slice(1) : req.url || ''
            const name = decodeURIComponent(pathname.split('?')[0] || '')
            if (!DELIVERY_DOCS.some((doc) => doc.name === name)) {
              next()
              return
            }

            if (req.method === 'GET') {
              const doc = await readDeliveryDoc(name)
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify(doc))
              return
            }

            if (req.method === 'PUT') {
              let raw = ''
              req.on('data', (chunk) => {
                raw += chunk
              })
              req.on('end', async () => {
                const body = raw ? JSON.parse(raw) : {}
                const doc = await writeDeliveryDoc(name, String(body.content || ''))
                res.setHeader('Content-Type', 'application/json')
                res.end(JSON.stringify(doc))
              })
              return
            }
          } catch (error) {
            res.statusCode = 500
            res.setHeader('Content-Type', 'application/json')
            res.end(
              JSON.stringify({
                error: error instanceof Error ? error.message : String(error),
              }),
            )
            return
          }

          next()
        })
      },
    },
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5200,
    // More specific /api/proxy/* routes MUST come before the catch-all /api → backend
    proxy: {
      ...apiProxy,
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5200,
    proxy: {
      ...apiProxy,
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
