# 🧠 Build Failure Analyzer (RAG-Powered, Human-in-the-Loop)

The **Build Failure Analyzer (BFA)** is an AI-assisted system that automatically analyzes CI/CD build or pipeline failures, retrieves known fixes using **Retrieval-Augmented Generation (RAG)**, and generates new remediation suggestions when needed.

What makes BFA different is its **self-curating memory**:

- SME-approved fixes are persisted
- Slack is used as a **human-in-the-loop approval layer**
- The system continuously improves without retraining models

---

## 🏗️ High-Level Architecture

BFA combines:

- **Vector search (ChromaDB)** for known error → fix pairs
- **LLM reasoning (CrewAI + Ollama)** when no good match exists
- **Slack workflows** for SME approval
- **JWT-secured APIs** for CI/CD agents
- **RAG domain context** for pipeline-specific heuristics

This results in **fast, explainable, and consistent fixes** with controlled learning.

---

## 🧬 RAG Workflow (How It Thinks)

### Retrieve

When a build error occurs:

- Error text is embedded
- Vector DB (Chroma) is queried
- If similarity ≥ threshold → reuse approved fix

### Augment

If no match (or low confidence):

- Domain-specific context (pipeline patterns) is retrieved
- Context + error is passed to LLM prompt
- SME-safe prompt structure is enforced

### Generate

- LLM generates a suggested fix
- Suggestion is sent to Slack
- SME can **Approve**, **Edit**, or **Discard**

Approved fixes are **stored back into the vector DB**.
The system gets smarter every time.

---

## 📝 Key Features

### RAG-Based Fix Recommendation

- ChromaDB vector search with embeddings
- Threshold-based similarity filtering
- Deterministic retrieval before LLM calls

### Human-in-the-Loop via Slack

- Slack interactive buttons:
  - Approve
  - Edit
  - Discard
- Edit mode tracked using Redis
- Slack thread-safe workflows
- DM notifications to reviewers

### Continuous Learning

- Only SME-approved fixes are persisted
- Prevents hallucinations from polluting memory
- Supports future analytics on fix reuse

### Pipeline Domain Context (RAG Extension)

- Separate vector collection (pipeline_context)
- Stores failure → solution heuristics
- Used to enrich LLM prompts before generation

### Securing API with Authentication

- JWT tokens signed using **DMZ-side RSA private key**
- No shared secrets in pipelines
- Analyzer APIs verify issuer

### Management Utilities

- CLI tools to:
  - List vector DB entries
  - Preview deletions
  - Delete by ID or error substring
- Safe preview mode supported

---

## 🗂️ Project Structure (Current)

```
build-failure-analyzer/
│
├── analyzer_service.py # FastAPI service (main entrypoint)
├── error_notifier.py # Slack + Email internal error alerts
├── llm_openwebui_client.py # querying to internal-chat.com
├── resolver_agent.py # normalize error text and query Redis + Vector + Call LLM
├── slack_helper.py # Slack + Email internal error alerts
├── jwt_dmz_issuer.py # JWT token issuer for CI/CD agents
├── pipeline_context_rag.py # Domain context RAG logic
├── vector_db.py # Vector DB + embeddings abstraction
├── vector_helper.py # CLI for vector DB management
│
├── tests/ # Full unit test suite
│ ├── README-UT.md
| ├── test_analyzer_api.py
| ├── test_slack_actions.py
| ├── test_slack_helper.py
| ├── test_error_notifier.py
| ├── test_jwt_auth_handler.py
| ├── test_pipeline_context_rag.py
| ├── test_vector_helper.py
| ├── test_llm_client.py
| ├── test_resolver_agent.py
| ├── test_rate_my_mr_api.py
| └── test_vector_db.py
│
├── .env
└── README.md
```

---

## ⚙️ How It Works

### 1. **Pipeline Log Analysis**

