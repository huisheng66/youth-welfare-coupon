-- Ubuntu MySQL 8：创建库与账号（在 mysql 客户端执行）
-- sudo mysql < deploy/setup-mysql.sql
-- 或：mysql -u root -p < deploy/setup-mysql.sql

CREATE DATABASE IF NOT EXISTS welfare
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 请修改密码后使用
CREATE USER IF NOT EXISTS 'welfare'@'localhost' IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';
CREATE USER IF NOT EXISTS 'welfare'@'%' IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';

GRANT ALL PRIVILEGES ON welfare.* TO 'welfare'@'localhost';
GRANT ALL PRIVILEGES ON welfare.* TO 'welfare'@'%';
FLUSH PRIVILEGES;
