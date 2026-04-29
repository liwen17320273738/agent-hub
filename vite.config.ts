/// <reference types="node" />
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { DELIVERY_DOCS, ensureDeliveryTemplates, listDeliveryDocs, readDeliveryDoc, writeDeliveryDoc } from './server/deliveryDocs.mjs'

type DevServerResponse = {
  readonly headersSent: boolean
  statusCode: number
  setHeader(name: string, value: string | number | readonly string[]): void
  end(chunk?: string | Uint8Array): void
}

/** 统一 JSON 错误响应，避免重复发送时抛错。 */
function sendJsonError(res: DevServerResponse, error: unknown, statusCode = 500) {
  if (res.headersSent) {
    return
  }
  const message = error instanceof Error ? error.message : String(error)
  res.statusCode = statusCode
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  try {
    res.end(JSON.stringify({ error: message }))
  } catch {
    res.end('{"error":"Internal server error"}')
  }
}

/** 成功 JSON 响应；若序列化失败则回退为统一错误。 */
function sendJson(res: DevServerResponse, data: unknown) {
  if (res.headersSent) {
    return
  }
  try {
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify(data))
  } catch (error) {
    sendJsonError(res, error)
  }
}

/** Marketplace crawl can take 1–2+ min; node-http-proxy defaults otherwise drop the connection (worse when the tab is backgrounded). */
const backendDevProxy = {
  target: 'http://127.0.0.1:8000',
  changeOrigin: true,
  timeout: 600_000,
  proxyTimeout: 600_000,
} as const

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

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const pipelineKeyForClient =
    (env.VITE_PIPELINE_API_KEY || env.PIPELINE_API_KEY || '').trim()

  return {
  base,
  define: {
    'import.meta.env.VITE_PIPELINE_API_KEY': JSON.stringify(pipelineKeyForClient),
  },
  plugins: [
    vue(),
    {
      name: 'wayne-delivery-docs-dev',
      configureServer(server) {
        server.middlewares.use(
          '/api/hub/delivery-docs',
          async (req, res, next) => {
            const run = async () => {
            await ensureDeliveryTemplates()

            if (req.method === 'GET' && req.url === '/') {
              const docs = await listDeliveryDocs()
              sendJson(res, { docs })
              return
            }

            if (req.method === 'POST' && req.url === '/init') {
              const docs = await listDeliveryDocs()
              sendJson(res, { docs })
              return
            }

            const pathname = req.url?.startsWith('/') ? req.url.slice(1) : req.url || ''
            let name: string
            try {
              name = decodeURIComponent(pathname.split('?')[0] || '')
            } catch {
              sendJsonError(res, new Error('Invalid path encoding'), 400)
              return
            }
            if (!DELIVERY_DOCS.some((doc: { name: string }) => doc.name === name)) {
              next()
              return
            }

            if (req.method === 'GET') {
              const doc = await readDeliveryDoc(name)
              sendJson(res, doc)
              return
            }

            if (req.method === 'PUT') {
              let raw = ''
              req.on('data', (chunk) => {
                raw += chunk
              })
              req.on('end', async () => {
                try {
                  let body: Record<string, unknown> = {}
                  if (raw) {
                    try {
                      body = JSON.parse(raw) as Record<string, unknown>
                    } catch {
                      sendJsonError(res, new Error('Invalid JSON body'), 400)
                      return
                    }
                  }
                  const doc = await writeDeliveryDoc(name, String(body.content || ''))
                  sendJson(res, doc)
                } catch (error) {
                  sendJsonError(res, error)
                }
              })
              req.on('error', (err) => {
                sendJsonError(res, err)
              })
              return
            }

            next()
            }

            try {
              await run()
            } catch (error) {
              sendJsonError(res, error)
            }
          },
        )
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
      '/api': { ...backendDevProxy },
      '/health': { ...backendDevProxy },
    },
  },
  preview: {
    port: 5200,
    proxy: {
      ...apiProxy,
      '/api': { ...backendDevProxy },
    },
  },
  }
})
