#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
荷蘭特價雷達 — Foldoo 爬蟲
每週抓 Foldoo 各超市彙整頁,輸出 data/deals.json 給 App 讀取。

用法:
    python scrape_foldoo.py                 # 正常爬取並寫檔
    python scrape_foldoo.py --dry-run       # 只印出結果,不寫檔
    python scrape_foldoo.py --html a.html AH # 用本機存檔的 HTML 測試某家的解析

注意:
- Foldoo 的公開網頁只顯示每家「Top ~24」筆(其餘在 App 內),所以這裡拿到的是精選熱門特價,
  份量與我們手動彙整時相近。要更完整需另接資料源。
- Foldoo 是 Next.js 站,頁面通常內嵌 __NEXT_DATA__ 的 JSON;程式優先解析它,失敗才退回 HTML。
  若 Foldoo 改版導致解析為 0 筆,調整下方 parse_* 函式即可(GitHub Actions 記錄會顯示每家筆數)。
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---- 設定 ------------------------------------------------------------------

SOURCES = {
    "AH":    "https://foldoo.app/albert-heijn-aanbiedingen",
    "Jumbo": "https://foldoo.app/jumbo-aanbiedingen",
    "Lidl":  "https://foldoo.app/lidl-aanbiedingen",
    "Dirk":  "https://foldoo.app/dirk-aanbiedingen",
}

# 荷蘭文分類 -> App 的四大類。未列到的關鍵字會被歸到 DEFAULT_CAT,SKIP_CATS 直接略過。
CAT_MAP = {
    "fruit": "produce", "groente": "produce", "groenten": "produce", "aardappel": "produce",
    "vlees": "meat", "vis": "meat", "kip": "meat",
    "frisdrank": "snack", "koffie": "snack", "thee": "snack", "chips": "snack",
    "snacks": "snack", "snoep": "snack", "koek": "snack", "zuivel": "snack",
    "kaas": "snack", "brood": "snack", "bier": "snack", "wijn": "snack",
    "diepvries": "snack", "maaltijd": "snack", "pasta": "snack", "rijst": "snack",
    "baby": "baby", "luier": "baby", "babyvoeding": "baby",
}
DEFAULT_CAT = "snack"

# 用「整詞」判斷某一行是不是分類標題(避免把商品名 Kipfilet 誤當成分類 kip)
CAT_LINE_VOCAB = [
    "fruit", "groente", "groenten", "aardappel", "vlees", "vis", "kip", "gevogelte",
    "zuivel", "kaas", "eieren", "brood", "chips", "snacks", "snoep", "koek",
    "frisdrank", "sap", "koffie", "thee", "bier", "wijn", "diepvries",
    "baby", "luiers", "babyvoeding", "verzorging", "drogist", "schoonmaak",
    "huishoudelijk", "huisdier",
]
_CAT_LINE_RE = re.compile(r"\b(" + "|".join(CAT_LINE_VOCAB) + r")\b", re.I)


def is_category_line(text):
    """只有當整行『幾乎就是分類詞本身』才算(如 'Fruit'、'Chips & Snacks'、'Baby'),
    避免把含有 luiers 的商品名(如 'Pampers luiers')誤判成分類。"""
    if len(text) > 22 or not _CAT_LINE_RE.search(text):
        return False
    residue = _CAT_LINE_RE.sub("", text)                 # 拿掉分類關鍵字
    residue = re.sub(r"[&/,\-\s\d]+", " ", residue)       # 拿掉符號/數字/空白
    # 若還剩下像商品名的字(3+ 字母),就不是純分類行
    return not re.search(r"[A-Za-zÀ-ÿ]{3,}", residue)


# 促銷字樣(這些行不是商品名,略過)
_PROMO_RE = re.compile(
    r"(\d+\s*\+\s*\d+|2e\s*halve|halve\s*prijs|gratis|op\s*=\s*op|"
    r"tot\s*-?\d+\s*%|cashback|korting|stapel)", re.I)


def is_name_line(s):
    if _PROMO_RE.search(s):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÿ]{3,}", s))   # 至少有一個像樣的詞
# 非食品類別(清潔、個人護理、寵物、家用等)直接跳過,不進 App
SKIP_CATS = {"verzorging", "schoonmaak", "huishoudelijk", "huisdier", "non food",
             "non-food", "drogisterij", "was", "toilet"}

