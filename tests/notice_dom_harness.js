// 通知交互脚本的 node 行为测试。
//
// 为什么需要它：门户 index.html 里那段 IIFE（红点判定、已读落盘、inert 切换、
// 焦点陷阱、Esc 守卫）此前只有字符串契约测试——把 seen !== null 守卫删掉、
// 把红点判定反转、把 markRead() 调用删掉，Python 侧用例全绿。
// 字符串测试盯不住"逻辑"，这里让 node 真跑一遍脚本。
//
// 两条硬约束：
// 1) 不在生产代码里加任何测试钩子。脚本原文从 index.html 原样抽取、逐字执行，
//    通知数据也从页面里那段注入脚本原样解析。页面不改一行。
// 2) 桩要"最小但够用"：只实现脚本真正用到的那几个 DOM 成员，
//    多一个成员都可能让变异测试失真（桩太宽容 = 测不出问题）。
//
// 用法：node notice_dom_harness.js <index.html>
// 输出：stdout 打印一个 JSON 报告 {场景名: {ok, error?}}，退出码恒为 0；
//       页面里找不到脚本时退出码 2（夹具问题，不是被测行为）。
'use strict';

const fs = require('fs');
const vm = require('vm');

const indexPath = process.argv[2];
if (!indexPath) {
  console.error('用法：node notice_dom_harness.js <index.html>');
  process.exit(2);
}
const html = fs.readFileSync(indexPath, 'utf8');

// ---------------------------------------------------------------- 脚本抽取

// 交互脚本的识别特征是存储键；数据脚本的特征是给 __NOTICES__ 赋值。
// 各自取"最后一个"匹配，兼容页面里存在其他内联脚本。
function lastScript(match) {
  const re = /<script>([\s\S]*?)<\/script>/g;
  let found = null;
  let m;
  while ((m = re.exec(html)) !== null) {
    if (m[1].includes(match)) found = m[1];
  }
  return found;
}

const SCRIPT = lastScript('portal_notice_read_id');
if (SCRIPT === null) {
  console.error('未在 %s 中找到通知交互脚本（缺少 portal_notice_read_id）', indexPath);
  process.exit(2);
}
const DATA_SCRIPT = lastScript('window.__NOTICES__=');
if (DATA_SCRIPT === null) {
  console.error('未在 %s 中找到通知数据脚本（缺少 window.__NOTICES__=）', indexPath);
  process.exit(2);
}

// 页面里真实注入的通知数据：让"最新 id"这类断言对着生产数据跑，
// 而不是对着桩里编的假 id（假 id 会掩盖"数据与脚本对不上"这类问题）。
const pageSandbox = { console };
pageSandbox.window = pageSandbox;
vm.createContext(pageSandbox);
vm.runInContext(DATA_SCRIPT, pageSandbox);
const PAGE_NOTICES = pageSandbox.__NOTICES__ || [];
const PAGE_LATEST = pageSandbox.__NOTICE_LATEST__ || '';

// ---------------------------------------------------------------- DOM 桩

function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    contains: (c) => set.has(c),
    _set: set,
  };
}

function makeDoc() {
  const doc = {
    activeElement: null,
    els: {},
    _handlers: {},
    getElementById(id) { return this.els[id] || null; },
    // 脚本只用 createElement 造 <p>/<article>/<div>/<span>/<h3>，全是纯文本容器
    createElement(tag) { return makeElement('<' + tag + '>', doc); },
    addEventListener(type, fn) {
      (this._handlers[type] = this._handlers[type] || []).push(fn);
    },
  };
  // 造一个可被脚本 dispatch 的事件对象
  doc.keyEvent = (key, shiftKey) => {
    const ev = {
      key: key,
      shiftKey: !!shiftKey,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
    };
    (doc._handlers.keydown || []).forEach((fn) => fn(ev));
    return ev;
  };
  doc.click = (id) => (doc.els[id]._handlers.click || []).forEach((fn) => fn({ type: 'click' }));
  return doc;
}

