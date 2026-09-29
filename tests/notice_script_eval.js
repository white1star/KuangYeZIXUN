// 注入块的 JS 求值器：用 node:vm 跑门户 index.html 里那段真实的数据脚本，
// 把 window.__NOTICES__ / window.__NOTICE_LATEST__ 的求值结果打成 JSON 打到 stdout。
//
// 存在的理由：Python 侧的字符串断言只能证明"源码里没有裸 </script>"，
// 证明不了"落到页面上还是不是原值"。真正能定案的是让 JS 引擎自己解析一遍——
// id 里带引号时裸插值会直接语法错误，带 </script> 时会被 HTML 解析器提前截断，
// 这两种后果都能在这里被真实复现与拦截。
//
// 约定：任何异常都不吞，异常直接以非零码抛出，由 pytest 判定为失败。
// 退出码 2 表示"页面里找不到数据脚本"，属于夹具问题而不是被测行为。
'use strict';

const fs = require('fs');
const vm = require('vm');

const indexPath = process.argv[2];
if (!indexPath) {
  console.error('用法：node notice_script_eval.js <index.html>');
  process.exit(2);
}

const html = fs.readFileSync(indexPath, 'utf8');

// 取最后一个赋值 window.__NOTICES__ 的内联脚本。
// 用"最后一个"而不是"唯一"：夹具页可能自带其他内联脚本，只有数据脚本会写这两个变量。
const DATA_RE = /<script>([\s\S]*?)<\/script>/g;
let dataScript = null;
let m;
while ((m = DATA_RE.exec(html)) !== null) {
  if (m[1].includes('window.__NOTICES__=')) dataScript = m[1];
}
if (dataScript === null) {
  console.error('未在 %s 中找到注入的数据脚本（window.__NOTICES__=）' + indexPath);
  process.exit(2);
}

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(dataScript, sandbox);

process.stdout.write(JSON.stringify({
  latest: sandbox.__NOTICE_LATEST__,
  notices: sandbox.__NOTICES__,
}));
