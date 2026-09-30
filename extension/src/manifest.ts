import { defineManifest } from '@crxjs/vite-plugin';

/**
 * Manifest V3. Permissions are kept to the minimum the product actually uses.
 * Capture only runs after the analyst clicks an action, gated by `activeTab` +
 * `scripting`. The one host permission is the local VC Alpha engine, so the
 * service worker can post a capture to it; no website is granted anything.
 *
 * `alarms` is required by `src/lib/retention.ts` for the daily purge.
 * `minimum_chrome_version` locks out browsers without the side panel API and
 * `chrome.storage.session`.
 */
export default defineManifest({
  manifest_version: 3,
  name: 'Treeo VC Scout',
  short_name: 'Treeo Scout',
  version: '1.0.0',
  description: 'Evidence-first founder intelligence and early-stage startup alpha for VC analysts.',
  minimum_chrome_version: '116',
  action: {
    default_title: 'Treeo VC Scout',
    default_popup: 'src/popup/index.html',
    default_icon: {
      16: 'icons/icon16.png',
      32: 'icons/icon32.png',
      48: 'icons/icon48.png',
      128: 'icons/icon128.png',
    },
  },
  icons: {
    16: 'icons/icon16.png',
    32: 'icons/icon32.png',
    48: 'icons/icon48.png',
    128: 'icons/icon128.png',
  },
  background: {
    service_worker: 'src/background/service-worker.ts',
    type: 'module',
  },
  side_panel: {
    default_path: 'src/sidepanel/index.html',
  },
  options_ui: {
    page: 'src/options/index.html',
    open_in_tab: true,
  },
  permissions: ['activeTab', 'storage', 'sidePanel', 'scripting', 'alarms'],
  host_permissions: ['http://127.0.0.1:8420/*'],
});