function makeElement(id, doc) {
  const el = {
    id: id,
    hidden: false,
    className: '',
    textContent: '',
    attrs: new Map(),
    classList: makeClassList(),
    children: [],
    focusCount: 0,
    _handlers: {},
    _focusables: [],
    addEventListener(type, fn) {
      (this._handlers[type] = this._handlers[type] || []).push(fn);
    },
    setAttribute(k, v) { this.attrs.set(k, String(v)); },
    removeAttribute(k) { this.attrs.delete(k); },
    getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; },
    hasAttribute(k) { return this.attrs.has(k); },
    focus() { this.focusCount += 1; doc.activeElement = this; },
    appendChild(child) { this.children.push(child); return child; },
    // 面板内可聚焦元素：脚本用 querySelectorAll(FOCUSABLE) 查，
    // 真实页面里是「关闭」按钮 + 通知内的链接/按钮，桩里给两个固定节点。
    querySelectorAll() { return this._focusables.slice(); },
  };
  return el;
}

function makeStorage(initial, throws) {
  return {
    getItem(k) {
      if (throws) throw new Error('SecurityError: 存储不可用');
      return Object.prototype.hasOwnProperty.call(initial, k) ? initial[k] : null;
    },
    setItem(k, v) {
      if (throws) throw new Error('SecurityError: 存储不可用');
      initial[k] = String(v);
    },
  };
}

// 跑一次脚本，返回可观察的句柄。opts:
//   notices / latest  通知数据（缺省用页面里真实注入的那份）
//   stored            localStorage 初始内容
//   storageThrows     模拟隐私模式 / 存储被禁用
function run(opts) {
  opts = opts || {};
  const doc = makeDoc();
  ['notice-bell', 'notice-dot', 'notice-panel', 'notice-mask', 'notice-close', 'notice-list']
    .forEach((id) => { doc.els[id] = makeElement(id, doc); });
  // 面板初始是关闭态：HTML 上带 aria-hidden="true" 与 inert
  doc.els['notice-panel'].setAttribute('aria-hidden', 'true');
  doc.els['notice-panel'].setAttribute('inert', '');
  doc.els['notice-bell'].setAttribute('aria-expanded', 'false');
  const link = makeElement('fake-notice-link', doc);
  doc.els['notice-panel']._focusables = [doc.els['notice-close'], link];

  const store = Object.assign({}, opts.stored || {});
  const sandbox = {
    document: doc,
    localStorage: makeStorage(store, !!opts.storageThrows),
    console: console,
  };
  sandbox.window = sandbox;
  sandbox.__NOTICES__ = opts.notices === undefined ? PAGE_NOTICES : opts.notices;
  sandbox.__NOTICE_LATEST__ = opts.latest === undefined ? PAGE_LATEST : opts.latest;
  vm.createContext(sandbox);
  vm.runInContext(SCRIPT, sandbox);  // 抛异常就让它冒到场景里
  return { doc: doc, els: doc.els, link: link, store: store, sandbox: sandbox };
}

const KEY = 'portal_notice_read_id';

// ---------------------------------------------------------------- 断言与场景

const report = {};
function assert(cond, msg) { if (!cond) throw new Error(msg); }
function scenario(name, fn) {
  try {
    fn();
    report[name] = { ok: true };
  } catch (e) {
    report[name] = { ok: false, error: (e && e.message) || String(e) };
  }
}

// 1. 首次访问：有通知、localStorage 空 → 红点可见
scenario('fresh_visit_dot_visible', () => {
  const s = run();
  assert(s.els['notice-dot'].hidden === false, '首次访问红点应可见');
  assert(Object.keys(s.store).length === 0, '首次访问不应写入已读状态');
});

