-- Ubuntu MySQL 8：创建库与账号（在 mysql 客户端以 root 执行）
--   sudo mysql < deploy/setup-mysql.sql
--   或：mysql -u root -p < deploy/setup-mysql.sql
--
-- T09 账号职责拆分（全部仅 localhost 来源，不再创建 '%' 账号）：
--   welfare_app     运行账号：仅业务库 DML，无 DDL、无 GRANT
--   welfare_migrate 迁移账号：发布期执行 alembic upgrade head 所需 DDL
--   welfare_backup  备份账号：仅读取与锁表，供 mysqldump 使用
--
-- 密码通过环境变量注入（install-ubuntu.sh 会生成并写入凭据清单），
-- 手工执行时请先替换下面的 CHANGE_ME_* 占位符。

CREATE DATABASE IF NOT EXISTS `welfare`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 1) 运行账号：应用常驻进程使用，凭据保存在 backend/.env
CREATE USER IF NOT EXISTS 'welfare_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
ALTER USER 'welfare_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON `welfare`.* TO 'welfare_app'@'localhost';

-- 2) 迁移账号：仅部署/升级时使用（deploy/migrate-release.sh），凭据不进 worker
CREATE USER IF NOT EXISTS 'welfare_migrate'@'localhost' IDENTIFIED BY 'CHANGE_ME_MIGRATE_PASSWORD';
ALTER USER 'welfare_migrate'@'localhost' IDENTIFIED BY 'CHANGE_ME_MIGRATE_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, DROP, ALTER, INDEX, REFERENCES, CREATE TEMPORARY TABLES
  ON `welfare`.* TO 'welfare_migrate'@'localhost';

-- 3) 备份账号：仅满足 mysqldump（--single-transaction --routines --triggers --events）
--    SHOW_ROUTINE 为全局权限，MySQL 8.0.15+ 支持无全局 SELECT 时导出例程定义
CREATE USER IF NOT EXISTS 'welfare_backup'@'localhost' IDENTIFIED BY 'CHANGE_ME_BACKUP_PASSWORD';
ALTER USER 'welfare_backup'@'localhost' IDENTIFIED BY 'CHANGE_ME_BACKUP_PASSWORD';
GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON `welfare`.* TO 'welfare_backup'@'localhost';
GRANT SHOW_ROUTINE ON *.* TO 'welfare_backup'@'localhost';

FLUSH PRIVILEGES;

-- 历史遗留清理：旧安装曾创建过 ALL 权限的 welfare@localhost / welfare@%。
-- 确认 backend/.env 与 cron 已切换到新账号后再执行：
--   DROP USER IF EXISTS 'welfare'@'%';
--   DROP USER IF EXISTS 'welfare'@'localhost';