# 荷蘭文月份縮寫 -> 月
NL_MONTHS = {"jan":1, "feb":2, "mrt":3, "maart":3, "apr":4, "mei":5, "jun":6,
             "jul":7, "aug":8, "sep":9, "sept":9, "okt":10, "nov":11, "dec":12}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "deals.json"
BABY_MANUAL = ROOT / "baby_manual.json"   # 藥妝嬰兒特價(手動維護,每次併入輸出)


# ---- 小工具 ----------------------------------------------------------------

def price_to_float(s):
    """'€2,49' / '2,49' -> 2.49 ; 失敗回 None"""
    if not s:
        return None
    m = re.search(r"(\d+)[.,](\d{2})", str(s))
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"\d+", str(s))
    return float(m.group(0)) if m else None


def parse_validity(text, today=None):
    """'t/m 12 jul' -> ISO 日期字串;抓不到就給今天 +6 天(週檔期預設)。"""
    today = today or dt.date.today()
    if text:
        m = re.search(r"t/m\s+(\d{1,2})\s+([a-z]+)", text.lower())
        if m:
            day = int(m.group(1))
            mon = NL_MONTHS.get(m.group(2)[:3])
            if mon:
                year = today.year
                # 若月份小於本月,視為明年(跨年)
                if mon < today.month:
                    year += 1
                try:
                    return dt.date(year, mon, day).isoformat()
                except ValueError:
                    pass
    return (today + dt.timedelta(days=6)).isoformat()


def map_category(cat_text):
    c = (cat_text or "").lower()
    for kw in SKIP_CATS:
        if kw in c:
            return None
    for kw, target in CAT_MAP.items():
        if kw in c:
            return target
    return DEFAULT_CAT


def discount_pct(orig, sale):
    if orig and sale and orig > sale:
        return round((1 - sale / orig) * 100)
    return None


# ---- 解析:優先 __NEXT_DATA__,退回 HTML ------------------------------------

