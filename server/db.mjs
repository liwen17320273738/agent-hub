import { DatabaseSync } from 'node:sqlite'
import { mkdirSync, existsSync } from 'node:fs'
import { dirname } from 'node:path'

/**
 * 使用 Node 内置 `node:sqlite`（Node 22.5+），避免原生模块编译与 pnpm 脚本策略问题。
 * @param {string} databasePath
 */
export function openDatabase(databasePath) {
  const dir = dirname(databasePath)
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
  const db = new DatabaseSync(databasePath)
  try {
    db.exec('PRAGMA journal_mode = WAL')
  } catch {
    /* ignore */
  }
  db.exec(`
    CREATE TABLE IF NOT EXISTS orgs (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      org_id TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      display_name TEXT,
      role TEXT NOT NULL DEFAULT 'member',
      created_at INTEGER NOT NULL,
      FOREIGN KEY (org_id) REFERENCES orgs(id)
    );
    CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY,
      org_id TEXT NOT NULL,
      agent_id TEXT NOT NULL,
      title TEXT NOT NULL,
      summary TEXT,
      messages_json TEXT NOT NULL,
      created_by TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      revision INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY (org_id) REFERENCES orgs(id)
    );
    CREATE INDEX IF NOT EXISTS idx_conv_org ON conversations(org_id);

    CREATE TABLE IF NOT EXISTS pipeline_tasks (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL DEFAULT 'web',
      source_message_id TEXT,
      source_user_id TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      current_stage_id TEXT NOT NULL DEFAULT 'intake',
      stages_json TEXT NOT NULL DEFAULT '[]',
      artifacts_json TEXT NOT NULL DEFAULT '[]',
      created_by TEXT NOT NULL DEFAULT 'system',
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_pt_status ON pipeline_tasks(status);
    CREATE INDEX IF NOT EXISTS idx_pt_stage ON pipeline_tasks(current_stage_id);
  `)
  migrateConversationRevisionSqlite(db)
  return db
}

/** 旧库无 revision 列时补齐（乐观锁） */
function migrateConversationRevisionSqlite(db) {
  const cols = db.prepare('PRAGMA table_info(conversations)').all()
  const names = new Set(cols.map((c) => c.name))
  if (!names.has('revision')) {
    db.exec('ALTER TABLE conversations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
  }
}
