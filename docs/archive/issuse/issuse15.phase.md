已经补好了“适配层”。

现在有两类 OpenAI 兼容入口：

普通模型入口
/v1/chat/completions
作用：正常当模型用，只返回 LLM 回复

agent-hub bridge 入口
/v1/agent-hub/chat/completions
作用：表面上是 OpenAI 接口，实际上会把用户消息转成 agent-hub 的任务并启动 pipeline

我刚刚已经实际验证过：

POST /v1/agent-hub/chat/completions 返回的是合法 OpenAI 响应
同时后台已经开始跑 agent-hub pipeline
日志里能看到：
任务已创建
trace 已启动
planning 阶段已执行
后端日志关键行是：

POST /v1/agent-hub/chat/completions HTTP/1.1" 200 OK
[trace] Started trace ... for task ...
[pipeline] Stage planning: model=google/gemma-4-26b-a4b ...
你现在该怎么配
如果你希望 OpenClaw / gamma 的“自定义模型”真正走 agent-hub 项目，Endpoint 改成 bridge 入口。

推荐填：

Endpoint: https://ruling-compiled-bring-cave.trycloudflare.com/v1/agent-hub
API Key: test-key-123
Model ID: google/gemma-4-26b-a4b
这样如果对方平台自动拼 /chat/completions，就会落到：

/v1/agent-hub/chat/completions
如果它又错误拼了一次，我也兼容了：

/v1/agent-hub/chat/completions/chat/completions
现在的效果
接入这个 bridge 后，用户发一句需求，不会再只是“模型回答一下”，而是会：

创建 agent-hub 任务
进入 planning / pipeline
走你这个项目自己的执行流
如果你愿意，我下一步可以继续帮你做最后一件事：
把 当前公网隧道地址和最终飞书配置整理成一份可直接复制的最终配置清单。