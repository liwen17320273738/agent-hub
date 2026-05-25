const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']

export function isImageAssetPath(path: string): boolean {
  const lower = (path || '').split('?')[0].toLowerCase()
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

/** Normalize artifact filePath/storage_path to a worktree-relative path when possible. */
export function normalizeWorktreeRelativePath(path: string, taskId?: string): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) return path

  let rel = path.replace(/\\/g, '/').replace(/^\/+/, '')

  if (taskId) {
    const taskScoped = rel.match(
      new RegExp(`${taskId.replace(/-/g, '\\-')}/(ui_mockups|architecture_diagrams)/(.+)$`, 'i'),
    )
    if (taskScoped) {
      return `${taskScoped[1]}/${taskScoped[2]}`
    }
  }

  const visualDir = rel.match(/(?:^|\/)(ui_mockups|architecture_diagrams)\/(.+)$/i)
  if (visualDir) {
    return `${visualDir[1]}/${visualDir[2]}`
  }

  return rel
}

/** URL for binary/HTML preview (FileResponse), not the JSON worktree reader. */
export function resolveWorktreeRawUrl(taskId: string, path: string): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) return path

  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const rel = normalizeWorktreeRelativePath(path, taskId)
  const encoded = rel.split('/').map((segment) => encodeURIComponent(segment)).join('/')
  return `${baseUrl}/tasks/${taskId}/worktree/raw/${encoded}`
}
