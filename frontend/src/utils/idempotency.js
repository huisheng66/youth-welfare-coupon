// 写操作幂等键（T13）
//
// 一次业务操作意图生成一个 key，通过 `Idempotency-Key` 请求头发送：
// 同一操作的超时重试、重复点击复用同一 key，服务端重放原结果而不重复执行；
// 重新发起的独立业务必须生成新 key（成功回调里重置）。

export function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID()
  }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

export function idempotencyHeader(key) {
  return key ? { 'Idempotency-Key': key } : {}
}
