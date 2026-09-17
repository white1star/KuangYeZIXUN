(function () {
  var ESCAPES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return ESCAPES[ch];
    });
  }

  function highlight(text, query) {
    var safe = esc(text);
    if (!query) return safe;
    var target = esc(query).toLowerCase();
    if (!target) return safe;
    var lower = safe.toLowerCase();
    var out = '';
    var pos = 0;
    var idx = lower.indexOf(target);
    while (idx >= 0) {
      out += safe.slice(pos, idx) + '<mark>' + safe.slice(idx, idx + target.length) + '</mark>';
      pos = idx + target.length;
      idx = lower.indexOf(target, pos);
    }
    return out + safe.slice(pos);
  }

  function entryHtml(a, query) {
    var html = '<article class="entry">';
    html += '<a class="entry-title" href="' + esc(a.url) + '" target="_blank" rel="noopener">'
      + highlight(a.title, query) + '</a>';
    if (a.member_count && a.member_count > 1) {
      html += '<span class="repost">另有 ' + (a.member_count - 1) + ' 家转载</span>';
    }
    if (a.summary) html += '<p class="entry-summary">' + highlight(a.summary, query) + '</p>';
    html += '<div class="entry-meta"><span>' + esc(a.source_name) + '</span><span>'
      + esc(a.published_at) + '</span>';
    (a.minerals || []).forEach(function (m) {
      html += '<span class="chip chip-mineral">' + esc(m) + '</span>';
    });
    (a.types || []).forEach(function (t) {
      html += '<span class="chip chip-type-' + esc(t) + '">' + esc(t) + '</span>';
    });
    html += '</div></article>';
    return html;
  }

  function Feed(container, chunk) {
    this.container = container;
    this.chunk = chunk || 80;
    this.items = [];
    this.query = '';
    this.shown = 0;
    this.more = document.createElement('button');
    this.more.type = 'button';
    this.more.className = 'btn-primary load-more';
    this.more.textContent = '加载更多';
    this.more.hidden = true;
    container.parentNode.insertBefore(this.more, container.nextSibling);
    var self = this;
    this.more.addEventListener('click', function () { self.append(); });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        if (entries.some(function (entry) { return entry.isIntersecting; })) self.append();
      }, {rootMargin: '600px'}).observe(this.more);
    }
  }

  Feed.prototype.set = function (items, query) {
    this.items = items || [];
    this.query = query || '';
    this.shown = 0;
    this.container.innerHTML = '';
    this.append();
  };

  Feed.prototype.append = function () {
    if (this.shown >= this.items.length) {
      this.more.hidden = true;
      return;
    }
    var end = Math.min(this.shown + this.chunk, this.items.length);
    var html = '';
    for (var i = this.shown; i < end; i++) html += entryHtml(this.items[i], this.query);
    this.container.insertAdjacentHTML('beforeend', html);
    this.shown = end;
    this.more.hidden = this.shown >= this.items.length;
  };

  function loadJSON(url) {
    return fetch(url, {cache: 'no-cache'}).then(function (resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    });
  }

  window.App = {
    esc: esc,
    highlight: highlight,
    entryHtml: entryHtml,
    Feed: Feed,
    loadJSON: loadJSON
  };
})();
