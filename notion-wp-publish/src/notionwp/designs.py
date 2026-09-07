"""고객사별 썸네일 디자인을 파일로 굳혀 둡니다.

한 고객사의 썸네일은 늘 같은 모습이어야 합니다. 그래서 색·서체·로고를 매번
다시 정하지 않고, 처음 한 번 정해 `designs/<고객사>.json` 에 적어 둡니다.
이후로는 그 파일만 읽습니다.

    designs/
      클리어톤의원.json      색·서체·영문명·도메인
      logos/클리어톤의원.png  로고 원본

**이미 있는 디자인 파일은 다시 만들지 않습니다.** 고쳐야 하면 사람이 파일을
고치거나, 고쳐 달라고 말해야 합니다. 실행할 때마다 자동으로 다시 정하면
같은 고객사의 썸네일이 조금씩 달라집니다.

색을 홈페이지에서 기계적으로 뽑는 건 믿을 게 못 됩니다 — 실제로 해 보면
카카오톡 상담 버튼 초록색이나 워드프레스 기본 팔레트 파랑이 나옵니다.
그래서 새 고객사는 사람(또는 에이전트)이 로고와 사이트를 보고 한 번 정합니다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .brand import Brand
from .thumbnail import Fonts, Palette

log = logging.getLogger(__name__)

DESIGN_DIR = Path(__file__).resolve().parents[2] / "designs"

PALETTE_KEYS = (
    "background", "accent", "title", "sub", "pill_bg",
    "pill_fg", "brand", "muted", "rule", "ornament",
)


class DesignError(RuntimeError):
    pass


def safe_name(client: str) -> str:
    """파일 이름으로 쓸 고객사 이름. 경로를 벗어나는 글자를 막습니다."""
    cleaned = re.sub(r"[^\w가-힣 .-]", "", (client or "").strip())
    return cleaned.replace("/", "").replace("..", "").strip() or "unnamed"


@dataclass
class Design:
    """한 고객사의 확정된 썸네일 디자인."""

    client: str
    palette: Palette
    name_en: str = ""
    domain: str = ""
    logo: bytes = b""
    logo_mime: str = "image/png"
    latin_font: str = "NataSans"
    hangul_font: str = "NotoSansKR"
    note: str = ""

    def brand(self) -> Brand:
        return Brand(
            name=self.client,
            name_en=self.name_en,
            domain=self.domain,
            color=self.palette.accent,
            logo=self.logo,
            logo_mime=self.logo_mime,
        )

    def fonts(self) -> Fonts:
        return Fonts.bundled(latin=self.latin_font, hangul=self.hangul_font)


def path_for(client: str, directory: Path | None = None) -> Path:
    return (directory or DESIGN_DIR) / f"{safe_name(client)}.json"


def load(client: str, directory: Path | None = None) -> Design | None:
    """확정된 디자인을 읽습니다. 없으면 None — 아직 정해지지 않은 고객사입니다."""
    root = directory or DESIGN_DIR
    path = path_for(client, root)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DesignError(f"디자인 파일을 읽지 못했습니다 ({path}): {exc}") from exc

    missing = [k for k in PALETTE_KEYS if k not in raw.get("palette", {})]
    if missing:
        raise DesignError(f"디자인 파일에 색이 빠졌습니다 ({path}): {', '.join(missing)}")

    logo = b""
    logo_name = raw.get("logo", "")
    if logo_name:
        logo_path = root / "logos" / logo_name
        if logo_path.exists():
            logo = logo_path.read_bytes()
        else:
            # 로고가 없어도 워드마크로 그릴 수 있으므로 멈추지 않습니다.
            log.warning("로고 파일이 없습니다: %s", logo_path)

    return Design(
        client=raw.get("client", client),
        palette=Palette(**{k: raw["palette"][k] for k in PALETTE_KEYS}),
        name_en=raw.get("name_en", ""),
        domain=raw.get("domain", ""),
        logo=logo,
        logo_mime=raw.get("logo_mime", "image/png"),
        latin_font=raw.get("latin_font", "NataSans"),
        hangul_font=raw.get("hangul_font", "NotoSansKR"),
        note=raw.get("note", ""),
    )


def save(design: Design, directory: Path | None = None, *, overwrite: bool = False) -> Path:
    """디자인을 굳힙니다. 이미 있으면 덮어쓰지 않습니다(`overwrite` 로만 가능)."""
    root = directory or DESIGN_DIR
    path = path_for(design.client, root)

    if path.exists() and not overwrite:
        raise DesignError(
            f"'{design.client}' 디자인은 이미 확정되어 있습니다 ({path}). "
            "고치려면 파일을 직접 고치세요 — 자동으로 다시 만들면 썸네일이 달라집니다."
        )

    root.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {
        "client": design.client,
        "name_en": design.name_en,
        "domain": design.domain,
        "latin_font": design.latin_font,
        "hangul_font": design.hangul_font,
        "palette": {k: getattr(design.palette, k) for k in PALETTE_KEYS},
        "note": design.note,
    }

    if design.logo:
        ext = {"image/png": "png", "image/svg+xml": "svg", "image/jpeg": "jpg"}.get(
            design.logo_mime, "png"
        )
        logo_name = f"{safe_name(design.client)}.{ext}"
        (root / "logos").mkdir(parents=True, exist_ok=True)
        (root / "logos" / logo_name).write_bytes(design.logo)
        body["logo"] = logo_name
        body["logo_mime"] = design.logo_mime

    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def known(directory: Path | None = None) -> list[str]:
    root = directory or DESIGN_DIR
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.json"))