// 2. 打开面板：红点消失 + localStorage 落盘为最新 id
scenario('open_marks_read', () => {
  const s = run();
  s.doc.click('notice-bell');
  assert(s.els['notice-dot'].hidden === true, '打开面板后红点应消失');
  assert(s.store[KEY] === PAGE_LATEST,
    '已读状态应落盘为最新 id，实际 ' + JSON.stringify(s.store[KEY]));
});

// 3. 刷新：localStorage 已有最新 id → 红点不再出现
scenario('reload_after_read_no_dot', () => {
  const s = run({ stored: { [KEY]: PAGE_LATEST } });
  assert(s.els['notice-dot'].hidden === true, '已读过最新一条就不该亮红点');
});

// 4. localStorage 抛错（隐私模式）：红点不显示，且脚本不抛异常
//    删掉 seen !== null 守卫后，本场景会红：null !== latest 成立 → 红点亮起
scenario('storage_unavailable_degrades_silently', () => {
  const s = run({ storageThrows: true });
  assert(s.els['notice-dot'].hidden === true, '存储不可用时不得亮红点（无已读依据）');
  s.doc.click('notice-bell');  // markRead 写不进去也必须静默
  assert(s.els['notice-panel'].classList.contains('on'), '存储不可用时面板仍应能打开');
  assert(Object.keys(s.store).length === 0, '存储不可用时不应有落盘');
});

// 5. 无通知：红点不显示 + 面板渲染"暂无通知"空态
scenario('empty_notices_render_placeholder', () => {
  const s = run({ notices: [], latest: '' });
  assert(s.els['notice-dot'].hidden === true, '无通知时不该亮红点');
  s.doc.click('notice-bell');
  const kids = s.els['notice-list'].children;
  assert(kids.length === 1, '空态应只渲染一个节点，实际 ' + kids.length);
  assert(kids[0].className === 'np-empty', '空态节点 class 应为 np-empty');
  assert(kids[0].textContent === '暂无通知', '空态文案应为"暂无通知"');
  assert(Object.keys(s.store).length === 0, '无通知时不应写入已读状态');
});

// 6. 打开态的 aria / inert / 焦点：inert 不跟着切换，关闭后焦点会掉进屏幕外
scenario('open_toggles_inert_aria_and_focus', () => {
  const s = run();
  const panel = s.els['notice-panel'];
  s.doc.click('notice-bell');
  assert(panel.classList.contains('on'), '打开后面板应带 on 类');
  assert(panel.hasAttribute('inert') === false, '打开时必须摘掉 inert');
  assert(panel.getAttribute('aria-hidden') === 'false', '打开时 aria-hidden 应为 false');
  assert(s.els['notice-bell'].getAttribute('aria-expanded') === 'true', '铃铛 aria-expanded 应为 true');
  assert(s.doc.activeElement === s.els['notice-close'], '打开后焦点应移进面板');
});

// 7. 关闭态还原：inert 与 aria-hidden 复位，焦点交还铃铛
scenario('close_restores_inert_aria_and_focus', () => {
  const s = run();
  const panel = s.els['notice-panel'];
  s.doc.click('notice-bell');
  const bellFocusAfterOpen = s.els['notice-bell'].focusCount;
  s.doc.click('notice-bell');  // 再点一次铃铛 = 关闭
  assert(panel.classList.contains('on') === false, '再次点击应关闭面板');
  assert(panel.hasAttribute('inert') === true, '关闭时必须加回 inert');
  assert(panel.getAttribute('aria-hidden') === 'true', '关闭时 aria-hidden 应为 true');
  assert(s.doc.activeElement === s.els['notice-bell'], '关闭后焦点应交还铃铛');
  assert(s.els['notice-bell'].focusCount === bellFocusAfterOpen + 1,
    '关闭动作应真实调用了一次铃铛 focus()');
});

