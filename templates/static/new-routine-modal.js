/* ============================================================
   New Routine Modal — behavior (vanilla JS, no dependencies)
   ------------------------------------------------------------
   Matches the existing Easel front-end pattern (see
   templates/static/routines.js). Exposes a small global API:

     NewRoutineModal.init({
       endpoint:  '/api/routine/new',   // default
       onCreated: (result, payload) => { ... },   // optional
       submit:    async (payload) => { ... }       // optional override
                  // if provided, replaces the built-in fetch
     });
     NewRoutineModal.open();
     NewRoutineModal.close();

   ── SCHEDULE MODEL ────────────────────────────────────────
   The UI offers three friendly frequencies that map onto cron:
     Daily   → hour, minute
     Weekly  → day_of_week ("mon".."sun"), hour, minute
     Monthly → day (1..31), hour, minute
   Time is entered as 12-hour (1–12 / 5-minute steps / AM·PM) and
   converted to 24-hour for the cron fields. The browser timezone
   rides along so the schedule is interpreted where the user is.

   ── API CONTRACT ──────────────────────────────────────────
   POST /api/routine/new  (FastAPI: two Pydantic body models)
   Body:
   {
     "cron_values": {
       "year": null, "month": null, "day": null, "week": null,
       "day_of_week": "mon", "hour": "9", "minute": "0",
       "second": null, "timezone": "America/Denver"
     },
     "cron_chat": { "job_name": "Morning brief", "message": "..." }
   }
   Unused cron_values keys are null; the scheduler skips them.
   Response: 200 { "created_job_id": "<uuid>" }
            400 { "detail": "..." }
   ============================================================ */

