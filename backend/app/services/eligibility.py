"""业务资格统一检查（T12）。

账号启用 / 用户核验 / 门店启用 / 模板启用四类资格规则集中在这一处，
新发券（单条/批量/名单导入）、时长调整、兑换等入口复用同一套判定，
避免各入口自写一套导致边界漂移。完整行为矩阵见 PRODUCT.md「业务资格规则」。
"""

from sqlalchemy.orm import Session

from app.models.entities import (
    Account,
    CouponTemplate,
    Merchant,
    Role,
    UserProfile,
    VerifyStatus,
)


class EligibilityError(ValueError):
    """业务资格不满足；消息面向操作者，可直接作为 400 detail / 行级失败原因。"""


# 各入口的核验拒绝文案是已对外稳定的契约（导入结果与测试断言依赖原文），
# 统一资格检查后按动作保留原措辞，避免同一拒绝在三个入口出现三种说法漂移。
_VERIFY_MESSAGES = {
    "发券": "仅可为已核验通过的用户发券",
    "调整时长": "仅可为已核验用户调整时长",
    "兑换": "请先完成身份核验",
}


def require_benefit_user(db: Session, user: Account | None, *, action: str) -> UserProfile:
    """领券/入账/兑换资格：角色为 user、账号启用、身份核验已通过。

    已核验用户变更身份字段后自动转入复核（pending），复核期间暂停新发券、
    入账与兑换；其名下已有券默认保留可用，不随复核冻结。
    """
    if not user or user.role != Role.user:
        raise EligibilityError("目标用户无效")
    if not user.is_active:
        raise EligibilityError(f"该用户账号已停用，无法{action}")
    profile = db.query(UserProfile).filter(UserProfile.account_id == user.id).first()
    if not profile or profile.verify_status != VerifyStatus.approved:
        raise EligibilityError(_VERIFY_MESSAGES.get(action, f"仅可为已核验通过的用户{action}"))
    return profile


def require_issuable_template(db: Session, template: CouponTemplate | None) -> CouponTemplate:
    """发券资格：模板存在且启用，关联门店存在且启用。

    模板/门店停用只停止新增发放，不影响已发券的生命周期（实例按自身
    有效期处理）。
    """
    if not template or not template.is_active:
        raise EligibilityError("券模板不可用")
    merchant = db.get(Merchant, template.merchant_id)
    if not merchant or not merchant.is_active:
        raise EligibilityError("关联商家不可用")
    return template


def require_exchangeable_template(db: Session, template: CouponTemplate | None) -> CouponTemplate:
    """兑换资格：在发券资格之上，模板必须标价（cost_points > 0）。

    兑换目录经 `filter_exchangeable_catalog` 提前过滤，用户不应在点击后
    才发现门店停用；本检查是执行时的再次确认。
    """
    if not template or not template.is_active:
        raise EligibilityError("该券不可兑换")
    merchant = db.get(Merchant, template.merchant_id)
    if not merchant or not merchant.is_active:
        raise EligibilityError("关联商家不可用")
    return template
