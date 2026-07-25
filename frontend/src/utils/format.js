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
  return { draft: '未提交', pending: '待审核', approved: '已通过', rejected: '已驳回' }[s] || s || '-'
}

export function verifyStatusType(s) {
  return { draft: 'info', pending: 'warning', approved: 'success', rejected: 'danger' }[s] || 'info'
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
