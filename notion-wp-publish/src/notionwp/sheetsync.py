"""명령줄 진입점 — 노션 플래너의 발행 완료 행을 마스터 시트 발행 로그에 옮겨 적습니다.

    python -m notionwp.sheetsync --dry-run          # 무엇이 들어갈지만 확인
    python -m notionwp.sheetsync                    # 실제 기입
    python -m notionwp.sheetsync --client 제로클리닉  # 한 곳만

대상은 `config/sheet-log.json` 에서 읽습니다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from .config import ConfigError, NotionConfig, load_secrets
from .gsheets import SheetsClient, SheetsError, load_credentials_info
from .notion_api import NotionClient
from .registry import load_defaults
from .runlog import RunLogger
from .sheetlog import SheetLogError, Syncer, load_targets, summarize

log = logging.getLogger(__name__)

STAGE = "마스터 시트 기록"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="notionwp.sheetsync",
        description="노션 콘텐츠 플래너의 발행 완료 행을 고객사 마스터 시트에 기입합니다.",
    )
    parser.add_argument(
        "--client", default="", help="이름에 이 문자열이 들어가는 고객사만 처리합니다."
    )
    parser.add_argument("--config", help="대상 설정 파일 (기본: config/sheet-log.json)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="시트를 건드리지 않고 무엇이 새로 들어갈지만 보여줍니다.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="자세한 로그")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        secrets = load_secrets()
        targets = load_targets(args.config, only=args.client)
        credentials = load_credentials_info()
    except (ConfigError, SheetLogError, SheetsError) as exc:
        print(f"설정 오류\n{exc}", file=sys.stderr)
        return 2

    if not targets:
        print()
        print("대상 고객사가 없습니다. config/sheet-log.json 을 확인하세요.")
        return 0

    defaults = load_defaults()
    notion = NotionClient(
        secrets.notion_token,
        NotionConfig(database_id="", api_version=defaults.notion.api_version),
    )
    sheets = SheetsClient(credentials)

    failed = False
    for target in targets:
        try:
            results = Syncer(target, notion, sheets, dry_run=args.dry_run).run()
        except Exception as exc:
            # 한 고객사가 넘어져도 나머지는 계속 진행합니다.
            print(f"[{target.client}] 실행 중단: {exc}", file=sys.stderr)
            failed = True
            continue

        print()
        print(summarize(target, results, dry_run=args.dry_run))

        # 확인만 한 회차는 로그를 남기지 않습니다. 실제로 시트를 바꾼 회차만 남깁니다.
        if not args.dry_run:
            run_log = replace(defaults.run_log, stage=STAGE)
            RunLogger(run_log, target.client, notion).write(
                results, note=f"플래너 → 마스터 시트 ({target.sheet or '첫 번째 탭'})"
            )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
