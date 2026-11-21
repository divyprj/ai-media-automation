/**
 * Divyansh Prajapati AI Social Intelligence Operating System
 * Central Local Web Dashboard Client Application
 */

(function () {
  "use strict";

  // Application State
  const state = {
    activeView: "health",
    queueStatusFilter: "",
    systemStatus: null,
    ws: null,
    wsReconnectAttempts: 0,
    autoScrollLogs: true,
    dependencies: [],
  };

  // DOM Elements
  const elements = {
    // Header & Telemetry
    wsBadge: document.getElementById("ws-status-badge"),
    wsText: document.getElementById("ws-status-text"),
    systemBadge: document.getElementById("system-status-badge"),
    systemText: document.getElementById("system-status-text"),
    modeBadge: document.getElementById("mode-badge"),
    btnPause: document.getElementById("btn-pause-toggle"),
    btnPauseText: document.getElementById("btn-pause-text"),
    btnEmergencyStop: document.getElementById("btn-emergency-stop"),
    btnEmergencyResume: document.getElementById("btn-emergency-resume"),
    emergencyBanner: document.getElementById("emergency-banner"),
    btnBannerResume: document.getElementById("btn-banner-resume"),

    // Nav Badges
    navDiscoveryBadge: document.getElementById("nav-discovery-badge"),
    navQueueBadge: document.getElementById("nav-queue-badge"),
    navHistoryBadge: document.getElementById("nav-history-badge"),

    // View 1 Elements
    statAutomationState: document.getElementById("stat-automation-state"),
    statWorkersSub: document.getElementById("stat-workers-sub"),
    statUptime: document.getElementById("stat-uptime"),
    statAwaitingCount: document.getElementById("stat-awaiting-count"),
    statReadyCount: document.getElementById("stat-ready-count"),
    statPublishedCount: document.getElementById("stat-published-count"),
    btnRefreshHealth: document.getElementById("btn-refresh-health"),
    btnModeAuto: document.getElementById("btn-mode-auto"),
    btnModeManual: document.getElementById("btn-mode-manual"),
    btnTriggerDiscovery: document.getElementById("btn-trigger-discovery"),
    btnTriggerEmergencyPanel: document.getElementById("btn-trigger-emergency-panel"),

    // Meters
    meterValQueued: document.getElementById("meter-val-queued"),
    meterFillQueued: document.getElementById("meter-fill-queued"),
    meterValAwaiting: document.getElementById("meter-val-awaiting"),
    meterFillAwaiting: document.getElementById("meter-fill-awaiting"),
    meterValReady: document.getElementById("meter-val-ready"),
    meterFillReady: document.getElementById("meter-fill-ready"),
    meterValPublished: document.getElementById("meter-val-published"),
    meterFillPublished: document.getElementById("meter-fill-published"),
    meterValRejected: document.getElementById("meter-val-rejected"),
    meterFillRejected: document.getElementById("meter-fill-rejected"),

    // View 2 Elements
    discoveryContainer: document.getElementById("discovery-items-container"),
    filterSource: document.getElementById("filter-source"),
    filterVerified: document.getElementById("filter-verified"),
    filterMinScore: document.getElementById("filter-min-score"),
    filterScoreVal: document.getElementById("filter-score-val"),
    btnPollDiscoveryView: document.getElementById("btn-poll-discovery-view"),
    btnRefreshDiscovery: document.getElementById("btn-refresh-discovery"),

    // View 3 Elements
    queueContainer: document.getElementById("queue-items-container"),
    btnRefreshQueue: document.getElementById("btn-refresh-queue"),

    // View 4 Elements
    historyContainer: document.getElementById("history-items-container"),
    histTotalCount: document.getElementById("hist-total-count"),
    histXCount: document.getElementById("hist-x-count"),
    histLinkedinCount: document.getElementById("hist-linkedin-count"),
    btnRefreshHistory: document.getElementById("btn-refresh-history"),

    // View 5 Elements
    depTableBody: document.getElementById("dependencies-table-body"),
    filterDepInput: document.getElementById("filter-dep-input"),

    // View 6 Elements
    terminalBody: document.getElementById("terminal-body"),
    logCountIndicator: document.getElementById("log-count-indicator"),
    btnClearLogs: document.getElementById("btn-clear-logs"),
    btnRefreshLogs: document.getElementById("btn-refresh-logs"),
    filterLogEvent: document.getElementById("filter-log-event"),
    chkAutoscroll: document.getElementById("chk-autoscroll"),

    // Modal
    modalEdit: document.getElementById("modal-edit-post"),
    editPostText: document.getElementById("edit-post-text"),
    editPostId: document.getElementById("edit-post-id"),
    modalCharCount: document.getElementById("modal-char-count"),
    modalMaxChars: document.getElementById("modal-max-chars"),
    modalEmDashWarning: document.getElementById("modal-em-dash-warning"),
    btnModalCleanDashes: document.getElementById("btn-modal-clean-dashes"),
    btnModalCancel: document.getElementById("btn-modal-cancel"),
    btnModalSave: document.getElementById("btn-modal-save"),
    btnCloseModal: document.getElementById("btn-close-modal"),

    // Toast Container
    toastContainer: document.getElementById("toast-container"),
  };

  // =========================================================================
  // Toast Notifications
  // =========================================================================
  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    let icon = "ℹ️";
    if (type === "success") icon = "✅";
    if (type === "error") icon = "❌";
    toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;
    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px) scale(0.95)";
      setTimeout(() => toast.remove(), 200);
    }, 3500);
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // =========================================================================
  // WebSocket Connection
  // =========================================================================
  function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || "localhost:8000";
    const wsUrl = `${protocol}//${host}/ws`;

    try {
      state.ws = new WebSocket(wsUrl);

      state.ws.onopen = function () {
        state.wsReconnectAttempts = 0;
        elements.wsBadge.className = "badge badge-ws connected";
        elements.wsText.textContent = "WS Connected";
        appendTerminalLine("SYSTEM", "WebSocket live connection established.", "text-emerald");
      };

      state.ws.onmessage = function (event) {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessage(data);
        } catch (e) {
          console.error("Failed to parse WS message:", e);
        }
      };

      state.ws.onclose = function () {
        elements.wsBadge.className = "badge badge-ws disconnected";
        elements.wsText.textContent = "WS Reconnecting...";
        scheduleWsReconnect();
      };

      state.ws.onerror = function (err) {
        console.warn("WebSocket error:", err);
      };
    } catch (e) {
      scheduleWsReconnect();
    }
  }

  function scheduleWsReconnect() {
    state.wsReconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(1.5, state.wsReconnectAttempts), 10000);
    setTimeout(initWebSocket, delay);
  }

  function handleWebSocketMessage(data) {
    if (!data) return;

    if (data.type === "connection_established") {
      appendTerminalLine("WS", "Handshake verified with local server.", "text-sky");
    } else if (data.type === "status_change") {
      fetchStatus();
      appendTerminalLine("STATUS", `Automation state changed: ${JSON.stringify(data)}`, "text-amber");
    } else if (data.type === "queue_update") {
      fetchQueue();
      fetchStatus();
      appendTerminalLine("QUEUE", `Job ${data.job_id} updated [action: ${data.action}].`, "text-sky");
    } else if (data.type === "discovery_cycle") {
      fetchDiscovery();
      fetchStatus();
      appendTerminalLine("DISCOVERY", `Discovery cycle #${data.poll_count} completed.`, "text-emerald");
    } else if (data.type === "queue_cycle") {
      fetchStatus();
      if (data.recovered_jobs > 0) {
        appendTerminalLine("QUEUE_RECOVERY", `Recovered ${data.recovered_jobs} stuck jobs.`, "text-amber");
      }
    } else if (data.type === "mode_change") {
      elements.modeBadge.textContent = data.mode;
      appendTerminalLine("MODE", `Operating mode switched to ${data.mode}.`, "text-sky");
    }
  }

  // =========================================================================
  // API Calls & State Sync
  // =========================================================================
  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) throw new Error("Failed to fetch status");
      const data = await res.json();
      state.systemStatus = data;
      renderStatus(data);
    } catch (e) {
      console.error("fetchStatus error:", e);
    }
  }

  function renderStatus(data) {
    // Status Badge & Controls
    if (data.emergency_shutoff || data.emergency_halt) {
      elements.systemBadge.className = "badge badge-system halted";
      elements.systemText.textContent = "EMERGENCY HALTED";
      elements.emergencyBanner.classList.remove("hidden");
      elements.btnEmergencyStop.classList.add("hidden");
      elements.btnEmergencyResume.classList.remove("hidden");
      elements.statAutomationState.textContent = "HALTED";
      elements.statAutomationState.className = "stat-value text-red";
      elements.statWorkersSub.textContent = "All background workers frozen";
    } else if (data.is_paused || data.paused) {
      elements.systemBadge.className = "badge badge-system paused";
      elements.systemText.textContent = "SYSTEM PAUSED";
      elements.emergencyBanner.classList.add("hidden");
      elements.btnEmergencyStop.classList.remove("hidden");
      elements.btnEmergencyResume.classList.add("hidden");
      elements.statAutomationState.textContent = "PAUSED";
      elements.statAutomationState.className = "stat-value text-amber";
      elements.statWorkersSub.textContent = "Polling & dispatch paused";
      elements.btnPauseText.textContent = "Resume";
    } else {
      elements.systemBadge.className = "badge badge-system online";
      elements.systemText.textContent = "SYSTEM ONLINE";
      elements.emergencyBanner.classList.add("hidden");
      elements.btnEmergencyStop.classList.remove("hidden");
      elements.btnEmergencyResume.classList.add("hidden");
      elements.statAutomationState.textContent = "ACTIVE";
      elements.statAutomationState.className = "stat-value text-emerald";
      elements.statWorkersSub.textContent = `${data.active_workers || 1} Worker Active`;
      elements.btnPauseText.textContent = "Pause";
    }

    elements.modeBadge.textContent = data.mode || "AUTONOMOUS";
    elements.statUptime.textContent = `${Math.floor(data.uptime || 0)}s`;

    // Queue Counts & Meters
    const qc = data.queue_counts || {};
    const queued = qc.queued || 0;
    const awaiting = qc.awaiting_approval || 0;
    const ready = qc.ready_for_manual || 0;
    const published = qc.published || 0;
    const rejected = qc.rejected || 0;
    const total = Math.max(1, queued + awaiting + ready + published + rejected);

    elements.statAwaitingCount.textContent = awaiting;
    elements.statReadyCount.textContent = ready;
    elements.statPublishedCount.textContent = published;

    elements.meterValQueued.textContent = queued;
    elements.meterFillQueued.style.width = `${(queued / total) * 100}%`;

    elements.meterValAwaiting.textContent = awaiting;
    elements.meterFillAwaiting.style.width = `${(awaiting / total) * 100}%`;

    elements.meterValReady.textContent = ready;
    elements.meterFillReady.style.width = `${(ready / total) * 100}%`;

    elements.meterValPublished.textContent = published;
    elements.meterFillPublished.style.width = `${(published / total) * 100}%`;

    elements.meterValRejected.textContent = rejected;
    elements.meterFillRejected.style.width = `${(rejected / total) * 100}%`;

    elements.navQueueBadge.textContent = awaiting + ready + queued;
    elements.navHistoryBadge.textContent = published;
  }

  // =========================================================================
  // View 2: News Discovery
  // =========================================================================
  async function fetchDiscovery() {
    try {
      let url = "/api/items?limit=50";
      const src = elements.filterSource.value;
      const ver = elements.filterVerified.value;
      const minScore = elements.filterMinScore.value;

      if (src) url += `&source_type=${encodeURIComponent(src)}`;
      if (ver) url += `&is_verified=${encodeURIComponent(ver)}`;
      if (minScore > 0) url += `&min_score=${encodeURIComponent(minScore)}`;

      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch discovery items");
      const items = await res.json();
      renderDiscoveryItems(items);
      elements.navDiscoveryBadge.textContent = items.length;
    } catch (e) {
      console.error("fetchDiscovery error:", e);
    }
  }

  function renderDiscoveryItems(items) {
    if (!items || items.length === 0) {
      elements.discoveryContainer.innerHTML = `
        <div class="empty-state">
          <p>No discovered items matching filters. Click "Ingest Feeds" to poll configured sources.</p>
        </div>`;
      return;
    }

    elements.discoveryContainer.innerHTML = items
      .map((item) => {
        const score = Math.round(item.verification_score || 0);
        let scoreClass = "score-low";
        if (score >= 70) scoreClass = "score-high";
        else if (score >= 40) scoreClass = "score-med";

        const sourceLabel = (item.source_type || "UNKNOWN").toUpperCase();
        const dateStr = item.discovered_at ? new Date(item.discovered_at).toLocaleTimeString() : "";

        return `
        <div class="item-card">
          <div>
            <div class="item-card-header">
              <span class="badge badge-mode">${escapeHtml(sourceLabel)}</span>
              <span class="score-badge ${scoreClass}">Score: ${score}/100</span>
            </div>
            <h4 class="item-title mt-3">${escapeHtml(item.title)}</h4>
            <p class="item-summary mt-3">${escapeHtml(item.summary || "")}</p>
          </div>
          <div class="item-footer">
            <span class="text-sub">${dateStr}</span>
            <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer" class="source-link">
              Source URL ↗
            </a>
          </div>
        </div>`;
      })
      .join("");
  }

  // =========================================================================
  // View 3: Publishing Queue
  // =========================================================================
  async function fetchQueue() {
    try {
      let url = "/api/queue?limit=50";
      if (state.queueStatusFilter) {
        url += `&status=${encodeURIComponent(state.queueStatusFilter)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch queue items");
      const jobs = await res.json();
      renderQueueItems(jobs);
    } catch (e) {
      console.error("fetchQueue error:", e);
    }
  }

  function renderQueueItems(jobs) {
    if (!jobs || jobs.length === 0) {
      elements.queueContainer.innerHTML = `
        <div class="empty-state">
          <p>Publishing queue is currently empty for status: ${state.queueStatusFilter || "ALL"}.</p>
        </div>`;
      return;
    }

    elements.queueContainer.innerHTML = jobs
      .map((job) => {
        const platform = (job.platform || "x").toLowerCase();
        const platformClass = platform === "linkedin" ? "platform-linkedin" : "platform-x";
        const content = job.content || {};
        const text = content.text || "";
        const chars = content.character_count || text.length;
        const maxChars = platform === "linkedin" ? 3000 : 280;
        const isOverLimit = chars > maxChars;
        const status = job.status || "queued";

        let statusClass = "badge-mode";
        if (status === "published") statusClass = "badge-emerald";
        if (status === "rejected") statusClass = "badge-system halted";
        if (status === "awaiting_approval") statusClass = "badge-system paused";

        const xIntent = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`;
        const linkedInIntent = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(content.attribution_url || "https://example.com")}`;

        return `
        <div class="queue-card" data-job-id="${escapeHtml(job.job_id)}">
          <div class="queue-card-header">
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="platform-pill ${platformClass}">${escapeHtml(platform.toUpperCase())}</span>
              <span class="badge ${statusClass}">${escapeHtml(status)}</span>
            </div>
            <div class="text-sub font-mono ${isOverLimit ? 'text-red' : ''}">
              ${chars} / ${maxChars} chars
            </div>
          </div>

          <div class="queue-post-text">${escapeHtml(text)}</div>

          <div class="queue-card-actions">
            <div class="action-buttons-group">
              <button class="btn btn-secondary btn-sm btn-edit-post" data-job-id="${escapeHtml(job.job_id)}" data-text="${encodeURIComponent(text)}" data-platform="${platform}">
                ✏️ Edit
              </button>
              <button class="btn btn-secondary btn-sm btn-copy-post" data-text="${encodeURIComponent(text)}">
                📋 Copy
              </button>
              ${platform === "x" ? `
                <a href="${xIntent}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm">
                  𝕏 Launch Tweet
                </a>
              ` : `
                <a href="${linkedInIntent}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm">
                  in Share
                </a>
              `}
            </div>

            <div class="action-buttons-group">
              ${status !== "published" && status !== "rejected" ? `
                <button class="btn btn-success btn-sm btn-approve-post" data-job-id="${escapeHtml(job.job_id)}">
                  ✓ Approve
                </button>
                <button class="btn btn-danger btn-sm btn-reject-post" data-job-id="${escapeHtml(job.job_id)}">
                  ✕ Reject
                </button>
                <button class="btn btn-primary btn-sm btn-publish-now" data-job-id="${escapeHtml(job.job_id)}">
                  ⚡ Publish Now
                </button>
              ` : ""}
            </div>
          </div>
        </div>`;
      })
      .join("");

    attachQueueItemEvents();
  }

  function attachQueueItemEvents() {
    // Edit buttons
    document.querySelectorAll(".btn-edit-post").forEach((btn) => {
      btn.onclick = function () {
        const jobId = this.getAttribute("data-job-id");
        const rawText = decodeURIComponent(this.getAttribute("data-text") || "");
        const platform = this.getAttribute("data-platform") || "x";
        openEditModal(jobId, rawText, platform);
      };
    });

    // Copy buttons
    document.querySelectorAll(".btn-copy-post").forEach((btn) => {
      btn.onclick = function () {
        const text = decodeURIComponent(this.getAttribute("data-text") || "");
        navigator.clipboard.writeText(text).then(() => {
          showToast("Copied post content to clipboard!", "success");
        }).catch(() => {
          showToast("Failed to copy automatically", "error");
        });
      };
    });

    // Approve buttons
    document.querySelectorAll(".btn-approve-post").forEach((btn) => {
      btn.onclick = async function () {
        const jobId = this.getAttribute("data-job-id");
        try {
          const res = await fetch(`/api/queue/${encodeURIComponent(jobId)}/approve`, { method: "POST" });
          if (!res.ok) throw new Error("Approval failed");
          showToast(`Job ${jobId} approved!`, "success");
          fetchQueue();
          fetchStatus();
        } catch (e) {
          showToast(e.message, "error");
        }
      };
    });

    // Reject buttons
    document.querySelectorAll(".btn-reject-post").forEach((btn) => {
      btn.onclick = async function () {
        const jobId = this.getAttribute("data-job-id");
        try {
          const res = await fetch(`/api/queue/${encodeURIComponent(jobId)}/reject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: "Rejected via dashboard" }),
          });
          if (!res.ok) throw new Error("Rejection failed");
          showToast(`Job ${jobId} rejected.`, "info");
          fetchQueue();
          fetchStatus();
        } catch (e) {
          showToast(e.message, "error");
        }
      };
    });

    // Publish Now buttons
    document.querySelectorAll(".btn-publish-now").forEach((btn) => {
      btn.onclick = async function () {
        const jobId = this.getAttribute("data-job-id");
        try {
          const res = await fetch(`/api/queue/${encodeURIComponent(jobId)}/publish-now`, { method: "POST" });
          if (res.status === 403) {
            showToast("Action blocked: Emergency shutoff active!", "error");
            return;
          }
          if (!res.ok) throw new Error("Publish failed");
          showToast(`Job ${jobId} published successfully!`, "success");
          fetchQueue();
          fetchStatus();
        } catch (e) {
          showToast(e.message, "error");
        }
      };
    });
  }

  // =========================================================================
  // Edit Modal & Em Dash Linter
  // =========================================================================
  function openEditModal(jobId, text, platform) {
    elements.editPostId.value = jobId;
    elements.editPostText.value = text;
    elements.modalMaxChars.textContent = platform === "linkedin" ? "3000" : "280";
    checkModalEmDashes();
    elements.modalEdit.classList.remove("hidden");
  }

  function closeEditModal() {
    elements.modalEdit.classList.add("hidden");
  }

  function cleanDashes(text) {
    return text.replace(/—/g, ": ").replace(/--/g, "-").replace(/–/g, "-");
  }

  function checkModalEmDashes() {
    const text = elements.editPostText.value;
    elements.modalCharCount.textContent = text.length;
    const hasEmDash = /[—–]|--/.test(text);
    if (hasEmDash) {
      elements.modalEmDashWarning.classList.remove("hidden");
    } else {
      elements.modalEmDashWarning.classList.add("hidden");
    }
  }

  async function saveEditedPost() {
    const jobId = elements.editPostId.value;
    const text = cleanDashes(elements.editPostText.value);

    try {
      const res = await fetch(`/api/queue/${encodeURIComponent(jobId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_text: text }),
      });
      if (!res.ok) throw new Error("Failed to save post");
      showToast("Post draft updated & re-linted successfully!", "success");
      closeEditModal();
      fetchQueue();
    } catch (e) {
      showToast(e.message, "error");
    }
  }

  // =========================================================================
  // View 4: Publication History
  // =========================================================================
  async function fetchHistory() {
    try {
      const res = await fetch("/api/queue?status=published&limit=50");
      if (!res.ok) throw new Error("Failed to fetch history");
      const jobs = await res.json();
      renderHistory(jobs);
    } catch (e) {
      console.error("fetchHistory error:", e);
    }
  }

  function renderHistory(jobs) {
    const xCount = jobs.filter((j) => (j.platform || "").toLowerCase() === "x").length;
    const liCount = jobs.filter((j) => (j.platform || "").toLowerCase() === "linkedin").length;

    elements.histTotalCount.textContent = jobs.length;
    elements.histXCount.textContent = xCount;
    elements.histLinkedinCount.textContent = liCount;

    if (!jobs || jobs.length === 0) {
      elements.historyContainer.innerHTML = `
        <div class="empty-state">
          <p>No published releases recorded yet.</p>
        </div>`;
      return;
    }

    elements.historyContainer.innerHTML = jobs
      .map((job) => {
        const text = job.content?.text || "";
        const platform = (job.platform || "x").toUpperCase();
        const dateStr = job.created_at ? new Date(job.created_at).toLocaleString() : "";
        return `
        <div class="item-card">
          <div>
            <div class="item-card-header">
              <span class="badge badge-emerald">${escapeHtml(platform)} PUBLISHED</span>
              <span class="text-sub">${dateStr}</span>
            </div>
            <div class="queue-post-text mt-3">${escapeHtml(text)}</div>
          </div>
          <div class="item-footer">
            <span class="text-sub">Release: @divyprjai</span>
            <span class="badge badge-zero-cost">Verified ₹0</span>
          </div>
        </div>`;
      })
      .join("");
  }

  // =========================================================================
  // View 5: Cost & Dependency Register
  // =========================================================================
  async function fetchDependencies() {
    try {
      const res = await fetch("/api/cost-register");
      if (!res.ok) throw new Error("Failed to fetch dependencies");
      const data = await res.json();
      state.dependencies = data;
      renderDependencies(data);
    } catch (e) {
      console.error("fetchDependencies error:", e);
    }
  }

  function renderDependencies(items) {
    const filter = (elements.filterDepInput.value || "").toLowerCase();
    const filtered = items.filter(
      (item) =>
        (item.name || "").toLowerCase().includes(filter) ||
        (item.category || "").toLowerCase().includes(filter) ||
        (item.license || "").toLowerCase().includes(filter)
    );

    if (filtered.length === 0) {
      elements.depTableBody.innerHTML = `
        <tr><td colspan="6" class="text-center text-sub">No dependencies matching search filter.</td></tr>`;
      return;
    }

    elements.depTableBody.innerHTML = filtered
      .map(
        (item) => `
        <tr>
          <td><strong>${escapeHtml(item.name)}</strong></td>
          <td><span class="badge badge-mode">${escapeHtml(item.category || "General")}</span></td>
          <td><span class="text-sub font-mono">${escapeHtml(item.license || "Open")}</span></td>
          <td>${escapeHtml(item.auth || "None")}</td>
          <td><span class="text-emerald font-mono font-bold">${escapeHtml(item.cost || "₹0.00")}</span></td>
          <td><span class="text-sub">${escapeHtml(item.purpose || "Local verification")}</span></td>
        </tr>`
      )
      .join("");
  }

  // =========================================================================
  // View 6: System Logs & Audit Trail
  // =========================================================================
  async function fetchLogs() {
    try {
      const eventFilter = elements.filterLogEvent.value;
      let url = "/api/logs?limit=100";
      if (eventFilter) url += `&event_type=${encodeURIComponent(eventFilter)}`;

      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch logs");
      const logs = await res.json();
      renderLogs(logs);
    } catch (e) {
      console.error("fetchLogs error:", e);
    }
  }

  function renderLogs(logs) {
    elements.logCountIndicator.textContent = `${logs.length} entries`;
    if (!logs || logs.length === 0) {
      elements.terminalBody.innerHTML = `<div class="terminal-line text-sub">No log entries found.</div>`;
      return;
    }

    elements.terminalBody.innerHTML = logs
      .map((entry) => {
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : "";
        const detailsStr = entry.details ? JSON.stringify(entry.details) : "";
        return `
        <div class="terminal-line">
          <span class="log-time">[${time}]</span>
          <span class="log-event ${escapeHtml(entry.event_type)}">${escapeHtml(entry.event_type)}</span>:
          <span>${escapeHtml(detailsStr)}</span>
        </div>`;
      })
      .join("");

    if (state.autoScrollLogs) {
      elements.terminalBody.scrollTop = elements.terminalBody.scrollHeight;
    }
  }

  function appendTerminalLine(type, message, colorClass = "") {
    const time = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = "terminal-line";
    line.innerHTML = `
      <span class="log-time">[${time}]</span>
      <span class="log-event ${colorClass}">${escapeHtml(type)}</span>:
      <span>${escapeHtml(message)}</span>`;
    elements.terminalBody.appendChild(line);

    if (state.autoScrollLogs) {
      elements.terminalBody.scrollTop = elements.terminalBody.scrollHeight;
    }
  }

  // =========================================================================
  // Navigation & Event Bindings
  // =========================================================================
  function initEventHandlers() {
    // Tab switching
    document.querySelectorAll(".tab-button").forEach((btn) => {
      btn.onclick = function () {
        const targetView = this.getAttribute("data-view");
        document.querySelectorAll(".tab-button").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-view").forEach((v) => v.classList.remove("active"));
        this.classList.add("active");
        const viewEl = document.getElementById(`view-${targetView}`);
        if (viewEl) viewEl.classList.add("active");
        state.activeView = targetView;

        if (targetView === "discovery") fetchDiscovery();
        if (targetView === "queue") fetchQueue();
        if (targetView === "history") fetchHistory();
        if (targetView === "register") fetchDependencies();
        if (targetView === "logs") fetchLogs();
      };
    });

    // Queue sub-tabs
    document.querySelectorAll(".sub-tab").forEach((tab) => {
      tab.onclick = function () {
        document.querySelectorAll(".sub-tab").forEach((t) => t.classList.remove("active"));
        this.classList.add("active");
        state.queueStatusFilter = this.getAttribute("data-queue-status") || "";
        fetchQueue();
      };
    });

    // Pause / Resume Toggle
    elements.btnPause.onclick = async function () {
      const isPaused = state.systemStatus?.is_paused || state.systemStatus?.paused;
      const endpoint = isPaused ? "/api/status/resume" : "/api/status/pause";
      try {
        const res = await fetch(endpoint, { method: "POST" });
        if (!res.ok) throw new Error("Pause/Resume toggle failed");
        showToast(isPaused ? "Automation resumed!" : "Automation paused.", "info");
        fetchStatus();
      } catch (e) {
        showToast(e.message, "error");
      }
    };

    // Emergency Stop
    const triggerEmergencyStop = async function () {
      try {
        const res = await fetch("/api/status/emergency-shutoff", { method: "POST" });
        if (!res.ok) throw new Error("Emergency stop failed");
        showToast("EMERGENCY STOP ACTIVATED! All loops halted.", "error");
        fetchStatus();
      } catch (e) {
        showToast(e.message, "error");
      }
    };

    elements.btnEmergencyStop.onclick = triggerEmergencyStop;
    elements.btnTriggerEmergencyPanel.onclick = triggerEmergencyStop;

    // Emergency Resume
    const triggerEmergencyResume = async function () {
      try {
        const res = await fetch("/api/system/emergency-resume", { method: "POST" });
        if (!res.ok) throw new Error("Resume failed");
        showToast("Operations resumed after emergency halt.", "success");
        fetchStatus();
      } catch (e) {
        showToast(e.message, "error");
      }
    };

    elements.btnEmergencyResume.onclick = triggerEmergencyResume;
    elements.btnBannerResume.onclick = triggerEmergencyResume;

    // Operating Mode
    elements.btnModeAuto.onclick = async () => {
      await fetch("/api/system/toggle-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "AUTONOMOUS" }),
      });
      elements.btnModeAuto.className = "btn btn-sm btn-primary";
      elements.btnModeManual.className = "btn btn-sm btn-secondary";
      showToast("Switched to Autonomous Mode", "success");
      fetchStatus();
    };

    elements.btnModeManual.onclick = async () => {
      await fetch("/api/system/toggle-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "MANUAL" }),
      });
      elements.btnModeAuto.className = "btn btn-sm btn-secondary";
      elements.btnModeManual.className = "btn btn-sm btn-primary";
      showToast("Switched to Manual Approval Gate Mode", "info");
      fetchStatus();
    };

    // Manual Trigger Discovery
    const triggerDiscovery = async function () {
      try {
        showToast("Ingesting configured feeds...", "info");
        const res = await fetch("/api/items/trigger-discovery", { method: "POST" });
        if (!res.ok) throw new Error("Discovery trigger failed");
        showToast("Discovery cycle initiated!", "success");
        setTimeout(fetchDiscovery, 800);
      } catch (e) {
        showToast(e.message, "error");
      }
    };

    elements.btnTriggerDiscovery.onclick = triggerDiscovery;
    elements.btnPollDiscoveryView.onclick = triggerDiscovery;

    // Refresh Buttons
    elements.btnRefreshHealth.onclick = fetchStatus;
    elements.btnRefreshDiscovery.onclick = fetchDiscovery;
    elements.btnRefreshQueue.onclick = fetchQueue;
    elements.btnRefreshHistory.onclick = fetchHistory;
    elements.btnRefreshLogs.onclick = fetchLogs;

    // Discovery Filters
    elements.filterSource.onchange = fetchDiscovery;
    elements.filterVerified.onchange = fetchDiscovery;
    elements.filterMinScore.oninput = function () {
      elements.filterScoreVal.textContent = this.value;
      fetchDiscovery();
    };

    // Dependencies search
    elements.filterDepInput.oninput = () => renderDependencies(state.dependencies);

    // Logs Controls
    elements.btnClearLogs.onclick = () => {
      elements.terminalBody.innerHTML = `<div class="terminal-line text-sub">Terminal cleared.</div>`;
      elements.logCountIndicator.textContent = "0 entries";
    };
    elements.filterLogEvent.onchange = fetchLogs;
    elements.chkAutoscroll.onchange = function () {
      state.autoScrollLogs = this.checked;
    };

    // Modal Edit Post
    elements.editPostText.oninput = checkModalEmDashes;
    elements.btnModalCleanDashes.onclick = () => {
      elements.editPostText.value = cleanDashes(elements.editPostText.value);
      checkModalEmDashes();
      showToast("Em dashes replaced with valid formatting.", "info");
    };
    elements.btnModalCancel.onclick = closeEditModal;
    elements.btnCloseModal.onclick = closeEditModal;
    elements.btnModalSave.onclick = saveEditedPost;
  }

  // =========================================================================
  // Initial Boot
  // =========================================================================
  function init() {
    initEventHandlers();
    initWebSocket();
    fetchStatus();
    fetchDiscovery();
    fetchQueue();
    fetchDependencies();
    fetchLogs();

    // Regular status polling fallback every 10s
    setInterval(fetchStatus, 10000);
  }

  window.addEventListener("DOMContentLoaded", init);
})();
