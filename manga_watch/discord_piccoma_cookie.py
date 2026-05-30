from __future__ import annotations

from typing import Callable, Mapping, Optional

from manga_watch.piccoma_cookie import PiccomaCookieSaveError, save_piccoma_cookie_secret

PICCOMA_COOKIE_COMMAND = "piccoma-cookie"
PICCOMA_COOKIE_SET_SUBCOMMAND = "set"
PICCOMA_COOKIE_SET_MODAL_CUSTOM_ID = "piccoma_cookie:set"
PICCOMA_COOKIE_INPUT_CUSTOM_ID = "piccoma_cookie_value"


class PiccomaCookieCommandHandler:
    def __init__(
        self,
        *,
        secret_saver: Callable[[str], None] = save_piccoma_cookie_secret,
    ):
        self.secret_saver = secret_saver

    @classmethod
    def from_env(cls) -> "PiccomaCookieCommandHandler":
        return cls()

    def build_set_modal(self) -> Mapping[str, object]:
        return {
            "custom_id": PICCOMA_COOKIE_SET_MODAL_CUSTOM_ID,
            "title": "ピッコマ cookie 更新",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": PICCOMA_COOKIE_INPUT_CUSTOM_ID,
                            "label": "Cookie header",
                            "style": 2,
                            "required": True,
                            "min_length": 3,
                            "placeholder": "name=value; name2=value2",
                        }
                    ],
                }
            ],
        }

    def handle_modal_submit(self, data: Mapping[str, object]) -> Mapping[str, object]:
        cookie_header = _modal_text_value(data, PICCOMA_COOKIE_INPUT_CUSTOM_ID)
        try:
            self.secret_saver(cookie_header or "")
        except PiccomaCookieSaveError as exc:
            return {"content": f"ピッコマ cookie を保存できませんでした: {exc}", "components": []}
        except Exception:
            return {"content": "ピッコマ cookie を保存できませんでした。Cloud Run logs を確認してください。", "components": []}
        return {"content": "ピッコマ cookie を Secret Manager に保存しました。", "components": []}


def _modal_text_value(data: Mapping[str, object], custom_id: str) -> Optional[str]:
    components = data.get("components")
    if not isinstance(components, list):
        return None
    for row in components:
        if not isinstance(row, Mapping):
            continue
        row_components = row.get("components")
        if not isinstance(row_components, list):
            continue
        for component in row_components:
            if not isinstance(component, Mapping):
                continue
            if str(component.get("custom_id") or "") == custom_id:
                value = str(component.get("value") or "").strip()
                return value or None
    return None