// 8. Esc 只在面板打开时生效：关闭态按 Esc 不得抢焦点
//    去掉 Esc 守卫后，本场景会红：close() 被触发，focusCount +1
scenario('escape_only_while_open', () => {
  const s = run();
  const panel = s.els['notice-panel'];
  s.doc.keyEvent('Escape');  // 关闭态
  assert(panel.classList.contains('on') === false, '关闭态按 Esc 不应打开面板');
  assert(s.els['notice-bell'].focusCount === 0, '关闭态按 Esc 不应抢走焦点');
  s.doc.click('notice-bell');
  assert(panel.classList.contains('on') === true, '前置条件：面板应已打开');
  s.doc.keyEvent('Escape');  // 打开态
  assert(panel.classList.contains('on') === false, '打开态按 Esc 应关闭面板');
  assert(s.els['notice-bell'].focusCount === 1, '打开态按 Esc 应关闭并交还焦点');
});

// 9. 焦点陷阱：Tab / Shift+Tab 在面板首尾之间绕回
scenario('tab_is_trapped_in_open_panel', () => {
  const s = run();
  s.doc.click('notice-bell');
  const first = s.els['notice-close'];
  const last = s.link;
  s.doc.activeElement = last;
  let ev = s.doc.keyEvent('Tab');
  assert(ev.defaultPrevented === true, '末位按 Tab 应吞掉默认行为');
  assert(s.doc.activeElement === first, '末位按 Tab 应绕回首个可聚焦元素');
  s.doc.activeElement = first;
  ev = s.doc.keyEvent('Tab', true);
  assert(ev.defaultPrevented === true, '首位按 Shift+Tab 应吞掉默认行为');
  assert(s.doc.activeElement === last, '首位按 Shift+Tab 应绕回末位可聚焦元素');
  // 焦点在面板外时要先收回来
  s.doc.activeElement = s.els['notice-bell'];
  ev = s.doc.keyEvent('Tab');
  assert(ev.defaultPrevented === true, '焦点在面板外时 Tab 应被接管');
  assert(s.doc.activeElement === first, '焦点在面板外时 Tab 应先把焦点收进面板');
});

// 10. 关闭态不得拦 Tab：页面其余部分保持浏览器默认顺序
scenario('tab_not_trapped_while_closed', () => {
  const s = run();
  s.doc.activeElement = s.els['notice-bell'];
  const ev = s.doc.keyEvent('Tab');
  assert(ev.defaultPrevented === false, '关闭态不该抢 Tab');
  assert(s.doc.activeElement === s.els['notice-bell'], '关闭态不该移动焦点');
});

// 11. 置顶徽标：pinned 的通知在日期旁渲染"置顶"
scenario('pinned_badge_rendered', () => {
  const notices = [
    { id: 'p1', date: '2026-01-01', title: '置顶那条', body: '正文', pinned: true },
    { id: 'p2', date: '2026-01-02', title: '普通那条', body: '正文', pinned: false },
  ];
  const s = run({ notices: notices, latest: 'p1' });
  const box = s.els['notice-list'];
  assert(box.children.length === 2, '应渲染两条通知');
  const pinnedDate = box.children[0].children[0];
  const normalDate = box.children[1].children[0];
  assert(pinnedDate.children.length === 1 && pinnedDate.children[0].textContent === '置顶',
    '置顶通知的日期旁应有"置顶"徽标');
  assert(normalDate.children.length === 0, '未置顶通知不应有徽标');
  // 通知内容必须是纯文本节点，不能有 HTML 解析痕迹
  assert(box.children[0].children[1].textContent === '置顶那条', '标题应走 textContent');
  assert(box.children[0].children[2].textContent === '正文', '正文应走 textContent');
});

// 12. 页面本身必须真的有通知，否则前 1~3 条场景没有意义
scenario('page_has_notices', () => {
  assert(PAGE_NOTICES.length > 0, '门户页面的注入块里一条通知都没有，前置条件不成立');
  assert(PAGE_LATEST !== '', '注入块缺少 __NOTICE_LATEST__');
});

process.stdout.write(JSON.stringify(report));