def _walk_json_for_deals(node, found):
    """遞迴走訪任意 JSON,湊出看起來像特價的物件。"""
    if isinstance(node, dict):
        keys = {k.lower() for k in node.keys()}
        name = node.get("title") or node.get("name") or node.get("productName")
        price = (node.get("price") or node.get("salePrice") or node.get("newPrice")
                 or node.get("actiePrijs"))
        if name and price is not None and ("price" in " ".join(keys) or "prijs" in " ".join(keys)):
            found.append(node)
        for v in node.values():
            _walk_json_for_deals(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_json_for_deals(v, found)


def parse_next_data(html, store):
    """嘗試從 __NEXT_DATA__ 取得結構化特價。回傳 list 或 []。"""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    raw = []
    _walk_json_for_deals(data, raw)
    deals = []
    for r in raw:
        name = r.get("title") or r.get("name") or r.get("productName")
        sale = price_to_float(r.get("price") or r.get("salePrice") or r.get("newPrice") or r.get("actiePrijs"))
        orig = price_to_float(r.get("oldPrice") or r.get("originalPrice") or r.get("fromPrice") or r.get("vanPrijs"))
        cat_text = r.get("category") or r.get("categorie") or ""
        valid = r.get("validUntil") or r.get("endDate") or r.get("geldigTot") or ""
        if not name:
            continue
        d = build_deal(store, name, orig, sale,
                       cat_text if isinstance(cat_text, str) else "",
                       valid, r.get("subtitle") or "")
        if d:
            deals.append(d)
    return dedupe(deals)


def parse_html_cards(html, store):
    """退回方案:用 BeautifulSoup 掃出含價格的卡片。"""
    soup = BeautifulSoup(html, "html.parser")
    deals = []
    # 找出所有含 € 價格的節點,往上找卡片容器
    seen_containers = set()
    def looks_like_card(txt):
        if "€" not in txt or len(txt) > 260:
            return False
        # 需含至少一個「像商品名」的詞(4+ 字母,且不是月份)
        for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", txt):
            if w.lower()[:3] not in NL_MONTHS:
                return True
        return False

    for el in soup.find_all(string=re.compile(r"€\s?\d+[.,]\d{2}")):
        card = el
        for _ in range(6):
            if card.parent is None:
                break
            card = card.parent
            if looks_like_card(card.get_text(" ", strip=True)):
                break
        key = id(card)
        if key in seen_containers:
            continue
        seen_containers.add(key)
        txt = card.get_text("\n", strip=True)
        prices = re.findall(r"€\s?(\d+[.,]\d{2})", txt)
        if not prices:
            continue
        sale = price_to_float(prices[0])
        orig = price_to_float(prices[1]) if len(prices) > 1 else None
        if orig and sale and orig < sale:      # 保證 orig >= sale
            orig, sale = sale, orig
        disc = re.search(r"-?(\d{1,2})\s?%", txt)
        valid = ""
        vm = re.search(r"t/m[^\n]*", txt)
        if vm:
            valid = vm.group(0)
        # 逐行找「名稱」與「分類」
        name, cat_text = "", ""
        for line in txt.split("\n"):
            s = line.strip()
            if not s or "€" in s or "%" in s or s.lower().startswith("t/m"):
                continue
            if not cat_text and is_category_line(s):
                cat_text = s
                continue
            if not name and is_name_line(s):
                name = s
        if not name:
            continue
        d = build_deal(store, name, orig, sale, cat_text, valid,
                       f"-{disc.group(1)}%" if disc else "")
        if d:
            deals.append(d)
    return dedupe(deals)


def build_deal(store, name, orig, sale, cat_text, valid, note):
    cat = map_category(cat_text)
    if cat is None:            # 明確屬於非食品類別 -> 丟棄
        return None
    end = parse_validity(valid) if isinstance(valid, str) else valid
    pct = discount_pct(orig, sale)
    extra = note or ""
    if pct and "%" not in extra:
        extra = (extra + f" -{pct}%").strip()
    return {
        "cat": cat,
        "prod": name.strip(),
        "brand": "",
        "store": store,
        "orig": orig,
        "sale": sale,
        "unit": "",
        "promo": "直接折扣",
        "end": end,
        "note": extra.strip(),
    }


def dedupe(deals):
    out, seen = [], set()
    for d in deals:
        k = (d["store"], d["prod"].lower(), d["sale"])
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


# ---- 主流程 ----------------------------------------------------------------

def load_baby_manual():
    """讀取手動維護的藥妝嬰兒特價;檔案不存在或格式錯就回空清單。"""
    if not BABY_MANUAL.exists():
        return []
    try:
        data = json.loads(BABY_MANUAL.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"baby_manual.json 格式錯誤,略過:{e}", file=sys.stderr)
        return []
    items = data.get("deals", data) if isinstance(data, dict) else data
    clean = []
    for x in items:
        if isinstance(x, dict) and x.get("prod") and x.get("store"):
            x.setdefault("cat", "baby")
            clean.append(x)
    return clean


def scrape_store(store, url, session):
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text
    deals = parse_next_data(html, store)
    if not deals:
        deals = parse_html_cards(html, store)
    return deals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印出,不寫檔")
    ap.add_argument("--html", nargs=2, metavar=("FILE", "STORE"),
                    help="用本機 HTML 檔測試某家解析")
    args = ap.parse_args()

    if args.html:
        path, store = args.html
        html = Path(path).read_text(encoding="utf-8")
        deals = parse_next_data(html, store) or parse_html_cards(html, store)
        print(f"{store}: 解析到 {len(deals)} 筆")
        print(json.dumps(deals, ensure_ascii=False, indent=2))
        return

    session = requests.Session()
    all_deals = []
    supermarket_count = 0
    for store, url in SOURCES.items():
        try:
            d = scrape_store(store, url, session)
            print(f"[{store}] {len(d)} 筆  ({url})")
            all_deals.extend(d)
            supermarket_count += len(d)
        except Exception as e:                       # noqa: BLE001
            print(f"[{store}] 失敗:{e}", file=sys.stderr)
        time.sleep(2)  # 客氣一點

    # 併入手動維護的藥妝嬰兒特價(Kruidvat/Etos),讓「嬰兒用品」每週都在、不被覆蓋
    baby = load_baby_manual()
    print(f"[嬰兒用品] 併入 {len(baby)} 筆(來自 baby_manual.json)")
    all_deals.extend(baby)

    payload = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "foldoo.app(超市)+ baby_manual.json(藥妝嬰兒)",
        "count": len(all_deals),
        "deals": all_deals,
    }

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n共 {len(all_deals)} 筆(dry-run,未寫檔)")
        return

    # 安全閥只看「超市」抓到幾筆:超市解析壞掉時不覆蓋舊檔(嬰兒手動資料不算數)
    if supermarket_count < 8:
        print(f"超市只抓到 {supermarket_count} 筆,疑似解析失效,保留現有 data/deals.json 不覆蓋。",
              file=sys.stderr)
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已寫入 {OUT}({len(all_deals)} 筆)")


if __name__ == "__main__":
    main()
