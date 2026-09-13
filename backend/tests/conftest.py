"""pytest 进程级测试环境隔离（必须最先生效）。

conftest 先于所有测试模块被导入：把 Settings 的 env_file 指向不存在的占位
路径，显式断开与本地 backend/.env（真实 AMAP_WEB_KEY / SMTP / SECRET_KEY）
的 dotenv 回退，保证测试无外部副作用、不因本机配置差异而漂移。

背景：部分测试模块（如 test_activation_outbox）在 import tests._helpers 之前
就先 import 了 app.*，app.core.config 模块加载时 _ENV_FILE 已定格为 ".env"，
导致整个进程的真实 .env 泄漏（2026-09-13 AMAP_WEB_KEY 进入配置使 geo 测试
命中真实高德 API）。此 conftest 从时序上根治；tests/_helpers.py 内的同名
逻辑保留，供非 pytest 入口直接导入时兜底。
"""

import os
from pathlib import Path

os.environ["APP_SETTINGS_ENV_FILE"] = str(Path(__file__).resolve().parent / "_isolated_no_env_file")
