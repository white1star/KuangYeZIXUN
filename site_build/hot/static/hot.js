(function () {
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var search = document.getElementById('hot-search');
  var empty = document.getElementById('empty');
  var items = Array.prototype.slice.call(document.querySelectorAll('.hot-item, .top-item'));
  var cards = Array.prototype.slice.call(document.querySelectorAll('[data-card]'));
  var columns = document.querySelector('.columns');
  var columnCards = columns
    ? Array.prototype.slice.call(columns.querySelectorAll(':scope > .card'))
    : [];
  var activeCat = '全部';
  var cols = [];
  var resizeTimer = null;

  function columnCount() {
    var width = columns ? columns.clientWidth : 0;
    if (width >= 1120) return 4;
    if (width >= 820) return 3;
    if (width >= 540) return 2;
    return 1;
  }

  function buildColumns(count) {
    columns.classList.add('is-masonry');
    columns.innerHTML = '';
    cols = [];
    for (var i = 0; i < count; i += 1) {
      var col = document.createElement('div');
      col.className = 'mcol';
      columns.appendChild(col);
      cols.push(col);
    }
  }

  function layout() {
    if (!columns) return;
    var count = columnCount();
    if (cols.length !== count) buildColumns(count);

    var heights = cols.map(function () { return 0; });
    columnCards.forEach(function (card) {
      var target = 0;
      for (var i = 1; i < heights.length; i += 1) {
        if (heights[i] < heights[target]) target = i;
      }
      cols[target].appendChild(card);
      if (!card.hidden) heights[target] += card.offsetHeight + 14;
    });
  }

  function matches(el, query) {
    if (activeCat !== '全部' && el.getAttribute('data-category') !== activeCat) {
      return false;
    }
    if (query && el.textContent.toLowerCase().indexOf(query) === -1) {
      return false;
    }
    return true;
  }

  function apply() {
    var query = (search.value || '').trim().toLowerCase();
    var filtering = activeCat !== '全部' || !!query;
    var visible = 0;

    items.forEach(function (el) {
      var show = matches(el, query);
      el.hidden = !show;
      if (show) visible += 1;
    });

    cards.forEach(function (card) {
      if (!filtering || card.hasAttribute('data-keep')) {
        card.hidden = false;
        return;
      }
      var any = card.querySelector('.hot-item:not([hidden]), .top-item:not([hidden])');
      card.hidden = !any;
    });

    layout();
    empty.hidden = visible > 0;
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      activeCat = chip.getAttribute('data-cat') || '全部';
      chips.forEach(function (c) { c.classList.toggle('active', c === chip); });
      apply();
    });
  });

  var timer = null;
  search.addEventListener('input', function () {
    window.clearTimeout(timer);
    timer = window.setTimeout(apply, 120);
  });

  Array.prototype.slice.call(document.querySelectorAll('.word, .topic-word')).forEach(function (btn) {
    btn.addEventListener('click', function () {
      search.value = btn.getAttribute('data-word') || '';
      apply();
      var board = document.getElementById('board');
      if (board) board.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  window.addEventListener('resize', function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(layout, 150);
  });

  apply();
})();
