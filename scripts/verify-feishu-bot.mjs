/**
 * 验证飞书自定义应用凭证是否可用：获取 tenant_access_token。
 * 控制台：https://open.feishu.cn/app → 创建企业自建应用 → 凭证与基础信息 → App ID / App Secret
 * 需在「权限管理」中按需开通 API；仅获取 token 一般无需额外权限。
 *
 * 用法：
 *   FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx node scripts/verify-feishu-bot.mjs
 * 或在项目根目录配置 .env.local（勿提交）：FEISHU_APP_ID=... FEISHU_APP_SECRET=...
 */
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

function loadDotenvLocal() {
  const p = resolve(root, ".env.local");
  if (!existsSync(p)) return;
  const text = readFileSync(p, "utf8");
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const i = t.indexOf("=");
    if (i === -1) continue;
    const key = t.slice(0, i).trim();
    let val = t.slice(i + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (!process.env[key]) process.env[key] = val;
  }
}

loadDotenvLocal();

const APP_ID = process.env.FEISHU_APP_ID?.trim();
const APP_SECRET = process.env.FEISHU_APP_SECRET?.trim();

const URL =
  "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal";

async function main() {
  if (!APP_ID || !APP_SECRET) {
    console.error(
      "缺少环境变量：请设置 FEISHU_APP_ID 与 FEISHU_APP_SECRET（可写入项目根 .env.local）",
    );
    process.exit(1);
  }

  const res = await fetch(URL, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      app_id: APP_ID,
      app_secret: APP_SECRET,
    }),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    console.error("HTTP", res.status, res.statusText);
    console.error(JSON.stringify(data, null, 2));
    process.exit(1);
  }

  if (data.code !== 0) {
    console.error("飞书 API 返回错误：", data.msg || data);
    console.error(JSON.stringify(data, null, 2));
    process.exit(1);
  }

  const token = data.tenant_access_token;
  const expire = data.expire;
  if (!token) {
    console.error("响应中无 tenant_access_token：", JSON.stringify(data, null, 2));
    process.exit(1);
  }

  console.log("飞书应用凭证验证成功。");
  console.log("- tenant_access_token 已获取（前 16 字符）:", String(token).slice(0, 16) + "…");
  console.log("- 有效期（秒）:", expire ?? "(未返回)");
  console.log("");
  console.log("若要在群聊里使用机器人：开放平台上该应用需开启「机器人」能力，发布版本后，在目标群中 @机器人 或 群设置 → 群机器人 → 添加。");
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
