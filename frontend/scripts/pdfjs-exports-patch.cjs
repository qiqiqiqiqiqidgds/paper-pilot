// pdfjs-dist 的 pdf.mjs 是自打包的 webpack ESM 文件，内部声明了
// `var __webpack_exports__ = {};`。Next.js dev 模式下 webpack 用 eval() 包裹模块，
// 该 var 声明在 eval 作用域内提升，遮蔽了外层传入的 __webpack_exports__ 参数
// （提升后为 undefined），导致 webpack 前缀的 __webpack_require__.r(undefined)
// 抛出 "Object.defineProperty called on non-object"，PDF 渲染直接崩溃。
// 生产构建走模块对象包装（非 eval），同名 var 只重绑定参数、无害，所以此补丁
// 对 prod 无副作用。这里把内部变量改名，绕开与 webpack 注入导出的命名冲突。
const TARGET = /^var __webpack_exports__ = \{\};$/m;

module.exports = function pdfjsExportsPatch(source) {
  const patched = source.replace(TARGET, "var __pdfjs_inner_exports = {};");
  if (patched === source) {
    // 失配绝不能静默：pdfjs-dist 升级后打包格式一旦变化，dev 下 PDF 渲染会
    // 直接崩溃且无任何提示。这里显式告警，让问题在构建/启动期可见。
    console.warn(
      "[pdfjs-exports-patch] 未找到 `var __webpack_exports__ = {};` —— " +
        "pdfjs-dist 打包格式可能已变化，PDF 渲染在 dev 模式下会崩溃。" +
        "请检查 node_modules/pdfjs-dist/build/pdf.mjs 并更新本补丁的正则。"
    );
  }
  return patched;
};
