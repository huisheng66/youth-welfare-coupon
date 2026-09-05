from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import Account, Merchant, Role
from app.schemas.common import Page
from app.schemas.merchant import MerchantCreate, MerchantOut, MerchantUpdate
from app.services.audit import write_audit

router = APIRouter(prefix="/merchants", tags=["商家"])


@router.get("", response_model=Page[MerchantOut])
def list_merchants(
    q: str | None = None,
    active_only: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.super_admin, Role.issue_admin, Role.merchant)),
) -> Page[MerchantOut]:
    query = db.query(Merchant).order_by(Merchant.created_at.desc())
    # 商家角色固定锁定本店：绑定缺失或来自 query 的覆盖都不生效，防止越权读取他店资料
    if account.role == Role.merchant:
        if not account.merchant_id:
            return Page(total=0, items=[])
        query = query.filter(Merchant.id == account.merchant_id)
    if active_only:
        query = query.filter(Merchant.is_active.is_(True))
    if q:
        query = query.filter(Merchant.name.ilike(f"%{q}%"))
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return Page(total=total, items=[MerchantOut.model_validate(i) for i in items])


@router.post("", response_model=MerchantOut)
def create_merchant(
    body: MerchantCreate,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> MerchantOut:
    if db.query(Merchant).filter(Merchant.name == body.name).first():
        raise HTTPException(status_code=400, detail="商家名称已存在")
    merchant = Merchant(**body.model_dump())
    db.add(merchant)
    write_audit(db, actor_id=admin.id, action="create_merchant", target_type="merchant", target_id=body.name)
    db.commit()
    db.refresh(merchant)
    return MerchantOut.model_validate(merchant)


@router.put("/{merchant_id}", response_model=MerchantOut)
def update_merchant(
    merchant_id: str,
    body: MerchantUpdate,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> MerchantOut:
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != merchant.name:
        if db.query(Merchant).filter(Merchant.name == data["name"]).first():
            raise HTTPException(status_code=400, detail="商家名称已存在")
    for k, v in data.items():
        setattr(merchant, k, v)
    write_audit(db, actor_id=admin.id, action="update_merchant", target_type="merchant", target_id=merchant_id)
    db.commit()
    db.refresh(merchant)
    return MerchantOut.model_validate(merchant)


@router.get("/{merchant_id}", response_model=MerchantOut)
def get_merchant(
    merchant_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.super_admin, Role.issue_admin, Role.merchant)),
) -> MerchantOut:
    merchant = db.get(Merchant, merchant_id)
    # 查询阶段限定门店范围：他店对象与不存在统一 404，避免暴露门店联系方式是否存在
    if merchant and account.role == Role.merchant and merchant.id != account.merchant_id:
        merchant = None
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    return MerchantOut.model_validate(merchant)
