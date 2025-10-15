(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  let CURRENT_CONFIG = {};
  let IS_HASSIO = false;
  let IS_READONLY = false;

  // Load configuration
  async function settingsLoadConfig() {
    try {
      const response = await fetch(window.API('api/config'));
      const data = await response.json();
      
      CURRENT_CONFIG = data.config || {};
      IS_HASSIO = data.is_hassio || false;
      IS_READONLY = data.readonly || false;
      
      // Show readonly banner if in HA mode
      const banner = $('#settings-readonly-banner');
      if (banner) {
        banner.style.display = IS_READONLY ? 'block' : 'none';
      }
      
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

  // Save configuration (Docker mode only)
  async function settingsSaveConfig() {
    if (IS_READONLY) {
      window.showToast('Settings are read-only in Home Assistant mode', 'error');
      return;
    }

    try {
      const saveBtn = $('#settings-save-btn');
      if (saveBtn) saveBtn.classList.add('loading');

      // Gather all settings from all tabs
      const config = {
        ...settingsGatherGeneral(),
        ...settingsGatherLLM(),
        ...settingsGatherPersonality(),
        ...settingsGatherIntegrations(),
        ...settingsGatherCommunications(),
        ...settingsGatherMonitoring(),
        ...settingsGatherPush()
      };

      const response = await fetch(window.API('api/config'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });

      const result = await response.json();

      if (result.ok) {
        window.showToast('Settings saved successfully', 'success');
        
        if (result.restart_required) {
          window.showToast('Restart required for changes to take effect', 'info');
        }
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

  // ===== GENERAL SETTINGS =====
  function settingsPopulateGeneral() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-bot-name')) $('#set-bot-name').value = get('bot_name', 'Jarvis Prime');
    if ($('#set-bot-icon')) $('#set-bot-icon').value = get('bot_icon', '­ЪДа');
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
      bot_icon: $('#set-bot-icon')?.value || '­ЪДа',
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

  // ===== LLM & AI SETTINGS =====
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
    
    // EnviroGuard
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

  // ===== PERSONALITY SETTINGS =====
  function settingsPopulatePersonality() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-personality-enabled')) $('#set-personality-enabled').checked = get('personality_enabled', true);
    if ($('#set-active-persona')) $('#set-active-persona').value = get('active_persona', 'auto');
    if ($('#set-personality-min-interval-minutes')) $('#set-personality-min-interval-minutes').value = get('personality_min_interval_minutes', 90);
    if ($('#set-personality-interval-jitter-pct')) $('#set-personality-interval-jitter-pct').value = get('personality_interval_jitter_pct', 20);
    if ($('#set-personality-daily-max')) $('#set-personality-daily-max').value = get('personality_daily_max', 6);
    if ($('#set-personality-quiet-hours')) $('#set-personality-quiet-hours').value = get('personality_quiet_hours', '23:00-06:00');
    if ($('#set-chat-enabled')) $('#set-chat-enabled').checked = get('chat_enabled', true);
    
    // Enabled personas
    if ($('#set-enable-dude')) $('#set-enable-dude').checked = get('enable_dude', true);
    if ($('#set-enable-chick')) $('#set-enable-chick').checked = get('enable_chick', false);
    if ($('#set-enable-nerd')) $('#set-enable-nerd').checked = get('enable_nerd', false);
    if ($('#set-enable-rager')) $('#set-enable-rager').checked = get('enable_rager', false);
    if ($('#set-enable-comedian')) $('#set-enable-comedian').checked = get('enable_comedian', false);
    if ($('#set-enable-action')) $('#set-enable-action').checked = get('enable_action', false);

    setReadonly('#settings-personality-panel');
  }

  function settingsGatherPersonality() {
    return {
      personality_enabled: $('#set-personality-enabled')?.checked || false,
      active_persona: $('#set-active-persona')?.value || 'auto',
      personality_min_interval_minutes: parseInt($('#set-personality-min-interval-minutes')?.value || '90'),
      personality_interval_jitter_pct: parseInt($('#set-personality-interval-jitter-pct')?.value || '20'),
      personality_daily_max: parseInt($('#set-personality-daily-max')?.value || '6'),
      personality_quiet_hours: $('#set-personality-quiet-hours')?.value || '23:00-06:00',
      chat_enabled: $('#set-chat-enabled')?.checked || false,
      enable_dude: $('#set-enable-dude')?.checked || false,
      enable_chick: $('#set-enable-chick')?.checked || false,
      enable_nerd: $('#set-enable-nerd')?.checked || false,
      enable_rager: $('#set-enable-rager')?.checked || false,
      enable_comedian: $('#set-enable-comedian')?.checked || false,
      enable_action: $('#set-enable-action')?.checked || false
    };
  }

  // ===== INTEGRATIONS SETTINGS =====
  function settingsPopulateIntegrations() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    // Weather
    if ($('#set-weather-enabled')) $('#set-weather-enabled').checked = get('weather_enabled', true);
    if ($('#set-weather-lat')) $('#set-weather-lat').value = get('weather_lat', -26.2041);
    if ($('#set-weather-lon')) $('#set-weather-lon').value = get('weather_lon', 28.0473);
    if ($('#set-weather-city')) $('#set-weather-city').value = get('weather_city', 'Odendaalsrus');
    if ($('#set-weather-time')) $('#set-weather-time').value = get('weather_time', '07:00');
    
    // Digest
    if ($('#set-digest-enabled')) $('#set-digest-enabled').checked = get('digest_enabled', true);
    if ($('#set-digest-time')) $('#set-digest-time').value = get('digest_time', '08:00');
    
    // Heartbeat
    if ($('#set-heartbeat-enabled')) $('#set-heartbeat-enabled').checked = get('heartbeat_enabled', true);
    if ($('#set-heartbeat-interval-minutes')) $('#set-heartbeat-interval-minutes').value = get('heartbeat_interval_minutes', 120);
    if ($('#set-heartbeat-start')) $('#set-heartbeat-start').value = get('heartbeat_start', '06:00');
    if ($('#set-heartbeat-end')) $('#set-heartbeat-end').value = get('heartbeat_end', '20:00');
    
    // Radarr
    if ($('#set-radarr-enabled')) $('#set-radarr-enabled').checked = get('radarr_enabled', true);
    if ($('#set-radarr-url')) $('#set-radarr-url').value = get('radarr_url', '');
    if ($('#set-radarr-api-key')) $('#set-radarr-api-key').value = get('radarr_api_key', '');
    
    // Sonarr
    if ($('#set-sonarr-enabled')) $('#set-sonarr-enabled').checked = get('sonarr_enabled', true);
    if ($('#set-sonarr-url')) $('#set-sonarr-url').value = get('sonarr_url', '');
    if ($('#set-sonarr-api-key')) $('#set-sonarr-api-key').value = get('sonarr_api_key', '');

    setReadonly('#settings-integrations-panel');
  }

  function settingsGatherIntegrations() {
    return {
      weather_enabled: $('#set-weather-enabled')?.checked || false,
      weather_lat: parseFloat($('#set-weather-lat')?.value || '-26.2041'),
      weather_lon: parseFloat($('#set-weather-lon')?.value || '28.0473'),
      weather_city: $('#set-weather-city')?.value || 'Odendaalsrus',
      weather_time: $('#set-weather-time')?.value || '07:00',
      digest_enabled: $('#set-digest-enabled')?.checked || false,
      digest_time: $('#set-digest-time')?.value || '08:00',
      heartbeat_enabled: $('#set-heartbeat-enabled')?.checked || false,
      heartbeat_interval_minutes: parseInt($('#set-heartbeat-interval-minutes')?.value || '120'),
      heartbeat_start: $('#set-heartbeat-start')?.value || '06:00',
      heartbeat_end: $('#set-heartbeat-end')?.value || '20:00',
      radarr_enabled: $('#set-radarr-enabled')?.checked || false,
      radarr_url: $('#set-radarr-url')?.value || '',
      radarr_api_key: $('#set-radarr-api-key')?.value || '',
      sonarr_enabled: $('#set-sonarr-enabled')?.checked || false,
      sonarr_url: $('#set-sonarr-url')?.value || '',
      sonarr_api_key: $('#set-sonarr-api-key')?.value || ''
    };
  }

  // ===== COMMUNICATIONS SETTINGS =====
  function settingsPopulateCommunications() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    // SMTP Intake
    if ($('#set-smtp-enabled')) $('#set-smtp-enabled').checked = get('smtp_enabled', true);
    if ($('#set-smtp-port')) $('#set-smtp-port').value = get('smtp_port', 2525);
    if ($('#set-ingest-smtp-enabled')) $('#set-ingest-smtp-enabled').checked = get('ingest_smtp_enabled', true);
    
    // Proxy
    if ($('#set-proxy-enabled')) $('#set-proxy-enabled').checked = get('proxy_enabled', true);
    if ($('#set-proxy-port')) $('#set-proxy-port').value = get('proxy_port', 2580);
    
    // Webhook
    if ($('#set-webhook-enabled')) $('#set-webhook-enabled').checked = get('webhook_enabled', true);
    if ($('#set-webhook-port')) $('#set-webhook-port').value = get('webhook_port', 2590);
    
    // Apprise
    if ($('#set-intake-apprise-enabled')) $('#set-intake-apprise-enabled').checked = get('intake_apprise_enabled', true);
    if ($('#set-intake-apprise-port')) $('#set-intake-apprise-port').value = get('intake_apprise_port', 2591);
    if ($('#set-ingest-apprise-enabled')) $('#set-ingest-apprise-enabled').checked = get('ingest_apprise_enabled', true);

    setReadonly('#settings-communications-panel');
  }

  function settingsGatherCommunications() {
    return {
      smtp_enabled: $('#set-smtp-enabled')?.checked || false,
      smtp_port: parseInt($('#set-smtp-port')?.value || '2525'),
      ingest_smtp_enabled: $('#set-ingest-smtp-enabled')?.checked || false,
      proxy_enabled: $('#set-proxy-enabled')?.checked || false,
      proxy_port: parseInt($('#set-proxy-port')?.value || '2580'),
      webhook_enabled: $('#set-webhook-enabled')?.checked || false,
      webhook_port: parseInt($('#set-webhook-port')?.value || '2590'),
      intake_apprise_enabled: $('#set-intake-apprise-enabled')?.checked || false,
      intake_apprise_port: parseInt($('#set-intake-apprise-port')?.value || '2591'),
      ingest_apprise_enabled: $('#set-ingest-apprise-enabled')?.checked || false
    };
  }

  // ===== MONITORING SETTINGS =====
  function settingsPopulateMonitoring() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    // Uptime Kuma
    if ($('#set-uptimekuma-enabled')) $('#set-uptimekuma-enabled').checked = get('uptimekuma_enabled', true);
    if ($('#set-uptimekuma-url')) $('#set-uptimekuma-url').value = get('uptimekuma_url', '');
    if ($('#set-uptimekuma-api-key')) $('#set-uptimekuma-api-key').value = get('uptimekuma_api_key', '');
    
    // Technitium DNS
    if ($('#set-technitium-enabled')) $('#set-technitium-enabled').checked = get('technitium_enabled', true);
    if ($('#set-technitium-url')) $('#set-technitium-url').value = get('technitium_url', '');
    if ($('#set-technitium-api-key')) $('#set-technitium-api-key').value = get('technitium_api_key', '');

    setReadonly('#settings-monitoring-panel');
  }

  function settingsGatherMonitoring() {
    return {
      uptimekuma_enabled: $('#set-uptimekuma-enabled')?.checked || false,
      uptimekuma_url: $('#set-uptimekuma-url')?.value || '',
      uptimekuma_api_key: $('#set-uptimekuma-api-key')?.value || '',
      technitium_enabled: $('#set-technitium-enabled')?.checked || false,
      technitium_url: $('#set-technitium-url')?.value || '',
      technitium_api_key: $('#set-technitium-api-key')?.value || ''
    };
  }

  // ===== PUSH NOTIFICATIONS SETTINGS =====
  function settingsPopulatePush() {
    const get = (key, def = '') => CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    // Gotify
    if ($('#set-gotify-url')) $('#set-gotify-url').value = get('gotify_url', '');
    if ($('#set-gotify-client-token')) $('#set-gotify-client-token').value = get('gotify_client_token', '');
    if ($('#set-gotify-app-token')) $('#set-gotify-app-token').value = get('gotify_app_token', '');
    if ($('#set-push-gotify-enabled')) $('#set-push-gotify-enabled').checked = get('push_gotify_enabled', true);
    if ($('#set-ingest-gotify-enabled')) $('#set-ingest-gotify-enabled').checked = get('ingest_gotify_enabled', true);
    
    // ntfy
    if ($('#set-ntfy-url')) $('#set-ntfy-url').value = get('ntfy_url', '');
    if ($('#set-ntfy-topic')) $('#set-ntfy-topic').value = get('ntfy_topic', '');
    if ($('#set-push-ntfy-enabled')) $('#set-push-ntfy-enabled').checked = get('push_ntfy_enabled', false);

    setReadonly('#settings-push-panel');
  }

  function settingsGatherPush() {
    return {
      gotify_url: $('#set-gotify-url')?.value || '',
      gotify_client_token: $('#set-gotify-client-token')?.value || '',
      gotify_app_token: $('#set-gotify-app-token')?.value || '',
      push_gotify_enabled: $('#set-push-gotify-enabled')?.checked || false,
      ingest_gotify_enabled: $('#set-ingest-gotify-enabled')?.checked || false,
      ntfy_url: $('#set-ntfy-url')?.value || '',
      ntfy_topic: $('#set-ntfy-topic')?.value || '',
      push_ntfy_enabled: $('#set-push-ntfy-enabled')?.checked || false
    };
  }

  // ===== UTILITIES =====
  function setReadonly(panelSelector) {
    if (!IS_READONLY) return;
    
    const panel = $(panelSelector);
    if (!panel) return;
    
    // Disable all inputs in this panel
    $$('input, select, textarea').forEach(el => {
      if (panel.contains(el)) {
        el.disabled = true;
      }
    });
  }

  // ===== SUB-TAB SWITCHING =====
  function settingsInitSubTabs() {
    $$('[data-settings-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('[data-settings-tab]').forEach(x => x.classList.remove('active'));
        btn.classList.add('active');
        
        $$('.settings-panel').forEach(p => p.classList.remove('active'));
        const panelId = 'settings-' + btn.dataset.settingsTab + '-panel';
        const panel = $('#' + panelId);
        if (panel) panel.classList.add('active');
      });
    });
  }
  // ===== BACKUP & RESTORE FUNCTIONS =====
  
  async function backupDownloadNow() {
    try {
      const btn = $('#backup-download-btn');
      if (btn) btn.classList.add('loading');

      const response = await fetch(window.API('api/backup/create'), {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error('Backup creation failed');
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

      const response = await fetch(window.API('api/backup/restore'), {
        method: 'POST',
        body: formData
      });

      const result = await response.json();

      if (result.ok) {
        window.showToast('Backup restored successfully. Restarting...', 'success');
        
        // Reload page after 3 seconds
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

  // ===== GLOBAL FUNCTIONS =====
  window.settingsLoadConfig = settingsLoadConfig;
  window.settingsSaveConfig = settingsSaveConfig;
  window.backupDownloadNow = backupDownloadNow;
  window.backupRestoreFromFile = backupRestoreFromFile;

  // Initialize when settings tab is shown
  document.addEventListener('DOMContentLoaded', () => {
    settingsInitSubTabs();
    backupInitFileInput();
    
    // Load config when settings tab is clicked
    const settingsNavTab = document.querySelector('.nav-tab[data-tab="settings"]');
    if (settingsNavTab) {
      settingsNavTab.addEventListener('click', () => {
        settingsLoadConfig();
      });
    }
    
    // Save button
    const saveBtn = $('#settings-save-btn');
    if (saveBtn) {
      saveBtn.addEventListener('click', settingsSaveConfig);
    }

    // Backup download button
    const backupDownloadBtn = $('#backup-download-btn');
    if (backupDownloadBtn) {
      backupDownloadBtn.addEventListener('click', backupDownloadNow);
    }

    // Backup restore button
    const backupRestoreBtn = $('#backup-restore-btn');
    if (backupRestoreBtn) {
      backupRestoreBtn.addEventListener('click', backupRestoreFromFile);
    }
  });
})();
