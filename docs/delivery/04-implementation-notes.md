```markdown
# Todo Web App 部署方案

## 1. 环境矩阵

| 环境       | 配置                                                         |
|------------|------------------------------------------------------------|
| 开发环境   | 本地开发机，Python 3.8，PostgreSQL 12，Redis，Docker，Nginx |
| 测试环境   | 虚拟机或容器，Python 3.8，PostgreSQL 12，Redis，Docker，Nginx |
| 预发环境   | 服务器集群，Python 3.8，PostgreSQL 12，Redis，Docker，Nginx |
| 生产环境   | 服务器集群，Python 3.8，PostgreSQL 12，Redis，Docker，Nginx |

## 2. 依赖清单

| 运行时版本 | 系统依赖 | 第三方服务 |
|------------|----------|------------|
| Python 3.8 | PostgreSQL 12 | Docker, Redis, Nginx, Vite, FastAPI, SQLAlchemy, PyJWT, Element Plus, Pinia |
| Node.js 14.x | Nginx | Docker, Git, GitHub Actions/GitLab CI |

## 3. Docker

### Dockerfile

```Dockerfile
# 使用官方Python基础镜像
FROM python:3.8-slim

# 设置工作目录
WORKDIR /app

# 复制依赖
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动应用
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis
    environment:
      - DATABASE_URL=postgres://user:password@db:5432/dbname
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=your_secret_key

  db:
    image: postgres:12
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=dbname

  redis:
    image: redis:alpine

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - web

```

## 4. CI/CD

### GitHub Actions

```yaml
name: CI/CD

on: [push]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2
      - name: Set up Python 3.8
        uses: actions/setup-python@v2
        with:
          python-version: 3.8
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run tests
        run: |
          python -m unittest discover -s tests
      - name: Build Docker image
        run: docker build -t todo-web-app .
      - name: Push Docker image to GitHub Container Registry
        uses: actions/setup-container@v2
        with:
          image: mcr.microsoft.com/dotnet/sdk:6.0
        run: docker login -u ${{ github.actor }} -p ${{ github.token }}
        run: docker push todo-web-app
```

### GitLab CI

```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  script:
    - pip install -r requirements.txt
    - docker build -t todo-web-app .

test:
  stage: test
  script:
    - python -m unittest discover -s tests

deploy:
  stage: deploy
  script:
    - docker push todo-web-app
```

## 5. 环境变量

| 变量名                 | 必填 | 示例值                          |
|------------------------|------|--------------------------------|
| DATABASE_URL           | 是   | postgresql://user:password@db:5432/dbname |
| REDIS_URL              | 是   | redis://redis:6379/0           |
| SECRET_KEY            | 是   | your_secret_key                 |
| NGINX_PORT             | 否   | 80                              |
| VITE_ENV              | 否   | production                      |
| FASTAPI_ENV           | 否   | production                      |

## 6. 部署步骤

### Pre-deploy checks

1. 确认所有依赖都已安装。
2. 检查数据库连接。
3. 确认Redis服务运行正常。
4. 运行测试以确保没有未处理的错误。

### Deployment

1. 构建Docker镜像。
2. 将Docker镜像推送到容器注册库。
3. 使用Docker Compose启动应用。

### Post-deploy verification

1. 检查应用是否在指定端口上运行。
2. 确认数据库连接正常。
3. 运行端到端测试以确保所有功能正常。

## 7. 回滚方案

### 自动回滚触发条件

1. 应用启动失败。
2. 系统性能显著下降。
3. 用户报告严重错误。

### 手动回滚步骤

1. 停止当前运行的容器。
2. 删除旧的Docker镜像。
3. 使用备份的配置文件重新构建Docker镜像。
4. 重新启动应用。

## 8. 监控告警

### 关键指标

- 应用响应时间
- 系统负载
- 数据库查询性能
- Redis缓存命中率

### 告警规则

- 应用响应时间超过500毫秒
- 系统负载超过80%
- 数据库查询性能下降
- Redis缓存命中率低于90%

### 日志收集方案

- 使用ELK堆栈（Elasticsearch, Logstash, Kibana）收集和监控日志。
- 配置Nginx和FastAPI记录访问日志和错误日志。
- 配置PostgreSQL和Redis记录慢查询日志和错误日志。

## 9. 安全加固

### HTTPS

- 使用Let's Encrypt获取SSL证书。
- 配置Nginx强制使用HTTPS。

### 防火墙规则

- 限制对应用端口的访问。
- 禁止不必要的服务和端口。

### 密钥管理

- 使用密钥管理服务（如AWS KMS）存储敏感信息。
- 定期轮换密钥。

```
```