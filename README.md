# 青年福利券系统（一期）

身份核验 → **指定商家**优惠券发放 → 商家 Web 核销。

- 后端：Python FastAPI + SQLAlchemy + SQLite（可切云数据库）
- 前端：Vue 3 + Vite + Element Plus
- **不含**微信小程序、**不采集**银行卡

## 目录

```
backend/    API 服务
frontend/   Web（管理端 / 用户端 / 商家端，按角色进入）
```

## 快速启动

### Windows 一键启动

```powershell
.\start.ps1
```

默认：前端 http://127.0.0.1:5173/ ，后端 http://127.0.0.1:19001/

### 1. 后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 19001
```

- API 文档：http://127.0.0.1:19001/docs  
- 健康检查：http://127.0.0.1:19001/api/health  

首次启动会自动建表并写入演示数据。

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开：http://127.0.0.1:5173  


### 演示账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 超级管理员 | admin | admin123 |
| 发券管理员 | issuer | issuer123 |
| 商家 | merchant1 | merchant123 |
| 青年用户（已核验） | youth1 | youth123 |

## 推荐演示路径

1. `admin` 登录 → 仪表盘 / 商家 / 券模板（可设兑换时长）  
2. `issuer` 批量发券，或管理端「志愿时长」给用户入账  
3. `youth1` →「时长兑换」或「我的优惠券」出示**动态券码**  
4. `merchant1` 粘贴动态码预览并核销  
5. 管理端导出核销流水 CSV  

## 已实现能力

- 用户核验、指定商家发券/批量发券、商家核销  
- 动态短时券码（约 60 秒刷新 + 二维码）  
- CSV 导出（核销流水、券列表）  
- 志愿服务时长入账与用户自助兑换  
- 商家统计、核销预览、审计日志  

### 二期预留

- 微信小程序（复用 REST + JWT）  

## 环境变量（后端）

复制 `backend/.env.example` 为 `backend/.env`：

```env
SECRET_KEY=请改成随机长字符串
DATABASE_URL=sqlite:///./data/app.db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 上云数据库

将 `DATABASE_URL` 改为例如：

```env
# PostgreSQL
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/welfare

# MySQL
DATABASE_URL=mysql+pymysql://user:password@host:3306/welfare
```

并安装对应驱动（`psycopg2-binary` 或 `pymysql`）。表结构由启动时 `create_all` 创建（生产建议再接入 Alembic 迁移）。

## 角色能力摘要

- **超管**：商家、账号、审计、全部业务  
- **发券管理员**：用户审核、券模板、发券/作废、流水  
- **商家**：仅本店核销与本店流水  
- **用户**：资料、提交核验、查看本人券码  

## 二期预留

- 微信小程序（复用现有 REST + JWT）  
- 志愿服务时长账户表 `point_accounts` / `point_ledgers` 已预留  

## 安全说明

- 用户主键为系统 UUID，**不使用银行卡**  
- 券模板强制绑定商家；核销校验 `merchant_id`  
- 核销使用状态条件更新，降低并发重复核销风险  
