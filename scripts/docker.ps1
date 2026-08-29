# 青年福利券系统 — Docker 常用命令（PowerShell 版）
# 用法：
#   .\scripts\docker.ps1 up        # 启动开发环境
#   .\scripts\docker.ps1 logs api  # 跟踪 api 日志
#   .\scripts\docker.ps1 help      # 显示所有命令
#
# 等价于 Makefile，供 Windows 无 make 的环境使用

param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

function Invoke-Docker {
    param([string[]]$CmdArgs)
    Write-Host "==> docker compose $CmdArgs" -ForegroundColor Cyan
    & docker compose @CmdArgs
}

switch ($Command.ToLower()) {
    "help" {
        Write-Host "用法: .\scripts\docker.ps1 <command>"
        Write-Host ""
        Write-Host "启动:"
        Write-Host "  up          启动开发环境（显式叠加 docker-compose.dev.yml）"
        Write-Host "  up-prod     启动生产模式（仅 base compose）"
        Write-Host "  up-https    启动生产 + HTTPS（Caddy，需设 WELFARE_DOMAIN）"
        Write-Host "  down        停止容器（保留数据）"
        Write-Host "  down-clean  停止并删除数据卷（⚠️ 丢失数据库）"
        Write-Host ""
        Write-Host "构建:"
        Write-Host "  build       构建镜像"
        Write-Host "  rebuild     强制重新构建（无缓存）"
        Write-Host ""
        Write-Host "观测:"
        Write-Host "  ps          容器状态"
        Write-Host "  logs        跟踪所有日志（可加服务名：logs api）"
        Write-Host "  health      健康检查"
        Write-Host ""
        Write-Host "调试:"
        Write-Host "  shell api   进入 api 容器"
        Write-Host "  shell web   进入 web 容器"
        Write-Host "  shell redis 进入 redis 容器"
        Write-Host ""
        Write-Host "数据:"
        Write-Host "  seed        临时 seed 演示账号"
        Write-Host "  backup      备份数据库到 ./backup/"
        Write-Host "  restore FILE=<path>  恢复数据库"
        Write-Host ""
        Write-Host "校验:"
        Write-Host "  validate    校验 compose 配置"
        Write-Host "  scan        trivy 镜像扫描（需安装 trivy）"
    }
    "up"       { Invoke-Docker @("-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "up", "-d", "--build") }
    "up-prod"  { Invoke-Docker @("-f", "docker-compose.yml", "up", "-d", "--build") }
    "up-https" { Invoke-Docker @("-f", "docker-compose.yml", "-f", "docker-compose.https.yml", "up", "-d", "--build") }
    "down"     { Invoke-Docker @("down") }
    "down-clean" { Invoke-Docker @("down", "-v") }
    "build"    { Invoke-Docker @("build") }
    "rebuild"  { Invoke-Docker @("build", "--no-cache") }
    "ps"       { Invoke-Docker @("ps") }
    "logs"     {
        if ($Args) { Invoke-Docker @("logs", "-f", "--tail=100") @Args }
        else { Invoke-Docker @("logs", "-f", "--tail=100") }
    }
    "health" {
        Write-Host "=== API ===" -ForegroundColor Cyan
        try { (Invoke-WebRequest -UseBasicParsing http://localhost/api/health -TimeoutSec 3).Content }
        catch { try { (Invoke-WebRequest -UseBasicParsing http://localhost:19001/api/health -TimeoutSec 3).Content } catch { "unreachable" } }
        Write-Host ""
        Write-Host "=== Web ===" -ForegroundColor Cyan
        try { $r = Invoke-WebRequest -UseBasicParsing http://localhost/ -TimeoutSec 3; "HTTP $($r.StatusCode)" }
        catch { "unreachable" }
    }
    "shell" {
        if (-not $Args) { Write-Host "用法: shell <api|web|redis>" -ForegroundColor Yellow; break }
        Invoke-Docker @("exec", $Args[0], "sh")
    }
    "seed" {
        Invoke-Docker @("exec", "api", "python", "-c", "import os; os.environ['SEED_DEMO_ACCOUNTS']='true'; from app.seed import seed_if_empty; from app.core.database import SessionLocal; s=SessionLocal(); seed_if_empty(s); s.close(); print('SEED_DONE')")
    }
    "backup" {
        if (-not (Test-Path backup)) { New-Item -ItemType Directory backup | Out-Null }
        $ts = Get-Date -Format "yyyyMMdd-HHmmss"
        Invoke-Docker @("exec", "-T", "api", "python", "-c", "import shutil; shutil.copy('/app/data/app.db','/app/data/backup-$ts.db'); print('backup-$ts.db created')")
        Invoke-Docker @("cp", "api:/app/data/backup-$ts.db", "./backup/backup-$ts.db")
        Write-Host "==> ./backup/backup-$ts.db" -ForegroundColor Green
    }
    "restore" {
        $file = ($Args | Where-Object { $_ -like "FILE=*" }) -replace "FILE=", ""
        if (-not $file -or -not (Test-Path $file)) {
            Write-Host "用法: restore FILE=<path>" -ForegroundColor Yellow
            break
        }
        Invoke-Docker @("cp", $file, "api:/app/data/restore.db")
        Invoke-Docker @("exec", "api", "sh", "-c", "cp /app/data/restore.db /app/data/app.db")
        Invoke-Docker @("restart", "api")
        Write-Host "==> restored from $file" -ForegroundColor Green
    }
    "validate" {
        Invoke-Docker @("config", "--quiet")
        if ($LASTEXITCODE -eq 0) { Write-Host "compose OK" -ForegroundColor Green }
        if (-not (Test-Path .env)) { Write-Host "⚠️  .env 不存在，复制：cp .env.docker.example .env" -ForegroundColor Yellow }
    }
    "scan" {
        $trivy = Get-Command trivy -ErrorAction SilentlyContinue
        if (-not $trivy) { Write-Host "请先安装 trivy：https://aquasecurity.github.io/trivy/" -ForegroundColor Yellow; break }
        & trivy image welfare-api:latest --severity HIGH,CRITICAL --ignore-unfixed
        & trivy image welfare-web:latest --severity HIGH,CRITICAL --ignore-unfixed
    }
    default {
        Write-Host "未知命令: $Command" -ForegroundColor Red
        Write-Host "运行 .\scripts\docker.ps1 help 查看可用命令"
        exit 1
    }
}
