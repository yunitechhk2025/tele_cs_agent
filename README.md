# tele_cs_agent

基于 Telegram 的出海客服系统：集成大模型对话、RAG 知识库、询价转人工、多语言回复与合同草稿生成，并提供 React 管理后台。

## 架构概览

```
┌──────────────┐     ┌──────────────────────┐     ┌──────────────┐
│   Telegram   │────▶│   FastAPI 后端        │────▶│  PostgreSQL  │
│   客户       │◀────│                      │     └──────────────┘
└──────────────┘     │  ┌─────────────────┐ │     ┌──────────────┐
                     │  │ Telegram Bot    │ │────▶│   ChromaDB   │
┌──────────────┐     │  │ LLM / RAG       │ │     │  (向量知识库) │
│  管理后台     │────▶│  │ 合同生成等       │ │     └──────────────┘
│  (React)     │◀────│  └─────────────────┘ │     ┌──────────────┐
└──────────────┘     └──────────────────────┘────▶│    Redis     │
                                                 └──────────────┘
```

## 主要功能

- **多语言客服**：自动识别客户语言并尽量用同语言回复；支持常见多种语言。
- **RAG 知识库**：ChromaDB + OpenAI 嵌入，支持上传文档（如 TXT、MD、CSV）并在回答中检索相关知识。
- **询价与人工接管**：识别询价类问题后通知管理员 Telegram，可在后台查看会话并直接回复客户；人工处理期间客户再次发消息会触发跟进提醒。
- **人工回复与翻译**：可按客户询价语言进行翻译辅助；相关逻辑与会话字段配合使用。
- **合同与模板**：从会话生成合同草稿；支持 Word 模板、语言选择；可在对话流程中配合「发送合同」等能力（以当前实现为准）。
- **文件与商品图**：知识库/文件管理中的图片可在客户表达需要商品图等意图时，按规则自动选取并发送（具体规则见后端实现）。

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端 | Python 3.12、FastAPI |
| Telegram | python-telegram-bot |
| 大模型 | OpenAI API（可配置模型与 Base URL） |
| RAG | ChromaDB + OpenAI Embeddings |
| 数据库 | PostgreSQL、SQLAlchemy（异步） |
| 缓存 | Redis |
| 前端 | React 18、TypeScript、Ant Design 5 |
| 部署 | Docker、Docker Compose |

## 环境要求

- Docker 与 Docker Compose
- Telegram Bot Token（通过 [@BotFather](https://t.me/BotFather) 创建机器人）
- OpenAI API Key（或兼容 OpenAI API 的服务，需在环境变量中配置）

## 快速开始（Docker）

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入真实密钥与管理员信息
```

必填项示例：

```env
TELEGRAM_BOT_TOKEN=你的机器人Token
ADMIN_CHAT_ID=管理员的Telegram数字ID
OPENAI_API_KEY=你的OpenAI密钥
```

其他项（数据库、Redis、JWT、管理员账号密码等）请参照 [backend/.env.example](backend/.env.example)。**生产环境务必修改默认密码与 `JWT_SECRET`。**

修改 `backend/.env` 后需要**重启后端容器**才能生效；仅在前端或部分仅内存中生效的配置可能无需重启，以实际代码为准。

### 2. 启动服务

```bash
docker compose up -d --build
```

默认端口（与 [docker-compose.yml](docker-compose.yml) 一致）：

| 服务 | 端口 |
|------|------|
| PostgreSQL | 5432 |
| Redis | 6379 |
| 后端 API | 8000 |
| 管理前端（Nginx） | **3001** |

### 3. 打开管理后台

浏览器访问：**http://localhost:3001**

默认账号见 `backend/.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（示例中为 `admin` 与你在 `.env` 里设置的密码）。**上线前务必改为强密码。**

### 4. 绑定机器人与管理员

1. 在 Telegram 与 [@BotFather](https://t.me/BotFather) 对话，使用 `/newbot` 创建机器人，将 Token 写入 `TELEGRAM_BOT_TOKEN`。
2. 获取你的数字 Chat ID（例如通过 [@userinfobot](https://t.me/userinfobot)），写入 `ADMIN_CHAT_ID`。
3. 保存 `.env` 后执行：`docker compose restart backend`。

### 5. 维护知识库

登录管理后台 → **知识库**：手动新增条目或上传文件，用于 RAG 检索。

## 本地开发（可选）

### 后端

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

需本机已安装 PostgreSQL、Redis，或在 `.env` 中指向可访问的实例。

### 前端

```bash
cd frontend
npm install
npm run dev
```

开发服务器通常为 Vite 默认端口，并将 `/api` 代理到后端（以 [frontend/vite.config.ts](frontend/vite.config.ts) 为准）。

## API 说明（节选）

管理端通过后端 REST API 完成登录、会话、知识库、合同等操作。常见路径包括：

- `POST /api/auth/login`：管理员登录  
- `GET /api/conversations`：会话列表  
- `GET /api/conversations/{id}`：会话详情与消息  
- `POST /api/conversations/{id}/reply`：向客户发送回复  
- 知识库、合同相关：`/api/knowledge`、`/api/contracts` 等（以 [backend/app/api](backend/app/api) 路由为准）

完整列表可在运行后端后访问 OpenAPI 文档（若已启用）：`http://localhost:8000/docs`。

## 云端 / 生产部署建议

1. 将镜像推送到容器镜像仓库，在目标环境拉取并运行 Compose 或编排（如 Kubernetes）。  
2. 使用云厂商托管 PostgreSQL 与 Redis，在环境变量中填写 `DATABASE_URL`、`REDIS_URL`。  
3. 配置 HTTPS 域名、防火墙与安全组，仅暴露必要端口。  
4. 更新代码后一般在项目根目录执行：`git pull` 后 `docker compose up -d --build` 以重新构建并滚动更新。

## 开源协议

MIT
