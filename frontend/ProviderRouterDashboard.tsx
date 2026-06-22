/**
 * Provider Router Dashboard Plugin
 * 
 * A React component that renders as a tab in the Hermes Web UI dashboard.
 * Provides:
 * - Provider status overview (tokens, costs, health)
 * - Rotation settings and strategy configuration
 * - Local LLM management
 * - Notification log
 * - Manual controls (rotate, start/stop local, etc.)
 */

import React, { useState, useEffect, useCallback } from 'react';

// ─── API Client ───────────────────────────────────────────────────────────────

const API_BASE = '/api/plugins/provider-router';

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

// ─── Components ───────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const colors = {
    active: '#22c55e',
    rate_limited: '#f59e0b',
    exhausted: '#ef4444',
    error: '#ef4444',
    offline: '#6b7280',
  };
  const color = colors[status] || '#6b7280';
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: '12px',
      fontSize: '11px',
      fontWeight: 600,
      color: '#fff',
      background: color,
      textTransform: 'uppercase',
      letterSpacing: '0.5px',
    }}>
      {status}
    </span>
  );
}

function ProviderCard({ name, data }) {
  const { state, usage, credentials } = data;
  const isAvailable = state.is_available;
  
  return (
    <div style={{
      background: 'var(--surface-elevated, #1a1a2e)',
      borderRadius: '12px',
      padding: '16px',
      marginBottom: '12px',
      border: `1px solid ${isAvailable ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>{name}</h3>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            {state.model || 'No model set'}
          </div>
        </div>
        <StatusBadge status={state.status} />
      </div>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '12px', fontSize: '13px' }}>
        <div>
          <div style={{ color: 'var(--text-secondary)' }}>Tokens In</div>
          <div style={{ fontWeight: 600, fontFamily: 'monospace' }}>{state.tokens_in?.toLocaleString() || 0}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-secondary)' }}>Tokens Out</div>
          <div style={{ fontWeight: 600, fontFamily: 'monospace' }}>{state.tokens_out?.toLocaleString() || 0}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-secondary)' }}>Total Cost</div>
          <div style={{ fontWeight: 600, fontFamily: 'monospace' }}>${state.total_cost?.toFixed(4) || '0.0000'}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-secondary)' }}>Credentials</div>
          <div style={{ fontWeight: 600 }}>
            <span style={{ color: '#22c55e' }}>{credentials.active}</span>
            /{credentials.total}
            {credentials.exhausted > 0 && (
              <span style={{ color: '#ef4444', marginLeft: '4px' }}>({credentials.exhausted} exhausted)</span>
            )}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-secondary)' }}>Error Rate</div>
          <div style={{ fontWeight: 600, fontFamily: 'monospace' }}>
            {(state.error_rate * 100).toFixed(1)}%
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-secondary)' }}>Avg Latency</div>
          <div style={{ fontWeight: 600, fontFamily: 'monospace' }}>{state.avg_latency_ms?.toFixed(0) || 0}ms</div>
        </div>
      </div>

      {state.last_error && (
        <div style={{
          marginTop: '8px',
          padding: '8px',
          background: 'rgba(239,68,68,0.1)',
          borderRadius: '6px',
          fontSize: '12px',
          color: '#fca5a5',
          fontFamily: 'monospace',
        }}>
          Last error: {state.last_error}
        </div>
      )}
    </div>
  );
}

function LocalLLMSection({ status, onStart, onStop }) {
  const [modelPath, setModelPath] = status.model_path || '';
  const isRunning = status.running;
  const isHealthy = status.healthy;

  return (
    <div style={{
      background: 'var(--surface-elevated, #1a1a2e)',
      borderRadius: '12px',
      padding: '16px',
      marginBottom: '12px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>🖥️ Local LLM Fallback</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isRunning && (
            <StatusBadge status={isHealthy ? 'active' : 'error'} />
          )}
          {!isRunning && <StatusBadge status="offline" />}
        </div>
      </div>

      <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
        <div>Server: <code style={{ color: 'var(--text-primary)' }}>{status.url}</code></div>
        <div>Model: <code style={{ color: 'var(--text-primary)' }}>{status.model_name}</code></div>
        <div>Recommended: <code style={{ color: '#22c55e' }}>{status.recommended_model}</code></div>
      </div>

      <div style={{ marginBottom: '12px' }}>
        <label style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
          Model Path (GGUF)
        </label>
        <input
          type="text"
          value={modelPath}
          onChange={(e) => setModelPath(e.target.value)}
          placeholder="/path/to/model-Q4_K_M.gguf"
          style={{
            width: '100%',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'var(--surface)',
            color: 'var(--text-primary)',
            fontSize: '13px',
            fontFamily: 'monospace',
          }}
        />
      </div>

      <div style={{ display: 'flex', gap: '8px' }}>
        {!isRunning ? (
          <button
            onClick={onStart}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: 'none',
              background: '#22c55e',
              color: '#fff',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ▶ Start Server
          </button>
        ) : (
          <button
            onClick={onStop}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: 'none',
              background: '#ef4444',
              color: '#fff',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ⏹ Stop Server
          </button>
        )}
      </div>
    </div>
  );
}

function NotificationLog({ notifications }) {
  if (!notifications || notifications.length === 0) {
    return (
      <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '13px' }}>
        No notifications yet
      </div>
    );
  }

  return (
    <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
      {notifications.slice().reverse().map((n, i) => (
        <div
          key={i}
          style={{
            padding: '10px 12px',
            borderBottom: '1px solid var(--border)',
            fontSize: '13px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span style={{
              fontWeight: 600,
              color: n.severity === 'critical' ? '#ef4444' : n.severity === 'warning' ? '#f59e0b' : 'var(--text-primary)',
            }}>
              {n.type}
            </span>
            <span style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
              {new Date(n.timestamp).toLocaleString()}
            </span>
          </div>
          <div style={{ color: 'var(--text-secondary)' }}>{n.message}</div>
        </div>
      ))}
    </div>
  );
}

function SettingsPanel({ config, onSave }) {
  const [strategy, setStrategy] = useState(config.strategy || 'priority');
  const [autoSwitch, setAutoSwitch] = useState(config.auto_switch !== false);
  const [cooldown, setCooldown] = useState(config.rate_limit_cooldown_seconds || 60);

  const handleSave = () => {
    onSave({
      ...config,
      strategy,
      auto_switch: autoSwitch,
      rate_limit_cooldown_seconds: cooldown,
    });
  };

  return (
    <div style={{
      background: 'var(--surface-elevated, #1a1a2e)',
      borderRadius: '12px',
      padding: '16px',
      marginBottom: '12px',
    }}>
      <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', fontWeight: 600 }}>⚙️ Settings</h3>

      <div style={{ marginBottom: '16px' }}>
        <label style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
          Rotation Strategy
        </label>
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'var(--surface)',
            color: 'var(--text-primary)',
            fontSize: '13px',
          }}
        >
          <option value="priority">Priority (ordered list)</option>
          <option value="cost_first">Cost First (cheapest)</option>
          <option value="reliability_first">Reliability First (lowest error rate)</option>
          <option value="round_robin">Round Robin</option>
        </select>
      </div>

      <div style={{ marginBottom: '16px' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={autoSwitch}
            onChange={(e) => setAutoSwitch(e.target.checked)}
          />
          Auto-switch on provider failure
        </label>
      </div>

      <div style={{ marginBottom: '16px' }}>
        <label style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
          Rate Limit Cooldown (seconds)
        </label>
        <input
          type="number"
          value={cooldown}
          onChange={(e) => setCooldown(parseInt(e.target.value) || 60)}
          min={10}
          max={3600}
          style={{
            width: '100%',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'var(--surface)',
            color: 'var(--text-primary)',
            fontSize: '13px',
          }}
        />
      </div>

      <button
        onClick={handleSave}
        style={{
          padding: '8px 16px',
          borderRadius: '6px',
          border: 'none',
          background: '#3b82f6',
          color: '#fff',
          fontSize: '13px',
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        Save Settings
      </button>
    </div>
  );
}

// ─── Main Dashboard Component ─────────────────────────────────────────────────

export default function ProviderRouterDashboard() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshInterval, setRefreshInterval] = useState(10000); // 10s

  const fetchStatus = useCallback(async () => {
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

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, refreshInterval]);

  const handleStartLocal = async () => {
    try {
      await apiPost('/local/start');
      fetchStatus();
    } catch (e) {
      alert(`Failed to start local server: ${e.message}`);
    }
  };

  const handleStopLocal = async () => {
    try {
      await apiPost('/local/stop');
      fetchStatus();
    } catch (e) {
      alert(`Failed to stop local server: ${e.message}`);
    }
  };

  const handleRotate = async () => {
    try {
      await apiPost('/rotate');
      fetchStatus();
    } catch (e) {
      alert(`Rotation failed: ${e.message}`);
    }
  };

  const handleSaveConfig = async (newConfig) => {
    try {
      await apiPost('/config', newConfig);
      fetchStatus();
    } catch (e) {
      alert(`Failed to save config: ${e.message}`);
    }
  };

  const handleClearNotifications = async () => {
    try {
      await apiPost('/notifications/clear');
      fetchStatus();
    } catch (e) {
      // silent
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px' }}>
        <div style={{ color: 'var(--text-secondary)' }}>Loading provider status...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '20px', textAlign: 'center' }}>
        <div style={{ color: '#ef4444', marginBottom: '12px' }}>⚠️ Error: {error}</div>
        <button
          onClick={fetchStatus}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            border: 'none',
            background: '#3b82f6',
            color: '#fff',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  const providers = status?.providers || {};
  const notifications = status?.notifications || [];
  const localStatus = {
    running: status?.local_server_running || false,
    healthy: false,
    url: `http://127.0.0.1:${status?.config?.local_server_port || 8080}/v1`,
    model_path: status?.config?.local_model_path || '',
    model_name: status?.config?.local_model_name || 'local/llama-3.2-3b-instruct',
    recommended_model: status?.recommended_model || 'Llama-3.2-3B-Instruct-Q4_K_M.gguf',
  };

  const tabs = [
    { id: 'dashboard', label: '📊 Dashboard', icon: '📊' },
    { id: 'settings', label: '⚙️ Settings', icon: '⚙️' },
    { id: 'logs', label: '📋 Logs', icon: '📋' },
  ];

  return (
    <div style={{ padding: '16px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ margin: '0 0 8px 0', fontSize: '24px', fontWeight: 700 }}>
          🔀 Provider Router
        </h1>
        <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
          Intelligent token monitoring, provider rotation, and local LLM fallback
        </div>
      </div>

      {/* Quick Stats */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: '12px',
        marginBottom: '20px',
      }}>
        <div style={{
          background: 'var(--surface-elevated, #1a1a2e)',
          borderRadius: '12px',
          padding: '16px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '28px', fontWeight: 700, color: '#3b82f6' }}>
            {Object.keys(providers).length}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Providers</div>
        </div>
        <div style={{
          background: 'var(--surface-elevated, #1a1a2e)',
          borderRadius: '12px',
          padding: '16px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '28px', fontWeight: 700', color: '#22c55e' }}>
            {Object.values(providers).filter(p => p.state?.is_available).length}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Available</div>
        </div>
        <div style={{
          background: 'var(--surface-elevated, #1a1a2e)',
          borderRadius: '12px',
          padding: '16px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '28px', fontWeight: 700', color: '#f59e0b' }}>
            {status?.active_provider || '—'}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Active</div>
        </div>
        <div style={{
          background: 'var(--surface-elevated, #1a1a2e)',
          borderRadius: '12px',
          padding: '16px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: '28px', fontWeight: 700', color: localStatus.running ? '#22c55e' : '#6b7280' }}>
            {localStatus.running ? '✓' : '✗'}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Local LLM</div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex',
        gap: '4px',
        marginBottom: '20px',
        borderBottom: '1px solid var(--border)',
        paddingBottom: '0',
      }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '10px 20px',
              border: 'none',
              background: activeTab === tab.id ? 'var(--surface-elevated, #1a1a2e)' : 'transparent',
              color: activeTab === tab.id ? 'var(--text-primary)' : 'var(--text-secondary)',
              fontSize: '14px',
              fontWeight: activeTab === tab.id ? 600 : 400,
              cursor: 'pointer',
              borderRadius: '8px 8px 0 0',
              borderBottom: activeTab === tab.id ? '2px solid #3b82f6' : '2px solid transparent',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'dashboard' && (
        <div>
          {/* Quick Actions */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
            <button
              onClick={handleRotate}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--surface)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              🔄 Force Rotate
            </button>
            <button
              onClick={fetchStatus}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--surface)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              ↻ Refresh
            </button>
          </div>

          {/* Local LLM */}
          <LocalLLMSection
            status={localStatus}
            onStart={handleStartLocal}
            onStop={handleStopLocal}
          />

          {/* Provider Cards */}
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>
            Providers
          </h3>
          {Object.entries(providers).map(([name, data]) => (
            <ProviderCard key={name} name={name} data={data} />
          ))}
        </div>
      )}

      {activeTab === 'settings' && (
        <div>
          <SettingsPanel
            config={status?.config || {}}
            onSave={handleSaveConfig}
          />
        </div>
      )}

      {activeTab === 'logs' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>
              Notifications ({notifications.length})
            </h3>
            <button
              onClick={handleClearNotifications}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              Clear All
            </button>
          </div>
          <div style={{
            background: 'var(--surface-elevated, #1a1a2e)',
            borderRadius: '12px',
            overflow: 'hidden',
          }}>
            <NotificationLog notifications={notifications} />
          </div>
        </div>
      )}
    </div>
  );
}
