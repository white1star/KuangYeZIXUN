(function () {
  var search = document.getElementById('hot-search');
  var empty = document.getElementById('empty');
  var rows = Array.prototype.slice.call(document.querySelectorAll('.hot-item'));
  var words = Array.prototype.slice.call(document.querySelectorAll('.topic-word'));
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var activeCat = '全部';

  // ---- 瀑布流：把卡片放进当前最矮的列，紧凑不留空洞 ----
  var masonries = Array.prototype.slice.call(document.querySelectorAll('.masonry'));
  var state = [];

  function colCount(w) {
    if (w >= 1120) return 4;
    if (w >= 820) return 3;
    if (w >= 540) return 2;
    return 1;
  }

  function build(container, count) {
    container.classList.add('is-masonry');
    container.innerHTML = '';
    var cols = [];
    for (var i = 0; i < count; i += 1) {
      var col = document.createElement('div');
      col.className = 'mcol';
      container.appendChild(col);
      cols.push(col);
    }
    return cols;
  }

  function layoutOne(entry) {
    var count = colCount(entry.container.clientWidth || 1000);
    if (entry.cols.length !== count) entry.cols = build(entry.container, count);
    var visible = entry.cards.filter(function (c) { return !c.hidden; });
    // 先全塞进第一列，按「列宽」量出真实高度（直接在整宽容器里量会低估）
    entry.cols.forEach(function (col) { col.innerHTML = ''; });
    visible.forEach(function (c) { entry.cols[0].appendChild(c); });
    var sized = visible.map(function (c) { return { card: c, h: c.offsetHeight }; });
    // 高卡优先放进当前最短的列，列底最齐、留白最小
    sized.sort(function (a, b) { return b.h - a.h; });
    var heights = entry.cols.map(function () { return 0; });
    sized.forEach(function (item) {
      var target = 0;
      for (var i = 1; i < heights.length; i += 1) {
        if (heights[i] < heights[target]) target = i;
      }
      entry.cols[target].appendChild(item.card);
      heights[target] += item.h + 14;
    });
  }

  function layoutAll() {
    state.forEach(function (entry) {
      entry.cards.forEach(function (c) { entry.container.appendChild(c); });
      layoutOne(entry);
    });
  }

  masonries.forEach(function (container) {
    var entry = {
      container: container,
      cards: Array.prototype.slice.call(container.querySelectorAll(':scope > .card')),
      cols: []
    };
    state.push(entry);
  });

  // ---- 分类 / 关键词筛选 ----
  function matches(el, query) {
    if (activeCat !== '全部' && el.getAttribute('data-category') !== activeCat) return false;
    if (query && el.textContent.toLowerCase().indexOf(query) === -1) return false;
    return true;
  }

  function apply() {
    var query = (search && search.value || '').trim().toLowerCase();
    var filtering = activeCat !== '全部' || !!query;
    var visible = 0;

    rows.forEach(function (el) {
      var show = matches(el, query);
      el.hidden = !show;
      if (show) visible += 1;
    });

    // 无可见条目的卡片（非“常驻”卡）在筛选时隐藏
    state.forEach(function (entry) {
      entry.cards.forEach(function (card) {
        if (!filtering || card.hasAttribute('data-keep')) {
          card.hidden = false;
          return;
        }
        var any = card.querySelector('.hot-item:not([hidden])');
        card.hidden = !any;
      });
    });

    layoutAll();
    if (empty) empty.hidden = visible > 0;
  }

  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      activeCat = chip.getAttribute('data-cat') || '全部';
      chips.forEach(function (c) {
        var on = c === chip;
        c.classList.toggle('is-on', on);
        c.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      apply();
    });
  });

  words.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (!search) return;
      search.value = btn.getAttribute('data-word') || '';
      apply();
      var board = document.getElementById('board-top');
      if (board) board.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  if (search) {
    var timer = null;
    search.addEventListener('input', function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(apply, 120);
    });
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(layoutAll, 150);
  });

  apply();
  window.addEventListener('load', layoutAll);
})();
