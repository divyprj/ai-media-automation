"""Comprehensive test suite for Milestone 5: Web Dashboard & Background Scheduler.

Covers:
1. Application Lifecycle & Static Asset Delivery (FastAPI, Lifespan, index.html, style.css, app.js)
2. EmergencyController (Halt, resume, polling/publishing gate checks, SQLite persistence)
3. REST API Status & Automation Controls (/api/status, pause, resume, emergency stop/resume, toggle mode)
4. REST API News Discovery Stream (/api/items, /api/discovery, source/score/verification filters, manual trigger)
5. REST API Publishing Queue Management (/api/queue, inline edit with em-dash stripping, approve, reject, publish-now, 403 halt gate)
6. REST API Cost & Dependency Register (/api/cost-register, /api/dependencies, ₹0.00 verification)
7. REST API Audit Logs (/api/logs, event_type filters)
8. WebSocket Manager & Duplex Endpoint (/ws, connection handshake, message ack, broadcasting)
9. Background Async Scheduler Engine (start, stop, pause, resume, emergency stop, cycle executions, error resilience)
"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.config import Settings
from src.contracts.enums import Platform, PostStatus, SourceType
from src.contracts.schemas import AuditLogEntry, DiscoveredItem, GeneratedContent, PublishJob
from src.database.repository import Repository
from src.publishing.queue_manager import QueueManager
from src.scheduler.engine import SchedulerConfig, SchedulerEngine
from src.web.app import EmergencyController, create_app
from src.web.websocket import ConnectionManager


@pytest.fixture
def web_repo(temp_db_path: str) -> Repository:
    """Create and initialize a clean test SQLite repository."""
    repo = Repository(temp_db_path)
    repo.init_db()
    return repo


@pytest.fixture
def test_app(web_repo: Repository, test_settings: Settings):
    """FastAPI test application wired with isolated SQLite repository."""
    return create_app(settings=test_settings, repo=web_repo)


@pytest.fixture
def client(test_app) -> TestClient:
    """Synchronous test client for the dashboard application."""
    with TestClient(test_app) as c:
        yield c


# ==============================================================================
# 1. Application Lifecycle & Static Asset Delivery
# ==============================================================================

class TestAppLifecycleAndStaticAssets:
    """Test app creation, lifespan startup/shutdown, and static file endpoints."""

    def test_app_creation_with_defaults(self):
        """Verify create_app creates an instance with expected state objects."""
        app = create_app()
        assert app.title == "Divyansh Prajapati AI Social Intelligence Control Center"
        assert hasattr(app.state, "repo")
        assert hasattr(app.state, "emergency_controller")
        assert hasattr(app.state, "scheduler")
        assert hasattr(app.state, "ws_manager")

    def test_root_endpoint_serves_html(self, client: TestClient):
        """Verify GET / returns 200 OK with Divyansh Prajapati dashboard title."""
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Divyansh Prajapati" in res.text
        assert "@divyprjai" in res.text
        assert "Zero-Cost Dependency" in res.text

    def test_static_stylesheet_delivery(self, client: TestClient):
        """Verify GET /static/style.css serves valid CSS."""
        res = client.get("/static/style.css")
        assert res.status_code == 200
        assert "text/css" in res.headers["content-type"]
        assert "--bg-app:" in res.text

    def test_static_javascript_delivery(self, client: TestClient):
        """Verify GET /static/app.js serves valid JavaScript application code."""
        res = client.get("/static/app.js")
        assert res.status_code == 200
        assert "javascript" in res.headers["content-type"]
        assert "initWebSocket" in res.text


# ==============================================================================
# 2. EmergencyController Tests
# ==============================================================================

class TestEmergencyController:
    """Test EmergencyController halt state, resume, and persistence."""

    def test_controller_initial_unhalted_state(self, web_repo: Repository):
        """EmergencyController must start in unhalted state."""
        ec = EmergencyController(web_repo)
        assert ec.is_halted() is False
        assert ec.can_poll_feeds() is True
        assert ec.can_publish_jobs() is True

    def test_controller_trigger_halt(self, web_repo: Repository):
        """Triggering halt must update state and block operations."""
        ec = EmergencyController(web_repo)
        ec.trigger_halt(reason="Unit test emergency halt")
        assert ec.is_halted() is True
        assert ec.can_poll_feeds() is False
        assert ec.can_publish_jobs() is False

    def test_controller_resume(self, web_repo: Repository):
        """Resuming must clear halt state and restore operations."""
        ec = EmergencyController(web_repo)
        ec.trigger_halt()
        assert ec.is_halted() is True
        ec.resume()
        assert ec.is_halted() is False
        assert ec.can_poll_feeds() is True
        assert ec.can_publish_jobs() is True

    def test_controller_without_repo_fallback(self):
        """Verify in-memory fallback behavior when repo is None."""
        EmergencyController._halt_event = False
        ec = EmergencyController(repo=None)
        assert ec.is_halted() is False
        ec.trigger_halt()
        assert ec.is_halted() is True
        ec.resume()
        assert ec.is_halted() is False


# ==============================================================================
# 3. REST API Status & Automation Controls
# ==============================================================================

class TestStatusAndControlsAPI:
    """Test /api/status, pause/resume, and emergency circuit breaker endpoints."""

    def test_get_status_complete_payload(self, client: TestClient):
        """Verify GET /api/status returns telemetry, worker status, and account info."""
        res = client.get("/api/status")
        assert res.status_code == 200
        data = res.json()
        assert data["healthy"] is True
        assert "is_paused" in data
        assert "emergency_shutoff" in data
        assert "active_workers" in data
        assert "queue_counts" in data
        assert "uptime" in data
        assert data["account"]["handle"] == "@divyprjai"
        assert data["account"]["name"] == "Divyansh Prajapati"

    def test_pause_and_resume_system(self, client: TestClient):
        """Verify POST /api/status/pause and /api/status/resume toggle system pause."""
        res_pause = client.post("/api/status/pause")
        assert res_pause.status_code == 200
        assert res_pause.json()["is_paused"] is True
        assert res_pause.json()["status"] == "paused"

        status_res = client.get("/api/status")
        assert status_res.json()["is_paused"] is True
        assert status_res.json()["active_workers"] == 0

        res_resume = client.post("/api/status/resume")
        assert res_resume.status_code == 200
        assert res_resume.json()["is_paused"] is False
        assert res_resume.json()["status"] == "resumed"

        status_res_after = client.get("/api/status")
        assert status_res_after.json()["is_paused"] is False
        assert status_res_after.json()["active_workers"] == 1

    def test_emergency_shutoff_and_resume_endpoints(self, client: TestClient):
        """Verify emergency circuit breaker endpoints."""
        res_halt = client.post("/api/status/emergency-shutoff")
        assert res_halt.status_code == 200
        assert res_halt.json()["emergency_shutoff"] is True
        assert res_halt.json()["emergency_halt"] is True

        res_status = client.get("/api/status")
        assert res_status.json()["emergency_shutoff"] is True

        res_resume = client.post("/api/system/emergency-resume")
        assert res_resume.status_code == 200
        assert res_resume.json()["emergency_shutoff"] is False

        res_status_after = client.get("/api/status")
        assert res_status_after.json()["emergency_shutoff"] is False

    def test_toggle_mode_endpoint(self, client: TestClient):
        """Verify POST /api/system/toggle-mode switches mode."""
        res = client.post("/api/system/toggle-mode", json={"mode": "MANUAL"})
        assert res.status_code == 200
        assert res.json()["current_mode"] == "MANUAL"

        status_res = client.get("/api/status")
        assert status_res.json()["mode"] == "MANUAL"


# ==============================================================================
# 4. REST API News Discovery Stream
# ==============================================================================

class TestDiscoveryItemsAPI:
    """Test /api/items and /api/discovery endpoints with filters."""

    def test_get_items_empty(self, client: TestClient):
        """Verify GET /api/items returns an empty list on clean DB."""
        res = client.get("/api/items")
        assert res.status_code == 200
        assert res.json() == []

    def test_get_items_with_data_and_filters(self, client: TestClient, web_repo: Repository):
        """Verify querying and filtering discovered items."""
        item1 = DiscoveredItem(
            id="item_arxiv_1",
            source_type=SourceType.ARXIV,
            title="Reasoning LLMs in Distributed Memory",
            summary="Novel framework for distributed memory reasoning.",
            source_url="https://arxiv.org/abs/2401.00001",
            content_hash="hash_arxiv_1",
            is_verified=True,
            verification_score=85.0,
        )
        item2 = DiscoveredItem(
            id="item_github_1",
            source_type=SourceType.GITHUB,
            title="FastInference v2.0 Release",
            summary="Zero-overhead inference engine.",
            source_url="https://github.com/org/repo/releases/tag/v2.0",
            content_hash="hash_github_1",
            is_verified=False,
            verification_score=45.0,
        )
        web_repo.save_discovered_item(item1)
        web_repo.save_discovered_item(item2)

        # 1. Fetch all items
        res_all = client.get("/api/items")
        assert res_all.status_code == 200
        assert len(res_all.json()) == 2

        # 2. Filter by source_type
        res_arxiv = client.get("/api/items?source_type=arxiv")
        assert res_arxiv.status_code == 200
        assert len(res_arxiv.json()) == 1
        assert res_arxiv.json()[0]["id"] == "item_arxiv_1"

        # 3. Filter by is_verified
        res_verified = client.get("/api/items?is_verified=true")
        assert res_verified.status_code == 200
        assert len(res_verified.json()) == 1
        assert res_verified.json()[0]["is_verified"] is True

        # 4. Filter by min_score
        res_score = client.get("/api/items?min_score=80.0")
        assert res_score.status_code == 200
        assert len(res_score.json()) == 1
        assert res_score.json()[0]["verification_score"] >= 80.0

        # 5. Verify /api/discovery alias
        res_alias = client.get("/api/discovery?limit=10")
        assert res_alias.status_code == 200
        assert len(res_alias.json()) == 2

    def test_manual_trigger_discovery(self, client: TestClient):
        """Verify POST /api/items/trigger-discovery executes a discovery cycle."""
        res = client.post("/api/items/trigger-discovery")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ["completed", "skipped"]


# ==============================================================================
# 5. REST API Publishing Queue Management
# ==============================================================================

class TestPublishingQueueAPI:
    """Test /api/queue CRUD, inline edit, approval, rejection, and publish-now."""

    @pytest.fixture
    def sample_job(self, web_repo: Repository) -> PublishJob:
        """Seed a sample item and queued publish job into test database."""
        item = DiscoveredItem(
            id="item_q_1",
            source_type=SourceType.BLOG,
            title="OpenAI Frontier Model Benchmark",
            summary="New benchmark showing 15% improvement.",
            source_url="https://openai.com/index/frontier-benchmark",
            content_hash="hash_q_1",
            is_verified=True,
            verification_score=90.0,
        )
        web_repo.save_discovered_item(item)

        content = GeneratedContent(
            platform=Platform.X,
            text="OpenAI Frontier Model: 15% speedup on reasoning tasks. Analysis by @divyprjai",
            character_count=78,
            has_em_dash=False,
            attribution_url="https://openai.com/index/frontier-benchmark",
            is_sensitive=False,
        )
        job = PublishJob(
            job_id="job_test_q1",
            item_id="item_q_1",
            platform=Platform.X,
            content=content,
            status=PostStatus.AWAITING_APPROVAL,
            created_at=datetime.now(timezone.utc),
            retry_count=0,
        )
        web_repo.enqueue_publish_job(job)
        return job

    def test_get_queue_empty(self, client: TestClient):
        """Verify GET /api/queue returns empty list when no jobs enqueued."""
        res = client.get("/api/queue")
        assert res.status_code == 200
        assert res.json() == []

    def test_get_queue_with_items(self, client: TestClient, sample_job: PublishJob):
        """Verify GET /api/queue returns enqueued jobs with full payload and web intent."""
        res = client.get("/api/queue")
        assert res.status_code == 200
        jobs = res.json()
        assert len(jobs) == 1
        j = jobs[0]
        assert j["job_id"] == sample_job.job_id
        assert j["platform"] == "x"
        assert j["status"] == "awaiting_approval"
        assert "web_intent_x" in j
        assert "twitter.com/intent/tweet" in j["web_intent_x"]

    def test_get_queue_item_by_id(self, client: TestClient, sample_job: PublishJob):
        """Verify GET /api/queue/{id} returns single job and 404 for invalid ID."""
        res = client.get(f"/api/queue/{sample_job.job_id}")
        assert res.status_code == 200
        assert res.json()["job_id"] == sample_job.job_id

        res_404 = client.get("/api/queue/non_existent_job_id")
        assert res_404.status_code == 404

    def test_queue_approve_action(self, client: TestClient, sample_job: PublishJob):
        """Verify POST /api/queue/{id}/approve transitions status to READY_FOR_MANUAL."""
        res = client.post(f"/api/queue/{sample_job.job_id}/approve")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == PostStatus.READY_FOR_MANUAL.value

        res_get = client.get(f"/api/queue/{sample_job.job_id}")
        assert res_get.json()["status"] == PostStatus.READY_FOR_MANUAL.value

    def test_queue_reject_action(self, client: TestClient, sample_job: PublishJob):
        """Verify POST /api/queue/{id}/reject transitions status to REJECTED."""
        res = client.post(
            f"/api/queue/{sample_job.job_id}/reject",
            json={"reason": "Topic outside editorial focus"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == PostStatus.REJECTED.value

        res_get = client.get(f"/api/queue/{sample_job.job_id}")
        assert res_get.json()["status"] == PostStatus.REJECTED.value

    def test_queue_inline_edit_and_em_dash_sanitization(
        self, client: TestClient, sample_job: PublishJob
    ):
        """Verify PUT /api/queue/{id} updates draft text and strips em dashes."""
        draft_with_dash = "New breakthrough — verified by @divyprjai. Great benchmark."
        res = client.put(
            f"/api/queue/{sample_job.job_id}",
            json={"content_text": draft_with_dash},
        )
        assert res.status_code == 200
        data = res.json()
        # Verify 0 em dashes in result
        assert "—" not in data["content"]["text"]
        assert "New breakthrough: verified by @divyprjai" in data["content"]["text"]
        assert data["content"]["has_em_dash"] is False

    def test_queue_publish_now_action(self, client: TestClient, sample_job: PublishJob):
        """Verify POST /api/queue/{id}/publish-now marks job as published."""
        res = client.post(f"/api/queue/{sample_job.job_id}/publish-now")
        assert res.status_code == 200
        assert res.json()["status"] == PostStatus.PUBLISHED.value
        assert "x.com" in res.json()["url"]

    def test_queue_publish_now_blocked_on_emergency_halt(
        self, client: TestClient, sample_job: PublishJob
    ):
        """Verify POST /api/queue/{id}/publish-now returns 403 when halted."""
        client.post("/api/status/emergency-shutoff")
        res = client.post(f"/api/queue/{sample_job.job_id}/publish-now")
        assert res.status_code == 403
        assert "Emergency shutoff active" in res.json()["detail"]


# ==============================================================================
# 6. Cost & Dependency Register API
# ==============================================================================

class TestCostRegisterAPI:
    """Test /api/cost-register and /api/dependencies zero-cost validation."""

    def test_get_cost_register_returns_verified_items(self, client: TestClient):
        """Verify GET /api/cost-register reads DEPENDENCY_REGISTER.md and confirms ₹0.00 cost."""
        res = client.get("/api/cost-register")
        assert res.status_code == 200
        items = res.json()
        assert len(items) >= 20
        assert all(it["cost"] == "₹0.00" for it in items)

        names = {it["name"].lower() for it in items}
        for expected in ["fastapi", "sqlite 3", "ollama local engine", "matplotlib", "pillow"]:
            assert any(expected in n for n in names), f"Missing {expected} in cost register"

    def test_dependencies_alias_endpoint(self, client: TestClient):
        """Verify GET /api/dependencies returns identical zero-cost items."""
        res = client.get("/api/dependencies")
        assert res.status_code == 200
        assert len(res.json()) >= 20


# ==============================================================================
# 7. Audit Logs API
# ==============================================================================

class TestAuditLogsAPI:
    """Test /api/logs querying and filtering."""

    def test_get_audit_logs(self, client: TestClient, web_repo: Repository):
        """Verify recording and querying audit logs."""
        now = datetime.now(timezone.utc)
        web_repo.record_audit_log(
            AuditLogEntry(
                id="log_test_1",
                event_type="DISCOVERY_POLL",
                timestamp=now,
                details={"feed": "arxiv", "status": "ok"},
            )
        )
        web_repo.record_audit_log(
            AuditLogEntry(
                id="log_test_2",
                event_type="EMERGENCY_HALT",
                timestamp=now,
                details={"halted": True},
            )
        )

        res_all = client.get("/api/logs?limit=50")
        assert res_all.status_code == 200
        assert len(res_all.json()) >= 2

        res_filtered = client.get("/api/logs?event_type=EMERGENCY_HALT")
        assert res_filtered.status_code == 200
        assert len(res_filtered.json()) >= 1
        assert res_filtered.json()[0]["event_type"] == "EMERGENCY_HALT"


# ==============================================================================
# 8. WebSocket Connection & Real-Time Broadcasting
# ==============================================================================

class TestWebSocketEndpoint:
    """Test WebSocket handshake, message acknowledgment, and broadcasting."""

    def test_websocket_handshake_and_echo(self, client: TestClient):
        """Verify client connects, receives handshake, and gets echo acks."""
        with client.websocket_connect("/ws") as ws:
            # 1. Verify handshake message
            initial = ws.receive_json()
            assert initial["type"] == "connection_established"
            assert initial["healthy"] is True

            # 2. Send ping message and receive ack
            ws.send_text("client_ping")
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert ack["received"] == "client_ping"

    def test_websocket_connection_manager_broadcast(self):
        """Verify ConnectionManager broadcast method handles active/dead connections."""
        manager = ConnectionManager()
        assert len(manager.active_connections) == 0

        # Broadcast on empty connections must complete without error
        asyncio.run(manager.broadcast({"type": "test_broadcast"}))


# ==============================================================================
# 9. Background Async Scheduler Engine
# ==============================================================================

class TestSchedulerEngine:
    """Test SchedulerEngine lifecycle, interval polling, pause, and emergency checks."""

    def test_scheduler_config_defaults(self):
        """Verify default intervals on SchedulerConfig."""
        cfg = SchedulerConfig()
        assert cfg.discovery_interval == 60.0
        assert cfg.queue_interval == 15.0
        assert cfg.stuck_job_timeout == 300

    def test_scheduler_discovery_cycle_execution(self, web_repo: Repository):
        """Verify running a single discovery cycle updates last_poll_time and poll_count."""
        scheduler = SchedulerEngine(repo=web_repo)
        scheduler.is_running = True

        result = asyncio.run(scheduler.run_discovery_cycle())
        assert result["status"] == "completed"
        assert scheduler.poll_count == 1
        assert scheduler.last_poll_time is not None

    def test_scheduler_queue_cycle_execution(self, web_repo: Repository):
        """Verify running a single queue cycle updates cycle counts."""
        scheduler = SchedulerEngine(repo=web_repo)
        scheduler.is_running = True

        result = asyncio.run(scheduler.run_queue_cycle())
        assert result["status"] == "completed"
        assert scheduler.queue_cycle_count == 1
        assert scheduler.last_queue_time is not None

    def test_scheduler_respects_pause(self, web_repo: Repository):
        """When paused, discovery and queue cycles must be skipped."""
        scheduler = SchedulerEngine(repo=web_repo)
        scheduler.is_running = True
        scheduler.pause()
        assert scheduler.is_paused is True
        assert scheduler.can_poll_feeds() is False
        assert scheduler.can_publish_jobs() is False

        res_disc = asyncio.run(scheduler.run_discovery_cycle())
        assert res_disc["status"] == "skipped"
        assert res_disc["reason"] == "paused"

        res_queue = asyncio.run(scheduler.run_queue_cycle())
        assert res_queue["status"] == "skipped"
        assert res_queue["reason"] == "paused"

        scheduler.resume()
        assert scheduler.is_paused is False
        assert scheduler.can_poll_feeds() is True

    def test_scheduler_respects_emergency_halt(self, web_repo: Repository):
        """When emergency halt is active, cycles must be skipped."""
        ec = EmergencyController(web_repo)
        scheduler = SchedulerEngine(repo=web_repo, emergency_controller=ec)
        scheduler.is_running = True
        ec.trigger_halt()

        assert scheduler.is_halted() is True
        assert scheduler.can_poll_feeds() is False

        res = asyncio.run(scheduler.run_discovery_cycle())
        assert res["status"] == "skipped"
        assert res["reason"] == "halted"

    def test_scheduler_start_and_stop_lifecycle(self, web_repo: Repository):
        """Verify scheduler background tasks start and cancel cleanly on stop."""
        async def run_lifecycle():
            cfg = SchedulerConfig(discovery_interval=0.1, queue_interval=0.1)
            scheduler = SchedulerEngine(repo=web_repo, config=cfg)
            await scheduler.start()
            assert scheduler.is_running is True
            assert scheduler._discovery_task is not None
            assert scheduler._queue_task is not None

            # Let loops run briefly
            await asyncio.sleep(0.25)
            assert scheduler.poll_count >= 1
            assert scheduler.queue_cycle_count >= 1

            # Stop gracefully
            await scheduler.stop()
            assert scheduler.is_running is False
            assert scheduler._discovery_task is None
            assert scheduler._queue_task is None

        asyncio.run(run_lifecycle())

    def test_scheduler_cycle_broadcast_callback(self, web_repo: Repository):
        """Verify scheduler invokes broadcast callback on cycle completion."""
        broadcasted_events = []

        async def mock_broadcast(msg: dict):
            broadcasted_events.append(msg)

        scheduler = SchedulerEngine(
            repo=web_repo,
            broadcast_callback=mock_broadcast,
        )
        scheduler.is_running = True

        asyncio.run(scheduler.run_discovery_cycle())
        assert len(broadcasted_events) == 1
        assert broadcasted_events[0]["type"] == "discovery_cycle"

        asyncio.run(scheduler.run_queue_cycle())
        assert len(broadcasted_events) == 2
        assert broadcasted_events[1]["type"] == "queue_cycle"
