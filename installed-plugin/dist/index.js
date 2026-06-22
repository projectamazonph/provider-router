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
  if (!SDK) {
    console.warn("[provider-router] SDK not available — plugin will not load");
    return;
  }

  console.log("[provider-router] SDK found, initializing...");

  try {
    var React = SDK.React;
    var h = React.createElement;
    var hooks = SDK.hooks;
    var useState = hooks.useState;
    var useEffect = hooks.useEffect;
    var useCallback = hooks.useCallback;
    var api = SDK.api;

    var API_BASE = "/api/plugins/provider-router";

    // ─── API ───────────────────────────────────────────────────────────────────

    function apiGet(path) {
      return api.fetchJSON(API_BASE + path);
    }

    function apiPost(path, body) {
      return api.fetchJSON(API_BASE + path, { method: "POST", body: body || {} });
    }

    // ─── Status Badge ─────────────────────────────────────────────────────────

    function StatusBadge(props) {
      var colors = { active: "#22c55e", rate_limited: "#f59e0b", exhausted: "#ef4444", error: "#ef4444", offline: "#6b7280" };
      return h("span", { className: "inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide text-white", style: { background: colors[props.status] || "#6b7280" } }, props.status);
    }

    // ─── Helper: Stat (single grid cell) ──────────────────────────────────────

    function Stat(props) {
      return h("div", null,
        h("div", { className: "text-[var(--text-secondary)] text-[10px] mb-0.5" }, props.label),
        h("div", { className: "font-semibold font-mono text-xs" }, props.value)
      );
    }

    // ─── Stat Card ─────────────────────────────────────────────────────────────

    function StatCard(props) {
      return h("div", { className: "rounded-xl p-3 text-center", style: { background: "var(--surface-elevated, #1a1a2e)" } },
        h("div", { className: "text-xl font-bold", style: { color: props.color } }, props.value),
        h("div", { className: "text-[10px] text-[var(--text-secondary)]" }, props.label)
      );
    }

    // ─── Provider Card ────────────────────────────────────────────────────────

    function ProviderCard(props) {
      var name = props.name, data = props.data;
      var state = data.state || {};
      var creds = data.credentials || {};
      var ok = state.is_available;

      return h("div", { className: "rounded-xl p-4 mb-3", style: { background: "var(--surface-elevated, #1a1a2e)", border: "1px solid " + (ok ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)") } },
        h("div", { className: "flex justify-between items-center mb-3" },
          h("div", null,
            h("h3", { className: "text-sm font-semibold m-0" }, name),
            h("div", { className: "text-[11px] text-[var(--text-secondary)] mt-0.5" }, state.model || "No model")
          ),
          h(StatusBadge, { status: state.status })
        ),
        h("div", { className: "grid grid-cols-3 gap-3 text-xs" },
          h(Stat, { label: "Tokens In", value: (state.tokens_in || 0).toLocaleString() }),
          h(Stat, { label: "Tokens Out", value: (state.tokens_out || 0).toLocaleString() }),
          h(Stat, { label: "Cost", value: "$" + (state.total_cost || 0).toFixed(4) }),
          h(Stat, { label: "Creds", value: (creds.active || 0) + "/" + (creds.total || 0) + (creds.exhausted ? " (" + creds.exhausted + " ex)" : "") }),
          h(Stat, { label: "Errors", value: ((state.error_rate || 0) * 100).toFixed(1) + "%" }),
          h(Stat, { label: "Latency", value: (state.avg_latency_ms || 0).toFixed(0) + "ms" })
        ),
        state.last_error
          ? h("div", { className: "mt-2 p-2 rounded text-[11px] font-mono", style: { background: "rgba(239,68,68,0.1)", color: "#fca5a5" } }, "Error: " + state.last_error)
          : null
      );
    }

    // ─── Local LLM ────────────────────────────────────────────────────────────

    function LocalLLM(props) {
      var s = props.status;
      return h("div", { className: "rounded-xl p-4 mb-3", style: { background: "var(--surface-elevated, #1a1a2e)" } },
        h("div", { className: "flex justify-between items-center mb-3" },
          h("h3", { className: "text-sm font-semibold m-0" }, "Local LLM"),
          h(StatusBadge, { status: s.running ? "active" : "offline" })
        ),
        h("div", { className: "text-xs text-[var(--text-secondary)] mb-3" },
          h("div", null, "Server: ", h("code", null, s.url)),
          h("div", null, "Model: ", h("code", null, s.model_name)),
          h("div", null, "Recommended: ", h("code", { style: { color: "#22c55e" } }, s.recommended_model))
        ),
        h("button", {
          onClick: s.running ? props.onStop : props.onStart,
          className: "px-4 py-2 rounded text-xs font-semibold text-white cursor-pointer",
          style: { background: s.running ? "#ef4444" : "#22c55e", border: "none", outline: "none" }
        }, s.running ? "Stop Server" : "Start Server")
      );
    }

    // ─── Notifications ────────────────────────────────────────────────────────

    function NotifLog(props) {
      var n = props.notifications || [];
      if (!n.length) return h("div", { className: "p-5 text-center text-[var(--text-secondary)] text-xs" }, "No notifications");
      return h("div", { className: "max-h-96 overflow-y-auto" },
        n.slice().reverse().map(function (item, i) {
          var sevColor = item.severity === "critical" ? "#ef4444" : item.severity === "warning" ? "#f59e0b" : "inherit";
          return h("div", { key: i, className: "px-3 py-2 border-b border-[var(--border)] text-xs" },
            h("div", { className: "flex justify-between mb-1" },
              h("span", { className: "font-semibold", style: { color: sevColor } }, item.type),
              h("span", { className: "text-[var(--text-secondary)] text-[10px]" }, new Date(item.timestamp).toLocaleString())
            ),
            h("div", { className: "text-[var(--text-secondary)]" }, item.message)
          );
        })
      );
    }

    // ─── Settings ─────────────────────────────────────────────────────────────

    function Settings(props) {
      var cfg = props.config;
      var onSave = props.onSave;
      var _s1 = useState(cfg.strategy || "priority"), strat = _s1[0], setStrat = _s1[1];
      var _s2 = useState(cfg.auto_switch !== false), auto = _s2[0], setAuto = _s2[1];
      var _s3 = useState(cfg.rate_limit_cooldown_seconds || 60), cool = _s3[0], setCool = _s3[1];

      return h("div", { className: "rounded-xl p-4 mb-3", style: { background: "var(--surface-elevated, #1a1a2e)" } },
        h("h3", { className: "text-sm font-semibold mb-4 m-0" }, "Settings"),

        h("div", { className: "mb-4" },
          h("label", { className: "text-xs text-[var(--text-secondary)] block mb-1.5" }, "Rotation Strategy"),
          h("select", { value: strat, onChange: function (e) { setStrat(e.target.value); }, className: "w-full px-3 py-2 rounded border border-[var(--border)] bg-[var(--surface)] text-sm", style: { color: "var(--text-primary)" } },
            h("option", { value: "priority" }, "Priority"),
            h("option", { value: "cost_first" }, "Cost First"),
            h("option", { value: "reliability_first" }, "Reliability First"),
            h("option", { value: "round_robin" }, "Round Robin")
          )
        ),

        h("div", { className: "mb-4" },
          h("label", { className: "flex items-center gap-2 text-xs cursor-pointer" },
            h("input", { type: "checkbox", checked: auto, onChange: function (e) { setAuto(e.target.checked); } }),
            "Auto-switch on failure"
          )
        ),

        h("div", { className: "mb-4" },
          h("label", { className: "text-xs text-[var(--text-secondary)] block mb-1.5" }, "Rate Limit Cooldown (s)"),
          h("input", { type: "number", value: cool, onChange: function (e) { setCool(parseInt(e.target.value) || 60); }, min: 10, max: 3600, className: "w-full px-3 py-2 rounded border border-[var(--border)] bg-[var(--surface)] text-sm", style: { color: "var(--text-primary)" } })
        ),

        h("button", {
          onClick: function () { onSave(Object.assign({}, cfg, { strategy: strat, auto_switch: auto, rate_limit_cooldown_seconds: cool })); },
          className: "px-4 py-2 rounded text-xs font-semibold text-white cursor-pointer",
          style: { background: "#3b82f6", border: "none", outline: "none" }
        }, "Save")
      );
    }

    // ─── Main Dashboard Component ─────────────────────────────────────────────

    function ProviderRouterDashboard() {
      var _tab = useState("dashboard"), activeTab = _tab[0], setTab = _tab[1];
      var _st = useState(null), status = _st[0], setStatus = _st[1];
      var _ld = useState(true), loading = _ld[0], setLoading = _ld[1];
      var _err = useState(null), error = _err[0], setError = _err[1];

      var fetchStatus = useCallback(function () {
        apiGet("/status").then(function (d) { setStatus(d); setError(null); }).catch(function (e) { setError(e.message); }).finally(function () { setLoading(false); });
      }, []);

      useEffect(function () { fetchStatus(); var i = setInterval(fetchStatus, 15000); return function () { clearInterval(i); }; }, [fetchStatus]);

      if (loading) return h("div", { className: "flex items-center justify-center h-48 text-[var(--text-secondary)] text-sm" }, "Loading...");
      if (error) return h("div", { className: "p-5 text-center" }, h("div", { className: "text-red-500 mb-2" }, "Error: " + error), h("button", { onClick: fetchStatus, className: "px-4 py-2 bg-blue-500 text-white rounded text-xs cursor-pointer", style: { border: "none", outline: "none" } }, "Retry"));

      var providers = (status && status.providers) || {};
      var notifications = (status && status.notifications) || [];
      var config = (status && status.config) || {};
      var local = {
        running: status ? status.local_server_running : false,
        url: "http://127.0.0.1:" + (config.local_server_port || 8080) + "/v1",
        model_name: config.local_model_name || "local/llama-3.2-3b-instruct",
        recommended_model: status ? status.recommended_model : "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
      };

      var provCount = Object.keys(providers).length;
      var availCount = Object.values(providers).filter(function (p) { return p.state && p.state.is_available; }).length;

      var tabs = [
        { id: "dashboard", label: "Dashboard" },
        { id: "settings", label: "Settings" },
        { id: "logs", label: "Logs" },
      ];

      return h("div", { className: "p-4 max-w-4xl mx-auto" },
        // Stats row
        h("div", { className: "grid grid-cols-4 gap-2 mb-4" },
          h(StatCard, { value: provCount, label: "Providers", color: "#3b82f6" }),
          h(StatCard, { value: availCount, label: "Available", color: "#22c55e" }),
          h(StatCard, { value: (status && status.active_provider) || "—", label: "Active", color: "#f59e0b" }),
          h(StatCard, { value: local.running ? "OK" : "Off", label: "Local LLM", color: local.running ? "#22c55e" : "#6b7280" })
        ),

        // Local LLM card
        h(LocalLLM, {
          status: local,
          onStart: function () { apiPost("/local/start").then(fetchStatus); },
          onStop: function () { apiPost("/local/stop").then(fetchStatus); }
        }),

        // Tab bar
        h("div", { className: "flex gap-1 mb-4 border-b border-[var(--border)]" },
          tabs.map(function (t) {
            return h("button", {
              key: t.id,
              onClick: function () { setTab(t.id); },
              className: "px-4 py-2 text-xs font-medium rounded-t-lg cursor-pointer",
              style: {
                background: activeTab === t.id ? "var(--surface-elevated, #1a1a2e)" : "transparent",
                color: activeTab === t.id ? "var(--text-primary)" : "var(--text-secondary)",
                border: "none",
                borderBottom: activeTab === t.id ? "2px solid #3b82f6" : "2px solid transparent",
              }
            }, t.label);
          })
        ),

        // Tab content
        activeTab === "dashboard" && h("div", null,
          h("div", { className: "flex gap-2 mb-3" },
            h("button", { onClick: function () { apiPost("/rotate").then(fetchStatus); }, className: "px-3 py-1.5 rounded border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] text-xs cursor-pointer" }, "Rotate"),
            h("button", { onClick: fetchStatus, className: "px-3 py-1.5 rounded border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] text-xs cursor-pointer" }, "Refresh")
          ),
          h("h4", { className: "text-xs font-semibold mb-2" }, "Providers"),
          Object.entries(providers).map(function (e) { return h(ProviderCard, { key: e[0], name: e[0], data: e[1] }); })
        ),

        activeTab === "settings" && h(Settings, { config: config, onSave: function (c) { apiPost("/config", c).then(fetchStatus); } }),

        activeTab === "logs" && h("div", null,
          h("div", { className: "flex justify-between items-center mb-2" },
            h("h4", { className: "text-xs font-semibold m-0" }, "Notifications (" + notifications.length + ")"),
            h("button", { onClick: function () { apiPost("/notifications/clear").then(fetchStatus); }, className: "px-2 py-1 rounded border border-[var(--border)] text-[10px] text-[var(--text-secondary)] cursor-pointer", style: { background: "transparent" } }, "Clear")
          ),
          h("div", { className: "rounded-xl overflow-hidden", style: { background: "var(--surface-elevated, #1a1a2e)" } },
            h(NotifLog, { notifications: notifications })
          )
        )
      );
    }

    // ─── Register — synchronous, no setTimeout race ───────────────────────────

    if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
      window.__HERMES_PLUGINS__.register("provider-router", ProviderRouterDashboard);
      console.log("[provider-router] Registered successfully!");
    } else {
      console.error("[provider-router] Cannot register — __HERMES_PLUGINS__ not available");
    }

  } catch (err) {
    console.error("[provider-router] Init error:", err);
  }
})();