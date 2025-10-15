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
      
      const banner = $('#settings-readonly-banner');
      if (banner) banner.style.display = IS_READONLY ? 'block' : 'none';
      
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
// ===== LLM & AI SETTINGS =====
  function settingsPopulateLLM() {
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;

    // ---- BASIC CORE ----
    if ($('#set-llm-enabled'))
      $('#set-llm-enabled').checked = get('llm_enabled', true);
    if ($('#set-llm-persona-riffs-enabled'))
      $('#set-llm-persona-riffs-enabled').checked = get('llm_persona_riffs_enabled', true);
    if ($('#set-llm-rewrite-enabled'))
      $('#set-llm-rewrite-enabled').checked = get('llm_rewrite_enabled', false);
    if ($('#set-llm-models-dir'))
      $('#set-llm-models-dir').value = get('llm_models_dir', '/share/jarvis_prime/models');
    if ($('#set-llm-timeout-seconds'))
      $('#set-llm-timeout-seconds').value = get('llm_timeout_seconds', 20);
    if ($('#set-llm-max-cpu-percent'))
      $('#set-llm-max-cpu-percent').value = get('llm_max_cpu_percent', 80);
    if ($('#set-llm-ctx-tokens'))
      $('#set-llm-ctx-tokens').value = get('llm_ctx_tokens', 6096);
    if ($('#set-llm-gen-tokens'))
      $('#set-llm-gen-tokens').value = get('llm_gen_tokens', 300);
    if ($('#set-llm-threads'))
      $('#set-llm-threads').value = get('llm_threads', 3);
    if ($('#set-llm-models-priority'))
      $('#set-llm-models-priority').value = get('llm_models_priority', 'phi35_q5_uncensored,phi35_q5,phi35_q4,phi3');

    // ---- GENERAL ADVANCED ----
    if ($('#set-llm-memory-enabled'))
      $('#set-llm-memory-enabled').checked = get('llm_memory_enabled', true);
    if ($('#set-llm-autodownload'))
      $('#set-llm-autodownload').checked = get('llm_autodownload', true);
    if ($('#set-llm-hf-token'))
      $('#set-llm-hf-token').value = get('llm_hf_token', '');
    if ($('#set-llm-cleanup-on-disable'))
      $('#set-llm-cleanup-on-disable').checked = get('llm_cleanup_on_disable', true);
    if ($('#set-llm-riff-max-tokens'))
      $('#set-llm-riff-max-tokens').value = get('llm_riff_max_tokens', 32);
    if ($('#set-llm-rewrite-max-tokens'))
      $('#set-llm-rewrite-max-tokens').value = get('llm_rewrite_max_tokens', 256);
    if ($('#set-llm-max-lines'))
      $('#set-llm-max-lines').value = get('llm_max_lines', 30);
    if ($('#set-llm-system-prompt'))
      $('#set-llm-system-prompt').value = get('llm_system_prompt', '');

    // ---- MODEL FAMILIES ----
    const models = [
      'phi4_q4',
      'phi4_q5',
      'phi4_q6',
      'phi4_q8',
      'phi35_q4',
      'phi35_q5',
      'phi35_q5_uncensored',
      'phi3'
    ];
    models.forEach((m) => {
      const eKey = `llm_${m}_enabled`;
      const uKey = `llm_${m}_url`;
      const pKey = `llm_${m}_path`;
      if ($(`#set-${eKey}`)) $(`#set-${eKey}`).checked = get(eKey, false);
      if ($(`#set-${uKey}`)) $(`#set-${uKey}`).value = get(uKey, '');
      if ($(`#set-${pKey}`)) $(`#set-${pKey}`).value = get(pKey, '');
    });

    // ---- ENVIROGUARD BASE ----
    if ($('#set-llm-enviroguard-enabled'))
      $('#set-llm-enviroguard-enabled').checked = get('llm_enviroguard_enabled', true);
    if ($('#set-llm-enviroguard-poll-minutes'))
      $('#set-llm-enviroguard-poll-minutes').value = get('llm_enviroguard_poll_minutes', 30);
    if ($('#set-llm-enviroguard-hot-c'))
      $('#set-llm-enviroguard-hot-c').value = get('llm_enviroguard_hot_c', 30);
    if ($('#set-llm-enviroguard-normal-c'))
      $('#set-llm-enviroguard-normal-c').value = get('llm_enviroguard_normal_c', 22);
    if ($('#set-llm-enviroguard-cold-c'))
      $('#set-llm-enviroguard-cold-c').value = get('llm_enviroguard_cold_c', 10);

    // ---- ENVIROGUARD ADVANCED ----
    const advKeys = [
      'llm_enviroguard_max_stale_minutes',
      'llm_enviroguard_hysteresis_c',
      'llm_enviroguard_profiles',
      'llm_enviroguard_ha_enabled',
      'llm_enviroguard_ha_base_url',
      'llm_enviroguard_ha_token',
      'llm_enviroguard_ha_temp_entity',
      'llm_enviroguard_off_c',
      'llm_enviroguard_boost_c'
    ];
    advKeys.forEach((k) => {
      const el = $(`#set-${k}`);
      if (el !== null && el !== undefined) {
        const val = get(k, '');
        if (typeof el.type !== 'undefined' && el.type === 'checkbox') el.checked = Boolean(val);
        else el.value = val;
      }
    });

    setReadonly('#settings-llm-panel');
  }

  function settingsGatherLLM() {
    const cfg = {
      llm_enabled: $('#set-llm-enabled')?.checked || false,
      llm_persona_riffs_enabled: $('#set-llm-persona-riffs-enabled')?.checked || false,
      llm_rewrite_enabled: $('#set-llm-rewrite-enabled')?.checked || false,
      llm_models_dir: $('#set-llm-models-dir')?.value || '/share/jarvis_prime/models',
      llm_timeout_seconds: parseInt($('#set-llm-timeout-seconds')?.value || '20'),
      llm_max_cpu_percent: parseInt($('#set-llm-max-cpu-percent')?.value || '80'),
      llm_ctx_tokens: parseInt($('#set-llm-ctx-tokens')?.value || '6096'),
      llm_gen_tokens: parseInt($('#set-llm-gen-tokens')?.value || '300'),
      llm_threads: parseInt($('#set-llm-threads')?.value || '3'),
      llm_models_priority: $('#set-llm-models-priority')?.value || ''
    };

    // ---- GENERAL ADVANCED ----
    cfg.llm_memory_enabled = $('#set-llm-memory-enabled')?.checked || false;
    cfg.llm_autodownload = $('#set-llm-autodownload')?.checked || false;
    cfg.llm_hf_token = $('#set-llm-hf-token')?.value || '';
    cfg.llm_cleanup_on_disable = $('#set-llm-cleanup-on-disable')?.checked || false;
    cfg.llm_riff_max_tokens = parseInt($('#set-llm-riff-max-tokens')?.value || '32');
    cfg.llm_rewrite_max_tokens = parseInt($('#set-llm-rewrite-max-tokens')?.value || '256');
    cfg.llm_max_lines = parseInt($('#set-llm-max-lines')?.value || '30');
    cfg.llm_system_prompt = $('#set-llm-system-prompt')?.value || '';

    // ---- MODEL FAMILIES ----
    const models = [
      'phi4_q4',
      'phi4_q5',
      'phi4_q6',
      'phi4_q8',
      'phi35_q4',
      'phi35_q5',
      'phi35_q5_uncensored',
      'phi3'
    ];
    models.forEach((m) => {
      cfg[`llm_${m}_enabled`] = $(`#set-llm_${m}_enabled`)?.checked || false;
      cfg[`llm_${m}_url`] = $(`#set-llm_${m}_url`)?.value || '';
      cfg[`llm_${m}_path`] = $(`#set-llm_${m}_path`)?.value || '';
    });

    // ---- ENVIROGUARD ----
    [
      'llm_enviroguard_enabled',
      'llm_enviroguard_poll_minutes',
      'llm_enviroguard_hot_c',
      'llm_enviroguard_normal_c',
      'llm_enviroguard_cold_c',
      'llm_enviroguard_max_stale_minutes',
      'llm_enviroguard_hysteresis_c',
      'llm_enviroguard_profiles',
      'llm_enviroguard_ha_enabled',
      'llm_enviroguard_ha_base_url',
      'llm_enviroguard_ha_token',
      'llm_enviroguard_ha_temp_entity',
      'llm_enviroguard_off_c',
      'llm_enviroguard_boost_c'
    ].forEach((k) => {
      const el = $(`#set-${k}`);
      if (!el) return;
      if (el.type === 'checkbox') cfg[k] = el.checked;
      else if (el.type === 'number') cfg[k] = parseInt(el.value || '0', 10) || 0;
      else cfg[k] = el.value || '';
    });

    return cfg;
  }
