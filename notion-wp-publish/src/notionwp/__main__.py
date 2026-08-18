"""명령줄 진입점.

고객사 발행 설정은 노션 '고객사 설정표'에서 읽어옵니다. 저장소에 고객사별
설정 파일을 만들 필요가 없습니다.

    python -m notionwp --dry-run                     # 활성 고객사 전부
    python -m notionwp --client 클리어톤 --dry-run    # 한 곳만
    python -m notionwp --config config/기타.json      # 표를 거치지 않고 파일로
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config, ConfigError, load_secrets
from .publish import Publisher, summarize
from .registry import load_clients

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="notionwp",
        description="노션 콘텐츠 플래너에서 발행 조건을 만족한 원고를 워드프레스에 발행합니다.",
    )
    parser.add_argument(
        "--config",
        help=(
            "설정표를 쓰지 않고 이 JSON 파일 하나로 실행합니다. "
            "평소에는 쓸 일이 없고, 표에 없는 임시 대상을 돌릴 때만 씁니다."
        ),
    )
    parser.add_argument(
        "--client",
        default="",
        help="설정표의 고객사 중 이름에 이 문자열이 들어가는 곳만 처리합니다.",
    )
    parser.add_argument(
        "--defaults",
        help="공통 설정 파일 경로 (기본: config/defaults.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="워드프레스·노션을 건드리지 않고 어떤 원고가 조건을 통과하는지만 확인합니다.",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help=(
            "임시저장까지만 합니다. 워드프레스에 초안을 만들고 이미지·Rank Math 까지 "
            "채우되 공개하지 않고, 노션 상태도 바꾸지 않습니다."
        ),
    )
    parser.add_argument(
        "--prepare",
        metavar="DIR",
        help=(
            "발행하지 않고, 발행 대상 원고의 이미지를 DIR 에 내려받고 plan.json 을 만듭니다. "
            "이미지를 보고 ALT를 채우기 위한 준비 단계입니다."
        ),
    )
    parser.add_argument(
        "--plan",
        metavar="DIR",
        help=(
            "--prepare 로 만든 DIR 의 plan.json 을 써서 발행합니다. "
            "검수된 ALT와 배치가 그대로 적용됩니다."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="자세한 로그")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.dry_run and args.draft:
        print("--dry-run 과 --draft 는 함께 쓸 수 없습니다.", file=sys.stderr)
        return 2
    if args.prepare and (args.plan or args.draft or args.dry_run):
        print("--prepare 는 단독으로 실행하세요.", file=sys.stderr)
        return 2

    try:
        secrets = load_secrets()
        if args.config:
            configs = [Config.load(Path(args.config))]
        else:
            configs = load_clients(
                secrets.notion_token, defaults_path=args.defaults, only=args.client
            )
    except ConfigError as exc:
        print(f"설정 오류\n{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"고객사 설정표를 읽지 못했습니다: {exc}", file=sys.stderr)
        return 1

    if not configs:
        print()
        print("발행 대상 고객사가 없습니다. 설정표의 상태·워드프레스 주소를 확인하세요.")
        return 0

    failed = False
    for cfg in configs:
        if len(configs) > 1:
            print()
            print(f"━━━ {cfg.client} ━━━")

        publisher = Publisher(
            cfg,
            secrets,
            dry_run=args.dry_run,
            draft=args.draft,
            plan_root=Path(args.plan) if args.plan else None,
        )

        try:
            outcomes = (
                publisher.prepare(Path(args.prepare)) if args.prepare else publisher.run()
            )
        except Exception as exc:
            # 한 고객사가 넘어져도 나머지는 계속 진행합니다.
            print(f"[{cfg.client}] 실행 중단: {exc}", file=sys.stderr)
            failed = True
            continue

        print()
        print(summarize(outcomes))
        failed = failed or any(o.error for o in outcomes)

    # 한 건이라도 실패했으면 0이 아닌 코드로 끝내 루틴 로그에서 눈에 띄게 합니다.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
