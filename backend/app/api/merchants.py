import json
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_account, require_roles
from app.models.entities import Account, Merchant, Role, utcnow
from app.schemas.common import Page
from app.schemas.merchant import GeoResultOut, MerchantCreate, MerchantOut, MerchantUpdate
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


def _http_get_json(url: str, timeout: float = 5.0) -> dict:
    # 高德固定 https 域名且 URL 由本函数拼装，无 SSRF 面
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


@router.get("/geo-search", response_model=list[GeoResultOut])
def geo_search(
    keywords: str = Query(min_length=1, max_length=64),
    city: str | None = Query(default=None, max_length=32),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> list[GeoResultOut]:
    """按门店名在线解析 GCJ-02 坐标（高德 Web 服务 POI 搜索）。

    高德拾取器对游客/未认证开发者只显示 2 位小数，不足以定位门店；
    配置 AMAP_WEB_KEY 后管理员直接按名称搜索并点选，免去拾取器环节。
    """
    key = get_settings().amap_web_key
    if not key:
        raise HTTPException(
            status_code=400,
            detail="未配置 AMAP_WEB_KEY，无法在线搜索；可在 backend/.env 配置后使用，或手动粘贴坐标",
        )
    params = {"key": key, "keywords": keywords, "offset": "5", "page": "1", "extensions": "base"}
    if city:
        params["city"] = city
    url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(params)
    try:
        data = _http_get_json(url)
    except OSError as exc:
        raise HTTPException(status_code=502, detail="高德服务暂不可用，请稍后再试或手动填写坐标") from exc
    if data.get("status") != "1":
        info = data.get("info") or "未知错误"
        hint = (
            "（key 无效或类型不符：需在高德开放平台创建「Web服务」类型 key 并完成实名认证）"
            if data.get("infocode") in ("10001", "10009")
            else ""
        )
        raise HTTPException(status_code=502, detail=f"高德返回错误：{info}{hint}")
    out: list[GeoResultOut] = []
    for poi in data.get("pois") or []:
        lng, _, lat = (poi.get("location") or "").partition(",")
        if not lng or not lat:
            continue
        address = poi.get("address") or "".join(
            poi.get(k) or "" for k in ("pname", "cityname", "adname")
        )
        out.append(GeoResultOut(name=poi.get("name") or "", address=address, longitude=lng, latitude=lat))
        if len(out) >= 5:
            break
    return out


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
