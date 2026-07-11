#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
荷蘭特價雷達 — 官方 API 爬蟲(AH + Jumbo + Lidl,Dirk 預留)

不走統整站,直接打各超市自家 App 在用的 API:
  AH    : api.ah.nl            匿名 token,免登入
  Jumbo : mobileapi.jumbo.com  完全免驗證(含 promotion-overview)
  Lidl  : Lidl Plus app-gateway 特價端點,免登入(社群已驗證支援 NL)
  Dirk  : app-api.dirk.nl/v2   需要 App 內嵌 x-api-id / x-api-key
          → 設環境變數 DIRK_API_ID / DIRK_API_KEY 才會啟用,否則跳過

⚠️ 這些都是「非官方/逆向工程」端點:超市沒有公開 API,欄位與路徑可能改版,
   使用屬服務條款灰色地帶。僅供個人使用、低頻請求(本程式每次查詢間隔休息)。

輸出 data/deals.json:
  官方 API 抓到的三/四家 + baby_manual.json(藥妝嬰兒)。
  每家有安全閥:某家抓到 0 筆只警告該家、沿用不覆蓋其他家的舊資料。

用法:
    python scrape_official.py             # 全部抓、寫入 data/deals.json
    python scrape_official.py --dry-run   # 只印不寫
    python scrape_official.py --only AH   # 只抓某一家(除錯用)
    python scrape_official.py --debug     # 每家印第一筆原始 JSON(對欄位用)
    python scrape_official.py --selftest  # 不連網,用真實回應格式樣本測解析
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "deals.json"
BABY_MANUAL = ROOT / "baby_manual.json"

# 每分類的搜尋詞(荷文)。查詢詞決定分類 → 分類保證正確。
QUERIES = {
    "produce": ["aardbeien", "appels", "banaan", "tomaten", "komkommer",
                "paprika", "sla", "avocado", "druiven", "kersen", "meloen",
                "broccoli", "bloemkool", "champignons", "sinaasappel",
                "blauwe bessen", "aardappelen", "wortel", "courgette"],
    "meat":    ["kipfilet", "kipdijfilet", "gehakt", "biefstuk", "varkenshaas",
                "spek", "worst", "schnitzel", "hamburger", "zalm", "garnalen"],
    "baby":    ["luiers", "pampers", "nutrilon", "olvarit", "billendoekjes",
                "babyvoeding", "zwitsal"],
    "snack":   ["chips", "cola", "koffie", "thee", "chocolade", "koek",
                "ijs", "kaas", "yoghurt", "melk", "pindakaas", "noten",
                "frisdrank", "sap", "cruesli"],
}

TODAY = dt.date.today


# ---------------------------------------------------------------- 共用工具 --
def week_end(days=6):
    return (TODAY() + dt.timedelta(days=days)).isoformat()


def to_price(v, cents_if_int=False):
    """轉 float。Jumbo 的 amount 是「分」(int 365 = €3.65)→ cents_if_int=True。"""
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("amount", v.get("value"))
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if cents_if_int and isinstance(v, int):
        f = f / 100.0
    return round(f, 2)


def clip_date(s, fallback_days=6):
    if isinstance(s, str) and len(s) >= 10 and s[4] == "-":
        return s[:10]
    return week_end(fallback_days)


def make_deal(store, cat, prod, brand, orig, sale, unit, promo, end, note=""):
    if not prod or sale is None:
        return None
    if orig is not None and sale is not None and orig <= sale:
        orig = None  # 沒有真折扣就別畫刪除線
    return {"cat": cat, "prod": str(prod).strip(), "brand": (brand or "").strip(),
            "store": store, "orig": orig, "sale": sale,
            "unit": ("/ " + unit) if unit and not str(unit).startswith("/") else (unit or ""),
            "promo": promo or "直接折扣", "end": end, "note": note}


def dedupe(deals):
    out, seen = [], set()
    for d in deals:
        if d is None:
            continue
        k = (d["store"], d["prod"].lower(), d["sale"])
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


# ------------------------------------------------------------------- AH ----
AH_TOKEN = "https://api.ah.nl/mobile-auth/v1/auth/token/anonymous"
AH_SEARCH = "https://api.ah.nl/mobile-services/product/search/v2"
AH_UA = "Appie/8.22.3 Model/phone Android/13"


