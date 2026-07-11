# 荷蘭特價雷達 · 自動更新版

四家超市(AH / Jumbo / Lidl / Dirk)+ 藥妝(Kruidvat / Etos)嬰兒用品的特價追蹤。
每週一由 GitHub Actions 自動爬 Foldoo,更新 `data/deals.json`;App 開啟時自動抓最新資料。

```
bonus-radar/
├─ index.html                    # App 本體(手機/電腦瀏覽器直接開)
├─ scrape_foldoo.py              # 爬蟲:抓 Foldoo(超市)+ 併入藥妝嬰兒 → data/deals.json
├─ baby_manual.json              # 藥妝嬰兒特價(Kruidvat/Etos,手動維護,每週併入)
├─ requirements.txt              # 爬蟲相依套件
├─ data/deals.json               # 特價資料(每週被自動更新)
└─ .github/workflows/update.yml  # 每週一自動排程
```

---

## 一次性設定(約 10 分鐘)

### 1. 建 GitHub repo
1. 到 github.com 建一個新的 repo,例如叫 `bonus-radar`(Public 即可)。
2. 把這個資料夾整包上傳(網頁介面拖拉,或用 git push)。

### 2. 打開自動排程權限
1. Repo → **Settings → Actions → General**。
2. 最下面 **Workflow permissions** 選 **Read and write permissions**,存檔。
   (這樣 Actions 才能把更新後的 `deals.json` commit 回來。)

### 3. 先手動跑一次確認
1. Repo → **Actions** 分頁 → 左邊點「每週更新特價」→ 右邊 **Run workflow**。
2. 跑完看 log,每家應該顯示抓到幾筆。若 `data/deals.json` 有被更新即成功。
   > 之後每週一早上會自動跑,你什麼都不用做。

### 4. 讓 App 讀雲端資料
1. 開啟你 repo 裡的 `deals.json` 的 **raw** 網址,長這樣:
   ```
   https://raw.githubusercontent.com/你的帳號/bonus-radar/main/data/deals.json
   ```
2. 用瀏覽器開 `index.html`(下載到手機/電腦,或用 GitHub Pages 掛上線)。
3. 底部按 **設定自動來源** → 貼上上面那個 raw 網址 → 確定。
   之後每次開 App 都會自動同步;也可隨時按 **立即同步雲端**。

完成。此後每週一資料自動更新,App 自動抓,你只要打開來看。

---

## 兩種讀取方式(都保留)
- **自動**:設好 raw 網址後,App 每次開啟在背景同步,並可手動「立即同步雲端」。
- **手動**:若不想連雲端,也能用「匯出備份 / 匯入」搬 JSON,或每週我幫你產一份給你匯入。

你自己在 App 裡新增的特價(手動輸入的)**不會**被雲端同步覆蓋,會保留。

---

## 本機測試爬蟲
```bash
pip install -r requirements.txt
python scrape_foldoo.py --dry-run          # 實際爬,只印出不寫檔
python scrape_foldoo.py                     # 爬並寫入 data/deals.json
python scrape_foldoo.py --html page.html AH # 用存好的 HTML 測某家解析
```

---

## 已知限制(誠實說明)
- **份量**:Foldoo 公開網頁每家只顯示「Top ~24」熱門特價,其餘在它自家 App 內。
  所以這裡拿到的是精選熱門檔,不是每家上百項全品項。要全品項需另接資料源。
- **嬰兒用品的處理方式**:嬰兒用品每週都會被涵蓋,來源有兩條:
  1. 若 Foldoo 的超市 folder 有嬰兒品項(luiers/babyvoeding),爬蟲會自動歸到「嬰兒用品」抓進來;
  2. 藥妝(Kruidvat/Etos)的嬰兒特價來自 `baby_manual.json`,爬蟲每次執行都會**併入**輸出。
     所以嬰兒用品**不會被每週更新洗掉**。
  為什麼藥妝要手動維護?因為 Foldoo 不收藥妝,而各 folder 站的 Kruidvat/Etos 幾乎都是
  **掃描圖片**,沒有可靠的逐項文字價格,無法穩定自動抓。而且藥妝嬰兒多是 1+1、2+2、
  cashback 這種型態,本來就沒有單一標價。`baby_manual.json` 讓你(或每週我幫你)花一分鐘更新即可。
- **易壞**:Foldoo 改版可能讓超市解析變 0 筆。爬蟲有安全閥(超市抓到 <8 筆就中止、不覆蓋舊檔;
  嬰兒手動資料不計入此門檻),Actions log 會顯示每家筆數;真的壞掉時調整
  `scrape_foldoo.py` 的 `parse_*` 函式即可。
- 這是爬第三方彙整站,請留意 Foldoo 的服務條款,僅供個人使用、勿高頻請求。

### 維護嬰兒用品(baby_manual.json)
直接編輯 `baby_manual.json`(純文字,格式和一筆特價一樣),存檔 push 即可,下次自動更新就會帶上。
欄位:`cat` 固定 `"baby"`、`prod` 商品名、`brand` 品牌規格、`store`(Kruidvat/Etos/…)、
`sale`/`orig`(沒有固定價就填 `null`)、`promo`(如 `"1+1 gratis"`)、`end` 到期日、`note` 備註。
你也可以直接在 App 裡用「新增特價」加,那些手動項目一樣不會被雲端同步覆蓋。

---

## 想上線成網址(選用)
把 repo 開 **Settings → Pages → Source: main /(root)**,GitHub 會給你一個
`https://你的帳號.github.io/bonus-radar/` 網址,手機加到主畫面就像 App。
