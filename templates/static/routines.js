(function () {
  var ROUTINES = [];
  var editMode = false;

  var CLOCK = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.3"/><path d="M7 4.5V7.2L9 8.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="square"/></svg>';
  var CURSOR = '<svg width="12" height="14" viewBox="0 0 12 14" fill="none"><path d="M1.5 1.5v10l3-3H10L1.5 1.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="miter"/></svg>';

  var searchInput = document.getElementById('routines-search');

  function rEsc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── API → grid mapping ─────────────────────────────────── */

  // A scheduled routine from GET /api/routine/list looks like:
  //   { name, id, trigger, next_run_time, message }
  // The grid renders { id, title, description, schedule, type }.
  function mapJob(job) {
    return {
      id: job.id,
      title: job.name || 'Untitled routine',
      description: job.message || '',
      schedule: formatSchedule(job),
      type: 'scheduled'
    };
  }

  function formatSchedule(job) {
    if (job.next_run_time) {
      var d = new Date(job.next_run_time);
      if (!isNaN(d.getTime())) {
        var opts = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
        // Render in the routine's own timezone (with a short zone label) so the
        // time reads correctly regardless of where this page is being viewed.
        if (job.timezone) { opts.timeZone = job.timezone; opts.timeZoneName = 'short'; }
        try {
          return 'Next run · ' + d.toLocaleString(undefined, opts);
        } catch (e) {
          // Invalid/unknown tz string → fall back to browser-local formatting.
          return 'Next run · ' + d.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
          });
        }
      }
    }
    // Fallback: tidy the raw APScheduler trigger, e.g.
    // "cron[month='3', hour='9', minute='0']" → "month=3, hour=9, minute=0".
    if (job.trigger) {
      return String(job.trigger).replace(/^cron\[/, '').replace(/\]$/, '').replace(/'/g, '');
    }
    return 'Scheduled';
  }

  function loadRoutines() {
    fetch('/api/routine/list')
      .then(function (res) { return res.ok ? res.json() : []; })
      .then(function (jobs) {
        ROUTINES = (Array.isArray(jobs) ? jobs : []).map(mapJob);
        syncEditButton();
        renderGrid(searchInput ? searchInput.value : '');
      })
      .catch(function () {
        ROUTINES = [];
        syncEditButton();
        renderGrid('');
      });
  }

  /* ── grid ───────────────────────────────────────────────── */

  function renderGrid(q) {
    var grid = document.getElementById('routines-grid');
    if (!grid) return;
    grid.classList.toggle('edit-mode', editMode);
    var query = (q || '').toLowerCase();
    var list = query
      ? ROUTINES.filter(function(r) {
          return r.title.toLowerCase().indexOf(query) > -1 ||
                 r.description.toLowerCase().indexOf(query) > -1;
        })
      : ROUTINES;

    if (!list.length) {
      grid.innerHTML = '<div class="routines-empty">'
        + (query ? 'No routines match &ldquo;' + rEsc(q) + '&rdquo;' : 'No routines configured')
        + '</div>';
      return;
    }

    grid.innerHTML = list.map(function(r) {
      // In edit mode the schedule footer is swapped for a Delete action.
      var tail = editMode
        ? '<div class="routine-card-actions">'
          // Edit button hidden for now (placeholder, not yet wired). Re-add
          // '<button class="routine-card-edit" type="button">Edit</button>'
          // here once per-routine editing is implemented.
          + '<button class="routine-card-delete" type="button" data-rid="' + rEsc(r.id) + '">Delete</button>'
          + '</div>'
        : (r.schedule
            ? '<div class="routine-card-footer"><span class="routine-footer-clock">' + CLOCK + '</span>' + rEsc(r.schedule) + '</div>'
            : '');
      return '<div class="routine-card" data-rid="' + rEsc(r.id) + '">'
        + '<div class="routine-card-top">'
        + '<div class="routine-card-body">'
        + '<div class="routine-card-title">' + rEsc(r.title) + '</div>'
        + '</div>'
        + '<div class="routine-card-icon' + (r.type === 'scheduled' ? ' scheduled' : '') + '">' + (r.type === 'scheduled' ? CLOCK : CURSOR) + '</div>'
        + '</div>'
        + tail
        + '</div>';
    }).join('');

    if (editMode) {
      // Wire Delete; the per-card Edit button is a placeholder (does nothing yet).
      grid.querySelectorAll('.routine-card-delete').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          deleteRoutine(btn.dataset.rid);
        });
      });
    }
    // In normal mode the card is intentionally inert for now: the "Routine
    // Running" modal (openModal/buildModal below) is disabled until it can
    // reflect real run state. Re-enable by re-adding a card click handler
    // here that calls openModal(ROUTINES.find(...)).
  }

  function deleteRoutine(id) {
    if (!id) return;
    fetch('/api/routine/delete?job_id=' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function (res) { if (!res.ok) throw new Error('delete failed'); return res.json(); })
      .then(function () { loadRoutines(); })
      .catch(function () { loadRoutines(); });  // resync the grid either way
  }

  function syncEditButton() {
    var editBtn = document.getElementById('btn-edit-routines');
    if (!editBtn) return;
    // Nothing to edit on an empty grid: hide the toggle and leave edit mode.
    editBtn.style.display = ROUTINES.length ? '' : 'none';
    if (!ROUTINES.length && editMode) {
      editMode = false;
      editBtn.textContent = 'Edit Routines';
      editBtn.classList.remove('editing');
    }
  }

  /* ── "Routine Running" modal — DISABLED for now (kept for re-enable) ──
     Not wired to anything: clicking a card no longer opens it. See the note
     in renderGrid above to restore the click handler. ── */

  var modalOverlay = null;

  function openModal(routine) {
    if (!routine) return;
    if (!modalOverlay) modalOverlay = buildModal();
    document.getElementById('routine-modal-title').textContent = routine.title;
    document.getElementById('routine-modal-desc').textContent = routine.description;
    requestAnimationFrame(function() { modalOverlay.classList.add('visible'); });
  }

  function buildModal() {
    var div = document.createElement('div');
    div.className = 'routine-modal-overlay';
    div.id = 'routine-modal-overlay';
    div.innerHTML = '<div class="routine-modal">'
      + '<div class="routine-modal-status">'
      + '<span class="routine-modal-running"><span class="modal-pulse-dot"></span>Routine Running</span>'
      + '<button class="routine-modal-x" id="routine-modal-x" aria-label="Close">&times;</button>'
      + '</div>'
      + '<div class="routine-modal-title" id="routine-modal-title"></div>'
      + '<div class="routine-modal-desc" id="routine-modal-desc"></div>'
      + '<div class="routine-modal-dots"><div class="routine-modal-dot"></div><div class="routine-modal-dot"></div><div class="routine-modal-dot"></div></div>'
      + '<button class="btn-dismiss" id="routine-modal-dismiss">Dismiss</button>'
      + '</div>';
    document.body.appendChild(div);
    div.addEventListener('click', function(e) { if (e.target === div) closeModal(); });
    document.getElementById('routine-modal-x').addEventListener('click', closeModal);
    document.getElementById('routine-modal-dismiss').addEventListener('click', closeModal);
    return div;
  }

  function closeModal() {
    if (modalOverlay) modalOverlay.classList.remove('visible');
  }

  /* ── wiring ─────────────────────────────────────────────── */

  if (searchInput) {
    searchInput.addEventListener('input', function(e) { renderGrid(e.target.value); });
  }

  var editRoutinesBtn = document.getElementById('btn-edit-routines');
  if (editRoutinesBtn) {
    editRoutinesBtn.addEventListener('click', function () {
      editMode = !editMode;
      editRoutinesBtn.textContent = editMode ? 'Cancel' : 'Edit Routines';
      editRoutinesBtn.classList.toggle('editing', editMode);
      renderGrid(searchInput ? searchInput.value : '');
    });
  }

  if (window.NewRoutineModal) {
    NewRoutineModal.init({ onCreated: loadRoutines });
    var newRoutineBtn = document.querySelector('.btn-new-routine');
    if (newRoutineBtn) {
      newRoutineBtn.addEventListener('click', NewRoutineModal.open);
    }
  }

  loadRoutines();
})();