def ah_parse_product(p, cat):
    """AH search 回傳的一筆商品 → deal(非 Bonus 回 None)。"""
    now = to_price(p.get("currentPrice") or p.get("price"))
    before = to_price(p.get("priceBeforeBonus") or p.get("wasPrice"))
    bonus = bool(p.get("isBonus") or p.get("bonus")) or (before and now and now < before)
    if not bonus:
        return None
    promo = "Bonus"
    labels = p.get("discountLabels") or []
    if isinstance(labels, dict):
        labels = [labels]
    for lb in labels:
        if isinstance(lb, dict) and (lb.get("defaultDescription") or lb.get("text")):
            promo = str(lb.get("defaultDescription") or lb.get("text")).strip()
            break
    return make_deal("AH", cat, p.get("title") or p.get("name"), p.get("brand"),
                     before, now, p.get("salesUnitSize") or "",
                     promo, clip_date(p.get("bonusEndDate") or ""), "需 Bonuskaart")


def scrape_ah(debug=False):
    s = requests.Session()
    r = s.post(AH_TOKEN, json={"clientId": "appie"},
               headers={"User-Agent": AH_UA, "Content-Type": "application/json"},
               timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    deals, shown = [], False
    for cat, terms in QUERIES.items():
        for q in terms:
            try:
                r = s.get(AH_SEARCH, params={"query": q, "size": 40, "page": 0},
                          headers={"User-Agent": AH_UA,
                                   "Authorization": f"Bearer {token}"}, timeout=30)
                r.raise_for_status()
                items = r.json().get("products") or []
            except Exception as e:                       # noqa: BLE001
                print(f"  AH '{q}' 失敗:{e}", file=sys.stderr)
                continue
            if debug and items and not shown:
                print("AH 原始樣本:", json.dumps(items[0], ensure_ascii=False)[:1200],
                      file=sys.stderr)
                shown = True
            deals += [ah_parse_product(p, cat) for p in items]
            time.sleep(0.4)
    return dedupe(deals)


# ----------------------------------------------------------------- Jumbo ---
JUMBO_BASE = "https://mobileapi.jumbo.com/v17"
JUMBO_HEADERS = {"User-Agent": "okhttp/4.9.1", "Content-Type": "application/json"}


def jumbo_parse_product(p, cat):
    """Jumbo search 的一筆商品 → deal(沒促銷回 None)。價格單位是分。"""
    promo_obj = p.get("promotion") or p.get("promotions")
    if isinstance(promo_obj, list):
        promo_obj = promo_obj[0] if promo_obj else None
    prices = p.get("prices") or {}
    now = to_price(prices.get("promotionalPrice") or prices.get("price"),
                   cents_if_int=True)
    before = to_price(prices.get("price"), cents_if_int=True) \
        if prices.get("promotionalPrice") else None
    if not promo_obj and before is None:
        return None                      # 沒任何促銷跡象
    promo_txt = "直接折扣"
    end = week_end()
    if isinstance(promo_obj, dict):
        tags = promo_obj.get("tags") or []
        if isinstance(tags, list) and tags and isinstance(tags[0], dict):
            promo_txt = tags[0].get("text") or promo_txt
        end = clip_date(str(promo_obj.get("toDate") or promo_obj.get("validityEnd") or ""))
    return make_deal("Jumbo", cat, p.get("title"), "", before, now,
                     p.get("quantity") or "", promo_txt, end)


def scrape_jumbo(debug=False):
    s = requests.Session()
    deals, shown = [], False
    for cat, terms in QUERIES.items():
        for q in terms:
            try:
                r = s.get(f"{JUMBO_BASE}/search",
                          params={"q": q, "limit": 30, "offset": 0},
                          headers=JUMBO_HEADERS, timeout=30)
                r.raise_for_status()
                items = (r.json().get("products") or {}).get("data") or []
            except Exception as e:                       # noqa: BLE001
                print(f"  Jumbo '{q}' 失敗:{e}", file=sys.stderr)
                continue
            if debug and items and not shown:
                print("Jumbo 原始樣本:", json.dumps(items[0], ensure_ascii=False)[:1200],
                      file=sys.stderr)
                shown = True
            deals += [jumbo_parse_product(p, cat) for p in items]
            time.sleep(0.4)
    return dedupe(deals)


# ------------------------------------------------------------------ Lidl ---
# Lidl Plus app-gateway:門市與特價端點免登入(社群驗證,支援 NL)。
# 端點版本號會演進;失敗時依序嘗試多個版本。
LIDL_STORE_Q = "Rotterdam"     # 用來挑一家門市(特價以門市為準;全國大致相同)
LIDL_VERSIONS = ["v24", "v23", "v22"]
LIDL_UA = "okhttp/4.9.1"


def lidl_parse_offer(o):
    """Lidl offers 的一筆 → deal。欄位名寬容處理。"""
    title = o.get("title") or o.get("name") or o.get("commercialTitle")
    price = o.get("price") or {}
    now = to_price(price.get("deal") or price.get("current") or o.get("dealPrice")
                   or o.get("currentPrice"))
    before = to_price(price.get("regular") or o.get("regularPrice")
                      or o.get("oldPrice"))
    promo = o.get("offerTitle") or o.get("discountText") or "直接折扣"
    end = clip_date(str(o.get("endValidityDate") or o.get("validTo") or ""))
    unit = o.get("packaging") or o.get("unit") or ""
    # Lidl 不給分類 → 用名稱關鍵字歸類,對不到丟 snack 以外的先驗字典
    cat = lidl_guess_cat(f"{title or ''} {o.get('category') or ''}")
    if cat is None:
        return None
    return make_deal("Lidl", cat, title, o.get("brand") or "", before, now,
                     unit, str(promo), end)


_LIDL_CATS = [
    ("baby",    ["luier", "pamper", "baby", "billendoek", "nutrilon"]),
    ("meat",    ["kip", "gehakt", "biefstuk", "varken", "worst", "spek", "zalm",
                 "garnal", "schnitzel", "vlees", "vis", "burger", "saté", "filet"]),
    ("produce", ["aardbei", "appel", "banaan", "tomaat", "komkommer", "paprika",
                 "sla", "avocado", "druif", "kers", "meloen", "broccoli", "bloemkool",
                 "champignon", "sinaasappel", "bes", "aardappel", "wortel", "fruit",
                 "groente", "citroen", "mango", "kiwi", "pruim", "perzik", "nectarine"]),
    ("snack",   ["chips", "cola", "koffie", "thee", "chocola", "koek", "ijs", "kaas",
                 "yoghurt", "melk", "kwark", "pindakaas", "noten", "frisdrank", "sap",
                 "snoep", "drop", "bier", "wijn", "water", "cruesli", "muesli",
                 "pasta", "saus", "mayonaise", "brood"]),
]


def lidl_guess_cat(text):
    low = (text or "").lower()
    for cat, kws in _LIDL_CATS:
        if any(k in low for k in kws):
            return cat
    return None   # 非食品(工具、衣物等 Lidl 週商品)→ 丟棄


def scrape_lidl(debug=False):
    s = requests.Session()
    last_err = None
    for ver in LIDL_VERSIONS:
        base = f"https://appgateway.lidlplus.com/app/{ver}/NL"
        try:
            r = s.get(f"{base}/stores", params={"q": LIDL_STORE_Q},
                      headers={"User-Agent": LIDL_UA, "Accept-Language": "nl-NL"},
                      timeout=30)
            r.raise_for_status()
            stores = r.json()
            if isinstance(stores, dict):
                stores = stores.get("stores") or stores.get("items") or []
            if not stores:
                continue
            store_id = stores[0].get("id") or stores[0].get("storeId")
            r = s.get(f"{base}/offers", params={"storeId": store_id},
                      headers={"User-Agent": LIDL_UA, "Accept-Language": "nl-NL"},
                      timeout=30)
            r.raise_for_status()
            data = r.json()
            offers = data if isinstance(data, list) else \
                (data.get("offers") or data.get("items") or [])
            if debug and offers:
                print("Lidl 原始樣本:", json.dumps(offers[0], ensure_ascii=False)[:1200],
                      file=sys.stderr)
            return dedupe([lidl_parse_offer(o) for o in offers if isinstance(o, dict)])
        except Exception as e:                           # noqa: BLE001
            last_err = e
            continue
    print(f"  Lidl 各版本端點都失敗,最後錯誤:{last_err}", file=sys.stderr)
    return []


# ------------------------------------------------------------------ Dirk ---
def scrape_dirk(debug=False):
    """Dirk 需要 App 內嵌的 x-api-id / x-api-key。設了環境變數才啟用。"""
    api_id, api_key = os.getenv("DIRK_API_ID"), os.getenv("DIRK_API_KEY")
    if not (api_id and api_key):
        print("  Dirk:未設定 DIRK_API_ID / DIRK_API_KEY,跳過(見 README)。")
        return []
    s = requests.Session()
    try:
        r = s.get("https://app-api.dirk.nl/v2/offers",
                  headers={"User-Agent": "okhttp/4.9.1",
                           "x-api-id": api_id, "x-api-key": api_key}, timeout=30)
        r.raise_for_status()
        data = r.json()
        offers = data if isinstance(data, list) else (data.get("offers") or [])
        if debug and offers:
            print("Dirk 原始樣本:", json.dumps(offers[0], ensure_ascii=False)[:1200],
                  file=sys.stderr)
        out = []
        for o in offers:
            title = o.get("name") or o.get("title")
            cat = lidl_guess_cat(title or "")
            if cat is None:
                continue
            out.append(make_deal(
                "Dirk", cat, title, o.get("brand") or "",
                to_price(o.get("normalPrice") or o.get("fromPrice")),
                to_price(o.get("offerPrice") or o.get("price")),
                o.get("packaging") or "", "直接折扣",
                clip_date(str(o.get("endDate") or ""))))
        return dedupe(out)
    except Exception as e:                               # noqa: BLE001
        print(f"  Dirk 失敗:{e}", file=sys.stderr)
        return []


# -------------------------------------------------------------- Kruidvat ---
# kruidvat.nl 是 SAP Hybris(A.S. Watson)電商,嘗試標準 OCC 商品搜尋端點。
# 只查嬰兒關鍵字 → 全部歸「嬰兒用品」。端點站點代碼會嘗試多個候選。
KV_SITES = ["kvn", "kruidvat-nl", "nl"]
KV_QUERIES = ["luiers", "pampers", "billendoekjes", "babyvoeding",
              "nutrilon", "zwitsal", "babydoekjes"]


def kv_parse_product(p):
    """Hybris OCC 商品 → baby deal(沒有促銷跡象回 None)。"""
    title = p.get("name") or p.get("title")
    now = to_price((p.get("price") or {}))
    before = to_price(p.get("formerPrice") or p.get("wasPrice")
                      or p.get("strikePrice"))
    promos = p.get("potentialPromotions") or p.get("promotions") or []
    promo_txt = ""
    if isinstance(promos, list) and promos and isinstance(promos[0], dict):
        promo_txt = (promos[0].get("description") or promos[0].get("title")
                     or "").strip()
    if not promo_txt and not (before and now and now < before):
        return None                       # 沒促銷 → 不收,只收特價品
    return make_deal("Kruidvat", "baby", title, p.get("brand") or "",
                     before, now, "", promo_txt or "促銷", week_end(),
                     "kruidvat.nl 線上價")


def scrape_kruidvat(debug=False):
    s = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
               "Accept": "application/json", "Accept-Language": "nl-NL"}
    for site in KV_SITES:
        base = f"https://www.kruidvat.nl/api/v2/{site}/products/search"
        deals, ok, shown = [], False, False
        for q in KV_QUERIES:
            try:
                r = s.get(base, params={"query": q, "pageSize": 30,
                                        "fields": "FULL", "lang": "nl",
                                        "curr": "EUR"},
                          headers=headers, timeout=30)
                r.raise_for_status()
                items = r.json().get("products") or []
                ok = True
            except Exception as e:                       # noqa: BLE001
                print(f"  Kruidvat[{site}] '{q}' 失敗:{e}", file=sys.stderr)
                break                      # 這個站點代碼不對,換下一個
            if debug and items and not shown:
                print("Kruidvat 原始樣本:",
                      json.dumps(items[0], ensure_ascii=False)[:1200],
                      file=sys.stderr)
                shown = True
            deals += [kv_parse_product(p) for p in items]
            time.sleep(0.4)
        if ok:
            return dedupe(deals)
    return []


