# Dependency & Cost Register: 100% Zero-Cost Architecture Verification

**Project**: Autonomous AI Media & Social Intelligence System  
**Budget Policy**: Absolute ₹0.00 Expenditure  
**Last Verified**: 2026-11-21  

This register provides a complete and verified accounting of all libraries, runtime environments, external feeds, local AI models, database technologies, and tools utilized in the project. Every item is verified to require **₹0.00**, require **no credit card or billing details**, and entail **zero overage risk**.

---

## 1. System Runtimes & Infrastructure

| Component | Provider / Upstream | License | API Key / Auth | Cost | Overage Risk | Purpose & Verification Status |
|---|---|---|---|---|---|---|
| **Python 3.12+** | Python Software Foundation | PSF License | None | ₹0.00 | None | Base language runtime. Verified installed locally. |
| **`uv` Package Manager** | Astral Software Inc. | Apache-2.0 / MIT | None | ₹0.00 | None | Zero-overhead, blazing fast virtual environment manager. |
| **SQLite 3 (v3.46.1)** | SQLite Consortium | Public Domain | None | ₹0.00 | None | Zero-config embedded relational database operating in WAL mode. No external process or cloud billing. |
| **Ollama Local Engine** | Ollama Open Source | MIT License | None (localhost) | ₹0.00 | None | Runs open-weight models (`r1:latest` / `qwen2.5`) directly on host hardware. Fully air-gapped, zero network calls. |

---

## 2. Software Libraries & Python Dependencies

| Package | Minimum Version | License | Auth Required | Cost | Risk Factor | Verification / Fallback |
|---|---|---|---|---|---|---|
| **`fastapi`** | `>=0.115.0` | MIT | None | ₹0.00 | None | High-performance async web framework for local dashboard. |
| **`uvicorn`** | `>=0.30.0` | BSD-3-Clause | None | ₹0.00 | None | ASGI web server for local dashboard on localhost. |
| **`pydantic`** | `>=2.8.0` | MIT | None | ₹0.00 | None | Data validation and schema enforcement. Contract-first. |
| **`pydantic-settings`** | `>=2.4.0` | MIT | None | ₹0.00 | None | Environment variable parsing with default fallbacks. |
| **`httpx`** | `>=0.27.0` | BSD-3-Clause | None | ₹0.00 | None | Async HTTP client for polling public feeds and Ollama. |
| **`jinja2`** | `>=3.1.4` | BSD-3-Clause | None | ₹0.00 | None | Server-rendered templates for the local web dashboard. |
| **`matplotlib`** | `>=3.9.0` | PSF-based | None | ₹0.00 | None | Programmatic rendering of benchmark charts and comparisons. |
| **`pillow`** | `>=10.4.0` | HPND | None | ₹0.00 | None | Programmatic 16:9 social visual cards and watermark embedding. |
| **`python-dotenv`** | `>=1.0.1` | BSD-3-Clause | None | ₹0.00 | None | Local `.env` file loading. |
| **`pytest`** | `>=8.3.0` | MIT | None | ₹0.00 | None | Test framework executing deterministic offline tests. |
| **`pytest-asyncio`** | `>=0.24.0` | Apache-2.0 | None | ₹0.00 | None | Async test runner extension. |

---

## 3. External Intelligence & News Discovery Feeds

All monitored feeds are public, non-authenticated open access endpoints.

| Feed Source | Access Protocol | Endpoint Pattern | Auth Required | Cost | Rate Limit Policy & Safeguards |
|---|---|---|---|---|---|
| **arXiv Open Access** | Public RSS & Export API | `https://export.arxiv.org/rss/cs.AI` | None | ₹0.00 | Respects >=3.5s delay between requests; conditional GET with `If-Modified-Since`. |
| **GitHub Releases** | Atom XML Feed | `https://github.com/<owner>/<repo>/releases.atom` | None | ₹0.00 | Atom feeds are publicly cached by GitHub; no token required. 15m polling interval. |
| **Hugging Face** | Public REST API | `https://huggingface.co/api/daily_papers` | None | ₹0.00 | Free public community discovery API. Cached with 30m polling interval. |
| **AI Labs Official Blogs** | Public RSS / Atom / Sitemap | OpenAI, DeepMind, AWS, Microsoft, Meta RSS feeds | None | ₹0.00 | Standard XML web feeds parsed with defensive XML parser. 30m polling interval. |

---

## 4. Local AI Inference & Editorial Generation

| Model Family | Quantization | Size | Hardware Footprint | Cost | Operational Strategy |
|---|---|---|---|---|---|
| **`r1:latest`** (7.6B Qwen2 distillation) | Q4_K_M | 4.68 GB | ~4 GB VRAM / CPU offload | ₹0.00 | Primary high-value synthesis model. Strips `<think>` tags automatically. |
| **Heuristic Template Fallback** | N/A (Algorithmic) | 0 KB | 0 MB VRAM / 0 ms | ₹0.00 | Tier 2 instant fallback for zero-overhead draft generation when GPU is busy. |
| **Offline Mock Provider** | N/A (Unit Tests) | 0 KB | 0 MB VRAM / 0 ms | ₹0.00 | Tier 3 offline provider for test suites. Ensures 100% CI pass without running daemon. |

---

## 5. Publishing Platform Integration & Safety Safeguards

| Target Platform | Tier / Mechanism | Credentials Required | Cost | Overage Risk Strategy |
|---|---|---|---|---|
| **X (Twitter)** | Mode A: Free Developer API v2 | Optional Free Keys | ₹0.00 | Hard-capped at 50 posts/day; stops automatically when limit reached. |
| **X (Twitter)** | Mode B: Manual Web Intent & Clipboard | None (Browser Intent) | ₹0.00 | Zero-API fallback. Pre-fills `https://twitter.com/intent/tweet?text=...` with 1 click. |
| **LinkedIn** | Mode A: Community Management API | Optional Free Keys | ₹0.00 | Free developer quota if configured. |
| **LinkedIn** | Mode B: Manual Web Share Intent | None (Browser Intent) | ₹0.00 | Zero-API fallback. 1-click clipboard copy + share dialog trigger. |

---

## 6. Financial Audit Summary

- **Total Direct Software Cost**: **₹0.00**
- **Total Cloud / SaaS API Subscription Cost**: **₹0.00**
- **Total Infrastructure / Hosting Cost**: **₹0.00** (Localhost execution)
- **Payment Credentials Registered**: **0 (None)**
- **Maximum Financial Exposure**: **₹0.00**

*Attestation: All features across all milestones are architected to adhere strictly to this ₹0 register without exception.*
