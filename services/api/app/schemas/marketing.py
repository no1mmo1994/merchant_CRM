"""Schemas for the marketing tab: programs on offer + campaigns joined."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

#: Grab's own status buckets, in the order the Merchant app lists them:
#: always-on first, then live, then everything else. The dashboard
#: follows the same order so the two read the same way.
CAMPAIGN_STATUSES: tuple[str, ...] = (
    "evergreen",
    "ongoing",
    "upcoming",
    "inReview",
    "paused",
    "past",
)

_IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|svg)(\?|$)", re.IGNORECASE)
_IMAGE_HINT_RE = re.compile(r"(image|img|banner|icon|thumb|photo|logo|cover)", re.IGNORECASE)


def _is_expired_signed_url(url: str) -> bool:
    """True for a CloudFront signed URL whose `Expires` has passed.

    Grab hands out signed asset URLs that it does not refresh. Observed on
    2026-08-08: every image for "[Tiêu Điểm] Món ngon giá mềm giảm giá 5k"
    — list thumbnail, `assets.hero`, `assets.thumbnail` and the header
    hero — carried `Expires=1785296064`, i.e. 2026-07-29, and all four
    answered `403 AccessDenied`. Nothing on our side can revive them.

    Reading the timestamp costs nothing and is exact, so a dead URL is
    dropped before it reaches the browser and the card falls back to its
    placeholder instead of a broken-image icon. Unsigned URLs (no
    `Expires`) are always kept — most of Grab's CDN paths are public.
    """
    if "Expires=" not in url:
        return False
    try:
        values = parse_qs(urlparse(url).query).get("Expires") or []
        stamps = [int(v) for v in values if v]
        # Expired only when *every* stamp has passed. Taking just the first
        # would discard a working URL if a second, still-valid `Expires`
        # ever appeared alongside a stale one.
        return bool(stamps) and all(s < time.time() for s in stamps)
    except (ValueError, TypeError):
        # An `Expires` we can't read is not evidence of expiry — let the
        # browser try, and the frontend's error fallback catches it.
        return False


def _https(url: str) -> str:
    """Upgrade an image URL to https.

    Grab hands back its CloudFront assets over plain `http://`. A browser
    on an https dashboard blocks those as mixed content, so every program
    banner would silently render blank in production while looking fine on
    localhost. Verified the same paths serve 200 over https.
    """
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _usable_url(value: Any) -> bool:
    """An http(s) URL we have no proof is dead."""
    return (
        isinstance(value, str)
        and value.startswith(("http://", "https://"))
        and not _is_expired_signed_url(value)
    )


def _find_by_extension(raw: Any, _depth: int = 0) -> str:
    """First URL anywhere in the tree that ends in an image extension."""
    if _depth > 6:
        return ""
    if isinstance(raw, str):
        # An expired URL is not a match, so the walk continues past it —
        # a payload holding both a dead signed asset and a live public one
        # still lands on the live one.
        if _usable_url(raw) and _IMAGE_EXT_RE.search(raw):
            return _https(raw)
        return ""
    if isinstance(raw, dict):
        values: list[Any] = list(raw.values())
    elif isinstance(raw, list):
        values = raw
    else:
        return ""
    for v in values:
        found = _find_by_extension(v, _depth + 1)
        if found:
            return found
    return ""


def _find_by_hint(raw: Any, _depth: int = 0) -> str:
    """First extensionless URL whose key or path merely suggests an image."""
    if _depth > 6:
        return ""
    if isinstance(raw, dict):
        for key, v in raw.items():
            if _usable_url(v) and (
                _IMAGE_HINT_RE.search(key) or _IMAGE_HINT_RE.search(v)
            ):
                return _https(v)
        children: list[Any] = list(raw.values())
    elif isinstance(raw, list):
        children = raw
    else:
        return ""
    for v in children:
        found = _find_by_hint(v, _depth + 1)
        if found:
            return found
    return ""


def find_image_url(raw: Any, _depth: int = 0) -> str:
    """Dig the first plausible image URL out of an arbitrary payload.

    The capture in `marketing/getds_marketinghienco.py` never printed an
    image field, yet the app clearly renders one per program — so the key
    exists but its name is unknown. Guessing a single key name would
    quietly render every card blank if the guess were wrong; matching on
    the *shape* of the value instead works whatever Grab calls it.

    A real image extension anywhere in the payload beats a merely
    image-shaped key anywhere else. That has to be two full passes over
    the tree, not one pass with a fallback per node: interleaving them
    made an extensionless `meta.icon` win over a genuine `photos.thumb.jpg`
    purely because it sat in an earlier branch. Depth-capped because the
    payload nests and this runs per row.
    """
    return _find_by_extension(raw, _depth) or _find_by_hint(raw, _depth)


class SpotlightEvent(BaseModel):
    """One program the store is offered, from `gms/v1/spotlight/events`.

    Carries no discount / co-funding / minimum-order figures — that
    endpoint doesn't return them. `raw` is kept so the UI can surface
    whatever else Grab sent without another backend change, and so a
    future capture of the detail screen has something to compare against.
    """

    event_id: str = ""
    name: str = ""
    description: str = ""
    is_eligible: bool = False
    image_url: str = ""
    #: Filled in from the detail endpoint, which is the only place the
    #: economics live. None when that lookup was skipped or failed — the
    #: card then shows no funding note rather than an invented one.
    is_grab_cofund: bool | None = None
    #: Best funding share across the program's tiers, 0–1. Lets the card
    #: say "Grab tài trợ tới 20%" instead of just "co-funded", which is
    #: the difference between a program worth opening and one that isn't.
    max_grab_funded_pct: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CampaignPerformance(BaseModel):
    """Spend and return for a joined campaign.

    Grab sends these as strings, sometimes in scientific notation
    (`3.64e+06`) — the capture script has a `format_money` helper for
    exactly that. Parsed to numbers here so the UI never has to.
    """

    marketing_spend: float = 0.0
    assisted_sales: float = 0.0
    assisted_orders: int = 0
    #: Return on marketing spend, Grab's `ssmRoms`. 44.9 means 44.9x.
    roms: float = 0.0
    #: False when Grab returned no performance block at all — a campaign
    #: that has not started has no numbers, which is different from one
    #: that ran and returned nothing.
    has_data: bool = False


class MarketingCampaign(BaseModel):
    campaign_id: str = ""
    name: str = ""
    #: Grab's own sub-label, e.g. "Chiến dịch Tiêu điểm".
    campaign_type: str = ""
    #: Which bucket it came from — see `CAMPAIGN_STATUSES`.
    status: str = ""
    start_time: str = ""
    end_time: str = ""
    image_url: str = ""
    performance: CampaignPerformance = Field(default_factory=CampaignPerformance)
    raw: dict[str, Any] = Field(default_factory=dict)


class MarketingCounts(BaseModel):
    in_review: int = 0
    upcoming: int = 0
    ongoing: int = 0
    evergreen: int = 0
    paused: int = 0
    past: int = 0
    total: int = 0


# ── Program detail ───────────────────────────────────────────────────────────
#
# `gms/v1/events/{id}` returns the terms as rendered UI, not as data:
# sections keyed by `uiType`, each with a `params` **JSON string**, and the
# money lives inside Vietnamese sentences —
#   "Giảm 12.000đ cho đơn hàng"
#   "Giá trị đơn hàng tối thiểu 40.000đ"
#   "Grab đồng tài trợ 1.000đ"
#
# So the figures have to be read out of prose. That is fragile by nature, so
# every parsed number keeps the sentence it came from: the UI shows Grab's
# own wording and treats the number as a convenience, never as the record.

#: A VND amount: dot- or comma-grouped thousands, or a bare integer, followed
#: by a currency marker. Requiring the marker is what stops "50%" or a
#: standalone "3" being read as money.
#:
#: The trailing `(?!\w)` is not cosmetic. Vietnamese is full of words starting
#: with đ — "đơn", "đồng", "được" — so a bare `đ` alternative matches the first
#: letter of the *next word*: "tối đa 500 đơn hàng" parsed as 500đ. In a
#: CO_FUND bullet that silently replaces Grab's real contribution with an
#: order-count cap, which is exactly the number this whole feature exists to
#: get right. `\w` is Unicode-aware here, so "đơn" is rejected while
#: "12.000đ", "12.000đ." and "12.000đ/đơn" all still match.
_MONEY_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:đ|₫|vnd)(?!\w)", re.IGNORECASE
)
#: Some programs discount by percentage instead ("MÓN XỊN GIẢM 50%"), which
#: has no fixed VND value — the cost depends on the item.
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def parse_money(text: str) -> int | None:
    """First VND amount in a sentence, or None.

    `12.000đ` → `12000`. Returns None rather than 0 when nothing matches:
    "no figure in this sentence" and "the figure is zero" have to stay
    distinguishable, otherwise a co-funding share Grab never stated would
    read as "Grab pays nothing".
    """
    m = _MONEY_RE.search(text or "")
    if not m:
        return None
    digits = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(digits)
    except ValueError:
        return None


def parse_percent(text: str) -> float | None:
    """First percentage in a sentence, or None."""
    m = _PERCENT_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


#: "tối đa 50.000đ" — the ceiling on a percentage discount. Anchored to the
#: phrase rather than "some money later in the title", because a title can
#: name a minimum order in the same breath ("Giảm 20% cho đơn từ 40.000đ,
#: tối đa 50.000đ") and picking the wrong one understates the cap.
_CAP_ANCHOR_RE = re.compile(r"tối\s*đa|up\s*to|max(?:imum)?", re.IGNORECASE)


def parse_discount_cap(text: str) -> int | None:
    """The "tối đa Yđ" ceiling, or None when the title doesn't state one.

    Requires the anchor phrase. Without it there is no way to tell a cap
    from a minimum order or any other amount in the sentence, and a
    guessed ceiling is worse than an absent one.
    """
    m = _CAP_ANCHOR_RE.search(text or "")
    if not m:
        return None
    return parse_money(text[m.end() :])


def classify_discount(title: str) -> tuple[int | None, float | None, int | None]:
    """Read a tier title as `(flat_vnd, percent, cap_vnd)`.

    Which kind of discount a title states is decided by **whichever figure
    comes first**, not by "is there a percent sign anywhere". Both forms
    routinely carry the other kind of number further along:

        "Giảm 20% tối đa 50.000đ"                  → percent, cap 50.000
        "Giảm 12.000đ, áp dụng 100% thời gian KM"  → flat 12.000

    Scanning for a `%` anywhere would read the second as a 100%-off tier
    and demote its real 12.000đ discount to a cap, which then makes
    `merchant_cost_vnd` unknown — the one number this feature exists to
    produce. Position is what separates them.
    """
    money = _MONEY_RE.search(title or "")
    percent = _PERCENT_RE.search(title or "")

    if percent is not None and (money is None or percent.start() < money.start()):
        return None, parse_percent(title), parse_discount_cap(title)
    return parse_money(title), None, None


class PromoBullet(BaseModel):
    """One condition line under a promo tier, kept verbatim."""

    type: str = ""
    content: str = ""


class PromoTier(BaseModel):
    """One discount option inside a program, with its economics.

    A program can offer several: "giảm 12.000 / giảm 10.000 / giảm 8.000",
    each with its own minimum order and co-funding.
    """

    title: str = ""
    category: str = ""
    #: Grab's own kind for the row: `ORDER` (whole-basket discount) or
    #: `ITEM` (selected dishes). Ad placements carry `*_AD` and are not
    #: tiers at all — see `AdPlacement`.
    kind: str = ""
    #: Set only for a flat discount ("Giảm 12.000đ"). Stays None for a
    #: percentage tier even when the title names a cap in đồng — the cap
    #: is a ceiling, not the amount, and treating it as the amount would
    #: overstate the discount on every order below it.
    discount_vnd: int | None = None
    discount_percent: float | None = None
    #: The "tối đa Yđ" ceiling on a percentage tier. Kept so the figure
    #: isn't thrown away, but deliberately separate from `discount_vnd`.
    discount_cap_vnd: int | None = None
    min_order_vnd: int | None = None
    grab_cofund_vnd: int | None = None
    #: `discount − cofund`. What the store actually pays per order, which
    #: is the number that decides whether a program is worth joining —
    #: Grab never states it directly. None for percentage tiers: the cost
    #: rides on the item price and no fixed figure exists.
    merchant_cost_vnd: int | None = None
    #: `cofund / discount`. Observed range so far is 8–20%, not the
    #: 50–80% one might assume.
    grab_funded_pct: float | None = None
    #: Set when the parsed figures contradict each other — e.g. Grab's
    #: stated contribution exceeds the discount itself. The numbers are
    #: still reported; this exists so a misread can't look clean.
    parse_note: str = ""
    bullets: list[PromoBullet] = Field(default_factory=list)


class AdPlacement(BaseModel):
    """Where a program advertises the store — not a discount tier.

    Grab lists these inside the same `LEVER_ITEM_V2` section as the promo
    tiers, under a "Quảng cáo" group, distinguished only by a `*_AD` row
    type: `CAROUSEL_AD`, `SEARCH_AD`. They restate the campaign's headline
    discount but carry no per-tier terms, because an ad placement has no
    co-funding split — the cost comes out of the ad budget, which the
    `COST` section states separately.

    Mixed in with the tiers they render as promo cards with every economic
    field blank, which reads as "Grab funds an unknown share" for
    something that has no share to fund.
    """

    #: `CAROUSEL_AD`, `SEARCH_AD`, …
    kind: str = ""
    title: str = ""
    #: Grab's `promo.subtitle`, e.g. "Đơn tối thiểu 40.000₫".
    subtitle: str = ""


class EventCostItem(BaseModel):
    title: str = ""
    fee: str = ""
    notes: list[str] = Field(default_factory=list)


class EventScheduleItem(BaseModel):
    label: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)


class EventOptIn(BaseModel):
    """The join action Grab offers at the bottom of the program page."""

    #: Grab's own button label, e.g. "Tham gia chiến dịch".
    cta: str = ""
    #: The terms sentence shown next to it, with its markdown link intact.
    terms: str = ""


class SpotlightEventDetail(BaseModel):
    event_id: str = ""
    name: str = ""
    description: str = ""
    status: str = ""
    #: Banner from `assets.hero`, falling back to the header section.
    hero_image_url: str = ""
    #: The detail payload's own `isEligible`, kept verbatim — but it is
    #: **not** the "can this store join?" signal. Verified against the
    #: live store: all six offered programs come back `isEligible: false`
    #: here while the *list* endpoint says `true` and every one of them
    #: renders an active join button. Use `can_join` instead; this field
    #: exists so the discrepancy stays visible rather than being quietly
    #: dropped.
    is_eligible: bool = False
    #: True when Grab included an OPT_IN action — the only signal in this
    #: payload that actually tracks whether the program is joinable.
    can_join: bool = False
    opt_in: EventOptIn | None = None
    is_promo_stacking: bool = False
    #: None when Grab sent no `LEVER_ITEM_V2` section, i.e. the payload
    #: never said either way. Distinct from False ("Grab stated it does
    #: not co-fund") — the UI must not announce "Grab không đồng tài trợ"
    #: on the strength of a missing section.
    is_grab_cofund: bool | None = None
    tiers: list[PromoTier] = Field(default_factory=list)
    #: Ad placements, kept out of `tiers` — see `AdPlacement`.
    ad_placements: list[AdPlacement] = Field(default_factory=list)
    costs: list[EventCostItem] = Field(default_factory=list)
    schedule: list[EventScheduleItem] = Field(default_factory=list)
    #: `uiType`s present in the payload that this code does not decode.
    #: Reported rather than dropped: Grab adds section types without
    #: notice, and silence would look like "the program has no such terms"
    #: instead of "we didn't read them".
    unknown_sections: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


def _as_params(section: dict[str, Any]) -> dict[str, Any]:
    """`params` arrives as a JSON *string*. Decode, tolerating an object."""
    raw = section.get("params")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _dedupe_tiers(tiers: list[PromoTier]) -> list[PromoTier]:
    """Drop tiers that repeat one already listed, keeping the first.

    Grab really does send the same row twice: #B0T1G100 lists "Giảm
    10.000₫ cho đơn hàng" twice with byte-identical bullets. Two rows the
    operator cannot tell apart are one offer shown twice — and a repeated
    tier makes a program look like it has more options than it does.

    Identity is the whole visible substance — every field the card shows,
    including the parsed figures. The parsed ones matter because a term
    can arrive somewhere other than a bullet: a minimum order stated in
    `promo.subtitle` leaves the bullets empty, so keying on bullets alone
    would merge two tiers whose minimum orders differ and delete a real
    offer. Dropping a genuine tier is worse than showing a duplicate.
    """
    seen: set[tuple[Any, ...]] = set()
    out: list[PromoTier] = []
    for t in tiers:
        key = (
            t.kind,
            t.category,
            t.title,
            tuple((b.type, b.content) for b in t.bullets),
            t.discount_vnd,
            t.discount_percent,
            t.discount_cap_vnd,
            t.min_order_vnd,
            t.grab_cofund_vnd,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _dedupe_ads(ads: list[AdPlacement]) -> list[AdPlacement]:
    seen: set[tuple[str, str, str]] = set()
    out: list[AdPlacement] = []
    for a in ads:
        key = (a.kind, a.title, a.subtitle)
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def parse_event_detail(raw: dict[str, Any]) -> SpotlightEventDetail:
    """Turn the rendered-UI payload into figures the dashboard can rank on."""
    detail = SpotlightEventDetail(
        event_id=str(raw.get("eventID") or ""),
        name=str(raw.get("name") or ""),
        description=str(raw.get("description") or ""),
        status=str(raw.get("status") or ""),
        is_eligible=bool(raw.get("isEligible", False)),
        raw=raw,
    )

    # `assets.hero` is the banner the Merchant app shows above the terms.
    assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
    hero = assets.get("hero") if isinstance(assets.get("hero"), dict) else {}
    hero_path = str(hero.get("path") or "")
    if hero_path and not _is_expired_signed_url(hero_path):
        detail.hero_image_url = _https(hero_path)

    for section in raw.get("sections") or []:
        if not isinstance(section, dict):
            continue
        ui_type = str(section.get("uiType") or "")
        params = _as_params(section)

        if ui_type == "LEVER_ITEM_V2":
            detail.is_promo_stacking = bool(params.get("isPromoStacking"))
            # Presence-checked, not `.get()`-coerced. Now that False means
            # "Grab funds none of it" and drives a 0% / 100% split on the
            # card, an omitted key must stay None — coercing it would put
            # a definite "shop pays everything" on a program that never
            # said so.
            # Scoped to this section, not carried across the loop: with two
            # LEVER sections a flag from the first would otherwise decide
            # the second's tiers, and a stale False forces a "Shop chịu
            # 100%" onto a tier that never claimed it.
            section_cofund: bool | None = None
            if "isGrabCoFund" in params:
                section_cofund = bool(params["isGrabCoFund"])
                detail.is_grab_cofund = section_cofund
            for group in params.get("items") or []:
                if not isinstance(group, dict):
                    continue
                category = str(group.get("title") or "")
                for sub in group.get("subItems") or []:
                    if not isinstance(sub, dict):
                        continue
                    promo = sub.get("promo") if isinstance(sub.get("promo"), dict) else {}
                    title = str(sub.get("title") or promo.get("title") or "")
                    # Grab moves fields between `sub` and `sub.promo` — the
                    # title already needs the same fallback.
                    kind = str(sub.get("type") or promo.get("type") or "")

                    # Ad placements share the section with the promo tiers
                    # but are a different thing: no per-order co-funding
                    # split, so every economic field would render blank.
                    # Suffix match rather than an allowlist — Grab can add
                    # a placement type, and a new one should land here
                    # rather than appear as a tier funding nothing.
                    if kind.endswith("_AD"):
                        detail.ad_placements.append(
                            AdPlacement(
                                kind=kind,
                                title=title,
                                subtitle=str(promo.get("subtitle") or ""),
                            )
                        )
                        continue

                    bullets: list[PromoBullet] = []
                    min_order: int | None = None
                    cofund: int | None = None
                    for b in sub.get("bullets") or []:
                        if not isinstance(b, dict):
                            continue
                        b_type = str(b.get("type") or "")
                        content = str(b.get("content") or "")
                        bullets.append(PromoBullet(type=b_type, content=content))
                        if b_type == "MOV":
                            min_order = parse_money(content)
                        elif b_type == "CO_FUND":
                            cofund = parse_money(content)

                    # Some rows put the minimum order in `promo.subtitle`
                    # instead of a MOV bullet.
                    if min_order is None and promo.get("subtitle"):
                        min_order = parse_money(str(promo["subtitle"]))

                    discount, percent, cap = classify_discount(title)

                    # `isGrabCoFund: false` is Grab stating it funds none
                    # of the discount — not silence. Five of the six
                    # programs this store is offered say exactly that, and
                    # rendering them as "Grab ?%" hides the single most
                    # important fact about them: the store pays all of it.
                    if section_cofund is False and cofund is None:
                        cofund = 0

                    merchant_cost = (
                        discount - cofund
                        if discount is not None and cofund is not None
                        else None
                    )
                    funded = (
                        cofund / discount
                        if discount and cofund is not None and discount > 0
                        else None
                    )
                    # A percentage tier has no đồng figure to divide by,
                    # but "Grab funds none of it" is still a known ratio.
                    if funded is None and cofund == 0:
                        funded = 0.0

                    # A contribution larger than the discount it funds is
                    # not something Grab offers; it means one of the two
                    # sentences was misread. Report both numbers and say
                    # so, rather than clamping to a plausible-looking one.
                    note = ""
                    if merchant_cost is not None and merchant_cost < 0:
                        note = (
                            "Số Grab tài trợ lớn hơn mức giảm — số liệu có thể "
                            "đọc sai, hãy đối chiếu với app Grab Merchant."
                        )
                        # Both raw figures stay visible, but the ratio does
                        # not survive: 12.000/1.000 is "Grab 1200%", which
                        # renders in the green "worth joining" tone and
                        # feeds the overview card's headline share — where
                        # `parse_note` never reaches. A ratio derived from
                        # numbers that contradict each other is not a
                        # number, so it is reported as unknown.
                        funded = None

                    detail.tiers.append(
                        PromoTier(
                            kind=kind,
                            title=title,
                            category=category,
                            discount_vnd=discount,
                            discount_percent=percent,
                            discount_cap_vnd=cap,
                            min_order_vnd=min_order,
                            grab_cofund_vnd=cofund,
                            merchant_cost_vnd=merchant_cost,
                            grab_funded_pct=funded,
                            parse_note=note,
                            bullets=bullets,
                        )
                    )

        elif ui_type == "COST":
            for item in params.get("items") or []:
                if not isinstance(item, dict):
                    continue
                detail.costs.append(
                    EventCostItem(
                        title=str(item.get("title") or ""),
                        fee=str(item.get("eyebrow") or ""),
                        notes=[
                            str(s.get("content") or "")
                            for s in (item.get("subItems") or [])
                            if isinstance(s, dict)
                        ],
                    )
                )

        elif ui_type == "MULTI_CONTENT_V2":
            for item in params.get("items") or []:
                if not isinstance(item, dict):
                    continue
                detail.schedule.append(
                    EventScheduleItem(
                        label=str(item.get("eyebrow") or ""),
                        content=str(item.get("content") or ""),
                        tags=[
                            str(t.get("value") or "")
                            for t in (item.get("tags") or [])
                            if isinstance(t, dict)
                        ],
                    )
                )

        elif ui_type == "EVENT_HEADER":
            # Title/description repeat the top level; the banner does not.
            if not detail.hero_image_url:
                for hero_item in params.get("heroes") or []:
                    if not isinstance(hero_item, dict):
                        continue
                    path = str(hero_item.get("path") or "")
                    if path and not _is_expired_signed_url(path):
                        detail.hero_image_url = _https(path)
                        break
            if not detail.description:
                detail.description = str(params.get("content") or "")

        elif ui_type == "EVENT_FOOTER":
            # Where the join action lives. Its presence is the honest
            # answer to "can this store join?" — see `can_join`.
            for item in params.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type == "OPT_IN":
                    detail.can_join = True
                    detail.opt_in = EventOptIn(
                        cta=str(item.get("cta") or ""),
                        terms=str(item.get("content") or ""),
                    )
                    break
                if item_type:
                    # Same reasoning as `unknown_sections`: if Grab renames
                    # the join action, `can_join` would quietly read False
                    # and the program would look closed. Say what we saw.
                    detail.unknown_sections.append(f"EVENT_FOOTER:{item_type}")

        elif ui_type:
            detail.unknown_sections.append(ui_type)

    detail.tiers = _dedupe_tiers(detail.tiers)
    detail.ad_placements = _dedupe_ads(detail.ad_placements)
    return detail


class MarketingOverviewResponse(BaseModel):
    """Everything the marketing tab needs, in one call.

    Both upstreams are fetched together because the page shows both and
    two round-trips from the browser would only make it slower. Either
    can fail on its own: a failure lands in `warnings` and the other
    half still renders, rather than blanking the page.
    """

    events: list[SpotlightEvent] = Field(default_factory=list)
    campaigns: list[MarketingCampaign] = Field(default_factory=list)
    counts: MarketingCounts = Field(default_factory=MarketingCounts)
    warnings: list[str] = Field(default_factory=list)