# --------------------------------------------------------------- 合併輸出 --
def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return None


def load_baby_manual():
    data = load_json(BABY_MANUAL) or []
    items = data.get("deals", data) if isinstance(data, dict) else data
    return [x for x in items if isinstance(x, dict) and x.get("prod")]


def previous_store_deals(store):
    """安全閥用:某家這次抓 0 筆時,沿用舊檔中該家資料。"""
    data = load_json(OUT)
    if not data:
        return []
    items = data.get("deals", []) if isinstance(data, dict) else data
    return [x for x in items if x.get("store") == store and x.get("cat") != "baby"]


SCRAPERS = {"AH": scrape_ah, "Jumbo": scrape_jumbo, "Lidl": scrape_lidl,
            "Dirk": scrape_dirk, "Kruidvat": scrape_kruidvat}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--only", choices=list(SCRAPERS))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    targets = {args.only: SCRAPERS[args.only]} if args.only else SCRAPERS
    all_deals = []
    for store, fn in targets.items():
        try:
            d = fn(debug=args.debug)
        except Exception as e:                           # noqa: BLE001
            print(f"[{store}] 整家失敗:{e}", file=sys.stderr)
            d = []
        if d:
            print(f"[{store}] 官方 API 抓到 {len(d)} 筆")
            all_deals += d
        else:
            prev = previous_store_deals(store)
            print(f"[{store}] 抓到 0 筆 → 沿用舊資料 {len(prev)} 筆(安全閥)")
            all_deals += prev

    baby = load_baby_manual()
    print(f"[嬰兒用品] 併入 {len(baby)} 筆(baby_manual.json)")
    all_deals += baby

    payload = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
               "source": "官方 App API(api.ah.nl / mobileapi.jumbo.com / Lidl Plus"
                         " / app-api.dirk.nl)+ baby_manual",
               "count": len(all_deals), "deals": all_deals}

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if len(all_deals) < 10:
        print("總筆數過少,不覆蓋舊檔。", file=sys.stderr)
        sys.exit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"已寫入 {OUT}(共 {len(all_deals)} 筆)")


