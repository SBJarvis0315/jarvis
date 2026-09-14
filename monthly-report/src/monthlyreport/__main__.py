"""월간 리포트 자동화 CLI.

    PYTHONPATH=src python3 -m monthlyreport period
    PYTHONPATH=src python3 -m monthlyreport inspect --client 참포도나무병원 --out inspect/champodonamu

`period` 는 대상 달을 계산해 JSON 으로 찍습니다. 스킬이 플래너 필터·리포트명·
CSV 파일명을 여기서 받아 씁니다.

`inspect` 는 소하에 로그인해 화면을 떠 둡니다. 발행도 수집도 하지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .period import PeriodError, resolve
from .soha import Credentials, Profile, SohaError, inspect


def _period_payload(args: argparse.Namespace) -> dict[str, object]:
    run_on = date.fromisoformat(args.run_on) if args.run_on else None
    period = resolve(args.month, run_on=run_on)
    previous = period.previous
    payload: dict[str, object] = {
        "대상": period.file_tag,
        "플래너_작업년월": period.planner_option,
        "데이터_기준일": period.snapshot.isoformat(),
        "csv": {
            "당월": [f"{name}-{period.file_tag}.csv" for name in ("prompts", "brand", "sources")],
            "전월": [f"{name}-{previous.file_tag}.csv" for name in ("prompts", "brand", "sources")],
        },
        "전월": {
            "대상": previous.file_tag,
            "플래너_작업년월": previous.planner_option,
        },
    }
    if args.client:
        payload["리포트명"] = period.report_name(args.client)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monthlyreport", description=__doc__)
    parser.add_argument("--month", help="대상 연월 (예: 2026-09). 없으면 실행일의 직전 달")
    parser.add_argument("--run-on", help="실행일을 가장합니다 (예: 2026-10-01). 시험용")
    parser.add_argument("--client", default="", help="고객사 이름 (리포트명 계산용)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("period", help="대상 달을 계산해 JSON 으로 찍습니다")

    scout = sub.add_parser("inspect", help="소하 화면을 떠 둡니다 (수집하지 않음)")
    gather = sub.add_parser("collect", help="소하에서 CSV 3종과 대시보드 캡쳐를 받습니다")
    for parser_ in (scout, gather):
        parser_.add_argument("--out", required=True, help="결과를 남길 디렉터리")
        parser_.add_argument("--slug", default="", help="환경변수 이름에 쓰는 고객사 약칭")
        parser_.add_argument("--soha-user", default="")
        parser_.add_argument("--soha-password", default="")
        parser_.add_argument("--headed", action="store_true", help="창을 띄웁니다")

    args = parser.parse_args(argv)

    try:
        if args.command == "period":
            print(json.dumps(_period_payload(args), ensure_ascii=False, indent=2))
            return 0

        creds = Credentials.resolve(
            args.slug or args.client or "default", args.soha_user, args.soha_password
        )

        if args.command == "collect":
            if not Profile.load().ready:
                raise SohaError(
                    "소하 화면 프로파일이 비어 있어 수집할 수 없습니다.\n"
                    "  먼저 `inspect` 로 화면을 뜨고,"
                    " src/monthlyreport/profiles/soha.json 을 채우세요.\n"
                    "  선택자를 추측해서 넣지 마세요 (inspect/NOTES.md 참고)."
                )
            raise SohaError("수집 단계는 아직 붙이지 않았습니다. inspect 결과가 먼저 필요합니다.")

        out = inspect(Path(args.out), creds, headless=not args.headed)
        print(f"정찰 결과: {out}/inspect.json")
        return 0
    except (PeriodError, SohaError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
