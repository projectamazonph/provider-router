/**
 * Provider Router — Dashboard Plugin
 *
 * Monitors token usage, manages provider rotation, and controls local LLM fallback.
 * Uses window.__HERMES_PLUGIN_SDK__ for React + UI components.
 * Registers via window.__HERMES_PLUGINS__.register().
 */

(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  var React = SDK.React;
  var h = React.createElement;
  var hooks = SDK.hooks;
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useCallback = hooks.useCallback;
  var useMemo = hooks.useMemo;
  var components = SDK.components;
  var utils = SDK.utils;
  var api = SDK.api;
  var useI18n = SDK.useI18n || function () { return { t: {}, locale: "en" }; };

  var API_BASE = "/api/plugins/provider-router";

  // ─── API Client ───────────────────────────────────────────────────────────

  function apiGet(path) {
    return api.fetchJSON(API_BASE + path);
  }

  function apiPost(path, body) {
    if (body === undefined) body = {};
    return fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) throw new Error("API error: " + res.status);
      return res.json();
    });
  }

  // ─── Helpers ──────────────────────────────────────────────────────────────

  function statusColor(status) {
    var map = { active: "#22c55e", rate_limited: "#f59e0b", exhausted: "#ef4444", error: "#ef4444", offline: "#6b7280" };
    return map[status] || "#6b7280";
  }

  function StatusBadge(_ref) {
    var status = _ref.status;
    return h("span", {
      style: {
        display: "inline-block", padding: "2px 8px", borderRadius: "12px",
        fontSize: "11px", fontWeight: 600, color: "#fff",
        background: statusColor(status), textTransform: "uppercase", letterSpacing: "0.5px",
      }
    }, status);
  }

  function StatCard(_ref2) {
    var value = _ref2.value, label = _ref2.label, color = _ref2.color;
    return h("div", {
      style: { background: "var(--surface-elevated, #1a1a2e)", borderRadius: "12px", padding: "16px", textAlign: "center" }
    },
      h("div", { style: { fontSize: "28px", fontWeight: 700, color: color } }, value),
      h("div", { style: { fontSize: "12px", color: "var(--text-secondary)" } }, label)
    );
  }

  // ─── Provider Card ────────────────────────────────────────────────────────

  function ProviderCard(_ref3) {
    var name = _ref3.name, data = _ref3.data;
    var state = data.state || {};
    var creds = data.credentials || {};
    var isAvailable = state.is_available;

    return h("div", {
      style: {
        background: "var(--surface-elevated, #1a1a2e)", borderRadius: "12px",
        padding: "16px", marginBottom: "12px",
        border: "1px solid " + (isAvailable ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"),
      }
    },
      h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" } },
        h("div", null,
          h("h3", { style: { margin: 0, fontSize: "16px", fontWeight: 600 } }, name),
          h("div", { style: { fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" } }, state.model || "No model set")
        ),
        h(StatusBadge, { status: state.status })
      ),
      h("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "12px", fontSize: "13px" } },
        statItem("Tokens In", (state.tokens_in || 0).toLocaleString()),
        statItem("Tokens Out", (state.tokens_out || 0).toLocaleString()),
        statItem("Total Cost", "$" + (state.total_cost || 0).toFixed(4)),
        statItem("Credentials",
          h("span", null,
            h("span", { style: { color: "#22c55e" } }, creds.active || 0),
            "/",
            creds.total || 0,
            (creds.exhausted > 0) ? h("span", { style: { color: "#ef4444", marginLeft: "4px" } }, "(" + creds.exhausted + " exhausted)") : null
          )
        ),
        statItem("Error Rate", ((state.error_rate || 0) * 100).toFixed(1) + "%"),
        statItem("Avg Latency", (state.avg_latency_ms || 0).toFixed(0) + "ms")
      ),
      state.last_error
        ? h("div", {
            style: { marginTop: "8px", padding: "8px", background: "rgba(239,68,68,0.1)", borderRadius: "6px", fontSize: "12px", color: "#fca5a5", fontFamily: "monospace" }
          }, "Last error: " + state.last_error)
        : null
    );
  }

  function statItem(label, value) {
    return h("div", null,
      h("div", { style: { color: "var(--text-secondary)" } }, label),
      h("div", { style: { fontWeight: 600, fontFamily: "monospace" } }, value)
    );
  }

  // ─── Local LLM Section ────────────────────────────────────────────────────

  function LocalLLMSection(_ref4) {
    var status = _ref4.status, onStart = _ref4.onStart, onStop = _ref4.onStop;
    var running = status.running;

    return h("div", { style: { background: "var(--surface-elevated, #1a1a2e)", borderRadius: "12px", padding: "16px", marginBottom: "12px" } },
      h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" } },
        h("h3", { style: { margin: 0, fontSize: "16px", fontWeight: 600 } }, "🖥️ Local LLM Fallback"),
        h(StatusBadge, { status: running ? "active" : "offline" })
      ),
      h("div", { style: { fontSize: "13px", color: "var(--text-secondary)", marginBottom: "12px" } },
        h("div", null, "Server: ", h("code", { style: { color: "var(--text-primary)" } }, status.url)),
        h("div", null, "Model: ", h("code", { style: { color: "var(--text-primary)" } }, status.model_name)),
        h("div", null, "Recommended: ", h("code", { style: { color: "#22c55e" } }, status.recommended_model))
      ),
      h("div", { style: { display: "flex", gap: "8px" } },
        !running
          ? h("button", { onClick: onStart, style: { padding: "8px 16px", borderRadius: "6px", border: "none", background: "#22c55e", color: "#fff", fontSize: "13px", fontWeight: 600, cursor: "pointer" } }, "▶ Start Server")
          : h("button", { onClick: onStop, style: { padding: "8px 16px", borderRadius: "6px", border: "none", background: "#ef4444", color: "#fff", fontSize: "13px", fontWeight: 600, cursor: "pointer" } }, "⏹ Stop Server")
      )
    );
  }

  // ─── Notification Log ─────────────────────────────────────────────────────

  function NotificationLog(_ref5) {
    var notifications = _ref5.notifications;
    if (!notifications || notifications.length === 0) {
      return h("div", { style: { padding: "20px", textAlign: "center", color: "var(--text-secondary)", fontSize: "13px" } }, "No notifications yet");
    }
    return h("div", { style: { maxHeight: "400px", overflowY: "auto" } },
      notifications.slice().reverse().map(function (n, i) {
        return h("div", { key: i, style: { padding: "10px 12px", borderBottom: "1px solid var(--border)", fontSize: "13px" } },
          h("div", { style: { display: "flex", justifyContent: "space-between", marginBottom: "4px" } },
            h("span", { style: { fontWeight: 600, color: n.severity === "critical" ? "#ef4444" : n.severity === "warning" ? "#f59e0b" : "var(--text-primary)" } }, n.type),
            h("span", { style: { color: "var(--text-secondary)", fontSize: "11px" } }, new Date(n.timestamp).toLocaleString())
          ),
          h("div", { style: { color: "var(--text-secondary)" } }, n.message)
        );
      })
    );
  }

  // ─── Settings Panel ───────────────────────────────────────────────────────

  function SettingsPanel(_ref6) {
    var config = _ref6.config, onSave = _ref6.onSave;
    var _useState = useState(config.strategy || "priority"), strategy = _useState[0], setStrategy = _useState[1];
    var _useState2 = useState(config.auto_switch !== false), autoSwitch = _useState[0], setAutoSwitch = _useState[1];
    var _useState3 = useState(config.rate_limit_cooldown_seconds || 60), cooldown = _useState[3], setCooldown = _useState[3];

    // Fix: useState returns [value, setter]
    var cs = useState(config.rate_limit_cooldown_seconds || 60);
    cooldown = cs[0]; setCooldown = cs[1];

    return h("div", { style: { background: "var(--surface-elevated, #1a1a2e)", borderRadius: "12px", padding: "16px", marginBottom: "12px" } },
      h("h3", { style: { margin: "0 0 16px 0", fontSize: "16px", fontWeight: 600 } }, "⚙️ Settings"),

      h("div", { style: { marginBottom: "16px" } },
        h("label", { style: { fontSize: "13px", color: "var(--text-secondary)", display: "block", marginBottom: "6px" } }, "Rotation Strategy"),
        h("select", { value: strategy, onChange: function (e) { setStrategy(e.target.value); }, style: { width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-primary)", fontSize: "13px" } },
          h("option", { value: "priority" }, "Priority (ordered list)"),
          h("option", { value: "cost_first" }, "Cost First (cheapest)"),
          h("option", { value: "reliability_first" }, "Reliability First"),
          h("option", { value: "round_robin" }, "Round Robin")
        )
      ),

      h("div", { style: { marginBottom: "16px" } },
        h("label", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", cursor: "pointer" } },
          h("input", { type: "checkbox", checked: autoSwitch, onChange: function (e) { setAutoSwitch(e.target.checked); } }),
          "Auto-switch on provider failure"
        )
      ),

      h("div", { style: { marginBottom: "16px" } },
        h("label", { style: { fontSize: "13px", color: "var(--text-secondary)", display: "block", marginBottom: "6px" } }, "Rate Limit Cooldown (seconds)"),
        h("input", { type: "number", value: cooldown, onChange: function (e) { setCooldown(parseInt(e.target.value) || 60); }, min: 10, max: 3600, style: { width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-primary)", fontSize: "13px" } })
      ),

      h("button", {
        onClick: function () {
          onSave(Object.assign({}, config, { strategy: strategy, auto_switch: autoSwitch, rate_limit_cooldown_seconds: cooldown }));
        },
        style: { padding: "8px 16px", borderRadius: "6px", border: "none", background: "#3b82f6", color: "#fff", fontSize: "13px", fontWeight: 600, cursor: "pointer" }
      }, "Save Settings")
    );
  }

  // ─── Main Dashboard Component ─────────────────────────────────────────────

  function ProviderRouterDashboard() {
    var _useState4 = useState("dashboard"), activeTab = _useState4[0], setActiveTab = _useState4[1];
    var _useState5 = useState(null), status = _useState5[0], setStatus = _useState5[1];
    var _useState6 = useState(true), loading = _useState6[0], setLoading = _useState6[1];
    var _useState7 = useState(null), error = _useState7[0], setError = _useState7[1];

    var fetchStatus = useCallback(function () {
      apiGet("/status").then(function (data) {
        setStatus(data);
        setError(null);
      }).catch(function (e) {
        setError(e.message);
      }).finally(function () {
        setLoading(false);
      });
    }, []);

    useEffect(function () {
      fetchStatus();
      var interval = setInterval(fetchStatus, 15000);
      return function () { clearInterval(interval); };
    }, [fetchStatus]);

    var handleStartLocal = useCallback(function () {
      apiPost("/local/start").then(fetchStatus).catch(function (e) { alert("Failed to start: " + e.message); });
    }, [fetchStatus]);

    var handleStopLocal = useCallback(function () {
      apiPost("/local/stop").then(fetchStatus).catch(function (e) { alert("Failed to stop: " + e.message); });
    }, [fetchStatus]);

    var handleRotate = useCallback(function () {
      apiPost("/rotate").then(fetchStatus).catch(function (e) { alert("Rotation failed: " + e.message); });
    }, [fetchStatus]);

    var handleSaveConfig = useCallback(function (newConfig) {
      apiPost("/config", newConfig).then(fetchStatus).catch(function (e) { alert("Failed to save: " + e.message); });
    }, [fetchStatus]);

    var handleClearNotifications = useCallback(function () {
      apiPost("/notifications/clear").then(fetchStatus);
    }, [fetchStatus]);

    if (loading) {
      return h("div", { style: { display: "flex", alignItems: "center", justifyContent: "center", height: "300px", color: "var(--text-secondary)" } }, "Loading provider status...");
    }

    if (error) {
      return h("div", { style: { padding: "20px", textAlign: "center" } },
        h("div", { style: { color: "#ef4444", marginBottom: "12px" } }, "⚠️ Error: " + error),
        h("button", { onClick: fetchStatus, style: { padding: "8px 16px", borderRadius: "6px", border: "none", background: "#3b82f6", color: "#fff", cursor: "pointer" } }, "Retry")
      );
    }

    var providers = (status && status.providers) ? status.providers : {};
    var notifications = (status && status.notifications) ? status.notifications : [];
    var config = (status && status.config) ? status.config : {};
    var localStatus = {
      running: status ? status.local_server_running : false,
      url: "http://127.0.0.1:" + (config.local_server_port || 8080) + "/v1",
      model_path: config.local_model_path || "",
      model_name: config.local_model_name || "local/llama-3.2-3b-instruct",
      recommended_model: status ? status.recommended_model : "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    };

    var providerCount = Object.keys(providers).length;
    var availableCount = Object.values(providers).filter(function (p) { return p.state && p.state.is_available; }).length;
    var activeProvider = status ? status.active_provider : "—";

    var tabs = [
      { id: "dashboard", label: "📊 Dashboard" },
      { id: "settings", label: "⚙️ Settings" },
      { id: "logs", label: "📋 Logs" },
    ];

    function renderDashboard() {
      return h("div", null,
        h("div", { style: { display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" } },
          h("button", { onClick: handleRotate, style: { padding: "8px 16px", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-primary)", fontSize: "13px", cursor: "pointer" } }, "🔄 Force Rotate"),
          h("button", { onClick: fetchStatus, style: { padding: "8px 16px", borderRadius: "6px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-primary)", fontSize: "13px", cursor: "pointer" } }, "↻ Refresh")
        ),
        h(LocalLLMSection, { status: localStatus, onStart: handleStartLocal, onStop: handleStopLocal }),
        h("h3", { style: { fontSize: "16px", fontWeight: 600, marginBottom: "12px" } }, "Providers"),
        Object.entries(providers).map(function (entry) {
          return h(ProviderCard, { key: entry[0], name: entry[0], data: entry[1] });
        })
      );
    }

    function renderSettings() {
      return h(SettingsPanel, { config: config, onSave: handleSaveConfig });
    }

    function renderLogs() {
      return h("div", null,
        h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" } },
          h("h3", { style: { margin: 0, fontSize: "16px", fontWeight: 600 } }, "Notifications (" + notifications.length + ")"),
          h("button", { onClick: handleClearNotifications, style: { padding: "6px 12px", borderRadius: "6px", border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", fontSize: "12px", cursor: "pointer" } }, "Clear All")
        ),
        h("div", { style: { background: "var(--surface-elevated, #1a1a2e)", borderRadius: "12px", overflow: "hidden" } },
          h(NotificationLog, { notifications: notifications })
        )
      );
    }

    return h("div", { style: { padding: "16px", maxWidth: "1200px", margin: "0 auto" } },
      // Header
      h("div", { style: { marginBottom: "20px" } },
        h("h1", { style: { margin: "0 0 8px 0", fontSize: "24px", fontWeight: 700 } }, "🔀 Provider Router"),
        h("div", { style: { color: "var(--text-secondary)", fontSize: "14px" } }, "Intelligent token monitoring, provider rotation, and local LLM fallback")
      ),

      // Quick Stats
      h("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px", marginBottom: "20px" } },
        h(StatCard, { value: providerCount, label: "Providers", color: "#3b82f6" }),
        h(StatCard, { value: availableCount, label: "Available", color: "#22c55e" }),
        h(StatCard, { value: activeProvider || "—", label: "Active", color: "#f59e0b" }),
        h(StatCard, { value: localStatus.running ? "✓" : "✗", label: "Local LLM", color: localStatus.running ? "#22c55e" : "#6b7280" })
      ),

      // Tabs
      h("div", { style: { display: "flex", gap: "4px", marginBottom: "20px", borderBottom: "1px solid var(--border)" } },
        tabs.map(function (tab) {
          return h("button", {
            key: tab.id,
            onClick: function () { setActiveTab(tab.id); },
            style: {
              padding: "10px 20px", border: "none",
              background: activeTab === tab.id ? "var(--surface-elevated, #1a1a2e)" : "transparent",
              color: activeTab === tab.id ? "var(--text-primary)" : "var(--text-secondary)",
              fontSize: "14px", fontWeight: activeTab === tab.id ? 600 : 400,
              cursor: "pointer", borderRadius: "8px 8px 0 0",
              borderBottom: activeTab === tab.id ? "2px solid #3b82f6" : "2px solid transparent",
            }
          }, tab.label);
        })
      ),

      // Tab Content
      activeTab === "dashboard" ? renderDashboard() : null,
      activeTab === "settings" ? renderSettings() : null,
      activeTab === "logs" ? renderLogs() : null
    );
  }

  // ─── Register ──────────────────────────────────────────────────────────────

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("provider-router", ProviderRouterDashboard);
  }
})();
