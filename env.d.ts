/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 生产构建也走同源 `/api/proxy/*`（需在 Nginx 等配置与 dev 相同的反向代理） */
  readonly VITE_USE_RELATIVE_PROXY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
