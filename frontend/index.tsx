/**
 * Provider Router — Dashboard Plugin Entry Point.
 * 
 * This file is loaded by the Hermes dashboard plugin system.
 * It registers the plugin and exports the main component.
 */

// @ts-ignore
import ProviderRouterDashboard from '../frontend/ProviderRouterDashboard';

// Plugin registration function called by the Hermes dashboard
// @ts-ignore
window.__HERMES_PLUGIN_REGISTER__ = function register(pluginAPI) {
  pluginAPI.register({
    name: 'provider-router',
    displayName: 'Provider Router',
    description: 'Monitor token usage, manage provider rotation, and control local LLM fallback',
    component: ProviderRouterDashboard,
    icon: '🔀',
    category: 'infrastructure',
    order: 10,
  });
};

// Also export for direct import
export default ProviderRouterDashboard;
