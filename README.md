# Autonomous AI Media & Social Intelligence System

An autonomous AI-powered media and social intelligence system that continuously discovers, researches, fact-checks, creates, and publishes content about Artificial Intelligence on X (Twitter) as the primary platform and LinkedIn as the secondary platform, operating with an **absolute ₹0 budget**.

---

## 1. Zero-Cost Architectural Guarantees

- **₹0 Total Budget**: 100% free software, open-access public feeds, local open-weight LLMs via Ollama, and embedded SQLite storage.
- **Zero Payment Credentials**: No credit card or billing details required.
- **Zero Overage Risk**: Zero reliance on metered commercial APIs. All primary inference runs locally on the host machine.
- **Dual-Mode Publishing**: Supports authorized free official APIs or an automated queue with 1-click manual web intents, ensuring publishing never requires paid API tiers.

---

## 2. System Architecture

```
[External Sources]
(arXiv, GitHub Releases Atom, HF Daily Papers/Models, AI Lab RSS & Sitemaps)
         │
         ▼
[Discovery & Sanitization] (Zero-width strip, XML escaping, injection defense)
         │
         ▼
[Multi-Layer Deduplication] (Canonical URL hash, Title trigram Jaccard, 48h temporal clustering)
         │
         ▼
[Fact Verification Engine] (0-100 score: domain authority, live OG metadata, artifact validation)
         │ (Score >= 70)
         ▼
[Editorial & Visual Generator] (0 em dashes, anti-slop linter, X/LinkedIn formatters, Matplotlib/Pillow cards)
         │
         ▼
[Publishing Queue & Safety] (Sensitive topic filter, idempotent SQLite WAL queue, emergency shutoff)
         │
    ┌────┴────────────────────────┐
    ▼                             ▼
[Mode A: Free API]        [Mode B: Manual Queue]
(X API v2 / LinkedIn)     (Web intents & 1-click clipboard)
         │                             │
         └──────────────┬──────────────┘
                        ▼
           [Local Web Dashboard (FastAPI)]
```

---

## 3. Technology Stack

| Layer | Component | Implementation | Cost |
|---|---|---|---|
| **Runtime** | Python 3.12+ | CPython via `uv` | ₹0.00 |
| **Package Manager** | `uv` | Astral `uv` | ₹0.00 |
| **Local LLM Engine** | Ollama | `r1:latest` (7.6B Q4) / heuristic fallback | ₹0.00 |
| **Database** | SQLite3 | WAL Mode, Normal Synchronous, Busy Timeout 5000ms | ₹0.00 |
| **Web Server** | FastAPI & Uvicorn | Async REST APIs & WebSocket status | ₹0.00 |
| **Data Validation** | Pydantic v2 | Contract-first schemas & settings | ₹0.00 |
| **Visual Generation** | Matplotlib & Pillow | 1200x675 16:9 dark-mode cards & benchmark charts | ₹0.00 |
| **Testing** | Pytest & pytest-asyncio | Offline deterministic unit & integration tests | ₹0.00 |

---

## 4. Directory Structure

```
/home/divyansh-prajapati/Downloads/X/
├── pyproject.toml                # Project metadata & uv dependencies
├── .env.example                  # Environment configuration template
├── .gitignore                    # Python, SQLite, environment exclusions
├── README.md                     # System architecture & quickstart
├── DEPENDENCY_REGISTER.md        # ₹0 cost & overage verification register
│
├── data/                         # SQLite databases & visual artifacts
│   ├── ai_media.db               # SQLite database file (WAL mode)
│   └── visuals/                  # Generated infographics & charts
│
├── src/                          # Application source code
│   ├── config.py                 # Pydantic Settings & environment loaders
│   ├── contracts/                # Contract-first schemas & enums
│   │   ├── enums.py              # Platform, PostStatus, SourceType, ContentType
│   │   └── schemas.py            # DiscoveredItem, GeneratedContent, PublishJob, SystemStatus
│   ├── database/                 # SQLite storage layer & migrations
│   │   ├── connection.py         # WAL-mode connection factory
│   │   ├── models.py             # DDL schemas & table initialization
│   │   └── repository.py         # Thread-safe CRUD repository
│   ├── discovery/                # News discovery & verification engine (M2)
│   ├── generator/                # Strict editorial content & visual generator (M3)
│   ├── publishing/               # Queue manager, safety filter, adapters (M4)
│   ├── scheduler/                # Background async task engine (M5)
│   └── web/                      # Central web dashboard & control center (M5)
│
└── tests/                        # Comprehensive automated test suite
    ├── test_contracts.py         # Contract serialization & validation tests
    └── test_database.py          # SQLite WAL, concurrency, and repository tests
```

---

## 5. Quickstart & Installation

### Prerequisites
- Python >= 3.12 (managed via `uv`)
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Ollama (optional for local LLM inference): `ollama run r1:latest`

### Setup Environment
```bash
# Clone or navigate to the project directory
cd /home/divyansh-prajapati/Downloads/X

# Create and sync virtual environment with dependencies
uv sync --extra dev

# Copy environment template
cp .env.example .env
```

### Running Tests
Execute the automated test suite using `uv`:
```bash
uv run pytest tests/test_contracts.py tests/test_database.py -v
```

### Running the System
```bash
# Start the FastAPI Web Dashboard & Background Scheduler
uv run uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload
```
Navigate to `http://localhost:8000` to access the Control Room Dashboard.
