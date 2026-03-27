/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 生产构建也走同源 `/api/proxy/*`（需在 Nginx 等配置与 dev 相同的反向代理） */
  readonly VITE_USE_RELATIVE_PROXY?: string
  /** 设为 `true` 启用企业模式：登录、服务端会话、组织共享对话、LLM 经服务端代理 */
  readonly VITE_ENTERPRISE?: string
  /**
   * 企业模式 API 前缀。开发默认 `/api/hub`（由 Vite 代理）；生产默认同源根路径。
   * 前后端分域时设为完整 origin+path，例如 `https://api.example.com`
   */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