# ---------------------------------------------------------------- 自我測試 --
def selftest():
    # AH:欄位依公開逆向工程文件
    ah = ah_parse_product({
        "title": "AH Aardbeien", "brand": "AH", "salesUnitSize": "400 g",
        "currentPrice": 2.49, "priceBeforeBonus": 3.49, "isBonus": True,
        "bonusEndDate": "2026-07-19",
        "discountLabels": [{"defaultDescription": "25% korting"}]}, "produce")
    assert ah and ah["sale"] == 2.49 and ah["orig"] == 3.49 \
        and ah["promo"] == "25% korting", ah

    # Jumbo:價格單位是「分」(README 實例 365 = €3.65)
    jm = jumbo_parse_product({
        "title": "Jumbo Kipfilet 300g", "quantity": "300 g",
        "prices": {"price": {"amount": 649}, "promotionalPrice": {"amount": 549}},
        "promotion": {"tags": [{"text": "2 voor 10.00"}], "toDate": "2026-07-14"}},
        "meat")
    assert jm and jm["sale"] == 5.49 and jm["orig"] == 6.49 \
        and jm["promo"] == "2 voor 10.00", jm

    # Jumbo 無促銷 → None
    assert jumbo_parse_product({"title": "x",
                                "prices": {"price": {"amount": 100}}}, "snack") is None

    # Lidl:Lidl Plus offers 格式(offerTitle 1+1 等)
    ld = lidl_parse_offer({
        "title": "Verse aardbeien 400g", "offerTitle": "-40%",
        "price": {"regular": 3.29, "deal": 1.99},
        "endValidityDate": "2026-07-12T20:59:59Z", "packaging": "400 g"})
    assert ld and ld["cat"] == "produce" and ld["sale"] == 1.99 \
        and ld["orig"] == 3.29, ld

    # Lidl 非食品(電鑽)→ 丟棄
    assert lidl_parse_offer({"title": "PARKSIDE accuboormachine",
                             "price": {"deal": 29.99}}) is None

    # orig <= sale 時不畫假刪除線
    x = make_deal("AH", "snack", "Test", "", 1.00, 1.50, "", "Bonus", "2026-07-19")
    assert x["orig"] is None

    # Kruidvat:SAP Hybris OCC 格式(promotion 或降價才收)
    kv = kv_parse_product({
        "name": "Pampers Baby-Dry maat 4", "brand": "Pampers",
        "price": {"value": 10.99}, "formerPrice": {"value": 13.49},
        "potentialPromotions": [{"description": "2e halve prijs"}]})
    assert kv and kv["cat"] == "baby" and kv["sale"] == 10.99 \
        and kv["promo"] == "2e halve prijs", kv
    # Kruidvat 沒促銷 → None
    assert kv_parse_product({"name": "Shampoo",
                             "price": {"value": 2.99}}) is None

    print("selftest OK — AH / Jumbo / Lidl / Kruidvat 解析與安全規則全部通過")


if __name__ == "__main__":
    main()
