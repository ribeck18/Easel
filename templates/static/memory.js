(function () {
  var list = document.getElementById('memory-list');
  var filterEl = document.getElementById('memory-filter');
  var noteTitle = document.getElementById('memory-note-title');
  var noteContent = document.getElementById('memory-note-content');

  var allNotes = [];
  var activeFilter = 'all';
  var noteMap = new Map();

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Mirror of the backend _slugify (services/consolidation.py): lowercase, every
  // non-alphanumeric run becomes a single hyphen, ends trimmed. Keeps frontend link
  // resolution in step with the slugs the consolidator writes.
  function slugify(text) {
    return String(text).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '');
  }

  function buildNoteMap(notes) {
    var map = new Map();
    notes.forEach(function(note) {
      var path = note.path || '';
      var base = path.replace(/^.*\//, '').replace(/\.md$/i, '');
      var entry = { path: path, title: note.title || base };
      // The filename slug is authoritative; only fall back to the title slug when it
      // doesn't collide, so [[Some Title]] resolves alongside [[some-title]].
      var pathSlug = slugify(base);
      if (pathSlug && !map.has(pathSlug)) map.set(pathSlug, entry);
      var titleSlug = slugify(note.title || '');
      if (titleSlug && !map.has(titleSlug)) map.set(titleSlug, entry);
    });
    return map;
  }

  // Pure (markdown string -> html string). Rewrites [[slug]], [[slug|alias]] and
  // [[slug#heading]] into anchors (resolved) or muted spans (dangling) before marked
  // runs. DOMPurify keeps class/data-*/href by default, so the markup survives sanitize.
  function linkifyWikilinks(markdown, map) {
    return String(markdown).replace(/\[\[([^\[\]]+?)\]\]/g, function(whole, inner) {
      var raw = inner.trim();
      var pipe = raw.indexOf('|');
      var target = (pipe >= 0 ? raw.slice(0, pipe) : raw).trim();
      var alias = pipe >= 0 ? raw.slice(pipe + 1).trim() : '';
      var hash = target.indexOf('#');
      var slugSource = (hash >= 0 ? target.slice(0, hash) : target).trim();
      var key = slugify(slugSource);
      if (!key) return whole;  // e.g. a bare [[#heading]] — leave untouched
      var hit = map.get(key);
      if (hit) {
        var label = alias || hit.title || slugSource;
        return '<a class="wikilink" href="#" data-path="' + esc(hit.path) + '">' + esc(label) + '</a>';
      }
      var missing = alias || slugSource.replace(/-/g, ' ');
      return '<span class="wikilink wikilink--missing" title="Note not found">' + esc(missing) + '</span>';
    });
  }

  function loadWiki() {
    fetch('/api/memory/wiki')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        allNotes = data.notes || [];
        noteMap = buildNoteMap(allNotes);
        renderNotes();
      })
      .catch(function() {
        list.innerHTML = '<div class="memory-empty">Could not load memory index.</div>';
      });
  }

  function renderNotes() {
    var notes = allNotes.filter(function(note) {
      if (activeFilter === 'all') return true;
      return String(note.path || '').indexOf(activeFilter + '/') === 0;
    });
    if (!notes.length) {
      list.innerHTML = '<div class="memory-empty">No notes in this view yet.</div>';
      return;
    }
    list.innerHTML = notes.map(function(note) {
      return '<button class="memory-list-item" data-path="' + esc(note.path) + '">'
        + '<span>' + esc(note.title) + '</span>'
        + '<small>' + esc(note.path) + '</small>'
        + '</button>';
    }).join('');
    list.querySelectorAll('.memory-list-item').forEach(function(button) {
      button.addEventListener('click', function() {
        loadNote(button.dataset.path, button.querySelector('span').textContent);
      });
    });
  }

  if (filterEl) {
    filterEl.querySelectorAll('.memory-filter-btn').forEach(function(button) {
      button.addEventListener('click', function() {
        activeFilter = button.dataset.filter;
        filterEl.querySelectorAll('.memory-filter-btn').forEach(function(b) {
          b.classList.toggle('active', b === button);
        });
        renderNotes();
      });
    });
  }

  if (noteContent) {
    noteContent.addEventListener('click', function(event) {
      var link = event.target.closest('.wikilink[data-path]');
      if (!link) return;
      event.preventDefault();
      loadNote(link.getAttribute('data-path'), link.textContent);
    });
  }

  function loadNote(path, title) {
    fetch('/api/memory/wiki/note?' + new URLSearchParams({ path: path }))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        noteTitle.textContent = title;
        noteContent.innerHTML = renderMarkdown(linkifyWikilinks(data.content || '', noteMap));
      });
  }

  loadWiki();
})();