When `analyzer_service.py` runs, it:
- Extracts unique error strings from build logs.
- For each error:
  1. Queries the **vector DB** for a similar fix.
  2. If a close match is found → recommends it directly.
  3. Otherwise → triggers an **LLM call** to generate a new fix.

### 2. **Slack Review Workflow**

AI-generated fixes are sent to a designated Slack channel via `slack_helper.py`.
Each fix comes with action buttons:

- ✅ **Approve** → Saves fix to vector DB (via `save_fix_to_db`)
- ✏️ **Edit** → SME can modify fix text
- 🚫 **Discard** → Ignores suggestion

API handlers were added in `analyzer_service.py`(Unified version holding all API routes) to handle slack actions using the Slack SDK.

### 3. **Created systemd service**
```bash
User build-failure-analyzer may run the following commands on bfa-server:
    (ALL) NOPASSWD: sudo /usr/bin/systemctl restart build-failure-analyzer,
                    sudo /usr/bin/systemctl stop build-failure-analyzer,
                    sudo /usr/bin/systemctl start build-failure-analyzer,
                    sudo /usr/bin/systemctl status build-failure-analyzer,
                    sudo /usr/bin/journalctl -u build-failure-analyzer -> to view the logs

build-failure-analyzer@bfa-server:~/build-failure-analyzer$ systemctl status build-failure-analyzer
● build-failure-analyzer.service - Build Failure Analyzer (FastAPI)
     Loaded: loaded (/etc/systemd/system/build-failure-analyzer.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-01-16 09:10:03 EST; 5min ago
 Invocation: e7ee00d472314e19bc239280d8b80cdd
   Main PID: 661969 (uvicorn)
      Tasks: 44 (limit: 38470)
     Memory: 80.4M (peak: 81.1M)
        CPU: 3.480s
     CGroup: /system.slice/build-failure-analyzer.service
             └─661969 /home/build-failure-analyzer/build-failure-analyzer/.venv/bin/python3 /home/build-failure-analyzer/build-failure-analyzer/.venv/bin/uvi>

Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:vector_db:[VectorDB] init_vector_db() -> /var/lib/redis/bfa-data
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:     Started server process [661969]
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:     Waiting for application startup.
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:analyzer:[RAG] Loaded domain context from /home/build-failure-analyzer/build-failure-analyzer/context/d>
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:vector_db:[VectorDB] Connected to Chroma collection 'fix_embeddings' (path=/var/lib/redis/bfa-data)
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:pipeline_context_rag:[RAG] Initialized domain context collection 'pipeline_context' at /var/lib/redis/b>
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:analyzer:[RAG] Domain context collection already has 75 vectors, skipping index
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:analyzer:[RAG] Domain context RAG initialized successfully
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:     Application startup complete.
Jan 16 09:10:05 bfa-server uvicorn[661969]: INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

## 🔐 Authentication & Security

### JWT Authentication

- Tokens are issued using **RSA private key** in DMZ
- Analyzer verifies:
  - iss (issuer)
  - aud (audience)
  - exp (expiry)

No shared secrets. CI/CD agents only receive signed tokens.

---

## 📢 Slack Error & Fix Handling

### Slack Actions

- Approve → Save fix to vector DB
- Edit → Enter edit mode (Redis-tracked)
- Discard → Drop suggestion safely

### Error Notifications

- Any internal exception triggers:
  - Slack DM alert
  - Optional SMTP email
- Fail-safe design:
  - Slack/email failures never crash the app

## 💾 Vector Database (RAG Memory)

The app uses **ChromaDB** as its vector store to persist embeddings and SME-approved fixes.

- **Embedding Model:** `text-embedding-3-large` (or configurable)
- **Persistence Directory:** `/var/lib/redis/bfa-data`
- **Delete/Query Utilities:**
  - `python3 vector_helper.py` — Query existing entries
  - `python3 vector_helper.py --id <doc-id>` — Delete unwanted entry

---
## 🧪 Unit Test Coverage

All critical components are fully unit-tested:

| **Component** | **Coverage** |
|---------------|--------------|
| Analyzer Service | API routing, dependencies, safety |
| Slack Actions | Approve/Edit/Discard flows |
| Error Notifier | Slack/email safety |
| JWT Issuer | Claims, expiry, CLI |
| Pipeline RAG | Indexing, querying, thresholds |
| Vector Helper | List / preview / delete logic |

### Run all tests

```bash
pytest -v
- No real Slack
- No real DB
- No network
- CI-safe
```

## 🔐 Environment Setup

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=sk-xxxx
SLACK_BOT_TOKEN=xoxb-xxxx
SLACK_SIGNING_SECRET=xxxx
```

