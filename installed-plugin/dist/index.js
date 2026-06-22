/**
 * Provider Router — Dashboard Plugin
 * 
 * Self-contained vanilla JS plugin for the Hermes dashboard.
 * No build step required.
 */

(function() {
  'use strict';

  const API_BASE = '/api/plugins/provider-router';

  // ─── API Client ───────────────────────────────────────────────────────────

  async function apiGet(path) {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  }

  async function apiPost(path, body = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  }

  // ─── Status Badge ─────────────────────────────────────────────────────────

  function statusBadge(status) {
    const colors = {
      active: '#22c55e',
      rate_limited: '#f59e0b',
      exhausted: '#ef4444',
      error: '#ef4444',
      offline: '#6b7280',
    };
    const color = colors[status] || '#6b7280';
    return `<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;color:#fff;background:${color};text-transform:uppercase;letter-spacing:0.5px;">${status}</span>`;
  }

  // ─── Main Dashboard Component ─────────────────────────────────────────────

  function ProviderRouterDashboard() {
    const [activeTab, setActiveTab] = React.useState('dashboard');
    const [status, setStatus] = React.useState(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState(null);

    const fetchStatus = React.useCallback(async () => {
      try {
        const data = await apiGet('/status');
        setStatus(data);
        setError(null);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }, []);

    React.useEffect(() => {
      fetchStatus();
      const interval = setInterval(fetchStatus, 15000);
      return () => clearInterval(interval);
    }, [fetchStatus]);

    if (loading) {
      return React.createElement('div', {
        style: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px', color: 'var(--text-secondary)' }
      }, 'Loading provider status...');
    }

    if (error) {
      return React.createElement('div', { style: { padding: '20px', textAlign: 'center' } },
        React.createElement('div', { style: { color: '#ef4444', marginBottom: '12px' } }, '⚠️ Error: ' + error),
        React.createElement('button', {
          onClick: fetchStatus,
          style: { padding: '8px 16px', borderRadius: '6px', border: 'none', background: '#3b82f6', color: '#fff', cursor: 'pointer' }
        }, 'Retry')
      );
    }

    const providers = (status && status.providers) ? status.providers : {};
    const notifications = (status && status.notifications) ? status.notifications : [];
    const config = (status && status.config) ? status.config : {};
    const localStatus = {
      running: status ? status.local_server_running : false,
      url: 'http://127.0.0.1:' + (config.local_server_port || 8080) + '/v1',
      model_path: config.local_model_path || '',
      model_name: config.local_model_name || 'local/llama-3.2-3b-instruct',
      recommended_model: status ? status.recommended_model : 'Llama-3.2-3B-Instruct-Q4_K_M.gguf',
    };

    const providerCount = Object.keys(providers).length;
    const availableCount = Object.values(providers).filter(function(p) { return p.state && p.state.is_available; }).length;
    const activeProvider = status ? status.active_provider : '—';

    // ─── Tab: Dashboard ────────────────────────────────────────────────────

    function renderDashboard() {
      return React.createElement('div', null,
        // Quick Actions
        React.createElement('div', { style: { display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' } },
          React.createElement('button', {
            onClick: async function() { await apiPost('/rotate'); fetchStatus(); },
            style: { padding: '8px 16px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-primary)', fontSize: '13px', cursor: 'pointer' }
          }, '🔄 Force Rotate'),
          React.createElement('button', {
            onClick: fetchStatus,
            style: { padding: '8px 16px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-primary)', fontSize: '13px', cursor: 'pointer' }
          }, '↻ Refresh')
        ),

        // Local LLM Section
        renderLocalLLM(),

        // Provider Cards
        React.createElement('h3', { style: { fontSize: '16px', fontWeight: 600, marginBottom: '12px' } }, 'Providers'),
        Object.entries(providers).map(function(entry) {
          return renderProviderCard(entry[0], entry[1]);
        })
      );
    }

    function renderLocalLLM() {
      return React.createElement('div', {
        style: { background: 'var(--surface-elevated, #1a1a2e)', borderRadius: '12px', padding: '16px', marginBottom: '12px' }
      },
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' } },
          React.createElement('h3', { style: { margin: 0, fontSize: '16px', fontWeight: 600 } }, '🖥️ Local LLM Fallback'),
          statusBadge(localStatus.running ? 'active' : 'offline')
        ),
        React.createElement('div', { style: { fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '12px' } },
          React.createElement('div', null, 'Server: ', React.createElement('code', { style: { color: 'var(--text-primary)' } }, localStatus.url)),
          React.createElement('div', null, 'Model: ', React.createElement('code', { style: { color: 'var(--text-primary)' } }, localStatus.model_name)),
          React.createElement('div', null, 'Recommended: ', React.createElement('code', { style: { color: '#22c55e' } }, localStatus.recommended_model))
        ),
        React.createElement('div', { style: { display: 'flex', gap: '8px' } },
          !localStatus.running
            ? React.createElement('button', {
                onClick: async function() { await apiPost('/local/start'); fetchStatus(); },
                style: { padding: '8px 16px', borderRadius: '6px', border: 'none', background: '#22c55e', color: '#fff', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }
              }, '▶ Start Server')
            : React.createElement('button', {
                onClick: async function() { await apiPost('/local/stop'); fetchStatus(); },
                style: { padding: '8px 16px', borderRadius: '6px', border: 'none', background: '#ef4444', color: '#fff', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }
              }, '⏹ Stop Server')
        )
      );
    }

    function renderProviderCard(name, data) {
      const state = data.state || {};
      const creds = data.credentials || {};
      const isAvailable = state.is_available;

      return React.createElement('div', {
        key: name,
        style: {
          background: 'var(--surface-elevated, #1a1a2e)',
          borderRadius: '12px',
          padding: '16px',
          marginBottom: '12px',
          border: '1px solid ' + (isAvailable ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'),
        }
      },
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' } },
          React.createElement('div', null,
            React.createElement('h3', { style: { margin: 0, fontSize: '16px', fontWeight: 600 } }, name),
            React.createElement('div', { style: { fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' } }, state.model || 'No model set')
          ),
          statusBadge(state.status)
        ),
        React.createElement('div', {
          style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '12px', fontSize: '13px' }
        },
          renderStat('Tokens In', (state.tokens_in || 0).toLocaleString()),
          renderStat('Tokens Out', (state.tokens_out || 0).toLocaleString()),
          renderStat('Total Cost', '$' + (state.total_cost || 0).toFixed(4)),
          renderStat('Credentials', React.createElement('span', null,
            React.createElement('span', { style: { color: '#22c55e' } }, creds.active || 0),
            '/',
            creds.total || 0,
            (creds.exhausted > 0) ? React.createElement('span', { style: { color: '#ef4444', marginLeft: '4px' } }, '(' + creds.exhausted + ' exhausted)') : null
          )),
          renderStat('Error Rate', ((state.error_rate || 0) * 100).toFixed(1) + '%'),
          renderStat('Avg Latency', (state.avg_latency_ms || 0).toFixed(0) + 'ms')
        ),
        state.last_error
          ? React.createElement('div', {
              style: { marginTop: '8px', padding: '8px', background: 'rgba(239,68,68,0.1)', borderRadius: '6px', fontSize: '12px', color: '#fca5a5', fontFamily: 'monospace' }
            }, 'Last error: ' + state.last_error)
          : null
      );
    }

    function renderStat(label, value) {
      return React.createElement('div', null,
        React.createElement('div', { style: { color: 'var(--text-secondary)' } }, label),
        React.createElement('div', { style: { fontWeight: 600, fontFamily: 'monospace' } }, value)
      );
    }

    // ─── Tab: Settings ─────────────────────────────────────────────────────

    function renderSettings() {
      const [strategy, setStrategy] = React.useState(config.strategy || 'priority');
      const [autoSwitch, setAutoSwitch] = React.useState(config.auto_switch !== false);
      const [cooldown, setCooldown] = React.useState(config.rate_limit_cooldown_seconds || 60);

      return React.createElement('div', {
        style: { background: 'var(--surface-elevated, #1a1a2e)', borderRadius: '12px', padding: '16px', marginBottom: '12px' }
      },
        React.createElement('h3', { style: { margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600 } }, '⚙️ Settings'),

        React.createElement('div', { style: { marginBottom: '16px' } },
          React.createElement('label', { style: { fontSize: '13px', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' } }, 'Rotation Strategy'),
          React.createElement('select', {
            value: strategy,
            onChange: function(e) { setStrategy(e.target.value); },
            style: { width: '100%', padding: '8px 12px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-primary)', fontSize: '13px' }
          },
            React.createElement('option', { value: 'priority' }, 'Priority (ordered list)'),
            React.createElement('option', { value: 'cost_first' }, 'Cost First (cheapest)'),
            React.createElement('option', { value: 'reliability_first' }, 'Reliability First'),
            React.createElement('option', { value: 'round_robin' }, 'Round Robin')
          )
        ),

        React.createElement('div', { style: { marginBottom: '16px' } },
          React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', cursor: 'pointer' } },
            React.createElement('input', { type: 'checkbox', checked: autoSwitch, onChange: function(e) { setAutoSwitch(e.target.checked); } }),
            'Auto-switch on provider failure'
          )
        ),

        React.createElement('div', { style: { marginBottom: '16px' } },
          React.createElement('label', { style: { fontSize: '13px', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' } }, 'Rate Limit Cooldown (seconds)'),
          React.createElement('input', {
            type: 'number', value: cooldown,
            onChange: function(e) { setCooldown(parseInt(e.target.value) || 60); },
            min: 10, max: 3600,
            style: { width: '100%', padding: '8px 12px', borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text-primary)', fontSize: '13px' }
          })
        ),

        React.createElement('button', {
          onClick: async function() {
            await apiPost('/config', Object.assign({}, config, {
              strategy: strategy,
              auto_switch: autoSwitch,
              rate_limit_cooldown_seconds: cooldown,
            }));
            fetchStatus();
          },
          style: { padding: '8px 16px', borderRadius: '6px', border: 'none', background: '#3b82f6', color: '#fff', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }
        }, 'Save Settings')
      );
    }

    // ─── Tab: Logs ─────────────────────────────────────────────────────────

    function renderLogs() {
      return React.createElement('div', null,
        React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' } },
          React.createElement('h3', { style: { margin: 0, fontSize: '16px', fontWeight: 600 } }, 'Notifications (' + notifications.length + ')'),
          React.createElement('button', {
            onClick: async function() { await apiPost('/notifications/clear'); fetchStatus(); },
            style: { padding: '6px 12px', borderRadius: '6px', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: '12px', cursor: 'pointer' }
          }, 'Clear All')
        ),
        React.createElement('div', { style: { background: 'var(--surface-elevated, #1a1a2e)', borderRadius: '12px', overflow: 'hidden', maxHeight: '400px', overflowY: 'auto' } },
          notifications.length === 0
            ? React.createElement('div', { style: { padding: '20px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '13px' } }, 'No notifications yet')
            : notifications.slice().reverse().map(function(n, i) {
                return React.createElement('div', {
                  key: i,
                  style: { padding: '10px 12px', borderBottom: '1px solid var(--border)', fontSize: '13px' }
                },
                  React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', marginBottom: '4px' } },
                    React.createElement('span', {
                      style: { fontWeight: 600, color: n.severity === 'critical' ? '#ef4444' : n.severity === 'warning' ? '#f59e0b' : 'var(--text-primary)' }
                    }, n.type),
                    React.createElement('span', { style: { color: 'var(--text-secondary)', fontSize: '11px' } }, new Date(n.timestamp).toLocaleString())
                  ),
                  React.createElement('div', { style: { color: 'var(--text-secondary)' } }, n.message)
                );
              })
        )
      );
    }

    // ─── Main Layout ───────────────────────────────────────────────────────

    const tabs = [
      { id: 'dashboard', label: '📊 Dashboard' },
      { id: 'settings', label: '⚙️ Settings' },
      { id: 'logs', label: '📋 Logs' },
    ];

    return React.createElement('div', { style: { padding: '16px', maxWidth: '1200px', margin: '0 auto' } },
      // Header
      React.createElement('div', { style: { marginBottom: '20px' } },
        React.createElement('h1', { style: { margin: '0 0 8px 0', fontSize: '24px', fontWeight: 700 } }, '🔀 Provider Router'),
        React.createElement('div', { style: { color: 'var(--text-secondary)', fontSize: '14px' } },
          'Intelligent token monitoring, provider rotation, and local LLM fallback'
        )
      ),

      // Quick Stats
      React.createElement('div', {
        style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '20px' }
      },
        renderStatCard(providerCount, 'Providers', '#3b82f6'),
        renderStatCard(availableCount, 'Available', '#22c55e'),
        renderStatCard(activeProvider || '—', 'Active', '#f59e0b'),
        renderStatCard(localStatus.running ? '✓' : '✗', 'Local LLM', localStatus.running ? '#22c55e' : '#6b7280')
      ),

      // Tabs
      React.createElement('div', {
        style: { display: 'flex', gap: '4px', marginBottom: '20px', borderBottom: '1px solid var(--border)' }
      },
        tabs.map(function(tab) {
          return React.createElement('button', {
            key: tab.id,
            onClick: function() { setActiveTab(tab.id); },
            style: {
              padding: '10px 20px',
              border: 'none',
              background: activeTab === tab.id ? 'var(--surface-elevated, #1a1a2e)' : 'transparent',
              color: activeTab === tab.id ? 'var(--text-primary)' : 'var(--text-secondary)',
              fontSize: '14px',
              fontWeight: activeTab === tab.id ? 600 : 400,
              cursor: 'pointer',
              borderRadius: '8px 8px 0 0',
              borderBottom: activeTab === tab.id ? '2px solid #3b82f6' : '2px solid transparent',
            }
          }, tab.label);
        })
      ),

      // Tab Content
      activeTab === 'dashboard' ? renderDashboard() : null,
      activeTab === 'settings' ? renderSettings() : null,
      activeTab === 'logs' ? renderLogs() : null
    );
  }

  function renderStatCard(value, label, color) {
    return React.createElement('div', {
      style: { background: 'var(--surface-elevated, #1a1a2e)', borderRadius: '12px', padding: '16px', textAlign: 'center' }
    },
      React.createElement('div', { style: { fontSize: '28px', fontWeight: 700, color: color } }, value),
      React.createElement('div', { style: { fontSize: '12px', color: 'var(--text-secondary)' } }, label)
    );
  }

  // ─── Register Plugin ──────────────────────────────────────────────────────

  // Wait for React to be available (dashboard loads React globally)
  function waitForReact(callback) {
    if (window.React && window.ReactDOM) {
      callback();
    } else {
      setTimeout(function() { waitForReact(callback); }, 100);
    }
  }

  waitForReact(function() {
    // Register with the plugin system
    if (window.__HERMES_PLUGIN_REGISTER__) {
      window.__HERMES_PLUGIN_REGISTER__({
        register: function(spec) {
          // Store for the dashboard to pick up
          window.__HERMES_PLUGINS__ = window.__HERMES_PLUGINS__ || {};
          window.__HERMES_PLUGINS__[spec.name] = spec;
        }
      });
    }

    // Also register via the global plugin registry
    if (window.HermesDashboard && window.HermesDashboard.registerPlugin) {
      window.HermesDashboard.registerPlugin({
        name: 'provider-router',
        label: 'Provider Router',
        icon: '🔀',
        component: ProviderRouterDashboard,
      });
    }
  });

  // Export for the plugin system
  window.ProviderRouterDashboard = ProviderRouterDashboard;

})();