// ===== PERSONALITY SETTINGS =====
  function settingsPopulatePersonality() {
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-personality-enabled'))
      $('#set-personality-enabled').checked = get('personality_enabled', true);
    if ($('#set-active-persona'))
      $('#set-active-persona').value = get('active_persona', 'auto');
    if ($('#set-personality-min-interval-minutes'))
      $('#set-personality-min-interval-minutes').value = get('personality_min_interval_minutes', 90);
    if ($('#set-personality-interval-jitter-pct'))
      $('#set-personality-interval-jitter-pct').value = get('personality_interval_jitter_pct', 20);
    if ($('#set-personality-daily-max'))
      $('#set-personality-daily-max').value = get('personality_daily_max', 6);
    if ($('#set-personality-quiet-hours'))
      $('#set-personality-quiet-hours').value = get('personality_quiet_hours', '23:00-06:00');
    if ($('#set-chat-enabled'))
      $('#set-chat-enabled').checked = get('chat_enabled', true);
    
    if ($('#set-enable-dude'))
      $('#set-enable-dude').checked = get('enable_dude', true);
    if ($('#set-enable-chick'))
      $('#set-enable-chick').checked = get('enable_chick', false);
    if ($('#set-enable-nerd'))
      $('#set-enable-nerd').checked = get('enable_nerd', false);
    if ($('#set-enable-rager'))
      $('#set-enable-rager').checked = get('enable_rager', false);
    if ($('#set-enable-comedian'))
      $('#set-enable-comedian').checked = get('enable_comedian', false);
    if ($('#set-enable-action'))
      $('#set-enable-action').checked = get('enable_action', false);

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
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-weather-enabled')) $('#set-weather-enabled').checked = get('weather_enabled', true);
    if ($('#set-weather-lat')) $('#set-weather-lat').value = get('weather_lat', -26.2041);
    if ($('#set-weather-lon')) $('#set-weather-lon').value = get('weather_lon', 28.0473);
    if ($('#set-weather-city')) $('#set-weather-city').value = get('weather_city', 'Odendaalsrus');
    if ($('#set-weather-time')) $('#set-weather-time').value = get('weather_time', '07:00');
    
    if ($('#set-digest-enabled')) $('#set-digest-enabled').checked = get('digest_enabled', true);
    if ($('#set-digest-time')) $('#set-digest-time').value = get('digest_time', '08:00');
    
    if ($('#set-heartbeat-enabled')) $('#set-heartbeat-enabled').checked = get('heartbeat_enabled', true);
    if ($('#set-heartbeat-interval-minutes'))
      $('#set-heartbeat-interval-minutes').value = get('heartbeat_interval_minutes', 120);
    if ($('#set-heartbeat-start'))
      $('#set-heartbeat-start').value = get('heartbeat_start', '06:00');
    if ($('#set-heartbeat-end'))
      $('#set-heartbeat-end').value = get('heartbeat_end', '20:00');
    
    if ($('#set-radarr-enabled')) $('#set-radarr-enabled').checked = get('radarr_enabled', true);
    if ($('#set-radarr-url')) $('#set-radarr-url').value = get('radarr_url', '');
    if ($('#set-radarr-api-key')) $('#set-radarr-api-key').value = get('radarr_api_key', '');
    
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
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-smtp-enabled')) $('#set-smtp-enabled').checked = get('smtp_enabled', true);
    if ($('#set-smtp-port')) $('#set-smtp-port').value = get('smtp_port', 2525);
    if ($('#set-ingest-smtp-enabled')) $('#set-ingest-smtp-enabled').checked = get('ingest_smtp_enabled', true);
    
    if ($('#set-proxy-enabled')) $('#set-proxy-enabled').checked = get('proxy_enabled', true);
    if ($('#set-proxy-port')) $('#set-proxy-port').value = get('proxy_port', 2580);
    
    if ($('#set-webhook-enabled')) $('#set-webhook-enabled').checked = get('webhook_enabled', true);
    if ($('#set-webhook-port')) $('#set-webhook-port').value = get('webhook_port', 2590);
    
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
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-monitoring-enabled'))
      $('#set-monitoring-enabled').checked = get('monitoring_enabled', true);
    if ($('#set-monitoring-interval-minutes'))
      $('#set-monitoring-interval-minutes').value = get('monitoring_interval_minutes', 60);
    if ($('#set-monitoring-max-incidents'))
      $('#set-monitoring-max-incidents').value = get('monitoring_max_incidents', 100);
    if ($('#set-monitoring-notify'))
      $('#set-monitoring-notify').checked = get('monitoring_notify', true);

    setReadonly('#settings-monitoring-panel');
  }

  function settingsGatherMonitoring() {
    return {
      monitoring_enabled: $('#set-monitoring-enabled')?.checked || false,
      monitoring_interval_minutes: parseInt($('#set-monitoring-interval-minutes')?.value || '60'),
      monitoring_max_incidents: parseInt($('#set-monitoring-max-incidents')?.value || '100'),
      monitoring_notify: $('#set-monitoring-notify')?.checked || false
    };
  }

  // ===== PUSH / NOTIFICATIONS =====
  function settingsPopulatePush() {
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-push-gotify-enabled'))
      $('#set-push-gotify-enabled').checked = get('push_gotify_enabled', true);
    if ($('#set-push-gotify-url'))
      $('#set-push-gotify-url').value = get('push_gotify_url', '');
    if ($('#set-push-gotify-token'))
      $('#set-push-gotify-token').value = get('push_gotify_token', '');
    
    if ($('#set-push-ntfy-enabled'))
      $('#set-push-ntfy-enabled').checked = get('push_ntfy_enabled', false);
    if ($('#set-push-ntfy-url'))
      $('#set-push-ntfy-url').value = get('push_ntfy_url', '');
    if ($('#set-push-ntfy-topic'))
      $('#set-push-ntfy-topic').value = get('push_ntfy_topic', '');
    if ($('#set-push-ntfy-priority'))
      $('#set-push-ntfy-priority').value = get('push_ntfy_priority', '5');
    
    if ($('#set-push-smtp-enabled'))
      $('#set-push-smtp-enabled').checked = get('push_smtp_enabled', false);
    if ($('#set-push-smtp-to'))
      $('#set-push-smtp-to').value = get('push_smtp_to', '');
    if ($('#set-push-smtp-subject'))
      $('#set-push-smtp-subject').value = get('push_smtp_subject', 'Jarvis Alert');

    setReadonly('#settings-push-panel');
  }

  function settingsGatherPush() {
    return {
      push_gotify_enabled: $('#set-push-gotify-enabled')?.checked || false,
      push_gotify_url: $('#set-push-gotify-url')?.value || '',
      push_gotify_token: $('#set-push-gotify-token')?.value || '',
      push_ntfy_enabled: $('#set-push-ntfy-enabled')?.checked || false,
      push_ntfy_url: $('#set-push-ntfy-url')?.value || '',
      push_ntfy_topic: $('#set-push-ntfy-topic')?.value || '',
      push_ntfy_priority: $('#set-push-ntfy-priority')?.value || '5',
      push_smtp_enabled: $('#set-push-smtp-enabled')?.checked || false,
      push_smtp_to: $('#set-push-smtp-to')?.value || '',
      push_smtp_subject: $('#set-push-smtp-subject')?.value || 'Jarvis Alert'
    };
  }

  // ===== BACKUP SETTINGS =====
  function settingsPopulateBackup() {
    const get = (key, def = '') =>
      CURRENT_CONFIG[key] !== undefined ? CURRENT_CONFIG[key] : def;
    
    if ($('#set-backup-enabled'))
      $('#set-backup-enabled').checked = get('backup_enabled', true);
    if ($('#set-backup-path'))
      $('#set-backup-path').value = get('backup_path', '/share/jarvis_prime/backups');
    if ($('#set-backup-interval-hours'))
      $('#set-backup-interval-hours').value = get('backup_interval_hours', 24);
    if ($('#set-backup-max-count'))
      $('#set-backup-max-count').value = get('backup_max_count', 7);

    setReadonly('#settings-backup-panel');
  }

  function settingsGatherBackup() {
    return {
      backup_enabled: $('#set-backup-enabled')?.checked || false,
      backup_path: $('#set-backup-path')?.value || '/share/jarvis_prime/backups',
      backup_interval_hours: parseInt($('#set-backup-interval-hours')?.value || '24'),
      backup_max_count: parseInt($('#set-backup-max-count')?.value || '7')
    };
  }

  // ===== HELPER =====
  function setReadonly(selector) {
    if (!IS_READONLY) return;
    $$(selector + ' input, ' + selector + ' select, ' + selector + ' textarea').forEach(el => {
      el.disabled = true;
      el.classList.add('readonly');
    });
  }

  // ===== INIT =====
  document.addEventListener('DOMContentLoaded', () => {
    $('#settings-save-btn')?.addEventListener('click', settingsSaveConfig);
    settingsLoadConfig();
  });

  // Export for global debugging if needed
  window.settings = {
    load: settingsLoadConfig,
    save: settingsSaveConfig
  };
})();