## Running the System
    1. Start the Slack Reviewer App

    This Flask service listens for Slack button interactions.

    python3 slack_reviewer.py

        Runs on port 5001 by default.
        Make sure it’s reachable via ngrok or your Kubernetes ingress.

    2. Run the Analyzer

    Run the main analyzer that processes build logs and sends results to Slack.

    python3 main.py

    3. Query or Clean the Vector Store

    # Preview and confirm before deleting by ID
    python3 vector_helper.py --id abc123 xyz789 --preview

    # Delete by ID without preview (but will warn if not found)
    python3 vector_helper.py --id abc123

    # Preview and confirm before deleting by error text
    python3 vector_helper.py --error "cmake" --preview

    # Delete by error without preview
    python3 vector_helper.py --error "cmake"

    # Preview all documents before deleting all
    python3 vector_helper.py --delete-all --preview

    # Delete all with confirmation (no preview)
    python3 vector_helper.py --delete-all

    # Delete all without any confirmation (dangerous!)
    python3 vector_helper.py --delete-all --force

    # Edit fix interactively (will prompt for input)
    python3 vector_helper.py --edit abc123

    # Edit fix with inline text
    python3 vector_helper.py --edit abc123 --fix "Run: sudo apt-get install cmake"

    # Edit fix with multi-line input (press Ctrl+D when done)
    python3 vector_helper.py --edit abc123 --interactive

    # Preview document before deleting
    python3 vector_helper.py --id abc123 --preview

    # List all documents
    python3 vector_helper.py


## 🧩 Tech Stack
    Component	                    Purpose
    Python 3.13+	                Core language
    ChromaDB	                    Vector storage & retrieval
    Ollama Embeddings	            Semantic understanding
    Flask	                        Slack webhook listener
    Slack SDK	                    Message sending & interactive review
    Redis Basic                     In-Memory store for caching and exchange data between flask and analyzer
## 📈 RAG Workflow Diagram
    Flowchart Top → Down (vertical)
        A[Pipeline Logs] --> B[Error Extraction]
        B --> C{Vector DB Lookup}
        C -->|Found Match| D[Recommend Existing Fix]
        C -->|No Match| E[LLM Generates New Fix]
        D --> F[Send to Slack for Review]
        E --> F
        F --> G[SME Approves/Edits/Discards]
        G -->|Approve| H[Persist Fix to Vector DB]

## 🧪 Example Output

    Found 2 unique error(s):
    1. Caused by: missing semicolon
    2. make: *** [build] Error 2

    🤖 Generated AI fix for error:
    Caused by: missing semicolon
    --
    1. Locate the pipeline script...
    ...
    ✅ Fix approved by @sme_user and saved to memory.

## 🧰 Future Enhancements

1. Auto-linting and pre-save validation for SME edits.

2. Web dashboard to visualize frequently recurring errors.

3. Fine-tuned embeddings for better semantic similarity.

4. Integration with Jira for ticket linking.

5. SLA-based auto-approval.

## Summary
The Build Failure Analyzer is:

- A production-grade RAG system
- With human-verified memory
- Designed for CI/CD reliability
- Secure, test-driven, and extensible
It doesn't just generate fixes —
it learns responsibly.
