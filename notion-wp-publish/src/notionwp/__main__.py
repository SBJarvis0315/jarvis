"""명령줄 진입점.

    python -m notionwp --config config/cleartone.json --dry-run
    python -m notionwp --config config/cleartone.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config, ConfigError, load_secrets
from .publish import Publisher, summarize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="notionwp",
        description="노션 콘텐츠 플래너에서 발행 조건을 만족한 원고를 워드프레스에 발행합니다.",
    )
    parser.add_argument("--config", required=True, help="고객사 설정 JSON 경로")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제로 발행하지 않고 어떤 원고가 통과하는지만 확인합니다.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="자세한 로그")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        cfg = Config.load(Path(args.config))
        secrets = load_secrets()
    except ConfigError as exc:
        print(f"설정 오류\n{exc}", file=sys.stderr)
        return 2

    publisher = Publisher(cfg, secrets, dry_run=args.dry_run)

    try:
        outcomes = publisher.run()
    except Exception as exc:
        print(f"실행 중단: {exc}", file=sys.stderr)
        return 1

    print()
    print(summarize(outcomes))

    # 한 건이라도 실패했으면 0이 아닌 코드로 끝내 루틴 로그에서 눈에 띄게 합니다.
    return 1 if any(o.error for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
