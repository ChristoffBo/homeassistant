(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  let CURRENT_CONFIG = {};
  let IS_HASSIO = false;
  let IS_READONLY = false;

  // ===== HELPER: Determine API URL based on environment =====
  function getApiUrl(endpoint) {
    if (IS_HASSIO) {
      // HA proxy path for addon
      return `/api/hassio_api/addon/jarvis_prime/${endpoint}`;
    } else {
      // Standalone Docker / direct access
      return `/api/${endpoint}`;
    }
  }

  // ===== SETTINGS LOAD =====
  async function settingsLoadConfig() {
    try {
      const response = await fetch(getApiUrl('config'));
      const data = await response.json();

      CURRENT_CONFIG = data.config || {};
      IS_HASSIO = data.is_hassio || false;
      IS_READONLY = data.readonly || false;

      const banner = $('#settings-readonly-banner');
      if (banner) banner.style.display = IS_READONLY ? 'block' : 'none';

      // Populate all settings forms
      settingsPopulateGeneral();
      settingsPopulateLLM();
      settingsPopulatePersonality();
      settingsPopulateIntegrations();
      settingsPopulateCommunications();
      settingsPopulateMonitoring();
      settingsPopulatePush();

      console.log('[settings] Config loaded', { is_hassio: IS_HASSIO, readonly: IS_READONLY });
    } catch (e) {
      console.error('[settings] Failed to load config:', e);
      window.showToast('Failed to load settings', 'error');
    }
  }

  // ===== SETTINGS SAVE =====
  async function settingsSaveConfig() {
    if (IS_READONLY) {
      window.showToast('Settings are read-only in Home Assistant mode', 'error');
      return;
    }

    try {
      const saveBtn = $('#settings-save-btn');
      if (saveBtn) saveBtn.classList.add('loading');

      const config = {
        ...settingsGatherGeneral(),
        ...settingsGatherLLM(),
        ...settingsGatherPersonality(),
        ...settingsGatherIntegrations(),
        ...settingsGatherCommunications(),
        ...settingsGatherMonitoring(),
        ...settingsGatherPush()
      };

      const response = await fetch(getApiUrl('config'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });

      const result = await response.json();

      if (result.ok) {
        window.showToast('Settings saved successfully', 'success');
        if (result.restart_required) window.showToast('Restart required for changes to take effect', 'info');
      } else {
        throw new Error(result.error || 'Save failed');
      }
    } catch (e) {
      console.error('[settings] Save failed:', e);
      window.showToast('Failed to save settings: ' + e.message, 'error');
    } finally {
      const saveBtn = $('#settings-save-btn');
      if (saveBtn) saveBtn.classList.remove('loading');
    }
  }

  // ===== READONLY HANDLER =====
  function setReadonly(panelSelector) {
    if (!IS_READONLY) return;
    const panel = $(panelSelector);
    if (!panel) return;
    $$(panelSelector + ' input, ' + panelSelector + ' select, ' + panelSelector + ' textarea').forEach(el => el.disabled = true);
  }

  // ===== GENERAL SETTINGS =====
  function settingsPopulateGeneral() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-bot-name')) $('#set-bot-name').value = get('bot_name', 'Jarvis Prime');
    if ($('#set-bot-icon')) $('#set-bot-icon').value = get('bot_icon', '🧠');
    if ($('#set-jarvis-app-name')) $('#set-jarvis-app-name').value = get('jarvis_app_name', 'Jarvis');
    if ($('#set-beautify-enabled')) $('#set-beautify-enabled').checked = get('beautify_enabled', true);
    if ($('#set-beautify-inline-images')) $('#set-beautify-inline-images').checked = get('beautify_inline_images', true);
    if ($('#set-silent-repost')) $('#set-silent-repost').checked = get('silent_repost', true);
    if ($('#set-greeting-enabled')) $('#set-greeting-enabled').checked = get('greeting_enabled', true);
    if ($('#set-retention-days')) $('#set-retention-days').value = get('retention_days', 30);
    if ($('#set-retention-hours')) $('#set-retention-hours').value = get('retention_hours', 24);
    if ($('#set-auto-purge-policy')) $('#set-auto-purge-policy').value = get('auto_purge_policy', 'off');

    setReadonly('#settings-general-panel');
  }

  function settingsGatherGeneral() {
    return {
      bot_name: $('#set-bot-name')?.value || 'Jarvis Prime',
      bot_icon: $('#set-bot-icon')?.value || '🧠',
      jarvis_app_name: $('#set-jarvis-app-name')?.value || 'Jarvis',
      beautify_enabled: $('#set-beautify-enabled')?.checked || false,
      beautify_inline_images: $('#set-beautify-inline-images')?.checked || false,
      silent_repost: $('#set-silent-repost')?.checked || false,
      greeting_enabled: $('#set-greeting-enabled')?.checked || false,
      retention_days: parseInt($('#set-retention-days')?.value || '30'),
      retention_hours: parseInt($('#set-retention-hours')?.value || '24'),
      auto_purge_policy: $('#set-auto-purge-policy')?.value || 'off'
    };
  }

  // ===== LLM SETTINGS =====
  function settingsPopulateLLM() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-llm-enabled')) $('#set-llm-enabled').checked = get('llm_enabled', true);
    if ($('#set-llm-persona-riffs-enabled')) $('#set-llm-persona-riffs-enabled').checked = get('llm_persona_riffs_enabled', true);
    if ($('#set-llm-rewrite-enabled')) $('#set-llm-rewrite-enabled').checked = get('llm_rewrite_enabled', false);
    if ($('#set-llm-models-dir')) $('#set-llm-models-dir').value = get('llm_models_dir', '/share/jarvis_prime/models');
    if ($('#set-llm-timeout-seconds')) $('#set-llm-timeout-seconds').value = get('llm_timeout_seconds', 20);
    if ($('#set-llm-max-cpu-percent')) $('#set-llm-max-cpu-percent').value = get('llm_max_cpu_percent', 80);
    if ($('#set-llm-ctx-tokens')) $('#set-llm-ctx-tokens').value = get('llm_ctx_tokens', 6096);
    if ($('#set-llm-gen-tokens')) $('#set-llm-gen-tokens').value = get('llm_gen_tokens', 300);
    if ($('#set-llm-threads')) $('#set-llm-threads').value = get('llm_threads', 3);
    if ($('#set-llm-models-priority')) $('#set-llm-models-priority').value = get('llm_models_priority', 'phi35_q5_uncensored,phi35_q5,phi35_q4,phi3');

    if ($('#set-llm-enviroguard-enabled')) $('#set-llm-enviroguard-enabled').checked = get('llm_enviroguard_enabled', true);
    if ($('#set-llm-enviroguard-poll-minutes')) $('#set-llm-enviroguard-poll-minutes').value = get('llm_enviroguard_poll_minutes', 30);
    if ($('#set-llm-enviroguard-hot-c')) $('#set-llm-enviroguard-hot-c').value = get('llm_enviroguard_hot_c', 30);
    if ($('#set-llm-enviroguard-normal-c')) $('#set-llm-enviroguard-normal-c').value = get('llm_enviroguard_normal_c', 22);
    if ($('#set-llm-enviroguard-cold-c')) $('#set-llm-enviroguard-cold-c').value = get('llm_enviroguard_cold_c', 10);

    setReadonly('#settings-llm-panel');
  }

  function settingsGatherLLM() {
    return {
      llm_enabled: $('#set-llm-enabled')?.checked || false,
      llm_persona_riffs_enabled: $('#set-llm-persona-riffs-enabled')?.checked || false,
      llm_rewrite_enabled: $('#set-llm-rewrite-enabled')?.checked || false,
      llm_models_dir: $('#set-llm-models-dir')?.value || '/share/jarvis_prime/models',
      llm_timeout_seconds: parseInt($('#set-llm-timeout-seconds')?.value || '20'),
      llm_max_cpu_percent: parseInt($('#set-llm-max-cpu-percent')?.value || '80'),
      llm_ctx_tokens: parseInt($('#set-llm-ctx-tokens')?.value || '6096'),
      llm_gen_tokens: parseInt($('#set-llm-gen-tokens')?.value || '300'),
      llm_threads: parseInt($('#set-llm-threads')?.value || '3'),
      llm_models_priority: $('#set-llm-models-priority')?.value || '',
      llm_enviroguard_enabled: $('#set-llm-enviroguard-enabled')?.checked || false,
      llm_enviroguard_poll_minutes: parseInt($('#set-llm-enviroguard-poll-minutes')?.value || '30'),
      llm_enviroguard_hot_c: parseInt($('#set-llm-enviroguard-hot-c')?.value || '30'),
      llm_enviroguard_normal_c: parseInt($('#set-llm-enviroguard-normal-c')?.value || '22'),
      llm_enviroguard_cold_c: parseInt($('#set-llm-enviroguard-cold-c')?.value || '10')
    };
  }
