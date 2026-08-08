"""Category management endpoints (translate, create, delete, sort)."""

from __future__ import annotations

from grab.client import GrabClient


async def translate_name(
    client: GrabClient,
    text: str,
    *,
    entity: str = "category",
    text_type: str = "name",
    source_lang: str = "vi",
    target_lang: str = "en",
) -> str:
    """POST /food/merchant/v1/menu-translations — VI → EN translation.

    Returns the English translation string, or empty string if the API
    accepted but returned no translation.
    """
    res = await client.post(
        "/food/merchant/v1/menu-translations",
        json={
            "textSourceLang": source_lang,
            "textType": text_type,
            "textTargetLang": [target_lang],
            "text": text,
            "entity": entity,
        },
    )
    res.raise_for_status()
    data = res.json()
    return (data.get("textTranslation") or {}).get(target_lang, "")


async def create_category(
    client: GrabClient,
    name_vi: str,
    name_en: str,
    *,
    selling_time_id: str = "AlwaysAvailable",
) -> dict:
    """POST /food/merchant/v2/categories — create a new category.

    The payload mirrors the original `creatdanhmuc.py`: the Vietnamese
    name is the canonical `name`, and the English translation is nested
    under `nameTranslation.translation.en`.
    """
    res = await client.post(
        "/food/merchant/v2/categories",
        json={
            "nameTranslation": {
                "translation": {
                    "ko": "",
                    "ja": "",
                    "en": name_en,
                    "zh": "",
                },
                "originalTranslationFromDS": {"en": name_en},
            },
            "sellingTimeID": selling_time_id,
            "name": name_vi,
        },
    )
    res.raise_for_status()
    return res.json()


async def delete_category(client: GrabClient, category_id: str) -> dict | None:
    """DELETE /food/merchant/v2/categories/{id} — delete a category.

    Returns the parsed JSON body if the server sent one, otherwise None.
    """
    res = await client.delete(f"/food/merchant/v2/categories/{category_id}", json={})
    res.raise_for_status()
    if res.content:
        return res.json()
    return None


async def sort_categories(
    client: GrabClient,
    sorts: list[dict],
    *,
    section_by_category: dict[str, str] | None = None,
) -> dict:
    """PUT /food/merchant/categories-sort — reorder categories.

    `sorts` is a list of `{resourceID, sortOrder}` dicts, exactly as
    built by the original `get_sapxepdanhmuc.py`.

    `section_by_category` maps category id → section id, from
    `menu.category_section_map`. Categories are grouped into one
    `sectionSorts` entry per section, because Grab reorders *within* a
    section and a menu can have several.

    Omitting it keeps the captured behaviour — a single group with
    `sectionID: ""` — which is right for a flat menu and wrong for a menu
    built from sections. Callers that can reach the menu should pass it;
    the fallback exists so this stays usable without one.
    """
    if section_by_category:
        grouped: dict[str, list[dict]] = {}
        for entry in sorts:
            section_id = section_by_category.get(str(entry.get("resourceID") or ""), "")
            grouped.setdefault(section_id, []).append(entry)
        section_sorts = [
            {"sectionID": section_id, "sorts": entries}
            for section_id, entries in grouped.items()
        ]
    else:
        section_sorts = [{"sectionID": "", "sorts": sorts}]

    res = await client.put(
        "/food/merchant/categories-sort",
        json={"sectionSorts": section_sorts},
    )
    res.raise_for_status()
    if res.content:
        return res.json()
    return {}
