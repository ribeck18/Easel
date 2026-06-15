(function () {
  var SKILLS = [];
  var GLOBAL_ENABLED = true;
  var HAS_WORKSPACE = true;

  var IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'];
  var TEXT_EXTS = ['md', 'markdown', 'txt', 'text', 'json', 'yaml', 'yml', 'toml',
    'csv', 'log', 'py', 'js', 'ts', 'sh', 'html', 'css', 'xml', 'ini', 'cfg'];

  function escH(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function inlineMd(text) {
    var s = escH(text);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
    return s;
  }

  function renderMd(md) {
    var lines = md.split('\n');
    var html = '';
    var inCode = false, codeBuf = [];
    var inTable = false, tableRows = [];
    var listBuf = [];

    function flushList() {
      if (!listBuf.length) return;
      html += '<ul>' + listBuf.map(function(i){ return '<li>' + i + '</li>'; }).join('') + '</ul>';
      listBuf = [];
    }

    function flushTable() {
      if (!tableRows.length) return;
      var header = tableRows[0];
      var body = tableRows.slice(2);
      html += '<table><thead><tr>'
        + header.map(function(c){ return '<th>' + inlineMd(c.trim()) + '</th>'; }).join('')
        + '</tr></thead><tbody>'
        + body.map(function(row){
            return '<tr>' + row.map(function(c){ return '<td>' + inlineMd(c.trim()) + '</td>'; }).join('') + '</tr>';
          }).join('')
        + '</tbody></table>';
      tableRows = [];
      inTable = false;
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      if (/^```/.test(line)) {
        if (!inCode) { flushList(); flushTable(); inCode = true; codeBuf = []; }
        else { html += '<pre><code>' + escH(codeBuf.join('\n')) + '</code></pre>'; inCode = false; codeBuf = []; }
        continue;
      }
      if (inCode) { codeBuf.push(line); continue; }

      if (/^\|/.test(line)) {
        flushList(); inTable = true;
        tableRows.push(line.split('|').slice(1,-1));
        continue;
      } else if (inTable) { flushTable(); }

      if      (/^# /.test(line))   { flushList(); html += '<h1>' + inlineMd(line.slice(2)) + '</h1>'; }
      else if (/^## /.test(line))  { flushList(); html += '<h2>' + inlineMd(line.slice(3)) + '</h2>'; }
      else if (/^### /.test(line)) { flushList(); html += '<h3>' + inlineMd(line.slice(4)) + '</h3>'; }
      else if (/^- /.test(line))   { listBuf.push(inlineMd(line.slice(2))); }
      else if (line.trim() === '')  { flushList(); }
      else                          { flushList(); html += '<p>' + inlineMd(line) + '</p>'; }
    }
    flushList(); flushTable();
    return html;
  }

  var currentSkillId = null;

  function applyGlobalState() {
    var page = document.getElementById('page-skills');
    if (page) page.classList.toggle('skills-globally-off', !GLOBAL_ENABLED);
  }

  function renderList(q) {
    var list = document.getElementById('skills-list');
    if (!list) return;

    if (!HAS_WORKSPACE && !SKILLS.length) {
      list.innerHTML = '<div class="skills-empty">No workspace is mounted, so skills are unavailable.</div>';
      return;
    }

    var query = (q || '').toLowerCase();
    var filtered = query
      ? SKILLS.filter(function(s){
          return s.name.toLowerCase().indexOf(query) > -1 ||
                 s.slug.toLowerCase().indexOf(query) > -1 ||
                 (s.description || '').toLowerCase().indexOf(query) > -1;
        })
      : SKILLS;

    var banner = !GLOBAL_ENABLED
      ? '<div class="skills-global-banner">Skills are globally disabled — the agent can’t use any skill. Enable them in Settings.</div>'
      : '';

    if (!filtered.length) {
      list.innerHTML = banner + '<div class="skills-empty">'
        + (query ? 'No skills match &ldquo;' + escH(q) + '&rdquo;' : 'No skills configured')
        + '</div>';
      return;
    }

    list.innerHTML = banner + filtered.map(function(s) {
      var refLabel = s.refs.length + ' ref' + (s.refs.length !== 1 ? 's' : '');
      var warn = s.valid ? '' : '<span class="skill-cat skill-warn">⚠ needs SKILL.md / description</span>';
      var sourceTag = '<span class="skill-cat skill-source-' + escH(s.source || 'workspace') + '">'
        + (s.source === 'stock' ? 'built-in' : 'skill') + '</span>';
      return '<div class="skill-card" data-sid="' + escH(s.slug) + '" tabindex="0" role="button">'
        + '<div class="skill-card-top">'
        +   '<div class="skill-card-body">'
        +     '<div class="skill-card-title">' + escH(s.name) + '</div>'
        +     '<div class="skill-card-desc">' + escH(s.description || s.slug) + '</div>'
        +   '</div>'
        +   '<div class="skill-card-right" data-no-expand="1">'
        +     '<label class="skill-toggle" title="' + (s.enabled ? 'Disable' : 'Enable') + ' skill">'
        +       '<input type="checkbox" data-sid="' + escH(s.slug) + '"' + (s.enabled ? ' checked' : '') + ' />'
        +       '<span class="skill-toggle-track"></span>'
        +     '</label>'
        +   '</div>'
        + '</div>'
        + '<div class="skill-card-footer">'
        +   (warn || sourceTag)
        +   '<span>' + refLabel + '</span>'
        + '</div>'
        + '</div>';
    }).join('');

    list.querySelectorAll('.skill-card').forEach(function(card) {
      card.addEventListener('click', function(e) {
        if (e.target.closest('[data-no-expand]')) return;
        var sid = card.dataset.sid;
        openDetail(SKILLS.find(function(s){ return s.slug === sid; }));
      });
      card.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
      });
    });

    list.querySelectorAll('.skill-toggle input').forEach(function(inp) {
      inp.addEventListener('change', function(e) {
        e.stopPropagation();
        var skill = SKILLS.find(function(s){ return s.slug === inp.dataset.sid; });
        if (skill) saveToggle(skill, inp.checked, inp);
      });
    });
  }

  function saveToggle(skill, enabled, inp) {
    fetch('/api/skills/' + encodeURIComponent(skill.slug) + '/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled })
    }).then(function(r) {
      if (!r.ok) throw new Error('toggle failed');
      skill.enabled = enabled;
      if (currentSkillId === skill.slug) syncDetailToggle(skill);
    }).catch(function() {
      if (inp) inp.checked = skill.enabled;   // revert on failure
    });
  }

  function syncDetailToggle(skill) {
    var inp = document.getElementById('dt-' + skill.slug);
    if (inp) inp.checked = skill.enabled;
    var lbl = document.getElementById('dt-label-' + skill.slug);
    if (lbl) {
      lbl.textContent = skill.enabled ? 'Enabled' : 'Disabled';
      lbl.style.color = skill.enabled ? 'oklch(62% 0.17 145)' : '';
    }
  }

  function openDetail(skill) {
    if (!skill) return;
    currentSkillId = skill.slug;
    document.getElementById('skills-list-view').style.display = 'none';
    document.getElementById('skills-detail-view').classList.add('active');
    document.getElementById('skills-detail-title').textContent = skill.name;

    var wrap = document.getElementById('skills-detail-toggle-wrap');
    wrap.innerHTML = '<label class="skill-toggle">'
      + '<input type="checkbox" id="dt-' + escH(skill.slug) + '"' + (skill.enabled ? ' checked' : '') + ' />'
      + '<span class="skill-toggle-track"></span>'
      + '</label>'
      + '<span id="dt-label-' + escH(skill.slug) + '" style="' + (skill.enabled ? 'color:oklch(62% 0.17 145)' : '') + '">'
      + (skill.enabled ? 'Enabled' : 'Disabled')
      + '</span>'
      + (skill.source === 'stock'
          ? '<span class="skill-builtin-note">Built-in — copy into <code>Easel/Skills/</code> to customize</span>'
          : '');

    document.getElementById('dt-' + skill.slug).addEventListener('change', function() {
      saveToggle(skill, this.checked, this);
      var listInp = document.querySelector('.skill-card[data-sid="' + skill.slug + '"] input[type=checkbox]');
      if (listInp) listInp.checked = this.checked;
    });

    var main = document.getElementById('skills-detail-main');
    var sidebar = document.getElementById('skills-detail-sidebar');
    main.innerHTML = '<p class="skills-loading">Loading…</p>';
    sidebar.innerHTML = '';

    fetch('/api/skills/' + encodeURIComponent(skill.slug))
      .then(function(r) { return r.json(); })
      .then(function(detail) {
        main.innerHTML = detail.body
          ? renderMd(detail.body)
          : '<p>No documentation available for this skill.</p>';
        main.scrollTop = 0;
        renderReferences(skill.slug, detail.references || [], main, sidebar);
      })
      .catch(function() { main.innerHTML = '<p>Could not load this skill.</p>'; });
  }

  function renderReferences(slug, refs, main, sidebar) {
    sidebar.innerHTML = '<div class="skills-sidebar-heading">Reference Files</div>'
      + (refs.length ? '' : '<div class="skill-ref-empty">None</div>')
      + refs.map(function(r) {
          return '<div class="skill-ref-item" data-ref="' + escH(r.path) + '" data-ext="' + escH(r.ext) + '" tabindex="0" role="button">'
            + '<div class="skill-ref-top">'
            +   '<span class="skill-ref-ext ext-' + escH(r.ext) + '">' + escH(r.ext || 'file') + '</span>'
            +   '<span class="skill-ref-name">' + escH(r.name) + '</span>'
            + '</div>'
            + '<div class="skill-ref-path">' + escH(r.path) + '</div>'
            + '</div>';
        }).join('');

    sidebar.querySelectorAll('.skill-ref-item').forEach(function(item) {
      function open() { showReference(slug, item.dataset.ref, item.dataset.ext, main, sidebar); }
      item.addEventListener('click', open);
      item.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  }

  function showReference(slug, path, ext, main, sidebar) {
    sidebar.querySelectorAll('.skill-ref-item').forEach(function(it) {
      it.classList.toggle('active', it.dataset.ref === path);
    });
    var url = '/api/skills/' + encodeURIComponent(slug) + '/reference?path=' + encodeURIComponent(path);
    ext = (ext || '').toLowerCase();

    if (IMAGE_EXTS.indexOf(ext) > -1) {
      main.innerHTML = '<div class="skill-ref-view"><img src="' + url + '" alt="' + escH(path) + '" /></div>';
      return;
    }
    if (TEXT_EXTS.indexOf(ext) > -1 || ext === '') {
      main.innerHTML = '<p class="skills-loading">Loading…</p>';
      fetch(url)
        .then(function(r) { return r.text(); })
        .then(function(text) {
          main.innerHTML = '<div class="skill-ref-view">'
            + (ext === 'md' || ext === 'markdown' ? renderMd(text) : '<pre>' + escH(text) + '</pre>')
            + '</div>';
          main.scrollTop = 0;
        })
        .catch(function() { main.innerHTML = '<p>Could not load this reference.</p>'; });
      return;
    }
    main.innerHTML = '<div class="skill-ref-view"><p>This file type is not previewable. '
      + '<a href="' + url + '" target="_blank" rel="noopener">Open / download</a></p></div>';
  }

  function closeDetail() {
    currentSkillId = null;
    document.getElementById('skills-list-view').style.display = '';
    document.getElementById('skills-detail-view').classList.remove('active');
    renderList(document.getElementById('skills-search').value);
  }

  function load() {
    Promise.all([
      fetch('/api/settings/skills').then(function(r){ return r.json(); }).catch(function(){ return { enabled: true }; }),
      fetch('/api/skills').then(function(r){ return r.json(); }).catch(function(){ return { workspace: true, skills: [] }; })
    ]).then(function(res) {
      GLOBAL_ENABLED = !!res[0].enabled;
      HAS_WORKSPACE = res[1].workspace !== false;
      SKILLS = res[1].skills || [];
      applyGlobalState();
      renderList('');
    });
  }

  document.getElementById('skills-back-btn').addEventListener('click', closeDetail);

  var skillsSearch = document.getElementById('skills-search');
  if (skillsSearch) {
    skillsSearch.addEventListener('input', function(e) { renderList(e.target.value); });
  }

  load();
})();
