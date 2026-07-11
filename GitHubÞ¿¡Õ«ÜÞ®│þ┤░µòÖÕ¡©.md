# GitHub 設定詳細教學(一步一步)

目標:把資料夾放上 GitHub,讓它每週一自動更新特價。
全程免費,只需做這一次。看到「→」代表「點下去」。

---

## 事前準備

- 一個 GitHub 帳號(沒有的話到 github.com → **Sign up** 註冊,免費)。
- 手邊有這個 `bonus-radar` 資料夾,裡面應該有這些檔案:
  ```
  index.html
  scrape_foldoo.py
  requirements.txt
  baby_manual.json
  README.md
  快速上手.md
  GitHub設定詳細教學.md
  data/deals.json                    ← 在 data 子資料夾裡
  .github/workflows/update.yml       ← 在 .github/workflows 子資料夾裡
  ```
  > 最後兩個在子資料夾裡,上傳時要保留這個結構(下面第 2 步會教)。

---

## 第 1 步:建立 repository(放程式的地方)

1. 登入 github.com。
2. 右上角 **+** → **New repository**。
3. **Repository name** 欄填:`bonus-radar`
4. 下面選 **Public**(公開;這樣 App 才能讀到 raw 網址,免費帳號的自動排程也才穩定)。
5. 其他都不用動,不要勾「Add a README」。
6. 綠色按鈕 **Create repository**。

會跳到一個空 repo 的頁面,先停在這。

---

## 第 2 步:上傳檔案(保留資料夾結構,最容易出錯這步)

GitHub 網頁上傳有個雷:直接選檔案會把子資料夾裡的東西拉平。用「拖拉整個資料夾」才會保留結構。以下用最保險的方式。

### 方法一(推薦,電腦版 Chrome/Edge 拖拉整包)

1. 在剛剛的空 repo 頁面,找到藍字 **uploading an existing file**(在 "Quick setup" 區塊)→ 點它。
   - 若沒看到,網址改成:`github.com/你的帳號/bonus-radar/upload/main`
2. 打開你電腦的檔案總管,進到 `bonus-radar` 資料夾。
3. **全選裡面所有東西**(包含 `data` 和 `.github` 這兩個資料夾本身),
   整批拖拉到 GitHub 網頁中間的虛線框裡放開。
   > 拖「資料夾」進去,GitHub 會自動保留 `data/…`、`.github/…` 的路徑。
4. 等下方檔案清單跑完(會看到 `data/deals.json`、`.github/workflows/update.yml` 等路徑)。
5. 頁面最下 **Commit changes**(綠色)。

上傳完成,repo 首頁應該看得到那些檔案和 `data`、`.github` 資料夾。

> 看不到 `.github` 資料夾?它以點開頭,GitHub 首頁有時不顯眼,但只要 Actions 分頁(第 4 步)
> 出現「每週更新特價」這個 workflow,就代表它有上傳成功。

### 方法二(手機,或方法一拖拉失敗時)

手機瀏覽器不好拖資料夾,改成「逐檔上傳 + 手動建路徑」:

1. 一般檔案(index.html 等)照方法一的上傳頁選檔上傳即可。
2. 子資料夾裡的檔案要用「打路徑」的方式建:
   - repo 首頁 → **Add file** → **Create new file**。
   - 檔名欄直接輸入完整路徑,例如打:`data/deals.json`
     (打出 `data/` 後 GitHub 會自動變成資料夾)。
   - 把電腦上 `data/deals.json` 的內容整段貼進來 → **Commit changes**。
   - 同樣方式建 `.github/workflows/update.yml`(內容整段貼上)。

---

## 第 3 步:開啟自動寫入權限(不開的話機器人存不回資料)

1. repo 頁面上方 **Settings**(齒輪圖示,在最右邊那排)。
2. 左側選單 **Actions** → 底下 **General**。
3. 捲到最下面 **Workflow permissions** 區塊。
4. 選 **Read and write permissions**(預設是唯讀,一定要改)。
5. **Save**。

