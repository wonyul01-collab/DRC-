"""adops 명령줄 인터페이스.

Hermes 스킬은 이 CLI만 호출한다. 스킬이 SQL이나 계산식을 직접 다루지
않게 하려는 의도다. 명령 표면이 좁을수록 에이전트가 헤매지 않는다.

    python3 -m adops ingest --from 2026-08-01 --to 2026-08-13
    python3 -m adops analyze --date 2026-08-13
    python3 -m adops report  --date 2026-08-13 --out out/
    python3 -m adops doctor
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import analyze as an
from . import config as cfgmod
from . import report as rp
from . import warehouse as wh
from .adapters import build_sources


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def cmd_ingest(args) -> int:
    cfg = cfgmod.load(args.config)
    date_from = args.date_from or _yesterday()
    date_to = args.date_to or date_from
    ts = datetime.now().isoformat(timespec="seconds")

    total, failures = 0, []
    with wh.connect(args.db) as conn:
        for src in build_sources(cfg, only=args.source):
            ok, why = src.available()
            if not ok:
                failures.append(f"{src.name}: {why}")
                wh.log_ingest(conn, ts=ts, source=src.name, table_name="-",
                              date_from=date_from, date_to=date_to, rows=0,
                              ok=False, message=why)
                continue
            try:
                results = src.fetch(date_from, date_to)
            except Exception as exc:                      # noqa: BLE001
                failures.append(f"{src.name}: {exc}")
                wh.log_ingest(conn, ts=ts, source=src.name, table_name="-",
                              date_from=date_from, date_to=date_to, rows=0,
                              ok=False, message=str(exc))
                continue

            for res in results:
                n = wh.upsert(conn, list(res.rows))
                total += n
                wh.log_ingest(conn, ts=ts, source=res.source,
                              table_name=res.table, date_from=date_from,
                              date_to=date_to, rows=n, ok=res.ok,
                              message=res.message)
                status = "OK " if res.ok else "WARN"
                print(f"[{status}] {res.source:<28} {res.table:<13} {n:>6}행"
                      + (f"  · {res.message}" if res.message else ""))
                if not res.ok:
                    failures.append(f"{res.source}: {res.message}")

    print(f"\n총 {total:,}행 적재 ({date_from} ~ {date_to})")
    if failures:
        print("\n경고:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
    # 일부 실패해도 0을 반환한다. 한 채널 때문에 리포트 전체가 멈추면 안 된다.
    return 0


def cmd_analyze(args) -> int:
    cfg = cfgmod.load(args.config)
    day = args.date or _yesterday()
    with wh.connect(args.db) as conn:
        pack = an.build(conn, cfg, day, mode=args.mode)
    path = an.write(pack, args.out or OUT_DIR)
    print(str(path))
    if args.stdout:
        print(json.dumps(pack, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_report(args) -> int:
    cfg = cfgmod.load(args.config)
    day = args.date or _yesterday()
    out = Path(args.out or OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)

    if args.pack:
        pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
    else:
        with wh.connect(args.db) as conn:
            pack = an.build(conn, cfg, day, mode=args.mode)
        an.write(pack, out)

    # Hermes가 작성한 해석을 본문에 끼워 넣는다.
    #
    # 파일이 없으면 조용히 건너뛰지 않고 실패시킨다. 예전에는 건너뛰었는데,
    # 그러면 해석이 통째로 빠진 리포트가 정상인 것처럼 생성되어 그대로
    # 발송된다. 숫자만 있고 개선방안이 없는 리포트는 목적을 잃는다.
    if args.commentary:
        cpath = Path(args.commentary)
        if not cpath.exists():
            print(f"오류: 코멘터리 파일이 없습니다 — {cpath}\n"
                  f"      쓰기 권한이 막힌 경로에 작성하려 했을 수 있습니다. "
                  f"저장소 안(out/)에 쓰세요.", file=sys.stderr)
            return 2
        text = cpath.read_text(encoding="utf-8").strip()
        if not text:
            print(f"오류: 코멘터리 파일이 비어 있습니다 — {cpath}", file=sys.stderr)
            return 2
        pack["commentary"] = text

    html = rp.render(pack)
    path = out / f"report-{pack['mode']}-{pack['as_of']}.html"
    path.write_text(html, encoding="utf-8")
    print(str(path))
    # 코멘터리 포함 여부를 눈에 보이게 남긴다. 없이 생성됐는데 모르고
    # 발송하는 일을 막기 위한 신호다.
    print("코멘터리: " + ("포함됨" if pack.get("commentary") else "없음 (숫자만)"))

    if args.mail:
        return _send(pack, path, args)
    return 0


def _send(pack: dict, path: Path, args) -> int:
    from . import mailer
    subject = args.subject or mailer.subject_for(pack)
    if not pack.get("commentary"):
        subject += " (숫자만)"
    try:
        rcpts = mailer.send_report(path, subject, to=args.to,
                                   env_path=args.env, dry_run=args.dry_run)
    except mailer.MailNotConfigured as exc:
        print(f"발송 실패: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:                                # noqa: BLE001
        print(f"발송 실패: {exc}", file=sys.stderr)
        return 3
    verb = "발송 예정" if args.dry_run else "발송 완료"
    print(f"{verb}: {', '.join(rcpts)}")
    print(f"제목: {subject}")
    return 0


def cmd_daily(args) -> int:
    """적재 → 분석 → 리포트 → 발송을 한 번에.

    LLM 을 전혀 쓰지 않는 경로다. 모델 크레딧이 떨어져도 숫자 리포트는
    매일 아침 도착해야 한다. 해석과 개선방안은 빠지지만, 아무것도 오지
    않아 원인조차 모르는 상황보다 낫다.
    """
    day = args.date or _yesterday()
    cfg = cfgmod.load(args.config)

    # 늦게 올라오는 채널이 있으므로 최근 며칠을 함께 다시 넣는다(멱등).
    ing = argparse.Namespace(
        config=args.config, db=args.db, source=None,
        date_from=(date.fromisoformat(day) - timedelta(days=args.backfill)).isoformat(),
        date_to=day,
    )
    cmd_ingest(ing)

    out = Path(args.out or OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    with wh.connect(args.db) as conn:
        pack = an.build(conn, cfg, day, mode=args.mode)
    an.write(pack, out)

    html = rp.render(pack)
    path = out / f"report-{pack['mode']}-{pack['as_of']}.html"
    path.write_text(html, encoding="utf-8")
    print(f"\n리포트: {path}")

    if pack["data_quality"]["gaps"]:
        print("데이터 결손:", file=sys.stderr)
        for g in pack["data_quality"]["gaps"]:
            print(f"  - {g}", file=sys.stderr)

    if args.no_mail:
        return 0
    return _send(pack, path, args)


def cmd_doctor(args) -> int:
    """설정·데이터 상태 점검. 크론을 걸기 전에 먼저 돌린다."""
    cfg = cfgmod.load(args.config)
    print(f"설정 파일       : {cfg.path or '(기본값만 사용 중)'}")
    print(f"기본 마진율     : {cfg.get('default_gross_margin_rate')}")
    print("채널 수수료율   :", cfg.get("channel_fees"))
    print()
    for ch in ("smartstore", "coupang", "own"):
        bep = cfg.bep_roas(ch)
        print(f"  {ch:<12} 손익분기 ROAS "
              + (f"{bep*100:,.0f}%" if bep else "계산불가(마진<수수료)"))
    print()

    sources = build_sources(cfg)
    print("데이터 소스:")
    for src in sources:
        ok, why = src.available()
        print(f"  [{'O' if ok else 'X'}] {src.name}" + (f" — {why}" if why else ""))
    print()

    with wh.connect(args.db) as conn:
        for table in ("spend", "sales", "search_terms", "catalog"):
            row = conn.execute(
                f"SELECT COUNT(*) n, MIN(date) a, MAX(date) b FROM {table}"
                if table != "catalog" else
                "SELECT COUNT(*) n, NULL a, NULL b FROM catalog"
            ).fetchone()
            span = f"{row['a']} ~ {row['b']}" if row["a"] else "-"
            print(f"  {table:<14} {row['n']:>8,}행   {span}")

        # 원가 누락은 수익성 분석 전체를 무의미하게 만든다.
        missing = conn.execute(
            "SELECT COUNT(DISTINCT s.sku) n FROM sales s "
            "LEFT JOIN catalog c ON c.sku = s.sku "
            "WHERE s.sku != '' AND (c.sku IS NULL OR c.cogs = 0)"
        ).fetchone()["n"]
        if missing:
            print(f"\n  경고: 원가 미등록 SKU {missing}개 — "
                  f"해당 매출은 기본 마진율로 추정됩니다.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adops", description="광고 효율 분석 파이프라인")
    p.add_argument("--config", help="설정 파일 경로")
    p.add_argument("--db", help="SQLite 경로")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("ingest", help="채널 데이터 적재")
    g.add_argument("--from", dest="date_from")
    g.add_argument("--to", dest="date_to")
    g.add_argument("--source", help="특정 소스만 (csv, naver_sa, ...)")
    g.set_defaults(func=cmd_ingest)

    g = sub.add_parser("analyze", help="분석 팩(JSON) 생성")
    g.add_argument("--date")
    g.add_argument("--mode", choices=["daily", "monthly"], default="daily")
    g.add_argument("--out")
    g.add_argument("--stdout", action="store_true", help="JSON을 표준출력에도")
    g.set_defaults(func=cmd_analyze)

    g = sub.add_parser("report", help="HTML 리포트 생성")
    g.add_argument("--date")
    g.add_argument("--mode", choices=["daily", "monthly"], default="daily")
    g.add_argument("--out")
    g.add_argument("--pack", help="기존 분석 팩 재사용")
    g.add_argument("--commentary", help="Hermes가 쓴 해석 텍스트 파일(HTML 조각)")
    g.add_argument("--mail", action="store_true", help="생성 후 메일 발송")
    g.add_argument("--to", help="수신자 (미지정 시 EMAIL_HOME_ADDRESS)")
    g.add_argument("--subject", help="제목 직접 지정")
    g.add_argument("--env", help=".env 경로 (기본 /opt/data/.env)")
    g.add_argument("--dry-run", action="store_true", help="발송 없이 대상만 확인")
    g.set_defaults(func=cmd_report)

    # LLM 없이 도는 폴백 경로. 크론이 이것을 부른다.
    g = sub.add_parser("daily", help="적재→분석→리포트→발송 일괄 (LLM 불필요)")
    g.add_argument("--date")
    g.add_argument("--mode", choices=["daily", "monthly"], default="daily")
    g.add_argument("--out")
    g.add_argument("--backfill", type=int, default=3,
                   help="함께 재적재할 이전 일수 (기본 3)")
    g.add_argument("--to")
    g.add_argument("--subject")
    g.add_argument("--env")
    g.add_argument("--no-mail", action="store_true", help="발송 없이 생성만")
    g.add_argument("--dry-run", action="store_true")
    g.set_defaults(func=cmd_daily, commentary=None, pack=None, mail=True)

    g = sub.add_parser("doctor", help="설정·데이터 상태 점검")
    g.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
