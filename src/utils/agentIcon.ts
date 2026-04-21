/**
 * Resolve agent icon name to a registered Element Plus icon component.
 * Unknown names fall back to User so the sidebar/chat never shows an empty box.
 */
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { User } from '@element-plus/icons-vue'
import type { Component } from 'vue'

const icons = ElementPlusIconsVue as Record<string, Component>

export function resolveAgentIcon(name: string | undefined | null): Component {
  if (!name || typeof name !== 'string') return User
  const c = icons[name]
  return c ?? User
}
