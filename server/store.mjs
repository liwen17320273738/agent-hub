import { openDatabase } from './db.mjs'

/**
 * @param {{ DATABASE_URL?: string, DATABASE_PATH: string }} env
 */
export async function createStore(env) {
  if (env.DATABASE_URL?.trim()) {
    return createPgStore(env.DATABASE_URL.trim())
  }
  const db = openDatabase(env.DATABASE_PATH)
  return createSqliteStore(db)
}

/** @param {import('node:sqlite').DatabaseSync} db */
function createSqliteStore(db) {
  return {
    kind: 'sqlite',

    countUsers() {
      return Promise.resolve(db.prepare('SELECT COUNT(*) AS c FROM users').get().c)
    },

    bootstrapOrgAndAdmin({ orgId, userId, email, passwordHash, displayName, role, now }) {
      db.prepare('INSERT INTO orgs (id, name, created_at) VALUES (?, ?, ?)').run(orgId, '默认企业', now)
      db.prepare(
        'INSERT INTO users (id, org_id, email, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
      ).run(userId, orgId, email, passwordHash, displayName, role, now)
      return Promise.resolve()
    },

    getUserSession(userId) {
      const row = db
        .prepare(
          `SELECT u.id, u.org_id, u.email, u.display_name, u.role, o.name AS org_name
           FROM users u JOIN orgs o ON o.id = u.org_id WHERE u.id = ?`,
        )
        .get(userId)
      return Promise.resolve(row ?? null)
    },

    findUserForLogin(email) {
      return Promise.resolve(db.prepare('SELECT id, password_hash FROM users WHERE email = ?').get(email) ?? null)
    },

    getConversation(id, orgId) {
      return Promise.resolve(
        db.prepare('SELECT * FROM conversations WHERE id = ? AND org_id = ?').get(id, orgId) ?? null,
      )
    },

    listConversations(orgId) {
      const rows = db
        .prepare(
          'SELECT id, org_id, agent_id, title, summary, messages_json, created_at, updated_at, revision FROM conversations WHERE org_id = ? ORDER BY updated_at DESC',
        )
        .all(orgId)
      return Promise.resolve(rows)
    },

    insertConversation({ id, orgId, agentId, title, createdBy, now }) {
      db.prepare(
        `INSERT INTO conversations (id, org_id, agent_id, title, summary, messages_json, created_by, created_at, updated_at, revision)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
      ).run(id, orgId, agentId, title, null, JSON.stringify([]), createdBy, now, now)
      const row = db.prepare('SELECT * FROM conversations WHERE id = ?').get(id)
      return Promise.resolve(row)
    },

    /**
     * @param {number} expectedRevision
     */
    updateConversationOptimistic({ id, orgId, title, summary, messagesJson, updatedAt, expectedRevision }) {
      const stmt = db.prepare(
        `UPDATE conversations SET title = ?, summary = ?, messages_json = ?, updated_at = ?, revision = revision + 1
         WHERE id = ? AND org_id = ? AND revision = ?`,
      )
      const info = stmt.run(title, summary, messagesJson, updatedAt, id, orgId, expectedRevision)
      if (info.changes === 0) {
        const cur = db.prepare('SELECT * FROM conversations WHERE id = ? AND org_id = ?').get(id, orgId)
        return Promise.resolve({ ok: false, current: cur ?? null })
      }
      const row = db.prepare('SELECT * FROM conversations WHERE id = ?').get(id)
      return Promise.resolve({ ok: true, row })
    },

    deleteConversation(id, orgId) {
      const r = db.prepare('DELETE FROM conversations WHERE id = ? AND org_id = ?').run(id, orgId)
      return Promise.resolve(r.changes)
    },

    findUserIdByEmail(email) {
      return Promise.resolve(db.prepare('SELECT id FROM users WHERE email = ?').get(email) ?? null)
    },

    insertMemberUser({ id, orgId, email, passwordHash, displayName, role, now }) {
      db.prepare(
        'INSERT INTO users (id, org_id, email, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
      ).run(id, orgId, email, passwordHash, displayName, role, now)
      return Promise.resolve()
    },
  }
}

async function ensurePgTables(pool) {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS orgs (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      created_at BIGINT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      org_id TEXT NOT NULL REFERENCES orgs(id),
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      display_name TEXT,
      role TEXT NOT NULL DEFAULT 'member',
      created_at BIGINT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY,
      org_id TEXT NOT NULL REFERENCES orgs(id),
      agent_id TEXT NOT NULL,
      title TEXT NOT NULL,
      summary TEXT,
      messages_json TEXT NOT NULL,
      created_by TEXT,
      created_at BIGINT NOT NULL,
      updated_at BIGINT NOT NULL,
      revision INT NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_conv_org ON conversations(org_id);
  `)
  try {
    await pool.query('ALTER TABLE conversations ADD COLUMN IF NOT EXISTS revision INT NOT NULL DEFAULT 0')
  } catch {
    /* 旧版 PostgreSQL 可手工迁移 */
  }
}

async function createPgStore(databaseUrl) {
  const { default: pg } = await import('pg')
  const pool = new pg.Pool({ connectionString: databaseUrl, max: 20, idleTimeoutMillis: 30_000 })
  await ensurePgTables(pool)

  return {
    kind: 'postgres',
    pool,

    async countUsers() {
      const r = await pool.query('SELECT COUNT(*)::int AS c FROM users')
      return r.rows[0].c
    },

    async bootstrapOrgAndAdmin({ orgId, userId, email, passwordHash, displayName, role, now }) {
      await pool.query('INSERT INTO orgs (id, name, created_at) VALUES ($1, $2, $3)', [orgId, '默认企业', now])
      await pool.query(
        'INSERT INTO users (id, org_id, email, password_hash, display_name, role, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)',
        [userId, orgId, email, passwordHash, displayName, role, now],
      )
    },

    async getUserSession(userId) {
      const r = await pool.query(
        `SELECT u.id, u.org_id, u.email, u.display_name, u.role, o.name AS org_name
         FROM users u JOIN orgs o ON o.id = u.org_id WHERE u.id = $1`,
        [userId],
      )
      return r.rows[0] ?? null
    },

    async findUserForLogin(email) {
      const r = await pool.query('SELECT id, password_hash FROM users WHERE email = $1', [email])
      return r.rows[0] ?? null
    },

    async getConversation(id, orgId) {
      const r = await pool.query('SELECT * FROM conversations WHERE id = $1 AND org_id = $2', [id, orgId])
      return r.rows[0] ?? null
    },

    async listConversations(orgId) {
      const r = await pool.query(
        'SELECT id, org_id, agent_id, title, summary, messages_json, created_at, updated_at, revision FROM conversations WHERE org_id = $1 ORDER BY updated_at DESC',
        [orgId],
      )
      return r.rows
    },

    async insertConversation({ id, orgId, agentId, title, createdBy, now }) {
      await pool.query(
        `INSERT INTO conversations (id, org_id, agent_id, title, summary, messages_json, created_by, created_at, updated_at, revision)
         VALUES ($1, $2, $3, $4, NULL, $5, $6, $7, $8, 0)`,
        [id, orgId, agentId, title, JSON.stringify([]), createdBy, now, now],
      )
      const r = await pool.query('SELECT * FROM conversations WHERE id = $1', [id])
      return r.rows[0]
    },

    async updateConversationOptimistic({ id, orgId, title, summary, messagesJson, updatedAt, expectedRevision }) {
      const r = await pool.query(
        `UPDATE conversations SET title = $1, summary = $2, messages_json = $3, updated_at = $4, revision = revision + 1
         WHERE id = $5 AND org_id = $6 AND revision = $7
         RETURNING *`,
        [title, summary, messagesJson, updatedAt, id, orgId, expectedRevision],
      )
      if (r.rowCount === 0) {
        const cur = await pool.query('SELECT * FROM conversations WHERE id = $1 AND org_id = $2', [id, orgId])
        return { ok: false, current: cur.rows[0] ?? null }
      }
      return { ok: true, row: r.rows[0] }
    },

    async deleteConversation(id, orgId) {
      const r = await pool.query('DELETE FROM conversations WHERE id = $1 AND org_id = $2', [id, orgId])
      return r.rowCount ?? 0
    },

    async findUserIdByEmail(email) {
      const r = await pool.query('SELECT id FROM users WHERE email = $1', [email])
      return r.rows[0] ?? null
    },

    async insertMemberUser({ id, orgId, email, passwordHash, displayName, role, now }) {
      await pool.query(
        'INSERT INTO users (id, org_id, email, password_hash, display_name, role, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)',
        [id, orgId, email, passwordHash, displayName, role, now],
      )
    },
  }
}
