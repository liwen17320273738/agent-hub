一、必须修才能真正跑通的（高危）
1. QQ webhook 的入站协议是错的
/gateway/qq/webhook 当前 schema：

class QQWebhookBody(BaseModel):
    content: Optional[str]
    author: Optional[Dict]
    id: Optional[str]
但 OneBot v11（NapCat / go-cqhttp / Lagrange）实际推送的是：

{"post_type":"message","message_type":"private","user_id":12345,
 "raw_message":"...","self_id":...,"message_id":...}
所以现在桥转过来的消息 0 条能解析。需要新写一个 QQOneBotEvent 解析。

2. 飞书事件订阅 v2 的加密 + URL verification 没处理
飞书 v2 默认开 encrypt_key，body 是 {"encrypt":"<aes>"}，要先 AES 解密
url_verification 校验事件不是带 header.token，是顶层 {"challenge","token","type":"url_verification"}
当前 challenge 直接 echo 了，但没校验 token，等于谁都能注册一个回调把你这个 endpoint 拿走
3. 反馈并发会撞同一个 task
用户连续发 3 条"改下颜色"，asyncio.create_task(_apply_feedback_in_background) 会并行 spawn 3 个 e2e 写同一个 project_dir、同一个 db_task.status。需要：

Redis 锁 feedback:running:<task_id>（SETNX + TTL）
拿不到锁就把后来的反馈合并到队列里（或直接告诉用户"上一轮还没跑完"）
4. repo_url 是 IM 用户可控的 SSRF 攻击面
现在 IM 发"接入仓库 https://10.0.0.1/secrets.git"会直接 git clone。project_binding.clone_and_bind 应该加 host 白名单（github.com / gitee.com / gitlab.com / 公司自有 host）+ scheme 限制 https。

二、工程上不补会很难用（中危）
5. 没有 clarifier，需求歧义不会反问
"做个 todo" → 直接跑完整 e2e，PRD 全靠 LLM 幻觉。建议在 planning 之前插一个 clarifier，缺关键信息（端、技术栈、目标用户）时回 IM 反问 1-2 轮再继续。

6. 多用户/多租户没做
created_by="gateway" 写死，IM user_id 没和 users 表关联。生产用会出现 A 在飞书发的反馈影响 B 的 task；token 用量也分不清谁花的。

7. Claude Code CLI 缺纯 API fallback
execute_claude_code 必须本机装 @anthropic-ai/claude-code，没装就掉到正则提取（基本不能用）。应当补一个用 Anthropic Tool Use 自己实现 read_file / write_file / bash 的进程内 agent 作为兜底。

8. 单 phase 600s 超时
带后端 + 前端 + DB migration 的项目几乎一定超。要么按子模块拆分，要么 timeout 抬到 1800s + 心跳。

三、补丁性的小问题（低危但要记着）
#	问题	改起来量
9
.env.example 没补 feishu_group_webhook、qq_bot_access_token
5 行
10
前端 PipelineTaskDetail.vue 没有反馈历史区
半天
11
FeedbackRecord 没和 PipelineTask 建外键
1 个 migration
12
新加的 notify/、gateway_binding.py、_apply_feedback_in_background 0 单测
1 天
13
observability 没按 IM user 维度的用量看板
1-2 天
要不要按下面的顺序继续？我建议优先级：

今天必修：3（并发锁）→ 1（QQ OneBot 协议）→ 4（SSRF 白名单）→ 2（飞书 v2 加密+token 校验）

本周工程：5（clarifier）→ 7（Claude Code 内置 fallback）→ 6（多用户绑定）

挑一个我直接接着写，或者一次把"今天必修"4 个全做掉？

今天必修"4 个全做掉

反馈并发锁：Redis SETNX + 队列合并，防同 task 多 e2e 同时跑
QQ webhook 改为 OneBot v11 正确 schema（post_type/message_type/user_id/raw_message）
project_binding.clone_and_bind 加 repo_url 白名单（host + scheme + IP 拦截）
飞书 v2 加密事件解密 + url_verification token 校验，补 feishu_encrypt_key 配置
lint + 跨文件检查
先看现有相关文件，避免改坏。

I have enough context. Let me start implementing.

Task 1: 反馈并发锁