---

## 第 4 步:先手動跑一次,確認會動

1. repo 上方 **Actions** 分頁。
   - 若第一次進 Actions 出現綠色 "I understand my workflows, go ahead and enable them" → 點它啟用。
2. 左側清單點 **每週更新特價**。
3. 右側會出現 **Run workflow** 下拉鈕 → 點開 → 綠色 **Run workflow**。
4. 頁面上會冒出一列黃色「進行中」的執行紀錄,等它變成綠色勾勾(約 1 分鐘)。
5. 點進那筆紀錄 → 點 **update** 這個 job → 展開 **Scrape Foldoo** 步驟看記錄:
   - 正常會看到每家抓到幾筆,例如 `[AH] 21 筆`、`[Jumbo] 16 筆`、`[嬰兒用品] 併入 4 筆`。
   - 再看 **Commit if changed** 步驟,出現「已更新並推送」或「資料無變化,略過」都算成功。

> 這一步過了,就代表整條自動化通了。之後每週一早上(荷蘭時間約 7 點)會自己跑。

---

## 第 5 步:拿到 App 要用的網址

1. repo 首頁點進 `data` 資料夾 → 點 `deals.json`。
2. 檔案右上角有顆 **Raw** 鈕 → 點它。
3. 瀏覽器網址列現在就是純資料網址,複製它,長這樣:
   ```
   https://raw.githubusercontent.com/你的帳號/bonus-radar/main/data/deals.json
   ```
4. 打開 `index.html`(電腦雙擊,或手機開啟)→ 捲到最底 → **設定自動來源** → 貼上網址 → 確定。

完成!以後開 App 會自動同步,也可按 **立即同步雲端**。

---

## (選用)第 6 步:把 App 掛成網址,手機直接開

不想每次找 index.html 檔案的話,可以用 GitHub Pages 變成一個網址:

1. **Settings** → 左側 **Pages**。
2. **Source** 選 **Deploy from a branch**;**Branch** 選 **main**、資料夾選 **/(root)** → **Save**。
3. 等一兩分鐘,同頁上方會出現網址:`https://你的帳號.github.io/bonus-radar/`
4. 手機瀏覽器開這個網址 → 選「加入主畫面」,就像一個 App。
   (第一次一樣要用底部「設定自動來源」貼上第 5 步的 raw 網址。)

---

## 每週會自動發生什麼

- 每週一 05:00 UTC(荷蘭夏令 07:00),GitHub 自動跑爬蟲。
- 抓到的新特價寫進 `data/deals.json` 並自動 commit。
- 你打開 App 時會自動同步到最新。你完全不用動手。

---

## 疑難排解

**Actions 裡沒有「每週更新特價」?**
→ `.github/workflows/update.yml` 沒上傳成功或路徑錯了。用第 2 步方法二重建這個路徑的檔案。

**執行變紅色失敗,點進去看?**
- **Commit if changed** 紅字、提到 permission / 403 → 第 3 步的寫入權限沒開,回去開了再重跑。
- **Scrape Foldoo** 顯示「超市只抓到 X 筆…保留現有不覆蓋」→ 這是安全機制,代表 Foldoo 改版了,
  把那段 log 貼給我,我幫你調 `scrape_foldoo.py` 的解析。

**App 貼了網址卻沒更新?**
- 確認網址是 **raw.githubusercontent.com** 開頭(不是 github.com/…/blob/…)。
- 按一次「立即同步雲端」。
- 若 repo 是 Private,raw 網址會失效 → 把 repo 改成 Public(Settings 最下 Danger Zone → Change visibility)。

**改了 `baby_manual.json` 怎麼生效?**
→ 在 repo 進到該檔 → 右上鉛筆圖示 **Edit** → 改完 **Commit changes**。下次自動更新(或手動 Run workflow)就會帶上。

---

卡在任何一步,把那一步的畫面或 Actions 的 log 文字貼給我,我直接幫你看是哪裡的問題。
