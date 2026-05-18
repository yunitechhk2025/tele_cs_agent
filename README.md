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
- **商品场景图推荐**：支持为推荐商品生成场景效果图；已生成的场景图会保存到数据库中，后续同商品、同场景、同风格请求会优先复用历史结果，避免重复生图。

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

登录管理后台 → **知识库**：拖拽多个文档批量上传（.txt / .md / .csv / .docx），系统会自动解析切块并生成向量索引，用于 RAG 检索。

### 5.1 用种子数据快速初始化（可选）

仓库自带两份样例数据，方便新环境一键灌入：

| 文件 | 内容 |
|------|------|
| `backend/seed_data/knowledge.json` | 13 条基线条目（FAQ / 政策 / 操作流程） |
| `backend/seed_data/cases.json` | 8 个真实业务案例（退款、物流、质量、大客户、跨境关税…） |

灌入步骤（任意环境，只要后端 API 可达）：

```bash
# 灌基线 13 条
python backend/scripts/import_knowledge.py \
  --base-url http://127.0.0.1:8000

# 追加 8 个案例
python backend/scripts/import_knowledge.py \
  --input backend/seed_data/cases.json \
  --base-url http://127.0.0.1:8000 \
  --skip-existing
```

`--skip-existing` 会按 (title, category) 跳过已存在条目，重复执行幂等。

参数也可以用环境变量代替：`KB_BASE_URL` / `KB_USERNAME` / `KB_PASSWORD`。

如需把当前环境的知识库导出为 JSON（方便迁移到其他环境）：

```bash
python backend/scripts/export_knowledge.py \
  --base-url http://127.0.0.1:8000 \
  --output backend/seed_data/knowledge.json
```

### 5.2 离线填充产品多语言

产品推荐链路不会在客户对话时翻译商品字段。导入或更新产品库后，先离线生成并写入产品翻译：

```bash
# 试跑，不调用 LLM、不写数据库，先确认剩余任务量
docker compose exec backend python scripts/fill_product_translations.py \
  --dry-run --only-missing --languages en,ja,ko,es,fr --limit 5

# 正式补齐外语；会显示批次进度条，失败后可原命令续跑
docker compose exec backend python scripts/fill_product_translations.py \
  --only-missing --languages en,ja,ko,es,fr --batch-size 20 --max-tokens 8000
```

默认语言为：简体中文、繁体中文、英文、日语、韩语、西班牙语、法语。脚本会把产品源字段写入 `zh-Hans`，用本地转换填充 `zh-Hant`，其余语言按批次调用当前 LLM 配置并写入 `product_entry_translations`。脚本支持断点续跑；如果中途失败，继续执行同一命令即可只补缺失项。当前进度以“待翻译 product-language 请求数”为单位统计，交互终端中会原地刷新，非 TTY 日志中会按批次输出。

两个脚本都只依赖 Python 标准库，可在任意 Python 3.10+ 环境运行，无需先 `pip install`。

### 6. 查看商品场景图与耗时

1. 登录管理后台，进入 **产品管理**。
2. 打开任一商品详情抽屉，找到 **场景图推荐 / 效果图生成**。
3. 点击 **生成 3 张场景图** 后，可在下方 **最近场景图生成记录** 中查看：
   - 生成状态
   - 生成耗时（`duration_ms`，单位毫秒）
   - 3 张场景图预览
   - 搭配商品链接

场景图查看方式：

- 在后台产品详情中直接预览、放大查看。
- 或直接打开后端图片地址，格式为：

```text
http://localhost:8000/api/scene-generations/<record_id>/images/0
http://localhost:8000/api/scene-generations/<record_id>/images/1
http://localhost:8000/api/scene-generations/<record_id>/images/2
```

说明：

- `<record_id>` 可从该商品的 **最近场景图生成记录** 中获取。
- 场景图会同时写入数据库；如果再次请求同一商品的相同场景与风格，系统会优先复用已有结果，而不是重新调用生图接口。
- 运行中的容器内也会保留文件副本，路径通常为 `/app/uploads/generated_scenes/<record_id>/`，便于排查，但复用逻辑以数据库中的图片记录为准。

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

**依赖只需装一次**（任选其一）：

```bash
cd frontend && npm install
```

或在本仓库根目录：

```bash
npm run install-frontend
```

启动开发服务器（任选其一）：

```bash
cd frontend && npm run dev
```

或在本仓库根目录：

```bash
npm run dev
```

浏览器打开 **http://localhost:5173**（Vite 开发服务器）。`/api` 会代理到本机 **http://localhost:8000**（见 [frontend/vite.config.ts](frontend/vite.config.ts)）。

**改界面时不必每次重新构建 Docker 镜像**：只要后端 API 已在跑（见上或用下面「仅起后端」），前端用 `npm run dev` 保存文件后会热更新，**刷新页面即可看到效果**。

仅起数据库 / Redis / 后端、不启动前端容器（避免占用 3001 与生产构建混淆）示例：

```bash
docker compose up -d db redis backend
```

然后另开终端执行 `cd frontend && npm run dev`。若仍启动了带前端的完整 Compose，请用 **5173** 访问开发版；**3001** 仍是 Nginx 里的生产构建，改代码后需 `docker compose build frontend` 才会变。

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
