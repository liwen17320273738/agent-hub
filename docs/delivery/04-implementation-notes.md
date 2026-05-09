## 部署运维方案

### 一、环境信息
| 环境 | 配置 | 说明 |
|---|---|---|
| 开发环境 | 虚拟机，浏览器兼容性测试 | 用于开发、测试和预览页面 |
| 生产环境 | 云服务器，负载均衡 | 用于部署上线后的个人名片页面 |

### 二、容器化
```dockerfile
# Dockerfile
FROM nginx:latest

COPY ./src/index.html /usr/share/nginx/html/
COPY ./src/css/main.css /usr/share/nginx/html/css/
COPY ./src/js/main.js /usr/share/nginx/html/js/

EXPOSE 80
```

### 三、CI/CD 配置
```yaml
# .github/workflows/deploy.yml
name: Deploy Personal Card Page

on:
  push:
    branches:
      - main

jobs:
  build:
    runs-on: ubuntu-latest

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Build Docker Image
      run: docker build -t personal-card-page .
    - name: Push Docker Image to Docker Hub
      run: docker push personal-card-page
    - name: Deploy to Production
      run: docker run -d -p 80:80 personal-card-page
```

### 四、监控告警
| 指标 | 阈值 | 告警方式 |
|---|---|---|
| 网站访问量 | 日访问量超过1000 | 邮件告警 |
| 网站响应时间 | 响应时间超过3秒 | 邮件告警 |
| 网站错误率 | 错误率超过5% | 邮件告警 |

### 五、部署策略
- 灰度比例: 10%
- 回滚条件: 网站访问量下降、错误率上升
- 回滚步骤: 
  1. 停止新版本部署
  2. 回滚到旧版本
  3. 检查网站状态

### 六、应急预案
| 故障场景 | 影响 | 处理步骤 |
|---|---|---|
| 网站访问量激增 | 网站访问速度变慢 | 增加服务器资源、优化数据库查询 |
| 网站出现错误 | 网站无法访问 | 检查服务器日志、修复错误代码 |
| 网站被攻击 | 网站被篡改 | 更新网站安全策略、修复漏洞 |

## 成功指标（自检清单）
- 包含 Dockerfile 或容器化配置
- 包含 CI/CD 配置文件
- 有回滚方案和步骤
- 有监控告警配置

## 协作委托
- 当「应用代码问题」时 → 委托给 Agent-developer，提供: 部署日志+错误信息
- 当「安全配置」时 → 委托给 Agent-security，提供: 环境配置+网络拓扑

## 职责边界
你负责: CI/CD 流水线, Docker/K8s, 监控告警, 安全加固, 灾备方案
- coding: 应用代码修改交给开发工程师
- testing: 功能测试交给 QA