# LibreChat 对接 Business Gateway 指南

本指南说明如何将 LibreChat 指向 Business Gateway 的 OpenAI 兼容接口，并提供测试、排错与部署建议。

## 1. 配置 LibreChat

在 LibreChat 的环境变量或配置文件中设置以下参数（名称可能依版本略有不同，请以 LibreChat 官方文档为准）：

- `OPENAI_API_BASE`：指向 Business Gateway 对外地址，例如：
  - `https://gateway.example.com`
- `OPENAI_API_KEY`：Business Gateway 的 API Key，例如：
  - `sk-user-xxxx`

示例（`.env` 片段）：

```dotenv
OPENAI_API_BASE=https://gateway.example.com
OPENAI_API_KEY=sk-user-xxxx
```

> 说明：Business Gateway 对外提供 `/v1/chat/completions` 路由，因此 `OPENAI_API_BASE` 不需要包含 `/v1` 后缀。

## 2. 测试网关是否可用

### 2.1 基础连通性测试（curl）

```bash
curl -X POST https://gateway.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-user-xxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": false
  }'
```

若返回符合 OpenAI 兼容响应结构的 JSON（包含 `choices` 等字段）则说明网关与下游 NewAPI 连接正常。

### 2.2 流式响应测试（SSE）

```bash
curl -N -X POST https://gateway.example.com/v1/chat/completions \
  -H "Authorization: Bearer sk-user-xxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

应看到持续输出的 `data:` 流式片段，最后以 `[DONE]` 结束。

## 3. 常见错误排查

### 3.1 401 Unauthorized

- API Key 无效或未配置。请确认：
  - `Authorization: Bearer <key>` 正确传入。
  - 数据库 `api_keys` 表中该 key 存在且 `is_active=true`。
  - 对应 `users` 表的 `status=active`。

### 3.2 402 Payment Required

- 计费相关拦截（余额不足、日限额、模型计价等）。请检查：
  - `wallets.balance` 是否足够。
  - 当日 `daily_spend` 是否超过 `DAILY_SPEND_LIMIT`。
  - `model_pricing` 中对应模型是否 `enabled=true`。
  - `MAX_COST_PER_REQUEST` 是否过低。

### 3.3 429 Too Many Requests

- Redis 限流触发（每 API Key 每分钟 60 次默认值）。
  - 检查 Redis 可用性与 `rate_limit` 逻辑。
  - 必要时调整限流阈值。

### 3.4 502 / 500 上游异常

- 下游 NewAPI 不可用或鉴权失败。请确认：
  - `DOWNSTREAM_BASE_URL` 是否正确。
  - `DOWNSTREAM_API_KEY` 是否有效。
  - NewAPI 服务自身是否可访问。

## 4. 推荐部署方式

### 4.1 Docker 部署

使用项目自带的 `Dockerfile` 构建并运行：

```bash
docker build -t business-gateway .
docker run -d --name business-gateway \
  -p 8000:8000 \
  --env-file .env \
  business-gateway
```

### 4.2 生产环境建议

- 使用反向代理（如 Nginx）配置 HTTPS。
- 将 Redis、PostgreSQL 等依赖作为独立服务部署。
- 配合进程管理（systemd / docker-compose / k8s）确保高可用。
- 打开应用监控与日志采集，便于排查计费与请求转发问题。
