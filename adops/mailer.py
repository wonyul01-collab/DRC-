"""리포트 메일 발송.

Hermes 를 거치지 않고 직접 보낸다. LLM 크레딧이 떨어져도 숫자 리포트는
나가야 하기 때문이다. 실제로 크레딧 소진으로 에이전트가 통째로 멈추는
일이 있었고, 그때 크론이 걸려 있었다면 아침에 메일이 그냥 오지 않고
원인도 드러나지 않았을 것이다.

해석과 개선방안은 LLM 이 필요하지만, 광고비·매출·ROAS·낭비 키워드는
파이썬이 계산한 값이라 모델 없이도 보낼 수 있다.

자격증명은 Hermes 와 같은 .env 를 읽는다. 설정을 두 벌 관리하지 않는다.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path


DEFAULT_ENV = Path("/opt/data/.env")


def load_env(path: str | Path | None = None) -> dict[str, str]:
    """.env 파싱. 이미 프로세스 환경에 있으면 그쪽을 우선한다."""
    out: dict[str, str] = {}
    p = Path(path or os.environ.get("HERMES_ENV") or DEFAULT_ENV)
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k.startswith("EMAIL_"):
                out[k] = v
    for k in ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST",
              "EMAIL_SMTP_PORT", "EMAIL_HOME_ADDRESS", "EMAIL_FROM_NAME"):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


class MailNotConfigured(RuntimeError):
    pass


def _recipients(env: dict[str, str], override: str | None) -> list[str]:
    raw = override or env.get("EMAIL_HOME_ADDRESS", "")
    return [a.strip() for a in re.split(r"[,;]", raw) if a.strip()]


def send_report(
    html_path: str | Path,
    subject: str,
    *,
    to: str | None = None,
    env_path: str | Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    """HTML 리포트를 본문으로 발송. 수신자 목록을 반환한다."""
    env = load_env(env_path)

    missing = [k for k in ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST")
               if not env.get(k)]
    if missing:
        raise MailNotConfigured(
            f"메일 설정 누락: {', '.join(missing)} — "
            f"{env_path or DEFAULT_ENV} 를 확인하세요."
        )

    # 구글 앱 비밀번호를 공백째 넣으면 셸이 잘라 4자만 저장된다.
    # 조용히 인증 실패하는 것보다 여기서 막는 편이 낫다.
    pw = env["EMAIL_PASSWORD"]
    if len(pw) < 8:
        raise MailNotConfigured(
            f"EMAIL_PASSWORD 가 {len(pw)}자입니다. 앱 비밀번호는 공백을 "
            f"제거한 16자여야 합니다. 공백에서 잘렸을 가능성이 높습니다."
        )

    rcpts = _recipients(env, to)
    if not rcpts:
        raise MailNotConfigured("수신자가 없습니다 — EMAIL_HOME_ADDRESS 를 설정하세요.")

    body = Path(html_path).read_text(encoding="utf-8")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((env.get("EMAIL_FROM_NAME", "광고 리포트"),
                              env["EMAIL_ADDRESS"]))
    msg["To"] = ", ".join(rcpts)
    msg["Date"] = formatdate(localtime=True)
    # HTML 을 못 읽는 클라이언트를 위한 대체 본문
    msg.set_content("HTML 리포트입니다. HTML 을 지원하는 메일 앱에서 확인하세요.")
    msg.add_alternative(body, subtype="html")

    if dry_run:
        return rcpts

    host = env["EMAIL_SMTP_HOST"]
    port = int(env.get("EMAIL_SMTP_PORT") or 587)
    ctx = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(env["EMAIL_ADDRESS"], pw)
            s.send_message(msg, to_addrs=rcpts)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(env["EMAIL_ADDRESS"], pw)
            s.send_message(msg, to_addrs=rcpts)
    return rcpts


def subject_for(pack: dict) -> str:
    """리포트 핵심 수치를 제목에 넣는다. 메일함 목록에서 바로 읽히도록."""
    t = pack.get("today", {}).get("totals", {})
    if pack.get("mode") == "monthly":
        mc = pack.get("monthly_close", {})
        mt = mc.get("totals", {})
        label = mc.get("period", {}).get("label", pack.get("as_of", ""))
        return (f"[월마감] {label} · 실매출 {mt.get('realized_sales', 0):,.0f}원 "
                f"· 공헌이익 {mt.get('contribution_profit', 0):,.0f}원")
    warn = " ⚠데이터결손" if pack.get("data_quality", {}).get("gaps") else ""
    return (f"[광고 리포트] {pack.get('as_of', '')} · "
            f"실매출 {t.get('realized_sales', 0):,.0f}원 · "
            f"공헌이익 {t.get('contribution_profit', 0):,.0f}원{warn}")
