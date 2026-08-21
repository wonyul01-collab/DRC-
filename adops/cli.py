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
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import analyze as an
from . import config as cfgmod
from . import metrics as mx
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
    out_dir = args.out or OUT_DIR
    path = an.write(pack, out_dir)
    bpath = an.write_brief(pack, out_dir)
    print(str(path))
    print(str(bpath))
    if args.brief:
        # 요약본만 표준출력에 낸다. 전체 팩은 7만자라 모델 컨텍스트에
        # 그대로 넣으면 토큰 비용이 10배 이상 든다.
        print(json.dumps(an.brief(pack), ensure_ascii=False, indent=1,
                         default=str))
    elif args.stdout:
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
    an.write_brief(pack, out)

    html = rp.render(pack)
    path = out / f"report-{pack['mode']}-{pack['as_of']}.html"
    path.write_text(html, encoding="utf-8")
    print(f"\n리포트: {path}")

    if pack["data_quality"]["gaps"]:
        print("데이터 결손:", file=sys.stderr)
        for g in pack["data_quality"]["gaps"]:
            print(f"  - {g}", file=sys.stderr)

    if not args.mail:
        return 0
    return _send(pack, path, args)


def cmd_automap(args) -> int:
    """채널별 상품 목록을 상품명으로 대조해 통합 SKU 매핑을 자동 생성한다.

    상품이 수백 개면 손으로 짝지을 수 없다. 이름이 대체로 비슷하므로
    그것으로 후보를 찾되, 수량·용량이 다르면(30포 vs 60포) 짝짓지 않는다.
    잘못 묶으면 원가가 통째로 틀어져 수익성 판정이 어긋나기 때문이다.

    확신이 낮은 짝은 자동 확정하지 않고 사람이 볼 목록으로 넘긴다.
    """
    import csv as _csv
    from . import automap as am

    with wh.connect(args.db) as conn:
        items = am.collect_items(conn)
        # 카탈로그의 기존 SKU 와 상품명. 이미 원가를 입력해 둔 상품이면
        # 그 SKU 를 재사용해야 원가가 연결된다.
        catalog = {
            r["sku"]: am.Item("catalog", r["sku"], r["product_name"] or "",
                              float(r["price"] or 0))
            for r in conn.execute(
                "SELECT sku, product_name, price FROM catalog")
        }

    if not items:
        print("상품 정보가 없습니다. 상품 목록이나 매출 데이터를 먼저 적재하세요.",
              file=sys.stderr)
        print("  상품 목록 폴더: data/raw/products_smartstore, products_coupang, "
              "products_own", file=sys.stderr)
        return 2

    by_channel: dict[str, int] = {}
    for it in items:
        by_channel[it.channel] = by_channel.get(it.channel, 0) + 1
    print("대조 대상:", ", ".join(f"{k} {v}개" for k, v in sorted(by_channel.items())))
    if len(by_channel) < 2:
        print("\n채널이 하나뿐이라 대조할 상대가 없습니다.", file=sys.stderr)
        print("다른 채널의 상품 목록도 넣어주세요.", file=sys.stderr)
        return 2

    groups, review = am.build_groups(items, threshold=args.threshold)

    counter = [0]
    # 새로 만드는 SKU 번호가 기존과 겹치지 않게 시작점을 뒤로 민다.
    for sku in catalog:
        m = re.match(r"SKU-(\d+)$", sku)
        if m:
            counter[0] = max(counter[0], int(m.group(1)))

    rows, matched_groups, reused = [], 0, 0
    for g in sorted(groups, key=lambda g: -len(g)):
        channels = {i.channel for i in g}
        if len(channels) < 2:
            continue                       # 짝을 못 찾은 단일 채널 상품
        matched_groups += 1
        sku, why = am.assign_sku(g, catalog, counter)
        if why != "신규 부여":
            reused += 1
        for it in sorted(g, key=lambda x: x.channel):
            rows.append([it.channel, it.code, sku, f"{it.name} [{why}]"])

    out = Path(args.out or "sku_map_자동생성.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["채널", "채널상품코드", "통합SKU", "비고"])
        w.writerows(rows)

    print(f"\n자동 매칭: {matched_groups}개 상품군 / {len(rows)}개 코드")
    print(f"  기존 카탈로그 SKU 재사용 {reused}개, 신규 부여 "
          f"{matched_groups - reused}개")
    print(f"  → {out}")

    if review:
        rp_path = out.with_name(out.stem + "_검토필요.csv")
        with rp_path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = _csv.writer(fh)
            w.writerow(["유사도", "채널A", "코드A", "상품명A",
                        "채널B", "코드B", "상품명B", "판단근거"])
            for pr in review[:200]:
                w.writerow([f"{pr.score*100:.0f}%",
                            pr.left.channel, pr.left.code, pr.left.name,
                            pr.right.channel, pr.right.code, pr.right.name,
                            pr.reason])
        print(f"\n확신이 낮아 보류한 짝 {len(review)}건 → {rp_path}")
        print("  같은 상품이 맞으면 자동생성 파일에 같은 통합SKU로 추가하세요.")

    unmatched = [g[0] for g in groups if len({i.channel for i in g}) < 2]
    if unmatched:
        print(f"\n짝을 못 찾은 상품 {len(unmatched)}개 "
              f"(한 채널에만 있거나 이름이 크게 다름)")
        for it in unmatched[:5]:
            print(f"  {it.channel:<11} {it.code:<16} {it.name[:30]}")

    print()
    print("확인 후 data/raw/sku_map/ 에 넣고 다시 적재하면 적용됩니다.")
    print("  주의: 자동 매칭 결과를 그대로 믿지 말고, 상품명이 실제로 같은")
    print("        상품인지 훑어보세요. 잘못 묶이면 원가가 틀어집니다.")
    return 0


def cmd_skumap(args) -> int:
    """매핑이 필요한 채널 상품코드를 뽑아 채워넣을 서식을 만든다.

    채널마다 코드 체계가 달라 매핑표가 필요한데, 어떤 코드가 있는지 사람이
    일일이 찾아 적는 것은 번거롭고 빠뜨리기 쉽다. 실제 데이터에서 아직
    원가가 대조되지 않는 코드만 추려 매출 큰 순서로 내보낸다.

    사용자는 '통합SKU' 한 칸만 채우면 된다.
    """
    import csv as _csv

    with wh.connect(args.db) as conn:
        rows = conn.execute(
            "SELECT ch, raw, name, SUM(rev) rev FROM ("
            "  SELECT s.store_channel ch, s.sku raw, MAX(s.product_name) name, "
            "         SUM(s.net_sales) rev "
            "    FROM sales s LEFT JOIN catalog c "
            "      ON c.sku = canon_sku(s.store_channel, s.sku) "
            "   WHERE s.sku != '' AND (c.sku IS NULL OR c.cogs = 0) "
            "   GROUP BY 1,2 "
            "  UNION ALL "
            "  SELECT p.store_channel, p.sku, '', 0 "
            "    FROM spend p LEFT JOIN catalog c2 "
            "      ON c2.sku = canon_sku(p.store_channel, p.sku) "
            "   WHERE p.sku != '' AND (c2.sku IS NULL OR c2.cogs = 0) "
            "   GROUP BY 1,2"
            ") GROUP BY ch, raw ORDER BY rev DESC"
        ).fetchall()

    if not rows:
        print("매핑이 필요한 코드가 없습니다. 모든 상품코드가 원가와 대조됩니다.")
        return 0

    out = Path(args.out or "sku_map_작성용.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["채널", "채널상품코드", "통합SKU", "비고"])
        for r in rows:
            # 통합SKU 는 비워둔다. 사람이 채울 칸이라는 것을 분명히 하기 위해서.
            w.writerow([r["ch"], r["raw"], "",
                        f"{r['name'] or ''} (매출 {float(r['rev'] or 0):,.0f}원)"])

    print(f"{out}  ({len(rows)}개 코드)")
    print()
    print("이 파일의 '통합SKU' 칸만 채우세요. 같은 상품이면 같은 값을 적습니다.")
    print("예:  smartstore, 1234567890, SKU-1001")
    print("     coupang,    87654321,   SKU-1001   ← 같은 상품이므로 같은 SKU")
    print()
    print("채운 뒤 data/raw/sku_map/ 에 넣고 다시 적재하면 적용됩니다.")
    return 0


def cmd_classify(args) -> int:
    """채널에서 받은 CSV 를 알맞은 폴더로 분류한다.

    폴더가 아홉 개라 손으로 넣다 보면 틀리기 쉽고, 잘못 넣으면 그 채널만
    빠진 리포트가 조용히 나간다. 헤더를 보고 어디에 속하는지 판정해준다.
    """
    from .adapters.csv_source import RAW_ROOT, classify

    src = Path(args.dir)
    if not src.exists():
        print(f"오류: 폴더가 없습니다 — {src}", file=sys.stderr)
        return 2

    files = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in (".csv", ".tsv", ".txt"))
    if not files:
        print(f"{src} 에 CSV 파일이 없습니다.")
        return 0

    dest_root = Path(args.to or RAW_ROOT)
    moved, unsure = 0, []

    for f in files:
        cands = classify(f)
        if not cands or cands[0][1] < 0.4:
            unsure.append(f)
            print(f"[?]  {f.name}")
            if cands:
                print(f"       가장 가까운 후보: {cands[0][0]} (일치율 "
                      f"{cands[0][1]*100:.0f}%)")
            else:
                print("       인식 실패 — 헤더를 확인하세요")
            continue

        name, ratio, hit = cands[0]
        mark = "OK " if ratio >= 0.7 else "~  "
        print(f"[{mark}] {f.name}")
        print(f"       → {name}  (일치율 {ratio*100:.0f}%, 인식 {len(hit)}개 컬럼)")
        if len(cands) > 1 and cands[1][1] > ratio * 0.8:
            print(f"       주의: {cands[1][0]} 와 비슷합니다. 결과를 확인하세요")

        if args.move:
            target = dest_root / name
            target.mkdir(parents=True, exist_ok=True)
            f.rename(target / f.name)
            print(f"       이동: {target}/{f.name}")
            moved += 1

    print()
    if args.move:
        print(f"{moved}개 이동 완료.")
    else:
        print("실제로 옮기려면 --move 를 붙이세요.")
    if unsure:
        print(f"\n분류하지 못한 파일 {len(unsure)}개:")
        for f in unsure:
            print(f"  - {f.name}")
        print("  헤더를 보여주시면 어댑터에 별칭을 추가할 수 있습니다:")
        print(f"  head -1 '{unsure[0]}'")
    return 0


def cmd_doctor(args) -> int:
    """설정·데이터 상태 점검. 크론을 걸기 전에 먼저 돌린다."""
    cfg = cfgmod.load(args.config)
    print(f"설정 파일       : {cfg.path or '(기본값만 사용 중)'}")
    print(f"기본 마진율     : {cfg.get('default_gross_margin_rate')}")
    print("채널 수수료율   :", cfg.get("channel_fees"))
    print()

    # 리포트가 실제로 쓰는 값을 그대로 보여준다. 예전에는 기본 마진율로만
    # 계산해서 출력했는데, 분석은 카탈로그 원가로 가중평균한 실제 마진을
    # 쓰기 때문에 둘이 달랐다. 여기서 확인한 숫자와 리포트의 판정 기준이
    # 어긋나면, 맞는 값을 틀렸다고 판단해 엉뚱한 곳을 고치게 된다.
    with wh.connect(args.db) as conn:
        actual = mx.channel_margin_rates(conn, cfg)
        has_cogs = conn.execute(
            "SELECT COUNT(*) n FROM catalog WHERE cogs > 0").fetchone()["n"]

    default_gm = float(cfg.get("default_gross_margin_rate", 0.45))
    src = "카탈로그 원가 기준" if has_cogs else "기본 마진율 기준(원가 미등록)"
    print(f"손익분기 ROAS   ({src})")
    for ch in ("smartstore", "coupang", "own"):
        gm = actual.get(ch, default_gm)
        bep = cfg.bep_roas(ch, gm)
        line = (f"{bep*100:,.0f}%" if bep else "계산불가(마진<수수료)")
        print(f"  {ch:<12} {line:>22}   (매출총이익률 {gm*100:.1f}%"
              f" − 수수료 {cfg.fee_rate(ch)*100:.2f}%)")
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
        # 채널마다 상품코드가 달라서 sku_map 을 거쳐 대조한다.
        rows = conn.execute(
            "SELECT s.store_channel ch, s.sku raw, "
            "       canon_sku(s.store_channel, s.sku) resolved, "
            "       SUM(s.net_sales) rev "
            "FROM sales s LEFT JOIN catalog c "
            "  ON c.sku = canon_sku(s.store_channel, s.sku) "
            "WHERE s.sku != '' AND (c.sku IS NULL OR c.cogs = 0) "
            "GROUP BY 1,2 ORDER BY rev DESC"
        ).fetchall()
        n_map = conn.execute("SELECT COUNT(*) n FROM sku_map").fetchone()["n"]
        print(f"\n  SKU 매핑 등록: {n_map}건")
        if rows:
            total = sum(float(r["rev"] or 0) for r in rows)
            print(f"  경고: 원가가 대조되지 않는 상품코드 {len(rows)}개 "
                  f"(해당 매출 {total:,.0f}원) — 기본 마진율로 추정됩니다.")
            print("        매출 상위 항목:")
            for r in rows[:8]:
                print(f"          {r['ch']:<11} {str(r['raw'])[:24]:<26} "
                      f"{float(r['rev'] or 0):>13,.0f}원")
            print("        catalog 에 없는 코드라면 sku_map 에 매핑을 추가하세요.")
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
    g.add_argument("--stdout", action="store_true", help="전체 팩을 표준출력에 (토큰 소모 큼)")
    g.add_argument("--brief", action="store_true",
                   help="요약본만 표준출력에 (권장, 전체 대비 약 1/10)")
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
    # 기본 동작은 발송이다. --mail 은 크론 줄에서 의도를 드러내기 위한
    # 명시적 별칭이고, --no-mail 로 끈다.
    g.add_argument("--mail", dest="mail", action="store_true", default=True,
                   help="메일 발송 (기본 동작)")
    g.add_argument("--no-mail", dest="mail", action="store_false",
                   help="발송 없이 생성만")
    g.add_argument("--dry-run", action="store_true")
    g.set_defaults(func=cmd_daily, commentary=None, pack=None)

    g = sub.add_parser("automap", help="상품명으로 통합 SKU 매핑 자동 생성")
    g.add_argument("--out", help="저장할 파일명 (기본 sku_map_자동생성.csv)")
    g.add_argument("--threshold", type=float, default=0.72,
                   help="후보로 볼 최소 유사도 (기본 0.72)")
    g.set_defaults(func=cmd_automap)

    g = sub.add_parser("skumap", help="매핑이 필요한 상품코드를 서식으로 추출")
    g.add_argument("--out", help="저장할 파일명 (기본 sku_map_작성용.csv)")
    g.set_defaults(func=cmd_skumap)

    g = sub.add_parser("classify", help="받은 CSV를 알맞은 폴더로 분류")
    g.add_argument("--dir", default="/opt/data/incoming",
                   help="분류할 파일이 있는 폴더 (기본 /opt/data/incoming)")
    g.add_argument("--to", help="대상 루트 (기본 data/raw)")
    g.add_argument("--move", action="store_true", help="실제로 이동")
    g.set_defaults(func=cmd_classify)

    g = sub.add_parser("doctor", help="설정·데이터 상태 점검")
    g.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
