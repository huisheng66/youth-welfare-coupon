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

默认：前端 **https://127.0.0.1:5173/**（HTTPS，便于手机扫码），后端 http://127.0.0.1:19001/

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

浏览器打开：https://127.0.0.1:5173/ （自签证书需点「继续访问」）  


### 演示账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 超级管理员 | admin | admin123 |
| 发券管理员 | issuer | issuer123 |
| 商家（餐饮） | merchant1 | merchant123 |
| 商家（书店） | merchant2 | merchant123 |
| 青年用户（已核验） | youth1 | youth123 |
| 青年用户（待审核） | youth2 | youth123 |

## 推荐演示路径

1. `admin` 登录 → 仪表盘 / 商家 / 券模板（可设兑换时长）  
2. `issuer` 批量发券，或管理端「志愿时长」给用户入账  
3. `youth1` →「时长兑换」或「我的优惠券」出示**动态券码**（二维码约 30 秒刷新；核销后用户端立即提示成功）  
4. `merchant1` →「核销」→ **扫码**（摄像头 / 相册）或粘贴动态码 → 预览 → 确认核销  
5. 管理端导出核销流水 CSV  

### 商家扫码说明

- 支持：后置摄像头实时扫、相册识图、手动粘贴  
- 可开启「扫码后自动核销」；默认仅预览再确认  

### 手机访问电脑前端（同一 Wi‑Fi）

前端必须监听 `0.0.0.0`（已配置）。用 **WLAN 的 IPv4**，不要用 VMware/WSL 虚拟网卡地址。

```powershell
# 查电脑 Wi‑Fi IP（示例 192.168.1.9）
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match 'WLAN|Wi-Fi' }

# 启动（推荐）
.\start.ps1
# 或手动：
# 后端: uvicorn ... --host 127.0.0.1 --port 19001
# 前端: npm run dev -- --host 0.0.0.0 --port 5173
```

手机请打开 **HTTPS**（摄像头要求安全上下文）：

`https://192.168.x.x:5173/`（换成你的 WLAN IP）

首次会提示证书不受信任：选 **高级 → 继续访问**。之后才能调摄像头。

若仍无法开摄像头：用页面上的 **拍照识别 / 相册选图**（走系统相机，不依赖网页摄像头 API）。

若一直转圈：

1. 确认前端是 `0.0.0.0:5173` + HTTPS  
2. Windows 防火墙放行 **入站 TCP 5173**  
3. 手机与电脑同一 Wi‑Fi  

API 经 Vite 代理到本机后端，手机**不必**直接访问 19001。

## 已实现能力

- 用户核验、指定商家发券/批量发券、商家核销  
- 动态短时券码（约 30 秒刷新 + 二维码；核销后用户端即时成功提示）  
- **商家扫码核销**（摄像头 / 相册）  
- CSV 导出（核销流水、券列表）  
- 志愿服务时长入账与用户自助兑换  
- 商家统计、核销预览、审计日志  
- **账号设置改密**（各角色）；超管可重置密码、启停账号  
- 用户首页券/时长概览与快捷出示；商家核销页近期流水  
- 待审**批量通过/驳回**；券列表 / 核销流水筛选分页与导出  
- 仪表盘今日发券/核销；志愿时长全局流水；用户核验历史  
- 演示账号自动补发未使用券，便于扫码演示  
- 登录失败限流；过期券自动扫描；用户 CSV 导出  
- 商家/模板/审计筛选；404 页；兑换后可直接出示券码  

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

- **超管**：商家、账号、审计、全部业务；重置密码 / 启停账号  
- **发券管理员**：用户审核、**商家维护**、券模板、发券/作废、流水  
- **商家**：仅本店核销与本店流水、改密  
- **用户**：资料、提交核验、出示动态码、时长兑换、改密  

## 二期预留

- 微信小程序（复用现有 REST + JWT）  
- 志愿服务时长账户表 `point_accounts` / `point_ledgers` 已预留  

## 安全说明

- 用户主键为系统 UUID，**不使用银行卡**  
- 券模板强制绑定商家；核销校验 `merchant_id`  
- 核销使用状态条件更新，降低并发重复核销风险  
