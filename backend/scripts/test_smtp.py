"""本地测 SMTP：在 backend 目录执行
  .\\.venv\\Scripts\\python.exe scripts\\test_smtp.py you@example.com
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ensure backend root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import clear_settings_cache, get_settings  # noqa: E402
from app.services.mail import send_test_email  # noqa: E402


async def main() -> None:
    clear_settings_cache()
    s = get_settings()
    print("smtp_configured =", s.smtp_configured)
    print("server =", s.mail_server, s.mail_port)
    print("user =", s.mail_username)
    print("from =", s.mail_sender)
    print("ssl_tls =", s.mail_ssl_tls, "starttls =", s.mail_starttls)
    if not s.smtp_configured:
        print("ERROR: 请先在 backend/.env 填写 MAIL_SERVER / MAIL_USERNAME / MAIL_PASSWORD")
        sys.exit(1)
    to = (sys.argv[1] if len(sys.argv) > 1 else s.mail_sender).strip()
    print("sending test mail to", to, "...")
    await send_test_email(to=to, settings=s)
    print("OK: sent")


if __name__ == "__main__":
    asyncio.run(main())
