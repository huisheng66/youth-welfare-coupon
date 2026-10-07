// 极轻量并发去重：同一 key 的在途 GET 请求复用同一个 Promise。
//
// 背景：管理端布局在每次路由切换时拉 /dashboard 取待审徽标数，仪表盘页自身
// 也要拉同一接口——进入仪表盘时同一请求会发出两次，既浪费往返又让首屏多等
// 一拍。这里只做「在途复用」，不缓存响应结果，因此不影响数据新鲜度
// （徽标数仍在每次路由切换时真实刷新）。

const inflight = new Map()

/**
 * 在途请求去重。
 * @param {string} key 去重键，通常是 `METHOD /path`
 * @param {() => Promise<any>} run 实际发起请求的函数
 * @returns {Promise<any>} 共享的 Promise；结束后自动移出在途表
 */
export function dedupe(key, run) {
  const existing = inflight.get(key)
  if (existing) return existing
  const p = (async () => run())().finally(() => {
    if (inflight.get(key) === p) inflight.delete(key)
  })
  inflight.set(key, p)
  return p
}

export default dedupe