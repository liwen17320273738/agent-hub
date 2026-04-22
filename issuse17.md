Issue 17 · 公网多通道接入（执行记录）

## 当前状态

| 路线 | 状态 | 说明 |
|------|------|------|
| A. iOS 快捷指令 / HTTP Shortcuts | ✅ 验证通过 | 公网隧道 → OpenClaw intake → Plan/Act 全链路 OK |
| B. 飞书自建应用 | 🟡 差 verification token | APP_ID / APP_SECRET 已配；需到飞书开放平台拿 VERIFICATION_TOKEN |
| D. QQ via NapCat | 🟡 待启动 | 用户决定是否开 |
| 公网隧道 | ✅ 在跑 | 见下方 URL |

## 公网隧道

```
https://puerto-ide-wilderness-leads.trycloudflare.com
```

> ⚠️ trycloudflare 免费临时隧道，关机或 7 天后会变。生产前用 `cloudflared tunnel create agent-hub` 创建具名隧道。

## Route A — iOS 快捷指令配方

### 前置
- `PIPELINE_API_KEY` = `test-key-123`（正式环境请改强密码）
- 公网 URL = `https://puerto-ide-wilderness-leads.trycloudflare.com`

### 步骤

1. 打开 **快捷指令 App** → 右上角 `+` 新建
2. 添加动作 **"询问输入"**
   - 提示：`任务标题`
   - 输入类型：文本
3. 再加一个 **"询问输入"**
   - 提示：`任务描述（可留空）`
   - 输入类型：文本
4. 添加 **"获取 URL 内容"**
   - URL：`https://puerto-ide-wilderness-leads.trycloudflare.com/api/gateway/openclaw/intake`
   - 方法：`POST`
   - 请求头：
     - `Authorization` = `Bearer test-key-123`
     - `Content-Type` = `application/json`
   - 请求体（JSON）：

```json
{
  "title": "<魔法变量：任务标题>",
  "description": "<魔法变量：任务描述>",
  "source": "openclaw",
  "userId": "wayne-ios",
  "messageId": "ios-shortcut",
  "planMode": true,
  "autoFinalAccept": false
}
```

5. 添加 **"显示结果"** → 把上一步返回值显示出来
6. 命名快捷指令为 **"派活给 AI 兵团"**，加到主屏幕 Widget

### planMode 说明
- `planMode: true`（默认推荐）：先出方案、返回审批链接，你确认后再跑
- `planMode: false`：直接创建任务、自动启动 pipeline
- `autoFinalAccept: true`：跑完自动上线，不停在验收环节

### 验收闭环
任务跑完后停在 `awaiting_final_acceptance`。
- **Web**：打开 `http://localhost:5200`（同 WiFi 手机也能访问）→ 任务详情 → "通过验收" / "打回重做"
- **Plan Inbox**：`http://localhost:5200/plan-inbox` 查看待审批计划
- **API**：调 approve/reject 链接（返回的 `planSession.links` 里有）

### 已验证（2026-04-22）

```
POST /api/gateway/openclaw/intake  planMode=true
→ {"ok":true, "action":"plan_pending", "plan":{5步方案}, "planSession":{links}}  ✅

POST /api/gateway/openclaw/intake  planMode=false
→ {"ok":true, "taskId":"a726...", "pipelineTriggered":true}  ✅

POST .../reject
→ {"ok":true, "action":"plan_rejected"}  ✅
```

## Route B — 飞书

### 已配置
```
FEISHU_APP_ID=cli_a94cf8aac7fb9bc4
FEISHU_APP_SECRET=RWtnvm5nQDVcgX0vGiGc5cYxk0UuEDcM
```

### 缺失
```
FEISHU_VERIFICATION_TOKEN=<从飞书开放平台获取>
```

### 获取方法
1. 登录 [飞书开放平台](https://open.feishu.cn/app) → 进入你的应用
2. 左侧 **事件与回调** → **加密策略**
3. 复制 **Verification Token**
4. 贴给我，我写进 `.env` 并重启

### 配完后飞书后台要填的两个 URL
- 事件订阅请求地址：`https://puerto-ide-wilderness-leads.trycloudflare.com/api/gateway/feishu/webhook`
- 卡片回调请求地址：同上

### 事件类型勾选
- `im.message.receive_v1`（接收消息）

## Route D — QQ via NapCat（可选）

需要用户确认后再开。步骤：
1. Docker 启动 NapCat
2. 扫码登录 QQ 小号
3. 配置 HTTP Server 指向公网 URL
4. 告知 access_token，写进 `.env`

## Android HTTP Shortcuts 配方

1. 安装 [HTTP Shortcuts](https://play.google.com/store/apps/details?id=ch.rmy.android.http_shortcuts)
2. 新建 Shortcut → 方法 `POST`
3. URL：`https://puerto-ide-wilderness-leads.trycloudflare.com/api/gateway/openclaw/intake`
4. Header：
   - `Authorization` = `Bearer test-key-123`
   - `Content-Type` = `application/json`
5. Body（JSON）：同 iOS 配方
6. 添加到桌面
