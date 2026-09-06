export function formatTime(v) {
  if (!v) return '-'
  try {
    return new Date(v).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return String(v)
  }
}

export function verifyStatusText(s) {
  return {
    draft: '未提交',
    pending: '待审核',
    approved: '已通过',
    rejected: '已驳回',
    superseded: '已失效',
  }[s] || s || '-'
}

export function verifyStatusType(s) {
  return {
    draft: 'info',
    pending: 'warning',
    approved: 'success',
    rejected: 'danger',
    superseded: 'info',
  }[s] || 'info'
}

export function couponStatusText(s) {
  return { unused: '未使用', used: '已使用', void: '已作废', expired: '已过期' }[s] || s || '-'
}

export function couponStatusType(s) {
  return { unused: 'warning', used: 'success', void: 'info', expired: 'info' }[s] || 'info'
}

export function redeemResultType(s) {
  return s === 'success' ? 'success' : 'danger'
}

export function roleLabel(role) {
  return {
    super_admin: '超级管理员',
    issue_admin: '发券管理员',
    merchant: '商家',
    user: '青年用户',
  }[role] || role
}

/** 志愿服务时长（小时），最多两位小数，去掉无意义尾零 */
export function formatHours(v) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  // T17：所有时长展示统一两位小数（服务端 Decimal 才是精确值，前端不做余额运算）
  return n.toFixed(2)
}