// ===== PERSONALITY / PERSONAS =====
  function settingsPopulatePersonality() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-persona-enabled')) $('#set-persona-enabled').checked = get('persona_enabled', true);
    if ($('#set-persona-default')) $('#set-persona-default').value = get('persona_default', 'Jarvis');
    if ($('#set-persona-override')) $('#set-persona-override').value = get('persona_override', '');
    if ($('#set-persona-riff-max-length')) $('#set-persona-riff-max-length').value = get('persona_riff_max_length', 400);

    setReadonly('#settings-personality-panel');
  }

  function settingsGatherPersonality() {
    return {
      persona_enabled: $('#set-persona-enabled')?.checked || false,
      persona_default: $('#set-persona-default')?.value || 'Jarvis',
      persona_override: $('#set-persona-override')?.value || '',
      persona_riff_max_length: parseInt($('#set-persona-riff-max-length')?.value || '400')
    };
  }

  // ===== INTEGRATIONS =====
  function settingsPopulateIntegrations() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-gotify-url')) $('#set-gotify-url').value = get('gotify_url', '');
    if ($('#set-gotify-token')) $('#set-gotify-token').value = get('gotify_token', '');
    if ($('#set-ntfy-url')) $('#set-ntfy-url').value = get('ntfy_url', '');
    if ($('#set-ntfy-topic')) $('#set-ntfy-topic').value = get('ntfy_topic', '');
    if ($('#set-smtp-server')) $('#set-smtp-server').value = get('smtp_server', '');
    if ($('#set-smtp-port')) $('#set-smtp-port').value = get('smtp_port', 587);
    if ($('#set-smtp-user')) $('#set-smtp-user').value = get('smtp_user', '');
    if ($('#set-smtp-pass')) $('#set-smtp-pass').value = get('smtp_pass', '');

    setReadonly('#settings-integrations-panel');
  }

  function settingsGatherIntegrations() {
    return {
      gotify_url: $('#set-gotify-url')?.value || '',
      gotify_token: $('#set-gotify-token')?.value || '',
      ntfy_url: $('#set-ntfy-url')?.value || '',
      ntfy_topic: $('#set-ntfy-topic')?.value || '',
      smtp_server: $('#set-smtp-server')?.value || '',
      smtp_port: parseInt($('#set-smtp-port')?.value || '587'),
      smtp_user: $('#set-smtp-user')?.value || '',
      smtp_pass: $('#set-smtp-pass')?.value || ''
    };
  }

  // ===== COMMUNICATION SETTINGS =====
  function settingsPopulateCommunications() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-msg-max-length')) $('#set-msg-max-length').value = get('msg_max_length', 2000);
    if ($('#set-msg-chunk-size')) $('#set-msg-chunk-size').value = get('msg_chunk_size', 500);
    if ($('#set-msg-auto-scroll')) $('#set-msg-auto-scroll').checked = get('msg_auto_scroll', true);

    setReadonly('#settings-communications-panel');
  }

  function settingsGatherCommunications() {
    return {
      msg_max_length: parseInt($('#set-msg-max-length')?.value || '2000'),
      msg_chunk_size: parseInt($('#set-msg-chunk-size')?.value || '500'),
      msg_auto_scroll: $('#set-msg-auto-scroll')?.checked || false
    };
  }

  // ===== MONITORING / LOGGING =====
  function settingsPopulateMonitoring() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-monitoring-enabled')) $('#set-monitoring-enabled').checked = get('monitoring_enabled', true);
    if ($('#set-monitoring-interval')) $('#set-monitoring-interval').value = get('monitoring_interval', 60);
    if ($('#set-monitoring-loglevel')) $('#set-monitoring-loglevel').value = get('monitoring_loglevel', 'INFO');

    setReadonly('#settings-monitoring-panel');
  }

  function settingsGatherMonitoring() {
    return {
      monitoring_enabled: $('#set-monitoring-enabled')?.checked || false,
      monitoring_interval: parseInt($('#set-monitoring-interval')?.value || '60'),
      monitoring_loglevel: $('#set-monitoring-loglevel')?.value || 'INFO'
    };
  }

  // ===== PUSH NOTIFICATIONS =====
  function settingsPopulatePush() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    if ($('#set-push-enabled')) $('#set-push-enabled').checked = get('push_enabled', true);
    if ($('#set-push-channels')) $('#set-push-channels').value = get('push_channels', 'gotify,ntfy,smtp');

    setReadonly('#settings-push-panel');
  }

  function settingsGatherPush() {
    return {
      push_enabled: $('#set-push-enabled')?.checked || false,
      push_channels: $('#set-push-channels')?.value || ''
    };
  }

  // ===== INIT =====
  function settingsInit() {
    $('#settings-save-btn')?.addEventListener('click', settingsSaveConfig);

    settingsLoadConfig();
  }

  document.addEventListener('DOMContentLoaded', settingsInit);
})();
// ===== BACKUP & RESTORE =====
async function backupDownloadNow() {
  try {
    const btn = $('#backup-download-btn');
    if (btn) btn.classList.add('loading');

    let endpoint = 'api/backup/create';
    if (IS_READONLY) {
      // In Home Assistant, use supervisor proxy endpoint if needed
      endpoint = '/api/jarvis/backup/create';
    }

    const response = await fetch(window.API(endpoint), {
      method: 'POST'
    });

    if (!response.ok) {
      throw new Error('Backup creation failed: ' + response.statusText);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `jarvis_backup_${new Date().toISOString().split('T')[0]}.tar.gz`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    window.showToast('Backup downloaded successfully', 'success');
  } catch (e) {
    console.error('[backup] Download failed:', e);
    window.showToast('Failed to create backup: ' + e.message, 'error');
  } finally {
    const btn = $('#backup-download-btn');
    if (btn) btn.classList.remove('loading');
  }
}

async function backupRestoreFromFile() {
  const input = $('#backup-file-input');
  if (input) input.click();
}

async function backupHandleFileUpload(file) {
  if (IS_READONLY) {
    window.showToast('Restore is not available in Home Assistant mode', 'error');
    return;
  }

  if (!confirm('Restore from this backup?\n\nThis will overwrite your current configuration, database, and files.\n\nJarvis will restart after restore.')) {
    return;
  }

  try {
    const btn = $('#backup-restore-btn');
    if (btn) {
      btn.classList.add('loading');
      btn.disabled = true;
    }

    const formData = new FormData();
    formData.append('backup', file);

    let endpoint = 'api/backup/restore';
    if (IS_READONLY) {
      endpoint = '/api/jarvis/backup/restore';
    }

    const response = await fetch(window.API(endpoint), {
      method: 'POST',
      body: formData
    });

    const result = await response.json();

    if (result.ok) {
      window.showToast('Backup restored successfully. Restarting...', 'success');

      setTimeout(() => {
        window.location.reload();
      }, 3000);
    } else {
      throw new Error(result.error || 'Restore failed');
    }
  } catch (e) {
    console.error('[backup] Restore failed:', e);
    window.showToast('Failed to restore backup: ' + e.message, 'error');

    const btn = $('#backup-restore-btn');
    if (btn) {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }
}

function backupInitFileInput() {
  const input = $('#backup-file-input');
  if (input) {
    input.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) {
        backupHandleFileUpload(file);
        input.value = '';
      }
    });
  }
}

// ===== FINAL INIT =====
document.addEventListener('DOMContentLoaded', () => {
  settingsInitSubTabs();
  backupInitFileInput();

  const settingsNavTab = document.querySelector('.nav-tab[data-tab="settings"]');
  if (settingsNavTab) {
    settingsNavTab.addEventListener('click', () => {
      settingsLoadConfig();
    });
  }

  const saveBtn = $('#settings-save-btn');
  if (saveBtn) saveBtn.addEventListener('click', settingsSaveConfig);

  const backupDownloadBtn = $('#backup-download-btn');
  if (backupDownloadBtn) backupDownloadBtn.addEventListener('click', backupDownloadNow);

  const backupRestoreBtn = $('#backup-restore-btn');
  if (backupRestoreBtn) backupRestoreBtn.addEventListener('click', backupRestoreFromFile);
});