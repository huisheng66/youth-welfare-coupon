from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_account, require_roles
from app.models.entities import Account, Merchant, Role, utcnow
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
    account: Account = Depends(require_roles(Role.super_admin, Role.issue_admin, Role.merchant, Role.user)),
) -> MerchantOut:
    merchant = db.get(Merchant, merchant_id)
    # 查询阶段限定门店范围：他店对象与不存在统一 404，避免暴露门店联系方式是否存在
    if merchant and account.role == Role.merchant and merchant.id != account.merchant_id:
        merchant = None
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    return MerchantOut.model_validate(merchant)


def _sniff_photo_type(data: bytes) -> str | None:
    """按魔数识别图片类型：不信任上传方的 Content-Type 头。"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/{merchant_id}/photo", response_model=MerchantOut)
def upload_merchant_photo(
    merchant_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> MerchantOut:
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    max_bytes = get_settings().merchant_photo_max_bytes
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"图片过大，最大 {max_bytes // (1024 * 1024)}MB")
    content_type = _sniff_photo_type(data)
    if not content_type:
        raise HTTPException(status_code=400, detail="仅支持 JPEG / PNG / WebP 图片")
    merchant.photo_blob = data
    merchant.photo_content_type = content_type
    merchant.photo_updated_at = utcnow()
    write_audit(db, actor_id=admin.id, action="upload_merchant_photo", target_type="merchant", target_id=merchant_id)
    db.commit()
    db.refresh(merchant)
    return MerchantOut.model_validate(merchant)


@router.delete("/{merchant_id}/photo", response_model=MerchantOut)
def delete_merchant_photo(
    merchant_id: str,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> MerchantOut:
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    merchant.photo_blob = None
    merchant.photo_content_type = ""
    merchant.photo_updated_at = utcnow()
    write_audit(db, actor_id=admin.id, action="delete_merchant_photo", target_type="merchant", target_id=merchant_id)
    db.commit()
    db.refresh(merchant)
    return MerchantOut.model_validate(merchant)


@router.get("/{merchant_id}/photo")
def get_merchant_photo(
    merchant_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
) -> Response:
    """门头照二进制：任意已登录角色可见（门店公开展示信息）。

    <img> 同源请求自动带认证 Cookie；带 photo_updated_at 版本参数时
    可安全使用短 max-age，覆盖旧图后客户端无需手动清缓存。
    """
    merchant = db.get(Merchant, merchant_id)
    if not merchant or not merchant.photo_blob:
        raise HTTPException(status_code=404, detail="门头照不存在")
    return Response(
        content=merchant.photo_blob,
        media_type=merchant.photo_content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )
