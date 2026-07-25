from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.entities import Account, CouponTemplate, Merchant, PointAccount, Role, UserProfile, VerifyStatus
from app.services.points import apply_points, get_or_create_account


def patch_existing_demo(db: Session) -> None:
    """Upgrade older demo DBs with points/exchange fields without wiping data."""
    youth = db.query(Account).filter(Account.username == "youth1").first()
    if youth:
        acc = get_or_create_account(db, youth.id)
        if acc.balance <= 0:
            apply_points(
                db,
                user_id=youth.id,
                change=10,
                reason="演示：补发志愿服务时长",
                operator_id=None,
                ref_type="seed_patch",
            )
    templates = db.query(CouponTemplate).filter(CouponTemplate.cost_points == 0).all()
    for t in templates:
        if "餐饮" in (t.name or "") or "演示" in (t.description or ""):
            t.cost_points = 2
    db.commit()


def seed_if_empty(db: Session) -> None:
    if db.query(Account).filter(Account.username == "admin").first():
        patch_existing_demo(db)
        return

    merchant = Merchant(
        name="示例餐饮店",
        contact_name="张店长",
        contact_phone="13800000001",
        address="示例路 1 号",
        description="青年福利合作餐饮商家（演示）",
    )
    db.add(merchant)
    db.flush()

    admin = Account(
        username="admin",
        password_hash=hash_password("admin123"),
        role=Role.super_admin,
        display_name="超级管理员",
    )
    issuer = Account(
        username="issuer",
        password_hash=hash_password("issuer123"),
        role=Role.issue_admin,
        display_name="发券管理员",
    )
    merchant_acc = Account(
        username="merchant1",
        password_hash=hash_password("merchant123"),
        role=Role.merchant,
        display_name="示例餐饮店核销员",
        merchant_id=merchant.id,
    )
    demo_user = Account(
        username="youth1",
        password_hash=hash_password("youth123"),
        role=Role.user,
        display_name="演示青年",
        phone="13900000001",
    )
    db.add_all([admin, issuer, merchant_acc, demo_user])
    db.flush()

    db.add(
        UserProfile(
            account_id=demo_user.id,
            real_name="李青年",
            organization="示例社区",
            id_number_masked="110***********1234",
            verify_status=VerifyStatus.approved,
            remark="种子演示用户，已通过核验",
        )
    )
    db.add(
        CouponTemplate(
            name="餐饮立减券",
            description="到店消费可抵用 1 次（演示）；可用时长兑换",
            merchant_id=merchant.id,
            valid_days=90,
            cost_points=2,
            is_active=True,
        )
    )
    db.add(PointAccount(user_id=demo_user.id, balance=0))
    db.flush()
    apply_points(
        db,
        user_id=demo_user.id,
        change=10,
        reason="演示：初始志愿服务时长",
        operator_id=admin.id,
        ref_type="seed",
    )
    db.commit()
