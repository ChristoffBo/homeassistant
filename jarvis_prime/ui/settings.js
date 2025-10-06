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

    if ($('#set-weather-enabled')) $('#set-weather-enabled').checked = get('weather_enabled', true);
    if ($('#set-weather-lat')) $('#set-weather-lat').value = get('weather_lat', -26.2041);
    if ($('#set-weather-lon')) $('#set-weather-lon').value = get('weather_lon', 28.0473);
    if ($('#set-weather-city')) $('#set-weather-city').value = get('weather_city', 'Odendaalsrus');
    if ($('#set-weather-time')) $('#set-weather-time').value = get('weather_time', '07:00');

    if ($('#set-digest-enabled')) $('#set-digest-enabled').checked = get('digest_enabled', true);
    if ($('#set-digest-time')) $('#set-digest-time').value = get('digest_time', '08:00');

    if ($('#set-heartbeat-enabled')) $('#set-heartbeat-enabled').checked = get('heartbeat_enabled', true);
    if ($('#set-heartbeat-interval-minutes')) $('#set-heartbeat-interval-minutes').value = get('heartbeat_interval_minutes', 120);
    if ($('#set-heartbeat-start')) $('#set-heartbeat-start').value = get('heartbeat_start', '06:00');
    if ($('#set-heartbeat-end')) $('#set-heartbeat-end').value = get('heartbeat_end', '20:00');

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
      weather_time: $('#set-weather-time')?.value