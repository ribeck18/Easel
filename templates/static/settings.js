(function () {
  var STORAGE_MODEL = 'easel_model';

  function loadModel() { return localStorage.getItem(STORAGE_MODEL) || 'mock-1'; }
  function saveModel(m){ localStorage.setItem(STORAGE_MODEL, m); }

  var keys = [];

  function escH(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  /* ── Providers ──────────────────────────────────────── */
  var providers = [];
  var activeProviderId = null;

  function fetchProviders() {
    fetch('/api/providers')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        providers = data.providers || [];
        activeProviderId = data.active_id || null;
        renderProviders();
      })
      .catch(function() { providers = []; activeProviderId = null; renderProviders(); });
  }

  function renderProviders() {
    var list = document.getElementById('providers-list');
    if (!list) return;
    if (!providers.length) {
      list.innerHTML = '<div class="api-key-empty">No providers configured. Add one to connect a model.</div>';
      return;
    }
    list.innerHTML = providers.map(function(p) {
      var active = p.id === activeProviderId ? ' · active' : '';
      return '<div class="api-key-row">'
        + '<div class="api-key-name">' + escH(p.label) + active + '</div>'
        + '<div class="api-key-value">' + escH(p.model) + '</div>'
        + '</div>';
    }).join('');
  }

  var provOverlay   = document.getElementById('provider-modal-overlay');
  var provOpenBtn   = document.getElementById('btn-add-provider');
  var provCloseBtn  = document.getElementById('provider-modal-x');
  var provLabel     = document.getElementById('provider-label');
  var provBaseUrl   = document.getElementById('provider-base-url');
  var provModel     = document.getElementById('provider-model');
  var provKey       = document.getElementById('provider-key');
  var provRevealBtn = document.getElementById('provider-reveal-btn');
  var provSaveBtn   = document.getElementById('provider-save-btn');
  var provRevealed  = false;

  function openProviderModal() {
    if (!provOverlay) return;
    provOverlay.classList.add('visible');
    if (provLabel)   provLabel.value = '';
    if (provBaseUrl) provBaseUrl.value = '';
    if (provModel)   provModel.value = '';
    if (provKey)   { provKey.value = ''; provKey.type = 'password'; }
    provRevealed = false;
    if (provRevealBtn) provRevealBtn.innerHTML = eyeSVG(false);
    setTimeout(function() { if (provLabel) provLabel.focus(); }, 60);
  }

  function closeProviderModal() { if (provOverlay) provOverlay.classList.remove('visible'); }

  if (provOpenBtn)  provOpenBtn.addEventListener('click', openProviderModal);
  if (provCloseBtn) provCloseBtn.addEventListener('click', closeProviderModal);
  if (provOverlay)  provOverlay.addEventListener('click', function(e) { if (e.target === provOverlay) closeProviderModal(); });

  if (provRevealBtn) {
    provRevealBtn.addEventListener('click', function() {
      provRevealed = !provRevealed;
      provKey.type = provRevealed ? 'text' : 'password';
      provRevealBtn.innerHTML = eyeSVG(provRevealed);
    });
  }

  if (provSaveBtn) {
    provSaveBtn.addEventListener('click', function() {
      var label   = provLabel ? provLabel.value.trim() : '';
      var baseUrl = provBaseUrl ? provBaseUrl.value.trim() : '';
      var model   = provModel ? provModel.value.trim() : '';
      var key     = provKey ? provKey.value.trim() : '';
      if (!label || !baseUrl || !model) return;
      fetch('/api/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label, base_url: baseUrl, model: model, api_key: key || null }),
      }).then(function() { fetchProviders(); });
      closeProviderModal();
    });
  }

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && provOverlay && provOverlay.classList.contains('visible')) closeProviderModal();
  });

  function eyeSVG(slashed) {
    var line = slashed ? '<path d="M2 2l10 10" stroke="currentColor" stroke-width="1.3" stroke-linecap="square"/>' : '';
    return '<svg width="13" height="13" viewBox="0 0 13 13" fill="none">'
      + '<path d="M1 6.5C1 6.5 3.5 1.5 6.5 1.5s5.5 5 5.5 5-2.5 5-5.5 5S1 6.5 1 6.5z" stroke="currentColor" stroke-width="1.2"/>'
      + '<circle cx="6.5" cy="6.5" r="1.75" fill="currentColor"/>'
      + line
      + '</svg>';
  }

  function fetchKeys() {
    fetch('/api/keys')
      .then(function(r) { return r.json(); })
      .then(function(names) { keys = names; renderKeys(); })
      .catch(function() { keys = []; renderKeys(); });
  }

  function renderKeys() {
    var list = document.getElementById('api-keys-list');
    if (!list) return;
    if (!keys.length) {
      list.innerHTML = '<div class="api-key-empty">No API keys configured. Add one to connect a provider.</div>';
      return;
    }
    list.innerHTML = keys.map(function(name) {
      return '<div class="api-key-row">'
        + '<div class="api-key-name">' + escH(name) + '</div>'
        + '<div class="api-key-value">••••••••••••••••</div>'
        + '</div>';
    }).join('');
  }

  /* ── Model ──────────────────────────────────────────── */
  var modelInput   = document.getElementById('model-input');
  var modelSaveBtn = document.getElementById('model-save-btn');
  var modelHint    = document.getElementById('model-hint');

  if (modelInput) {
    modelInput.value = loadModel();

    modelSaveBtn.addEventListener('click', function() {
      var val = modelInput.value.trim();
      if (!val) return;
      saveModel(val);
      fetch('/api/setmodel?' + new URLSearchParams({ model: val }), { method: 'POST' });
      var pill = document.querySelector('.nav-pill');
      if (pill) pill.innerHTML = '<span class="status-dot"></span>' + escH(val) + ' · ready';
      modelSaveBtn.textContent = 'Saved';
      modelSaveBtn.classList.add('saved');
      modelHint.textContent = 'Saved. Active on next conversation.';
      setTimeout(function() {
        modelSaveBtn.textContent = 'Save';
        modelSaveBtn.classList.remove('saved');
        modelHint.textContent = 'Used for all new conversations and eval runs.';
      }, 2200);
    });

    modelInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') modelSaveBtn.click();
    });
  }

  /* ── Modal ──────────────────────────────────────────── */
  var overlay      = document.getElementById('api-modal-overlay');
  var openBtn      = document.getElementById('btn-add-api');
  var closeBtn     = document.getElementById('api-modal-x');
  var modalName    = document.getElementById('modal-key-name');
  var modalValue   = document.getElementById('modal-key-value');
  var revealBtn    = document.getElementById('modal-reveal-btn');
  var apiSaveBtn   = document.getElementById('api-save-btn');
  var valRevealed  = false;

  function openModal() {
    overlay.classList.add('visible');
    if (modalName)  { modalName.value  = ''; }
    if (modalValue) { modalValue.value = ''; modalValue.type = 'password'; }
    valRevealed = false;
    revealBtn.innerHTML = eyeSVG(false);
    setTimeout(function() { if (modalName) modalName.focus(); }, 60);
  }

  function closeModal() { overlay.classList.remove('visible'); }

  if (openBtn)  openBtn.addEventListener('click', openModal);
  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (overlay)  overlay.addEventListener('click', function(e) { if (e.target === overlay) closeModal(); });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && overlay.classList.contains('visible')) closeModal();
  });

  if (revealBtn) {
    revealBtn.addEventListener('click', function() {
      valRevealed = !valRevealed;
      modalValue.type = valRevealed ? 'text' : 'password';
      revealBtn.innerHTML = eyeSVG(valRevealed);
    });
  }

  if (apiSaveBtn) {
    apiSaveBtn.addEventListener('click', function() {
      var name = modalName ? modalName.value.trim().toUpperCase().replace(/\s+/g, '_') : '';
      var val  = modalValue ? modalValue.value.trim() : '';
      if (!name || !val) return;
      fetch('/api/setkey?' + new URLSearchParams({ key_name: name, key: val }), { method: 'POST' })
        .then(function() { fetchKeys(); });
      closeModal();
    });
  }

  if (modalName)  modalName.addEventListener('keydown',  function(e) { if (e.key === 'Enter') { e.preventDefault(); if (modalValue) modalValue.focus(); } });
  if (modalValue) modalValue.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); if (apiSaveBtn) apiSaveBtn.click(); } });

  /* ── Tools toggle ───────────────────────────────────── */
  var toolsToggle = document.getElementById('tools-toggle-input');

  if (toolsToggle) {
    fetch('/api/settings/tools')
      .then(function(r) { return r.json(); })
      .then(function(data) { toolsToggle.checked = !!data.enabled; })
      .catch(function() {});

    toolsToggle.addEventListener('change', function() {
      fetch('/api/settings/tools?' + new URLSearchParams({ enabled: toolsToggle.checked }), { method: 'POST' });
    });
  }

  /* ── Skills toggle ──────────────────────────────────── */
  var skillsToggle = document.getElementById('skills-toggle-input');

  if (skillsToggle) {
    fetch('/api/settings/skills')
      .then(function(r) { return r.json(); })
      .then(function(data) { skillsToggle.checked = !!data.enabled; })
      .catch(function() {});

    skillsToggle.addEventListener('change', function() {
      fetch('/api/settings/skills?' + new URLSearchParams({ enabled: skillsToggle.checked }), { method: 'POST' });
    });
  }

  /* ── Memory settings ───────────────────────────────── */
  var memoryToggle = document.getElementById('memory-toggle-input');
  var memoryModelInput = document.getElementById('memory-model-input');
  var memorySaveBtn = document.getElementById('memory-save-btn');
  var memoryHint = document.getElementById('memory-hint');
  var userMemoryInput = document.getElementById('user-memory-input');
  var coreMemoryInput = document.getElementById('core-memory-input');
  var coreMemorySaveBtn = document.getElementById('core-memory-save-btn');
  var coreMemoryHint = document.getElementById('core-memory-hint');

  if (memoryToggle) {
    fetch('/api/settings/memory')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        memoryToggle.checked = !!data.enabled;
        if (memoryModelInput) memoryModelInput.value = data.model || '';
      })
      .catch(function() {});

    memoryToggle.addEventListener('change', saveMemorySettings);
  }

  if (memorySaveBtn) {
    memorySaveBtn.addEventListener('click', saveMemorySettings);
  }

  function saveMemorySettings() {
    fetch('/api/settings/memory?' + new URLSearchParams({
      enabled: memoryToggle ? memoryToggle.checked : false,
      model: memoryModelInput ? memoryModelInput.value.trim() : '',
    }), { method: 'POST' }).then(function() {
      if (!memorySaveBtn || !memoryHint) return;
      memorySaveBtn.textContent = 'Saved';
      memorySaveBtn.classList.add('saved');
      memoryHint.textContent = 'Saved. Active on the next turn.';
      setTimeout(function() {
        memorySaveBtn.textContent = 'Save';
        memorySaveBtn.classList.remove('saved');
        memoryHint.textContent = 'Used for background capture and consolidation.';
      }, 2200);
    });
  }

  function loadCoreMemory(kind, input) {
    if (!input) return;
    fetch('/api/memory/core?' + new URLSearchParams({ kind: kind }))
      .then(function(r) { return r.json(); })
      .then(function(data) { input.value = data.content || ''; })
      .catch(function() {});
  }

  loadCoreMemory('user', userMemoryInput);
  loadCoreMemory('memory', coreMemoryInput);

  function saveOneCore(kind, input) {
    return fetch('/api/memory/core?kind=' + kind, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: input ? input.value : '' }),
    }).then(function(r) {
      if (r.ok) return null;
      return r.json().then(function(body) {
        return { kind: kind, status: r.status, body: body };
      });
    });
  }

  if (coreMemorySaveBtn) {
    coreMemorySaveBtn.addEventListener('click', function() {
      Promise.all([
        saveOneCore('user', userMemoryInput),
        saveOneCore('memory', coreMemoryInput),
      ]).then(function(results) {
        var failure = results.filter(Boolean)[0];
        if (failure) {
          if (coreMemoryHint) {
            if (failure.status === 422 && failure.body) {
              coreMemoryHint.textContent =
                (failure.kind === 'user' ? 'USER.md' : 'MEMORY.md') +
                ' is too long (' + failure.body.current + '/' + failure.body.limit +
                ' chars). Trim it and save again.';
            } else if (failure.status === 409) {
              coreMemoryHint.textContent =
                'No workspace is mounted, so core memory cannot be saved.';
            } else {
              coreMemoryHint.textContent = 'Could not save core memory.';
            }
          }
          return;
        }
        coreMemorySaveBtn.textContent = 'Saved';
        coreMemorySaveBtn.classList.add('saved');
        if (coreMemoryHint) coreMemoryHint.textContent = 'Saved. Active on next message.';
        setTimeout(function() {
          coreMemorySaveBtn.textContent = 'Save Core Memory';
          coreMemorySaveBtn.classList.remove('saved');
          if (coreMemoryHint) coreMemoryHint.textContent = 'Injected on every message when memory is enabled.';
        }, 2200);
      });
    });
  }

  /* ── Agent instructions (agents.md) ─────────────────── */
  var agentsInput   = document.getElementById('agents-input');
  var agentsSaveBtn = document.getElementById('agents-save-btn');
  var agentsHint    = document.getElementById('agents-hint');

  if (agentsInput) {
    fetch('/api/agents')
      .then(function(r) { return r.json(); })
      .then(function(data) { agentsInput.value = data.content || ''; })
      .catch(function() {});

    agentsSaveBtn.addEventListener('click', function() {
      fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: agentsInput.value }),
      }).then(function() {
        agentsSaveBtn.textContent = 'Saved';
        agentsSaveBtn.classList.add('saved');
        agentsHint.textContent = 'Saved. Active on next message.';
        setTimeout(function() {
          agentsSaveBtn.textContent = 'Save';
          agentsSaveBtn.classList.remove('saved');
          agentsHint.textContent = 'Appended to the system prompt on every message.';
        }, 2200);
      });
    });
  }

  /* init */
  fetchProviders();
  fetchKeys();
})();
