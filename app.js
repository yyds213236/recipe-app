/* ===========================================================
   小锅菜谱 · 交互逻辑
   纯前端、零依赖、离线可用。数据来自 data.js 的 window.RECIPE_DB
   =========================================================== */
(function () {
  'use strict';

  var DB = window.RECIPE_DB || { ingredients: [], recipes: [], categories: [], tags: [] };
  var ING = DB.ingredients;
  var RECIPES = DB.recipes;
  var CATEGORIES = DB.categories || [];
  var TAGS = DB.tags || [];

  var ingById = {};
  ING.forEach(function (i) { ingById[i.id] = i; });
  var recById = {};
  RECIPES.forEach(function (r) { recById[r.id] = r; });

  var SEASONING = '调料';

  /* ---------- 图片（images-data.js，缺图时全部回退 emoji） ---------- */
  var IMGS = window.RECIPE_IMAGES || {};
  function photo(kind, id) {
    var e = IMGS[kind + ':' + id];
    return e && e.file ? e : null;
  }
  function imgTag(entry, cls, alt, eager) {
    return '<img class="' + cls + '" src="' + esc(entry.file) + '" alt="' + esc(alt || entry.title || '') +
      '" loading="' + (eager ? 'eager' : 'lazy') + '" decoding="async" draggable="false">';
  }
  function creditText(entry) {
    var bits = [];
    if (entry.title) bits.push(entry.title);
    if (entry.author) bits.push(entry.author);
    if (entry.license) bits.push(entry.license);
    return bits.join(' · ');
  }

  /* ---------- 本地存储 ---------- */
  var store = {
    get: function (k, d) {
      try {
        var v = localStorage.getItem(k);
        return v == null ? d : JSON.parse(v);
      } catch (e) { return d; }
    },
    set: function (k, v) {
      try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
    }
  };

  /* ---------- 状态 ---------- */
  var state = {
    sel: new Set(),
    basket: new Set(),
    search: '',
    tag: '全部',
    cat: '全部',
    pantryOpen: false,
    includeSeasoning: store.get('rcp.season', false),
    apiKey: store.get('rcp.apikey', ''),
    route: 'home',
    lastBase: 'home',
    ingredientChecks: {},
    stepDone: {},
    creditsQ: ''
  };
  (store.get('rcp.sel', []) || []).forEach(function (id) { if (ingById[id]) state.sel.add(id); });
  (store.get('rcp.basket', []) || []).forEach(function (id) { if (recById[id]) state.basket.add(id); });

  function persistSel() { store.set('rcp.sel', Array.from(state.sel)); }
  function persistBasket() { store.set('rcp.basket', Array.from(state.basket)); }

  /* ---------- 工具 ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function h(html) {
    var t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtAmt(n) {
    var v = Math.round(n * 100) / 100;
    if (Math.abs(v - Math.round(v)) < 0.001) return String(Math.round(v));
    return String(v);
  }
  function norm(s) {
    return String(s || '').toLowerCase().replace(/\s+/g, '').replace(/[·・]/g, '');
  }
  var DIFF = { 1: ['简单', '●○○'], 2: ['中等', '●●○'], 3: ['进阶', '●●●'] };
  function diffText(d) { return (DIFF[d] || DIFF[1])[0]; }
  function diffDots(d) { return (DIFF[d] || DIFF[1])[1]; }

  var toastEl = null, toastTimer = 0;
  function toast(msg) {
    if (!toastEl) {
      toastEl = h('<div class="toast" role="status" aria-live="polite"></div>');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, 1900);
  }

  /* ---------- 搜索索引（菜名 + 食材名 + 别名） ---------- */
  var searchText = {};
  RECIPES.forEach(function (r) {
    var parts = [r.name, r.cuisine].concat(r.tags || []);
    (r.ingredients || []).forEach(function (g) {
      var ing = ingById[g.id];
      if (!ing) return;
      parts.push(ing.name);
      if (ing.alias) parts = parts.concat(ing.alias);
    });
    searchText[r.id] = norm(parts.join(' '));
  });
  function recipeMatches(r, q) {
    if (!q) return true;
    return (searchText[r.id] || '').indexOf(q) !== -1;
  }

  /* ---------- 缺失计算 ---------- */
  function missingOf(r) {
    var miss = [];
    (r.ingredients || []).forEach(function (g) {
      if (g.optional) return;                      // 可选配料不算缺
      var ing = ingById[g.id];
      if (!ing) return;
      if (!state.includeSeasoning && ing.category === SEASONING) return; // 调料默认不计
      if (!state.sel.has(g.id)) miss.push(ing.name);
    });
    return miss;
  }

  /* ---------- 路由 ---------- */
  function parseRoute() {
    var raw = (location.hash || '').replace(/^#\/?/, '');
    var qi = raw.indexOf('?');
    var path = qi >= 0 ? raw.slice(0, qi) : raw;
    var qs = qi >= 0 ? raw.slice(qi + 1) : '';
    var params = {};
    qs.split('&').forEach(function (kv) {
      if (!kv) return;
      var p = kv.split('=');
      params[decodeURIComponent(p[0])] = decodeURIComponent((p[1] || '').replace(/\+/g, ' '));
    });

    // 可分享/便于截图的状态参数
    if (params.sel !== undefined) {
      state.sel.clear();
      params.sel.split(',').forEach(function (id) { if (ingById[id.trim()]) state.sel.add(id.trim()); });
      persistSel();
    }
    if (params.basket !== undefined) {
      state.basket.clear();
      params.basket.split(',').forEach(function (id) { if (recById[id.trim()]) state.basket.add(id.trim()); });
      persistBasket();
    }
    if (params.q !== undefined) state.search = params.q;
    if (params.tag !== undefined) state.tag = params.tag;
    if (params.season !== undefined) state.includeSeasoning = params.season === '1';
    if (params.merge !== undefined) state.mergeDemo = params.merge === '1';

    var seg = path.split('/').filter(Boolean);
    if (!seg.length) return { name: 'home' };
    if (seg[0] === 'recipe' && seg[1]) return { name: 'detail', id: seg[1] };
    if (seg[0] === 'pantry') return { name: 'pantry' };
    if (seg[0] === 'result') return { name: 'result' };
    if (seg[0] === 'basket') return { name: 'basket' };
    if (seg[0] === 'credits') return { name: 'credits' };
    return { name: 'home' };
  }

  function go(hash) {
    if (location.hash === hash) render();
    else location.hash = hash;
  }

  /* ---------- 底部 tab ---------- */
  function renderTabs(active) {
    var el = $('#tabbar');
    var items = [
      { k: 'home', href: '#/', label: '菜谱', ico: '🍳' },
      { k: 'pantry', href: '#/pantry', label: '食材', ico: '🧺' },
      { k: 'basket', href: '#/basket', label: '我的菜篮', ico: '🧡' }
    ];
    el.innerHTML = items.map(function (it) {
      var on = active === it.k ? ' aria-current="page"' : '';
      var badge = it.k === 'basket' && state.basket.size
        ? '<span class="tab-badge">' + state.basket.size + '</span>' : '';
      return '<a class="tab" href="' + it.href + '"' + on + '>' +
        '<span class="tab-ico">' + it.ico + '</span>' +
        '<span>' + it.label + '</span>' + badge + '</a>';
    }).join('');
  }

  /* =========================================================
     菜谱首页
     ========================================================= */
  var homeShell = null;

  function renderHome() {
    renderTabs('home');
    var view = $('#view');
    view.innerHTML = '';

    var hero = h(
      '<section class="hero">' +
        '<div class="hero-kicker">家里有什么 · 就做什么</div>' +
        '<h1 class="hero-title">今天吃点什么？</h1>' +
        '<p class="hero-sub">共 <b>' + RECIPES.length + '</b> 道家常菜 · <b>' + ING.length + '</b> 种食材，全部离线可用</p>' +
      '</section>'
    );
    view.appendChild(hero);

    var search = h(
      '<div class="search">' +
        '<label class="search-box">' +
          '<span class="ico">🔍</span>' +
          '<input id="q" type="search" inputmode="search" autocomplete="off" enterkeyhint="search" ' +
            'placeholder="搜菜名或食材，如 西红柿" value="' + esc(state.search) + '" aria-label="搜索菜名或食材">' +
          '<span class="kbd-hint">/</span>' +
        '</label>' +
      '</div>'
    );
    view.appendChild(search);

    var chips = h('<div class="chips" role="group" aria-label="菜谱分类"></div>');
    ['全部'].concat(TAGS).forEach(function (t) {
      var b = h('<button class="chip" type="button" aria-pressed="' + (state.tag === t) + '">' + t + '</button>');
      b.addEventListener('click', function () {
        state.tag = t;
        Array.prototype.forEach.call(chips.children, function (c) {
          c.setAttribute('aria-pressed', String(c.textContent === t));
        });
        updateHomeGrid();
      });
      chips.appendChild(b);
    });
    view.appendChild(chips);

    var head = h('<div class="section-head"><h2>全部菜谱</h2><span class="count" id="home-count"></span></div>');
    view.appendChild(head);
    var grid = h('<div class="grid" id="home-grid"></div>');
    view.appendChild(grid);

    view.appendChild(h(
      '<div class="home-foot"><a href="#/credits">🖼 图片来源与许可（维基百科 / 维基共享资源）→</a></div>'
    ));

    var q = $('#q', view);
    q.addEventListener('input', function () {
      state.search = q.value;
      updateHomeGrid();
    });

    updateHomeGrid();
  }

  function currentHomeList() {
    var q = norm(state.search);
    return RECIPES.filter(function (r) {
      if (state.tag !== '全部' && (r.tags || []).indexOf(state.tag) === -1) return false;
      return recipeMatches(r, q);
    });
  }

  function updateHomeGrid() {
    var grid = $('#home-grid');
    if (!grid) return;
    var list = currentHomeList();
    var count = $('#home-count');
    if (count) count.textContent = list.length + ' 道';

    if (!list.length) {
      grid.style.display = 'block';
      grid.innerHTML = '<div class="empty"><span class="big">🍽️</span>' +
        '没找到「<b>' + esc(state.search) + '</b>」相关的菜<br>换个食材名试试，比如番茄、土豆、鸡蛋</div>';
      return;
    }
    grid.style.display = '';
    var html = list.map(function (r) {
      var badge = '';
      if (state.sel.size) {
        var m = missingOf(r).length;
        badge = m === 0
          ? '<span class="card-badge">可做</span>'
          : '<span class="card-badge g1">缺 ' + m + '</span>';
      }
      var pic = photo('recipe', r.id);
      return '<button class="card' + (pic ? ' has-photo' : '') + '" type="button" data-id="' + r.id + '">' +
        badge +
        (pic
          ? '<span class="card-photo">' + imgTag(pic, 'card-img', r.name + ' 的照片') + '</span>'
          : '<span class="card-emoji">' + r.emoji + '</span>') +
        '<span class="card-body">' +
          '<span class="card-name">' + esc(r.name) + '</span>' +
          '<span class="card-meta">' +
            '<span>⏱ ' + r.time + ' 分钟</span><i>·</i>' +
            '<span class="d' + r.difficulty + '">' + diffText(r.difficulty) + '</span><i>·</i>' +
            '<span>' + r.ingredients.length + ' 样</span>' +
          '</span>' +
        '</span>' +
      '</button>';
    }).join('');
    grid.innerHTML = html;
  }

  /* =========================================================
     食材页（多选反查）
     ========================================================= */
  function renderPantry() {
    renderTabs('pantry');
    var view = $('#view');
    view.innerHTML = '';

    view.appendChild(h(
      '<section class="hero">' +
        '<div class="hero-kicker">冰箱里有什么，就选什么</div>' +
        '<h1 class="hero-title">挑几样食材</h1>' +
        '<p class="hero-sub">选好后，帮你算出哪些菜只差一两样</p>' +
      '</section>'
    ));

    var search = h(
      '<div class="search">' +
        '<label class="search-box">' +
          '<span class="ico">🔍</span>' +
          '<input id="pq" type="search" inputmode="search" enterkeyhint="search" autocapitalize="off" spellcheck="false" autocomplete="off" placeholder="搜食材，如 土豆 / 洋芋" ' +
            'value="" aria-label="搜索食材">' +
          '<span class="kbd-hint">/</span>' +
        '</label>' +
      '</div>'
    );
    view.appendChild(search);

    // 已选横条
    var selBar = h('<div class="pantry-selected' + (state.pantryOpen ? ' open' : '') + '" id="ps"></div>');
    view.appendChild(selBar);
    renderSelBar();

    var cats = h('<div class="cat-tabs" role="tablist" aria-label="食材分类"></div>');
    ['全部'].concat(CATEGORIES).forEach(function (c) {
      var b = h('<button class="cat-tab" role="tab" type="button" aria-selected="' + (state.cat === c) + '">' + c + '</button>');
      b.addEventListener('click', function () {
        state.cat = c;
        Array.prototype.forEach.call(cats.children, function (n) {
          n.setAttribute('aria-selected', String(n.textContent === c));
        });
        renderIngredientList();
      });
      cats.appendChild(b);
    });
    view.appendChild(cats);

    var list = h('<div id="ing-list"></div>');
    view.appendChild(list);
    view.appendChild(h('<div style="height:66px" aria-hidden="true"></div>'));

    var cta = h(
      '<div class="pantry-cta">' +
        '<button class="btn-primary" id="go-result" type="button">' +
          '看看能做什么 <span class="sub" id="cta-sub"></span>' +
        '</button>' +
      '</div>'
    );
    view.appendChild(cta);

    var pq = $('#pq', view);
    pq.addEventListener('input', renderIngredientList);
    $('#go-result', cta).addEventListener('click', function () {
      if (!state.sel.size) { toast('先选几样食材吧'); pq.focus(); return; }
      go('#/result');
    });

    renderIngredientList();
    updateCta();
  }

  function renderSelBar() {
    var bar = $('#ps');
    if (!bar) return;
    var names = Array.from(state.sel).map(function (id) { return ingById[id] ? ingById[id].name : id; });
    var pills = names.map(function (n, idx) {
      var id = Array.from(state.sel)[idx];
      return '<span class="sel-pill">' + esc(n) +
        '<button type="button" data-remove="' + id + '" aria-label="移除' + esc(n) + '">✕</button></span>';
    }).join('');

    bar.innerHTML =
      '<button class="ps-bar" type="button" id="ps-toggle">' +
        '<span class="ps-count">已选 ' + names.length + ' 种</span>' +
        '<span class="ps-hint">' + (names.length ? esc(names.slice(0, 3).join('、')) + (names.length > 3 ? '…' : '') : '点下方食材加入') + '</span>' +
        '<span class="ps-caret">▾</span>' +
      '</button>' +
      '<div class="ps-list">' + (pills || '<span class="ps-hint">还没选任何食材</span>') +
        '<button class="ps-clear" type="button" id="ps-clear">清空</button>' +
      '</div>';

    $('#ps-toggle', bar).addEventListener('click', function () {
      state.pantryOpen = !state.pantryOpen;
      bar.classList.toggle('open', state.pantryOpen);
    });
    $('#ps-clear', bar).addEventListener('click', function () {
      state.sel.clear();
      persistSel();
      renderSelBar();
      renderIngredientList();
      updateCta();
      toast('已清空');
    });
    Array.prototype.forEach.call(bar.querySelectorAll('[data-remove]'), function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        state.sel.delete(btn.getAttribute('data-remove'));
        persistSel();
        renderSelBar();
        renderIngredientList();
        updateCta();
      });
    });
  }

  function updateCta() {
    var sub = $('#cta-sub');
    if (!sub) return;
    var btn = $('#go-result');
    sub.textContent = state.sel.size ? '（' + state.sel.size + '）' : '';
    btn.disabled = false;
  }

  function renderIngredientList() {
    var list = $('#ing-list');
    if (!list) return;
    var q = norm($('#pq') ? $('#pq').value : '');

    var pool = ING.filter(function (i) {
      if (state.cat !== '全部' && i.category !== state.cat) return false;
      if (!q) return true;
      var s = norm(i.name + ' ' + (i.alias || []).join(' '));
      return s.indexOf(q) !== -1;
    });

    if (!pool.length) {
      list.innerHTML = '<div class="empty"><span class="big">🥄</span>没有找到这个食材<br>换个常见叫法再试试</div>';
      return;
    }

    // 按分类分组
    var groups = {};
    pool.forEach(function (i) {
      (groups[i.category] = groups[i.category] || []).push(i);
    });
    var order = CATEGORIES.filter(function (c) { return groups[c]; });
    Object.keys(groups).forEach(function (c) { if (order.indexOf(c) === -1) order.push(c); });

    list.innerHTML = order.map(function (cat) {
      var items = groups[cat].map(function (i) {
        var on = state.sel.has(i.id);
        var pic = photo('ingredient', i.id);
        return '<button class="ing" type="button" data-id="' + i.id + '" aria-pressed="' + on + '">' +
          (pic
            ? '<span class="e e-photo">' + imgTag(pic, 'ing-img', i.name) + '</span>'
            : '<span class="e">' + i.emoji + '</span>') +
          '<span class="t">' + esc(i.name) + '</span>' +
        '</button>';
      }).join('');
      return '<section class="ing-group"><h3>' + esc(cat) + ' · ' + groups[cat].length + '</h3>' +
        '<div class="ing-grid">' + items + '</div></section>';
    }).join('');
  }

  // 事件委托：食材选中
  document.addEventListener('click', function (e) {
    var ing = e.target.closest && e.target.closest('.ing');
    if (ing && state.route === 'pantry') {
      var id = ing.getAttribute('data-id');
      if (state.sel.has(id)) state.sel.delete(id); else state.sel.add(id);
      persistSel();
      ing.setAttribute('aria-pressed', String(state.sel.has(id)));
      renderSelBar();
      updateCta();
      return;
    }
    var card = e.target.closest && e.target.closest('.card, .res-card');
    if (card && card.getAttribute('data-id')) {
      go('#/recipe/' + card.getAttribute('data-id'));
    }
  });

  /* =========================================================
     反查结果页
     ========================================================= */
  function renderResult() {
    renderTabs('pantry');
    var view = $('#view');
    view.innerHTML = '';

    var calc = RECIPES.map(function (r) {
      return { r: r, miss: missingOf(r) };
    }).sort(function (a, b) {
      if (a.miss.length !== b.miss.length) return a.miss.length - b.miss.length;
      return a.r.time - b.r.time;
    });

    var ready = calc.filter(function (x) { return x.miss.length === 0; });
    var one = calc.filter(function (x) { return x.miss.length === 1; });
    var more = calc.filter(function (x) { return x.miss.length >= 2; });

    var names = Array.from(state.sel).map(function (id) { return ingById[id] ? ingById[id].name : id; });

    var head = h(
      '<section class="result-head">' +
        '<h2>能做什么？</h2>' +
        '<p>已选 <span class="stat">' + state.sel.size + '</span> 种食材' +
          (names.length ? '（' + esc(names.join('、')) + '）' : '') +
          '，可做 <span class="stat">' + ready.length + '</span> 道菜</p>' +
        '<p style="margin-top:4px;font-size:12px;color:var(--ink-3)">' +
          (one.length ? '另有 ' + one.length + ' 道只差 1 样' : '') +
          (one.length && more.length ? ' · ' : '') +
          (more.length ? more.length + ' 道差 2 样以上' : '') +
        '</p>' +
        '<div class="result-tools">' +
          '<label class="switch">' +
            '<input type="checkbox" id="season-toggle"' + (state.includeSeasoning ? ' checked' : '') + '>' +
            '<span class="track"></span>' +
            '<span>把调料也算上</span>' +
          '</label>' +
          '<button class="btn-ghost" type="button" id="ai-btn">✨ 让 AI 帮我搭一桌</button>' +
        '</div>' +
      '</section>'
    );
    view.appendChild(head);

    if (!state.sel.size) {
      view.appendChild(h(
        '<div class="empty"><span class="big">🧺</span>还没选食材<br>' +
        '<a href="#/pantry">去食材页挑几样 →</a></div>'
      ));
      return;
    }

    view.appendChild(h(
      '<div class="result-bar">' +
        '<button class="btn-ghost" type="button" id="back-pantry">← 修改食材</button>' +
        '<span class="inline-hint">调料默认不计入缺失</span>' +
      '</div>'
    ));

    function group(title, arr, pillCls, pillText, hint) {
      if (!arr.length) return '';
      var cards = arr.slice(0, 40).map(function (x) {
        var r = x.r;
        var missHtml = x.miss.length
          ? '<div class="miss-row"><span class="miss-label">缺：</span>' +
            x.miss.slice(0, 8).map(function (n) { return '<span class="miss">' + esc(n) + '</span>'; }).join('') +
            (x.miss.length > 8 ? '<span class="miss">+' + (x.miss.length - 8) + '</span>' : '') +
            '</div>'
          : '<div class="ready-note">✓ 食材齐全，现在就能做</div>';
        var rpic = photo('recipe', r.id);
        return '<button class="res-card" type="button" data-id="' + r.id + '">' +
          '<span class="res-emoji' + (rpic ? ' has-photo' : '') + '">' +
            (rpic ? imgTag(rpic, 'res-img', r.name) : r.emoji) +
          '</span>' +
          '<span class="res-body">' +
            '<span class="res-name">' + esc(r.name) + '</span>' +
            '<span class="res-meta"><span>⏱ ' + r.time + ' 分钟</span><span>🔥 ' + diffText(r.difficulty) +
              '</span><span>' + esc(r.cuisine) + '</span></span>' +
            '<span class="tags-row">' + (r.tags || []).map(function (t) {
              return '<span class="mini-tag">' + esc(t) + '</span>';
            }).join('') + '</span>' +
            missHtml +
          '</span>' +
        '</button>';
      }).join('');
      return '<section class="res-group"><div class="res-group-head">' +
        '<h3>' + title + '</h3><span class="pill ' + pillCls + '">' + pillText + '</span>' +
        (hint ? '<span style="font-size:11.5px;color:var(--ink-3)">' + hint + '</span>' : '') +
        '</div>' + cards + '</section>';
    }

    var body = '';
    body += group('现在就能做', ready, 'ok', '缺 0', '');
    body += group('差 1 样', one, '', '差 1', '买一样就能上桌');
    if (more.length) body += group('差 2 样以上', more, 'warn', '差 2+', '先放着，慢慢凑');

    if (!ready.length && !one.length) {
      body = '<div class="empty-soft"><span class="big">🍲</span>' +
        '<div>再多选两样，能解锁更多菜</div>' +
        '<div class="dim" style="font-size:12.5px;margin-top:4px">' +
          '现在的食材还凑不齐一道完整的菜' +
          (more.length ? ' · 最接近的是「' + esc(more[0].r.name) + '」，差 ' + more[0].miss.length + ' 样' : '') +
        '</div>' +
      '</div>' + body;
    }

    var wrap = h('<div>' + body + '</div>');
    view.appendChild(wrap);

    $('#season-toggle').addEventListener('change', function (e) {
      state.includeSeasoning = e.target.checked;
      store.set('rcp.season', state.includeSeasoning);
      renderResult();
    });
    $('#back-pantry').addEventListener('click', function () { go('#/pantry'); });
    $('#ai-btn').addEventListener('click', function () {
      openAiModal(ready.concat(one, more).slice(0, 3), ready, one, more);
    });
  }

  /* =========================================================
     我的菜篮
     ========================================================= */
  function renderBasket() {
    renderTabs('basket');
    var view = $('#view');
    view.innerHTML = '';

    view.appendChild(h(
      '<section class="hero">' +
        '<div class="hero-kicker">想做的菜，先放篮子里</div>' +
        '<h1 class="hero-title">我的菜篮</h1>' +
        '<p class="hero-sub">收藏 ' + state.basket.size + ' 道菜 · 可合并成一张采购清单</p>' +
      '</section>'
    ));

    if (!state.basket.size) {
      view.appendChild(h(
        '<div class="empty"><span class="big">🧺</span>菜篮还是空的<br>' +
        '在菜谱详情里点「加入我的菜篮」<br><a href="#/">去逛逛菜谱 →</a></div>'
      ));
      return;
    }

    var ids = Array.from(state.basket);
    view.appendChild(h(
      '<div class="basket-actions">' +
        '<button class="btn-primary" type="button" id="merge-btn">合并食材清单</button>' +
        '<button class="btn-secondary" type="button" id="clear-btn">清空菜篮</button>' +
      '</div>'
    ));

    var listHtml = ids.map(function (id) {
      var r = recById[id];
      if (!r) return '';
      var bpic = photo('recipe', r.id);
      return '<div class="basket-item">' +
        '<span class="res-emoji' + (bpic ? ' has-photo' : '') + '">' +
          (bpic ? imgTag(bpic, 'res-img', r.name) : r.emoji) +
        '</span>' +
        '<div class="res-body" data-id="' + r.id + '">' +
          '<div class="res-name">' + esc(r.name) + '</div>' +
          '<div class="res-meta"><span>⏱ ' + r.time + ' 分钟</span><span>🔥 ' + diffText(r.difficulty) +
            '</span><span>' + r.ingredients.length + ' 样食材</span></div>' +
        '</div>' +
        '<button class="bi-remove" type="button" data-rm="' + r.id + '" aria-label="从菜篮移除' + esc(r.name) + '">✕</button>' +
      '</div>';
    }).join('');
    var list = h('<div id="basket-list">' + listHtml + '<div id="shop-root"></div></div>');
    view.appendChild(list);

    Array.prototype.forEach.call(list.querySelectorAll('.bi-remove'), function (b) {
      b.addEventListener('click', function () {
        state.basket.delete(b.getAttribute('data-rm'));
        persistBasket();
        renderBasket();
      });
    });
    Array.prototype.forEach.call(list.querySelectorAll('.res-body'), function (b) {
      b.addEventListener('click', function () { go('#/recipe/' + b.getAttribute('data-id')); });
    });

    $('#merge-btn').addEventListener('click', function () { renderShopping(); });
    if (state.mergeDemo) {
      state.mergeDemo = false;
      renderShopping(true);   // demo/截图模式：不自动滚动，保留菜篮区
    }
    $('#clear-btn').addEventListener('click', function () {
      state.basket.clear();
      persistBasket();
      renderBasket();
      toast('菜篮已清空');
    });
  }

  function mergedShopping() {
    var map = {};
    var order = {};
    Array.from(state.basket).forEach(function (rid) {
      var r = recById[rid];
      if (!r) return;
      (r.ingredients || []).forEach(function (g) {
        if (g.optional) return;
        var ing = ingById[g.id];
        if (!ing) return;
        var key = g.id + '|' + g.unit;
        if (!map[key]) map[key] = { id: g.id, unit: g.unit, amount: 0, ing: ing };
        map[key].amount += Number(g.amount) || 0;
        order[key] = 1;
      });
    });
    return Object.keys(map).map(function (k) { return map[k]; }).sort(function (a, b) {
      var ca = CATEGORIES.indexOf(a.ing.category), cb = CATEGORIES.indexOf(b.ing.category);
      if (ca !== cb) return ca - cb;
      return a.ing.name.localeCompare(b.ing.name, 'zh');
    });
  }

  function renderShopping(noScroll) {
    var root = $('#shop-root');
    if (!root) return;
    var items = mergedShopping();
    var html = items.map(function (it) {
      return '<div class="shop-line"><span>' + it.ing.emoji + ' ' + esc(it.ing.name) +
        '<span class="cat">' + esc(it.ing.category) + '</span></span>' +
        '<span class="amt">' + fmtAmt(it.amount) + ' ' + esc(it.unit) + '</span></div>';
    }).join('');

    root.innerHTML =
      '<div class="shopping">' +
        '<h4>🧾 采购清单 · 共 ' + items.length + ' 项（同名同单位已合并）</h4>' +
        html +
        '<div class="basket-actions">' +
          '<button class="btn-primary" type="button" id="copy-btn">复制清单</button>' +
        '</div>' +
      '</div>';

    $('#copy-btn').addEventListener('click', function () {
      var text = '采购清单（' + state.basket.size + ' 道菜）\n' +
        items.map(function (it) {
          return '· ' + it.ing.name + ' ' + fmtAmt(it.amount) + ' ' + it.unit;
        }).join('\n') + '\n共 ' + items.length + ' 项';
      copyText(text);
    });
    if (!noScroll) root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function copyText(text) {
    var done = function () { toast('已复制到剪贴板'); };
    var fail = function () {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta);
      toast(ok ? '已复制到剪贴板' : '复制失败，请手动选择文本');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fail);
    } else fail();
  }

  /* ---------- 分享：系统分享面板 → 不支持就复制链接 ---------- */
  function shareUrlFor(id) {
    var base = (location.origin && location.origin !== 'null')
      ? location.origin + location.pathname
      : location.href.split('#')[0];   // file:// 下 origin 是 null，退回当前文件路径
    return base + '#/recipe/' + id;
  }

  function bindShare(sheet, r) {
    var btn = $('#share-recipe', sheet);
    if (!btn) return;
    btn.addEventListener('click', function () {
      var url = shareUrlFor(r.id);
      var title = r.name + ' · 小锅菜谱';
      var text = '今晚做这道：' + r.name + '，' + r.time + ' 分钟';
      if (navigator.share) {
        navigator.share({ title: title, text: text, url: url }).catch(function (err) {
          if (err && err.name === 'AbortError') return;   // 用户自己取消的，不打扰
          copyText(title + ' ' + url);
        });
        return;
      }
      copyText(title + ' ' + url);
    });
  }

  /* =========================================================
     菜谱详情 Sheet
     ========================================================= */
  var sheetEls = null;
  var timer = { total: 0, left: 0, id: 0, ctx: null };

  function closeSheet() {
    if (!sheetEls) return;
    stopTimer();
    var mask = sheetEls.mask, sheet = sheetEls.sheet;
    mask.classList.remove('show');
    sheet.classList.remove('show');
    var els = sheetEls;
    sheetEls = null;
    setTimeout(function () {
      if (els.mask.parentNode) els.mask.parentNode.removeChild(els.mask);
      if (els.sheet.parentNode) els.sheet.parentNode.removeChild(els.sheet);
    }, 300);
  }

  function openDetail(id) {
    var r = recById[id];
    if (!r) { toast('找不到这道菜'); return; }
    var pic = photo('recipe', r.id);
    closeSheet();

    var mains = [], seasons = [];
    (r.ingredients || []).forEach(function (g) {
      var ing = ingById[g.id];
      if (!ing) return;
      var item = { g: g, ing: ing };
      if (ing.category === SEASONING) seasons.push(item); else mains.push(item);
    });

    var mask = h('<div class="sheet-mask"></div>');
    var sheet = h(
      '<section class="sheet" role="dialog" aria-modal="true" aria-label="' + esc(r.name) + '">' +
        '<div class="sheet-grab"><i></i></div>' +
        (pic
          ? '<figure class="detail-photo">' + imgTag(pic, 'detail-img', r.name + ' 的照片', true) +
            '<figcaption class="photo-credit">📷 ' + esc(creditText(pic)) +
              ' · <a href="#/credits">来源</a></figcaption></figure>'
          : '') +
        '<header class="sheet-head' + (pic ? ' no-emoji' : '') + '">' +
          (pic ? '' : '<div class="sh-emoji">' + r.emoji + '</div>') +
          '<div class="sh-main">' +
            '<div class="sh-name">' + esc(r.name) + '</div>' +
            '<div class="sh-tags">' +
              '<span class="sh-tag">⏱ ' + r.time + ' 分钟</span>' +
              '<span class="sh-tag">🔥 ' + diffText(r.difficulty) + ' ' + diffDots(r.difficulty) + '</span>' +
              '<span class="sh-tag">🍽 ' + r.servings + ' 人份</span>' +
              '<span class="sh-tag">' + esc(r.cuisine) + '</span>' +
            '</div>' +
          '</div>' +
          '<button class="sh-close" type="button" id="sh-timer" aria-label="计时器">⏱</button>' +
          '<button class="sh-close" type="button" id="sh-close" aria-label="关闭">✕</button>' +
        '</header>' +
        '<div class="sheet-body">' +
          '<div class="block" id="timer-block" hidden>' +
            '<div class="timer">' +
              '<div class="timer-row">' +
                '<span class="timer-display" id="t-display" role="timer" aria-live="off">00:00</span>' +
                '<span class="sr-only" id="t-live" role="status" aria-live="polite"></span>' +
                '<button class="tbtn" type="button" id="t-start">开始</button>' +
                '<button class="tbtn" type="button" id="t-reset">重置</button>' +
                '<span style="font-size:11.5px;color:var(--ink-3);margin-left:auto">到点会响一声</span>' +
              '</div>' +
              '<div class="timer-presets">' +
                [1, 3, 5, 10, 15].map(function (m) {
                  return '<button class="tbtn" type="button" data-min="' + m + '">' + m + ' 分钟</button>';
                }).join('') +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="block">' +
            '<div class="block-head"><h3>食材</h3><span class="dim" id="ing-progress">0/' + mains.length + '</span></div>' +
            '<div class="ing-list" id="mains-list"></div>' +
          '</div>' +
          (seasons.length ?
          '<div class="block">' +
            '<div class="block-head"><h3>调料</h3><span class="dim">' + seasons.length + ' 样</span></div>' +
            '<div class="ing-list" id="seasons-list"></div>' +
          '</div>' : '') +
          '<div class="block">' +
            '<div class="block-head">' +
              '<h3>做法</h3>' +
              '<span class="dim">' + r.steps.length + ' 步</span>' +
              '<button class="btn-ghost" type="button" id="next-step" style="margin-left:auto">下一步 →</button>' +
            '</div>' +
            '<div class="steps" id="steps"></div>' +
          '</div>' +
        '</div>' +
        '<footer class="sheet-foot">' +
          '<button class="btn-primary" type="button" id="add-basket">' +
            (state.basket.has(r.id) ? '已在菜篮 · 移出' : '加入我的菜篮') +
          '</button>' +
          '<button class="icon-btn" type="button" id="share-recipe" aria-label="分享这道菜">📤</button>' +
        '</footer>' +
      '</section>'
    );

    document.body.appendChild(mask);
    document.body.appendChild(sheet);
    sheetEls = { mask: mask, sheet: sheet, recipe: r };
    void sheet.offsetWidth;
    mask.classList.add('show');
    sheet.classList.add('show');

    mask.addEventListener('click', closeSheet);
    $('#sh-close', sheet).addEventListener('click', closeSheet);
    $('#sh-timer', sheet).addEventListener('click', toggleTimerBlock);
    bindShare(sheet, r);

    // 食材清单
    function renderIngList(container, items, prefix) {
      container.innerHTML = items.map(function (it) {
        var key = prefix + ':' + it.g.id;
        var on = !!state.ingredientChecks[key];
        return '<button class="ing-row" type="button" aria-checked="' + on + '" data-key="' + key + '">' +
          '<span class="ing-check">✓</span>' +
          '<span class="nm">' + esc(it.ing.name) +
            (it.g.optional ? '<small>可选</small>' : '') +
          '</span>' +
          '<span class="qt">' + fmtAmt(it.g.amount) + ' ' + esc(it.g.unit) + '</span>' +
        '</button>';
      }).join('');
      Array.prototype.forEach.call(container.querySelectorAll('.ing-row'), function (btn) {
        btn.addEventListener('click', function () {
          var k = btn.getAttribute('data-key');
          state.ingredientChecks[k] = !state.ingredientChecks[k];
          btn.setAttribute('aria-checked', String(!!state.ingredientChecks[k]));
          updateIngProgress();
        });
      });
    }
    function updateIngProgress() {
      var done = mains.filter(function (it) { return state.ingredientChecks['main:' + it.g.id]; }).length;
      var el = $('#ing-progress', sheet);
      if (el) el.textContent = done + '/' + mains.length;
    }
    renderIngList($('#mains-list', sheet), mains, 'main');
    if (seasons.length) renderIngList($('#seasons-list', sheet), seasons, 'season');
    updateIngProgress();

    // 步骤
    var stepsEl = $('#steps', sheet);
    state.stepDone[r.id] = state.stepDone[r.id] || {};
    var doneMap = state.stepDone[r.id];

    function renderSteps() {
      var cur = -1;
      for (var i = 0; i < r.steps.length; i++) { if (!doneMap[i]) { cur = i; break; } }
      stepsEl.innerHTML = r.steps.map(function (s, i) {
        var done = !!doneMap[i];
        return '<div class="step' + (done ? '' : (i === cur ? ' current' : '')) + '" data-done="' + (done ? 1 : 0) + '" data-i="' + i + '">' +
          '<span class="step-num">' + (done ? '✓' : (i + 1)) + '</span>' +
          '<div class="step-body">' +
            '<div class="step-text">' + esc(s) + '</div>' +
            '<div class="step-foot">' +
              '<button class="step-done" type="button">' + (done ? '已完成' : '标记完成') + '</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      }).join('');
      Array.prototype.forEach.call(stepsEl.querySelectorAll('.step-done'), function (b) {
        b.addEventListener('click', function () {
          var i = +b.closest('.step').getAttribute('data-i');
          doneMap[i] = !doneMap[i];
          renderSteps();
        });
      });
    }
    renderSteps();

    $('#next-step', sheet).addEventListener('click', function () {
      var cur = -1;
      for (var i = 0; i < r.steps.length; i++) { if (!doneMap[i]) { cur = i; break; } }
      if (cur === -1) { toast('全部步骤都完成了，开饭吧 🎉'); return; }
      doneMap[cur] = true;
      renderSteps();
      var next = stepsEl.querySelector('.step.current');
      if (next) next.scrollIntoView({ behavior: 'smooth', block: 'center' });
      else toast('最后一步了，收工开饭 🎉');
    });

    // 加入菜篮
    var addBtn = $('#add-basket', sheet);
    addBtn.addEventListener('click', function () {
      if (state.basket.has(r.id)) {
        state.basket.delete(r.id);
        addBtn.textContent = '加入我的菜篮';
        toast('已从菜篮移出');
      } else {
        state.basket.add(r.id);
        addBtn.textContent = '已在菜篮 · 移出';
        toast('已加入我的菜篮');
      }
      persistBasket();
      renderTabs(state.route === 'basket' ? 'basket' : (state.route === 'pantry' || state.route === 'result' ? 'pantry' : 'home'));
      if (state.route === 'basket') renderBasket();
    });
  }

  /* ---------- 计时器 ---------- */
  function toggleTimerBlock() {
    var block = $('#timer-block');
    if (!block) return;
    block.hidden = !block.hidden;
    if (!block.hidden) block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function audioCtx() {
    if (!timer.ctx) {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) timer.ctx = new Ctx();
    }
    if (timer.ctx && timer.ctx.state === 'suspended') timer.ctx.resume();
    return timer.ctx;
  }

  function beep() {
    var ctx = audioCtx();
    if (!ctx) { toast('时间到！'); return; }
    var t0 = ctx.currentTime;
    [0, 0.28, 0.56].forEach(function (off, i) {
      var o = ctx.createOscillator();
      var g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = i === 2 ? 1180 : 880;
      g.gain.setValueAtTime(0.0001, t0 + off);
      g.gain.exponentialRampToValueAtTime(0.22, t0 + off + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + off + 0.22);
      o.connect(g).connect(ctx.destination);
      o.start(t0 + off);
      o.stop(t0 + off + 0.24);
    });
  }

  /* 只播报状态变化，不读每一秒 */
  function sayTimer(msg) {
    var el = $('#t-live');
    if (el) el.textContent = msg;
  }

  function paintTimer() {
    var d = $('#t-display');
    if (!d) return;
    var s = Math.max(0, Math.round(timer.left / 1000));
    var mm = String(Math.floor(s / 60)).padStart(2, '0');
    var ss = String(s % 60).padStart(2, '0');
    d.textContent = mm + ':' + ss;
    d.style.color = timer.left <= 10000 && timer.left > 0 ? 'var(--red)' : '';
  }

  function stopTimer() {
    if (timer.id) { clearInterval(timer.id); timer.id = 0; }
    timer.left = 0;
    timer.total = 0;
  }

  function startTimer(ms) {
    stopTimer();
    timer.total = ms;
    timer.left = ms;
    paintTimer();
    sayTimer('计时 ' + Math.round(ms / 60000) + ' 分钟开始');
    timer.id = setInterval(function () {
      timer.left -= 250;
      if (timer.left <= 0) {
        timer.left = 0;
        paintTimer();
        clearInterval(timer.id);
        timer.id = 0;
        beep();
        sayTimer('计时结束，时间到');
        toast('⏰ 时间到，去看看锅里');
        var start = $('#t-start');
        if (start) start.textContent = '开始';
        return;
      }
      paintTimer();
    }, 250);
    var start = $('#t-start');
    if (start) start.textContent = '暂停';
  }

  function bindTimerDelegation() {
    document.addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var preset = t.closest('[data-min]');
      if (preset && $('#timer-block')) {
        Array.prototype.forEach.call(document.querySelectorAll('[data-min]'), function (b) {
          b.setAttribute('aria-pressed', String(b === preset));
        });
        startTimer(+preset.getAttribute('data-min') * 60000);
        return;
      }
      if (t.id === 't-start') {
        if (!timer.total) { toast('先选个时长'); return; }
        if (timer.id) {
          clearInterval(timer.id); timer.id = 0;
          t.textContent = '继续';
        } else {
          var left = timer.left || timer.total;
          startTimer(left);
        }
        return;
      }
      if (t.id === 't-reset') {
        stopTimer();
        paintTimer();
        var start = $('#t-start');
        if (start) start.textContent = '开始';
        Array.prototype.forEach.call(document.querySelectorAll('[data-min]'), function (b) {
          b.setAttribute('aria-pressed', 'false');
        });
      }
    });
  }

  /* =========================================================
     AI 推荐（DeepSeek，可选）+ 本地降级
     ========================================================= */
  function localPicks(ready, one, more, n) {
    var pool = ready.concat(one, more);
    var out = [];
    var usedTags = {};
    while (out.length < n && pool.length) {
      var best = null, bestScore = -1e9;
      for (var i = 0; i < pool.length; i++) {
        var x = pool[i];
        if (out.indexOf(x) !== -1) continue;
        var score = -x.miss.length * 10;
        (x.r.tags || []).forEach(function (t) { if (!usedTags[t]) score += 3; });
        score -= x.r.time / 60; // 同等条件下优先快手
        if (score > bestScore) { bestScore = score; best = x; }
      }
      if (!best) break;
      out.push(best);
      (best.r.tags || []).forEach(function (t) { usedTags[t] = 1; });
    }
    return out.map(function (x) {
      var why = x.miss.length === 0
        ? '食材齐全，' + (x.r.tags[0] || '家常') + '口味，' + x.r.time + ' 分钟能上桌'
        : '只差 ' + x.miss.join('、') + '，顺手就能凑齐';
      return { id: x.r.id, reason: why };
    });
  }

  function openAiModal(_, ready, one, more) {
    var existing = document.querySelector('.modal-mask');
    if (existing) existing.remove();
    var mask = h(
      '<div class="modal-mask"><div class="modal" role="dialog" aria-modal="true" aria-label="AI 推荐">' +
        '<h3>✨ 让 AI 帮我搭一桌</h3>' +
        '<p>把已选食材和候选菜发给 DeepSeek，让它挑 3 道并说明理由。Key 只存在这台设备的 localStorage 里，不会上传到别处。</p>' +
        '<div class="field"><span>🔑</span><input id="ai-key" type="password" placeholder="DeepSeek API Key（sk-...）" value="' + esc(state.apiKey) + '" autocomplete="off"></div>' +
        '<div id="ai-result"></div>' +
        '<div class="modal-actions">' +
          '<button class="btn-secondary" type="button" id="ai-cancel">关闭</button>' +
          '<button class="btn-primary" type="button" id="ai-go">开始推荐</button>' +
        '</div>' +
      '</div></div>'
    );
    document.body.appendChild(mask);
    void mask.offsetWidth;
    mask.classList.add('show');
    var keyInput = $('#ai-key', mask);

    function close() {
      mask.classList.remove('show');
      setTimeout(function () { if (mask.parentNode) mask.remove(); }, 220);
    }
    mask.addEventListener('click', function (e) { if (e.target === mask) close(); });
    $('#ai-cancel', mask).addEventListener('click', close);

    $('#ai-go', mask).addEventListener('click', function () {
      var key = keyInput.value.trim();
      state.apiKey = key;
      store.set('rcp.apikey', key);
      var box = $('#ai-result', mask);
      var btn = $('#ai-go', mask);

      var fallback = function (note) {
        var picks = localPicks(ready, one, more, 3);
        box.innerHTML = '<div class="notice">' + note + '</div>' + renderPicks(picks);
      };

      if (!key) { fallback('没有填 Key，已降级为本地推荐（按「缺得最少 + 标签多样」挑的）'); return; }

      btn.disabled = true;
      btn.textContent = '推荐中…';
      box.innerHTML = '<div class="notice">正在请求 DeepSeek…（没有网络时会自动降级）</div>';

      var cand = ready.concat(one, more).slice(0, 24);
      var payload = {
        model: 'deepseek-chat',
        temperature: 0.7,
        max_tokens: 600,
        messages: [
          { role: 'system', content: '你是中国家常菜助手。只输出 JSON，不要解释、不要 markdown 代码块。' },
          { role: 'user', content: buildPrompt(cand) }
        ]
      };

      fetch('https://api.deepseek.com/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
        body: JSON.stringify(payload)
      }).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      }).then(function (json) {
        var text = json && json.choices && json.choices[0] && json.choices[0].message.content;
        var picks = parsePicks(text);
        if (!picks.length) throw new Error('bad format');
        box.innerHTML = renderPicks(picks);
      }).catch(function (err) {
        fallback('AI 请求失败（' + esc(err.message || '网络不可用') + '），已降级为本地推荐');
      }).then(function () {
        btn.disabled = false;
        btn.textContent = '再推荐一次';
      });
    });

    function renderPicks(picks) {
      return picks.map(function (p, i) {
        var r = recById[p.id];
        if (!r) return '';
        return '<div class="ai-pick"><span class="n">' + (i + 1) + '</span>' +
          '<div><div class="txt">' + esc(r.name) + ' · ' + r.time + ' 分钟</div>' +
          '<div class="why">' + esc(p.reason || '') + '</div></div></div>';
      }).join('');
    }
  }

  function buildPrompt(cand) {
    var selNames = Array.from(state.sel).map(function (id) { return ingById[id] ? ingById[id].name : id; });
    var lines = cand.map(function (x) {
      return '- id:' + x.r.id + ' 名称:' + x.r.name + ' 标签:' + (x.r.tags || []).join('/') +
        ' 时长:' + x.r.time + '分' + (x.miss.length ? ' 缺少:' + x.miss.join('、') : ' 食材齐全');
    });
    return '我有这些食材：' + (selNames.join('、') || '（未选）') + '\n' +
      '候选菜（只能从这里选）：\n' + lines.join('\n') + '\n\n' +
      '请挑 3 道搭配成一桌（荤素、汤菜、口味尽量不重复），只返回 JSON 数组，格式：' +
      '[{"id":"菜谱id","reason":"一句话推荐理由，20字以内"}]';
  }

  function parsePicks(text) {
    if (!text) return [];
    var s = String(text).trim().replace(/^```(json)?/i, '').replace(/```$/, '').trim();
    var a = s.indexOf('['), b = s.lastIndexOf(']');
    if (a >= 0 && b > a) s = s.slice(a, b + 1);
    var arr;
    try { arr = JSON.parse(s); } catch (e) { return []; }
    if (!Array.isArray(arr)) return [];
    return arr.filter(function (p) { return p && recById[p.id]; }).slice(0, 3)
      .map(function (p) { return { id: p.id, reason: String(p.reason || '').slice(0, 60) }; });
  }


  /* =========================================================
     图片来源页（credits）
     ========================================================= */
  function creditsItems() {
    var out = [];
    Object.keys(IMGS).forEach(function (k) {
      var e = IMGS[k];
      if (!e || !e.file) return;
      var parts = k.split(':');
      var obj = parts[0] === 'recipe' ? recById[parts[1]] : ingById[parts[1]];
      out.push({
        key: k,
        kind: parts[0],
        entry: e,
        name: (obj && obj.name) || parts[1],
        emoji: (obj && obj.emoji) || '🍽'
      });
    });
    out.sort(function (a, b) {
      if (a.kind !== b.kind) return a.kind === 'recipe' ? -1 : 1;
      return a.name.localeCompare(b.name, 'zh-Hans-CN');
    });
    return out;
  }

  function renderCredits() {
    renderTabs('credits');
    var view = $('#view');
    view.innerHTML = '';
    var all = creditsItems();
    var nR = all.filter(function (x) { return x.kind === 'recipe'; }).length;
    var nI = all.length - nR;

    view.appendChild(h(
      '<section class="hero">' +
        '<div class="hero-kicker">图片来源 · 版权说明</div>' +
        '<h1 class="hero-title">照片都是哪来的</h1>' +
        '<p class="hero-sub">图片来自<b>维基百科</b>与<b>维基共享资源</b>，遵循 CC（署名 / 相同方式共享）/ CC0 / 公有领域许可。' +
          '所有图片已下载到本地 images/ 目录，双击 index.html 也能正常显示。</p>' +
        '<p class="hero-sub" style="margin-top:6px">共 <b>' + all.length + '</b> 张：菜谱 <b>' + nR +
          '</b> 张 · 食材 <b>' + nI + '</b> 张。每张都标注了标题、作者、许可，点「原始页面」可回到出处核对。</p>' +
      '</section>'
    ));

    var box = h(
      '<div class="search">' +
        '<label class="search-box">' +
          '<span class="ico">🔍</span>' +
          '<input id="cq" type="search" inputmode="search" autocomplete="off" ' +
            'placeholder="搜菜名、食材、作者或许可，如 番茄 / CC BY-SA" value="' + esc(state.creditsQ || '') + '" aria-label="搜索图片来源">' +
        '</label>' +
      '</div>'
    );
    view.appendChild(box);

    var head = h('<div class="section-head"><h2>全部图片</h2><span class="count" id="credits-count"></span></div>');
    view.appendChild(head);
    var list = h('<div class="credits-list" id="credits-list"></div>');
    view.appendChild(list);

    var foot = h(
      '<div class="credits-foot">' +
        '署名说明：CC BY / CC BY-SA 类图片在菜谱详情页可见标注「标题 · 作者 · 许可」，' +
        '此处提供完整清单与原始链接。公有领域（PD）与 CC0 图片不要求署名，仍一并列出。' +
        '<br><a href="#/">← 回到菜谱</a>' +
      '</div>'
    );
    view.appendChild(foot);

    function paint() {
      var q = norm(state.creditsQ || '');
      var rows = all.filter(function (x) {
        if (!q) return true;
        var hay = norm([x.name, x.entry.title, x.entry.author, x.entry.license, x.entry.source].join(' '));
        return hay.indexOf(q) !== -1;
      });
      var cnt = $('#credits-count');
      if (cnt) cnt.textContent = rows.length + ' 张';
      if (!rows.length) {
        list.innerHTML = '<div class="empty"><span class="big">🖼️</span>' +
          (all.length ? '没有匹配「<b>' + esc(state.creditsQ) + '</b>」的图片' : '还没有抓到图片') + '</div>';
        return;
      }
      list.innerHTML = rows.map(function (x) {
        var e = x.entry;
        return '<div class="credit-row">' +
          '<span class="cr-thumb">' + imgTag(e, 'cr-img', x.name) + '</span>' +
          '<span class="cr-body">' +
            '<span class="cr-title">' + (x.kind === 'recipe' ? '🍳 ' : '🧺 ') + esc(x.name) + '</span>' +
            '<span class="cr-line">' + esc(e.title || '') + '</span>' +
            '<span class="cr-line dim">作者：' + esc(e.author || '未知') + '</span>' +
            '<span class="cr-meta">' +
              '<span class="lic-pill">' + esc(e.license || '未知许可') + '</span>' +
              '<span class="cr-src">' + esc((e.source || '').replace('commons.wikimedia.org', 'Commons')) + '</span>' +
              (e.page_url ? '<a class="cr-link" href="' + esc(e.page_url) + '" target="_blank" rel="noopener">原始页面 ↗</a>' : '') +
            '</span>' +
          '</span>' +
        '</div>';
      }).join('');
    }

    var q = $('#cq', view);
    q.addEventListener('input', function () {
      state.creditsQ = q.value;
      paint();
    });
    paint();
  }

  /* =========================================================
     渲染 & 路由
     ========================================================= */
  function render() {
    var route = parseRoute();
    state.route = route.name;
    closeSheet();
    var view = $('#view');
    view.scrollTop = 0;
    window.scrollTo(0, 0);

    if (route.name === 'home') renderHome();
    else if (route.name === 'pantry') renderPantry();
    else if (route.name === 'result') renderResult();
    else if (route.name === 'basket') renderBasket();
    else if (route.name === 'credits') renderCredits();

    if (route.name === 'detail') {
      var base = state.lastBase || 'home';
      if (base === 'basket') renderBasket();
      else if (state.sel.size) renderResult();
      else renderHome();
      requestAnimationFrame(function () { openDetail(route.id); });
      return;
    }
    state.lastBase = route.name;
  }

  window.addEventListener('hashchange', render);

  /* 键盘：/ 聚焦搜索，Esc 关闭 */
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      var q = $('#q') || $('#pq');
      if (q) { e.preventDefault(); q.focus(); q.select && q.select(); }
    }
    if (e.key === 'Escape') {
      var mask = document.querySelector('.modal-mask');
      if (mask) {
        var closeBtn = $('#ai-cancel', mask);
        if (closeBtn) closeBtn.click();
        return;
      }
      if (sheetEls) closeSheet();
    }
  });

  bindTimerDelegation();
  render();
  document.documentElement.setAttribute('data-ready', '1');
})();
