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
    if args.commentary and Path(args.commentary).exists():
        pack["commentary"] = Path(args.commentary).read_text(encoding="utf-8")

    html = rp.render(pack)
    path = out / f"report-{pack['mode']}-{pack['as_of']}.html"
    path.write_text(html, encoding="utf-8")
    print(str(path))
    return 0


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
    g.set_defaults(func=cmd_report)

    g = sub.add_parser("doctor", help="설정·데이터 상태 점검")
    g.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
