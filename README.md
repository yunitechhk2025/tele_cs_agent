# tele_cs_agent

# Telegram Customer Service Agent System

A full-featured AI-powered customer service system that integrates with Telegram, featuring RAG-based knowledge base Q&A, automatic language detection, human handoff for pricing inquiries, and automated contract generation.

## Architecture

```
┌──────────────┐     ┌──────────────────────┐     ┌──────────────┐
│   Telegram   │────▶│   FastAPI Backend     │────▶│  PostgreSQL  │
│   Clients    │◀────│                       │     └──────────────┘
└──────────────┘     │  ┌─────────────────┐  │     ┌──────────────┐
                     │  │  Telegram Bot    │  │────▶│   ChromaDB   │
┌──────────────┐     │  │  LLM Service    │  │     │  (RAG Store) │
│  Admin Panel │────▶│  │  RAG Service    │  │     └──────────────┘
│  (React SPA) │◀────│  │  Contract Gen   │  │     ┌──────────────┐
└──────────────┘     │  └─────────────────┘  │────▶│    Redis      │
                     └──────────────────────┘     └──────────────┘
```

## Features

### 1. Multi-language Customer Service
- Automatic language detection using OpenAI
- Responds to customers in their detected language
- Supports 15+ languages including Chinese, English, Japanese, Korean, Spanish, French, German, Arabic, Russian, and more

### 2. RAG Knowledge Base
- Vector-based document search using ChromaDB + OpenAI embeddings
- Upload documents (TXT, MD, CSV) to build your knowledge base
- AI generates answers based on relevant knowledge base entries
- Admin panel for managing knowledge base entries

### 3. Human Handoff for Pricing Inquiries
- AI automatically detects pricing/quotation-related questions
- Sends notification to admin's Telegram with:
  - Customer information
  - The pricing question
  - Direct link to admin dashboard conversation
  - Direct link to customer's Telegram profile
- Admin can reply directly from the dashboard

### 4. Automated Contract Generation
- Generate contract drafts from conversation history
- AI extracts key terms, requirements, and agreed details
- Contracts generated in the customer's language
- Edit, review, approve, and manage contracts in the admin panel

### 5. Admin Dashboard
- **Dashboard**: Overview statistics and recent conversations
- **Conversations**: Real-time chat view, reply to customers, manage handoffs
- **Knowledge Base**: Add, edit, delete, and upload knowledge entries
- **Contracts**: View, edit, approve, and export generated contracts

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12, FastAPI |
| Telegram Bot | python-telegram-bot |
| AI/LLM | OpenAI GPT-4o |
| RAG | ChromaDB + OpenAI Embeddings |
| Database | PostgreSQL + SQLAlchemy (async) |
| Cache | Redis |
| Frontend | React 18, TypeScript, Ant Design 5 |
| Deployment | Docker, Docker Compose |

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- OpenAI API Key

### 1. Clone and Configure

```bash
# Copy the environment file
cp backend/.env.example backend/.env

# Edit with your credentials
nano backend/.env
```

Required environment variables:
```
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=your_telegram_user_id
OPENAI_API_KEY=your_openai_key
```

### 2. Deploy with Docker Compose

```bash
docker-compose up -d --build
```

This starts:
- **PostgreSQL** on port 5432
- **Redis** on port 6379
- **Backend API** on port 8000
- **Frontend** on port 80

### 3. Access the Admin Dashboard

Open `http://localhost` in your browser.

Default credentials:
- Username: `admin`
- Password: `admin123`

> **Important**: Change the default password in your `.env` file for production.

### 4. Set Up Your Bot

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Create a new bot with `/newbot`
3. Copy the token to `TELEGRAM_BOT_TOKEN` in `.env`
4. Get your admin chat ID (talk to [@userinfobot](https://t.me/userinfobot))
5. Set `ADMIN_CHAT_ID` in `.env`
6. Restart: `docker-compose restart backend`

### 5. Add Knowledge Base Content

1. Log into the admin dashboard
2. Go to **Knowledge Base**
3. Either:
   - Click **Add Entry** to manually add Q&A pairs
   - Click **Upload File** to upload documentation files (.txt, .md, .csv)

## Local Development

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# Run with hot reload
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs on port 5173 and proxies `/api` requests to the backend.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Admin login |
| GET | `/api/dashboard/stats` | Dashboard statistics |
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/:id` | Conversation detail with messages |
| POST | `/api/conversations/:id/reply` | Send reply to customer |
| POST | `/api/conversations/:id/close` | Close conversation |
| GET | `/api/knowledge` | List knowledge entries |
| POST | `/api/knowledge` | Create knowledge entry |
| POST | `/api/knowledge/upload` | Upload knowledge file |
| DELETE | `/api/knowledge/:id` | Delete knowledge entry |
| GET | `/api/contracts` | List contracts |
| POST | `/api/contracts/generate` | Generate contract from conversation |
| PUT | `/api/contracts/:id` | Update contract |
| DELETE | `/api/contracts/:id` | Delete contract |

## Cloud Deployment

### AWS / GCP / Azure

1. Push your images to a container registry
2. Deploy using your cloud provider's container service (ECS, Cloud Run, AKS)
3. Set up managed PostgreSQL and Redis instances
4. Configure environment variables
5. Set up a domain with SSL

### Recommended Production Settings

```env
# Use strong secrets
JWT_SECRET=<random-64-char-string>
ADMIN_PASSWORD=<strong-password>

# Use managed database
DATABASE_URL=postgresql+asyncpg://user:pass@managed-db:5432/cs_agent

# Use managed Redis
REDIS_URL=redis://managed-redis:6379/0
```

## License

MIT
