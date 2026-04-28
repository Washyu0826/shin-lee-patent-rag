# Data Sources — Legal & Technical Triage

> 任何要被 ingest 進這個系統的資料，**必須先在這份文件登記**，並標明授權狀態。
> 沒有過第一欄審核的來源**禁止**抓取、ingest、commit。

---

## 原則（從用戶 feedback 直接落實）

1. **不能犯法** — 如果一個來源的授權不允許重新散布或 bulk crawl，就**不抓**
2. 公開範例（demo / screenshot）OK，但**不 commit 原始檔**進這個 GitHub repo（即便技術上可以）
3. 政府公開資料還是要逐案查授權（許多用「政府資料開放授權第 1 版」是 CC BY 4.0 相容，但**不是全部**）
4. 若是研究／本機測試，可在本機 ingest 但加進 `.gitignore` — **不公開**

---

## 已確認可用 ✅

| 來源 | URL | 授權 | 已實作？ |
|---|---|---|---|
| **TIPO 開放資料 — 專利公報 P13** | `https://cloud.tipo.gov.tw/S220/opdata/api/gazettes/P13` | 政府資料開放授權 | ✅ `scripts/fetch_real_patents.py` 直接打 API |

> 這是目前唯一**已驗證且實作**的資料來源。所有 benchmark 用的 100 篇真實專利都來自這裡。

---

## 待人工檢查的清單（用戶 2026-04-28 提供）

下表的 URL 是用戶在開發過程中發來的範例。**目前沒有任何一條**已實際抓取或 ingest。每一條要動之前必須先做下方「決策清單」。

| # | URL 摘要 | 來源類型 | 文件類型 | 授權初判 | 建議動作 |
|---:|---|---|---|---|---|
| 1 | `patentimages.storage.googleapis.com/.../US20190300000A1.pdf` | Google Patents（快取美國專利）| US 專利 PDF | US 政府著作 → 公有領域；Google 重新散布有自己的 ToS | 🟡 單篇 demo 抓取 OK，**不 commit**；批量抓需查 Google Patents ToS |
| 2 | `worldwide.espacenet.com/.../WO2022241607A1` | Espacenet（EPO）| 專利檢索頁面 | EPO ToS 禁止 bulk scraping；個別查閱 OK | 🔴 **不做** bulk crawl；如要單篇可手動下載原始 XML |
| 3 | `tiponet.tipo.gov.tw/.../M682456.pdf` | TIPO 直連 PDF | TW 專利 PDF | 政府資料開放授權範圍內 | 🟢 OK — 與現有 P13 公報來源相同 |
| 4 | `uspto.gov/.../ipr2023-01339_paper_12.pdf` | USPTO 官網 | **IPR 法律文書**（非專利本身）| US 政府著作 → 公有領域 | 🟡 OK 抓取但**文件類型不同**：需要法律文書專屬 chunker |
| 5 | `iso.org/.../PUB100080.pdf` | ISO | 國際標準 | **明確版權**，ISO 出售 | 🔴 **不做**：不抓、不 ingest、不 commit |
| 6 | `mol.gov.tw/.../post` | 勞動部公告 | 政府公文 | 須查該頁標註的開放授權 | 🟡 待手動檢查授權再決定 |
| 7 | `osa_dorm.ntu.edu.tw/.../宿舍管理辦法.pdf` | 台大 OSA | 學校規章 | 公開公告但未必允許重新散布 | 🟡 待人工確認，學校規章一般可引用不可整份散布 |
| 8 | `judicial.gov.tw/.../...html` | 司法院 | 司法文書 | 司法文書原則公開但有遮蔽規則 | 🟡 待人工確認 |

---

## 每個來源在動之前要回答的清單

1. **授權**：可以重新散布嗎？bulk crawl 允許嗎？需要署名嗎？
2. **個資 / PII**：文件內有姓名 / 身分證 / 地址嗎？需要遮蔽嗎？
3. **檔案是否 commit 進 repo**：
   - 若 commit → repo 變成「重新散布該文件」，需有授權允許
   - 若不 commit → 加進 `.gitignore`，本機 ingest 即可
4. **文件類型對應的 chunker**：
   - 專利 → 沿用 `xml_parser.py` 的 claim/abstract 切分
   - 法條 → 需要新 chunker（按「第 N 條」/「第 N 項」切）
   - 標準 → 需要新 chunker（按「Clause N」切）
   - 司法文書 → 不同樣態（判決書 / 裁定 / 命令）
   - 學校規章 → 接近法條但結構簡單

---

## 目前不打算做的事（明示）

- ❌ 自動爬蟲打多個來源（會踩到 Espacenet 之類的反爬規則）
- ❌ 在 GitHub repo 提交任何受版權保護的 PDF（即使 demo 用）
- ❌ 假裝系統「支援」某個來源 — 在程式碼真實寫出 ingest 路徑之前，README / docs 都不能這樣寫

## 後續流程

要新增一個資料來源時：

1. 在這份文件下方加一個段落，填完上面的決策清單
2. 程式碼層面先寫 chunker（如果需要）+ 對應的 ingest 腳本
3. 跑單篇本機測試
4. 視授權決定要不要 commit demo 檔案
5. 把該來源加進「已確認可用」表

---

> **Last review**: 2026-04-28（基於用戶當天提供的 URL 清單）。新增來源請補日期。