(function (global) {
  'use strict';

  // Weekday dropdown order (Sun–Sat); values are APScheduler day_of_week names.
  var WEEKDAYS = [
    ['sun', 'Sunday'], ['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'],
    ['thu', 'Thursday'], ['fri', 'Friday'], ['sat', 'Saturday']
  ];
  var WEEKDAY_LABEL = {};
  WEEKDAYS.forEach(function (w) { WEEKDAY_LABEL[w[0]] = w[1]; });

  var overlay = null;
  var frequency = 'daily';   // 'daily' | 'weekly' | 'monthly'
  var config = { endpoint: '/api/routine/new', onCreated: null, submit: null };

  /* ── helpers ───────────────────────────────────────────── */

  function pad2(n) { n = String(n); return n.length < 2 ? '0' + n : n; }

  function ordinal(n) {
    n = +n;
    var v = n % 100;
    var suffix = (v >= 11 && v <= 13) ? 'th' : (['th', 'st', 'nd', 'rd'][n % 10] || 'th');
    return n + suffix;
  }

  function el(id) { return document.getElementById(id); }

  function show(id, on) { var e = el(id); if (e) e.classList.toggle('nrm-show', !!on); }

  // The browser's IANA timezone, e.g. "America/Denver". The cron schedule is
  // interpreted in this zone server-side, so "9:00 AM" means 9:00 AM here.
  function localTimezone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; }
    catch (e) { return null; }
  }

  // A short label for the local zone, e.g. "MDT", for the live preview.
  function localTzLabel() {
    try {
      var part = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
        .formatToParts(new Date())
        .find(function (p) { return p.type === 'timeZoneName'; });
      return part ? part.value : '';
    } catch (e) { return ''; }
  }

  // <option> list builders.
  function optionsFrom(pairs) {
    return pairs.map(function (p) {
      return '<option value="' + p[0] + '">' + p[1] + '</option>';
    }).join('');
  }
  function numRange(from, to, fmt) {
    var pairs = [];
    for (var i = from; i <= to; i++) pairs.push([i, fmt ? fmt(i) : i]);
    return optionsFrom(pairs);
  }
  function minuteRange() {           // 5-minute steps: :00, :05 … :55
    var pairs = [];
    for (var m = 0; m < 60; m += 5) pairs.push([m, pad2(m)]);
    return optionsFrom(pairs);
  }

  /* ── cron model ────────────────────────────────────────── */

  // Convert the 12-hour time inputs to a 24-hour cron hour (12 AM → 0, 12 PM → 12).
  function hour24() {
    var h = +el('nrm-hour12').value % 12;
    return el('nrm-ampm').value === 'PM' ? h + 12 : h;
  }

  // The full APScheduler payload (unused cron fields = null).
  function buildPayload() {
    var cron = {
      year: null, month: null, day: null, week: null,
      day_of_week: null, hour: String(hour24()), minute: String(+el('nrm-minute').value),
      second: null, timezone: localTimezone()
    };
    if (frequency === 'weekly') cron.day_of_week = el('nrm-weekday').value;
    else if (frequency === 'monthly') cron.day = el('nrm-dom').value;

    return {
      cron_values: cron,
      cron_chat: {
        job_name: el('nrm-name').value.trim(),
        message: el('nrm-message').value.trim()
      }
    };
  }

  // Plain-English summary, e.g. "Runs every Monday at 9:00 AM" (tz appended later).
  function describeSchedule() {
    var time = el('nrm-hour12').value + ':' + pad2(el('nrm-minute').value) + ' ' + el('nrm-ampm').value;
    var when;
    if (frequency === 'weekly') when = 'every ' + WEEKDAY_LABEL[el('nrm-weekday').value];
    else if (frequency === 'monthly') when = 'on the ' + ordinal(el('nrm-dom').value) + ' of every month';
    else when = 'every day';
    return 'Runs ' + when + ' at ' + time + '.';
  }

  /* ── DOM ────────────────────────────────────────────────── */

  function build() {
    var div = document.createElement('div');
    div.className = 'nrm-overlay';
    div.id = 'nrm-overlay';
    div.innerHTML = '<div class="nrm-modal" role="dialog" aria-modal="true" aria-label="Create routine">'
      + '<div class="nrm-head">'
      +   '<div class="nrm-head-row">'
      +     '<span class="nrm-tag">New Routine</span>'
      +     '<button class="nrm-close" id="nrm-close" aria-label="Close">&times;</button>'
      +   '</div>'
      +   '<div class="nrm-title">Create a Routine</div>'
      +   '<div class="nrm-sub">Schedule a recurring agent run. Easel opens a fresh chat and sends your message on the schedule below.</div>'
      + '</div>'
      + '<div class="nrm-body">'
      +   '<div class="nrm-field">'
      +     '<label class="nrm-label" for="nrm-name">Routine name</label>'
      +     '<input class="nrm-input" id="nrm-name" type="text" placeholder="e.g. Morning standup brief" autocomplete="off" />'
      +   '</div>'
      +   '<div class="nrm-field">'
      +     '<label class="nrm-label" for="nrm-message">Message to agent</label>'
      +     '<textarea class="nrm-textarea" id="nrm-message" placeholder="What should the agent do each run? e.g. Summarize overnight activity and list today&rsquo;s top priorities."></textarea>'
      +   '</div>'
      +   '<div class="nrm-field">'
      +     '<label class="nrm-label">Run schedule</label>'
      +     '<div class="nrm-seg" id="nrm-freq" role="group" aria-label="Frequency">'
      +       '<button type="button" class="nrm-seg-btn" data-freq="daily">Daily</button>'
      +       '<button type="button" class="nrm-seg-btn" data-freq="weekly">Weekly</button>'
      +       '<button type="button" class="nrm-seg-btn" data-freq="monthly">Monthly</button>'
      +     '</div>'
      +     '<div class="nrm-when" id="nrm-when-weekly">'
      +       '<span class="nrm-when-label">On</span>'
      +       '<select class="nrm-select" id="nrm-weekday">' + optionsFrom(WEEKDAYS) + '</select>'
      +     '</div>'
      +     '<div class="nrm-when" id="nrm-when-monthly">'
      +       '<span class="nrm-when-label">On the</span>'
      +       '<select class="nrm-select" id="nrm-dom">' + numRange(1, 31, ordinal) + '</select>'
      +     '</div>'
      +     '<div class="nrm-dom-note" id="nrm-dom-note">Months without this day are skipped — e.g. February.</div>'
      +     '<div class="nrm-time">'
      +       '<span class="nrm-when-label">At</span>'
      +       '<select class="nrm-select" id="nrm-hour12">' + numRange(1, 12) + '</select>'
      +       '<span class="nrm-time-colon">:</span>'
      +       '<select class="nrm-select" id="nrm-minute">' + minuteRange() + '</select>'
      +       '<select class="nrm-select" id="nrm-ampm"><option value="AM">AM</option><option value="PM">PM</option></select>'
      +     '</div>'
      +   '</div>'
      +   '<div class="nrm-preview" id="nrm-preview">'
      +     '<div class="nrm-preview-text" id="nrm-preview-text"></div>'
      +   '</div>'
      + '</div>'
      + '<div class="nrm-footer">'
      +   '<span class="nrm-error-msg" id="nrm-error"></span>'
      +   '<button class="nrm-cancel" id="nrm-cancel">Cancel</button>'
      +   '<button class="nrm-create" id="nrm-submit">Create Routine</button>'
      + '</div>'
      + '</div>';
    document.body.appendChild(div);

    div.addEventListener('click', function (e) { if (e.target === div) close(); });
    el('nrm-close').addEventListener('click', close);
    el('nrm-cancel').addEventListener('click', close);
    el('nrm-submit').addEventListener('click', submit);

    Array.prototype.forEach.call(div.querySelectorAll('.nrm-seg-btn'), function (b) {
      b.addEventListener('click', function () { setFrequency(b.dataset.freq); });
    });
    ['nrm-weekday', 'nrm-dom', 'nrm-hour12', 'nrm-minute', 'nrm-ampm'].forEach(function (id) {
      el(id).addEventListener('change', updateState);
    });
    el('nrm-name').addEventListener('input', updateState);
    el('nrm-message').addEventListener('input', updateState);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && overlay && overlay.classList.contains('nrm-visible')) close();
    });

    return div;
  }

  /* ── state / validation ────────────────────────────────── */

  function setFrequency(freq) {
    frequency = freq;
    Array.prototype.forEach.call(document.querySelectorAll('#nrm-freq .nrm-seg-btn'), function (b) {
      var on = b.dataset.freq === freq;
      b.classList.toggle('active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    updateState();
  }

  function updateState() {
    // The conditional day rows follow the active frequency; their selects keep
    // their values while hidden, so switching back restores the prior choice.
    show('nrm-when-weekly', frequency === 'weekly');
    show('nrm-when-monthly', frequency === 'monthly');
    show('nrm-dom-note', frequency === 'monthly' && +el('nrm-dom').value >= 29);

    var desc = describeSchedule();
    var tz = localTzLabel();
    el('nrm-preview-text').textContent = tz ? desc.replace(/\.\s*$/, '') + ' ' + tz + '.' : desc;

    // The schedule is always valid now, so Create only needs name + message.
    el('nrm-submit').disabled = !el('nrm-name').value.trim() || !el('nrm-message').value.trim();
  }

  function showError(msg) {
    var e = el('nrm-error');
    e.textContent = msg || '';
    e.classList.toggle('nrm-show', !!msg);
  }

  /* ── submit ────────────────────────────────────────────── */

  async function defaultSubmit(payload) {
    var res = await fetch(config.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      var detail = 'Request failed (' + res.status + ')';
      try { var j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
      throw new Error(detail);
    }
    return res.json();
  }

  async function submit() {
    if (!el('nrm-name').value.trim() || !el('nrm-message').value.trim()) return;

    var btn = el('nrm-submit');
    var payload = buildPayload();
    showError('');
    btn.disabled = true;
    var prevLabel = btn.textContent;
    btn.textContent = 'Creating…';

    try {
      var handler = config.submit || defaultSubmit;
      var result = await handler(payload);
      if (typeof config.onCreated === 'function') config.onCreated(result, payload);
      close();
    } catch (err) {
      showError((err && err.message) || 'Could not create routine.');
      btn.disabled = false;
    } finally {
      btn.textContent = prevLabel;
    }
  }

  /* ── open / close ──────────────────────────────────────── */

  function open() {
    if (!overlay) overlay = build();
    el('nrm-name').value = '';
    el('nrm-message').value = '';
    el('nrm-weekday').value = 'mon';   // default weekly day
    el('nrm-dom').value = '1';         // default monthly day
    el('nrm-hour12').value = '9';      // default time: 9:00 AM daily
    el('nrm-minute').value = '0';
    el('nrm-ampm').value = 'AM';
    showError('');
    setFrequency('daily');             // sets active state + runs updateState
    requestAnimationFrame(function () { overlay.classList.add('nrm-visible'); });
    setTimeout(function () { el('nrm-name').focus(); }, 60);
  }

  function close() {
    if (overlay) overlay.classList.remove('nrm-visible');
  }

  /* ── public API ────────────────────────────────────────── */

  global.NewRoutineModal = {
    init: function (opts) { config = Object.assign(config, opts || {}); },
    open: open,
    close: close,
    // exposed for reuse / testing
    describeSchedule: describeSchedule,
    buildPayload: buildPayload
  };

})(window);
