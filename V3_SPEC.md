# v3 全面強化規格（30 題答案彙整）

## OCR & Ingestion
1. OCR 引擎：**用戶可選**（PaddleOCR / Tesseract）
2. 重複 PDF：**「重新處理」按鈕**，讓用戶決定
3. 入庫方式：**全部**：批次上傳 + XML 解析 + 自動掃描資料夾
4. OCR QA：**並排比較**（OCR 結果 vs 原始 PDF）
5. XML 切塊：**claims 和 abstract 分開切**（各自獨立 chunk）

## Chat & LLM
6. 回答語言：**全英文**
7. Streaming：**Yes**
8. 多輪對話：**Yes，最多 10 輪** + 可切換專利檔案範圍
9. 建議問題：**動態生成**（根據已上傳文件）

## UI & UX
10. UI 主題：**亮色專業風**（白底 + 藍色輔色）
11. PDF 預覽：**高亮 + 縮放**（兩個都要）
12. 引用顯示：**全部**（專利號 + 條號 + 頁碼 + 可點擊跳到 PDF）+ **可展開收合**
13. 檢索：**完整混合**（向量 + 關鍵字 + metadata filter）
14. i18n：**中英雙語 UI**
15. 回饋：**讚/踩 + 文字回饋**（兩者都要）
16. 對話匯出：**完整對話 + 引用**
17. 對話歷史：**localStorage 持久化**
18. 專利瀏覽：**基本列表 + 書目資料**

## Admin & Monitoring
19. 評測：**全部**：HTML 報表 + 即時儀表板 + CI 回歸
20. 後台管理：**簡單使用者統計**（查詢次數 / 熱門問題）
21. 異常警報：**基本 Webhook 通知**

## Architecture & Deployment
22. 登入：**簡單 username/password**
23. 知識庫分組：**按檔案/標籤**
24. 專利比較：**基本表格比較**
25. 部署：**Kubernetes 部署檔**（加上 Docker Compose）
26. 安全：**基本 rate limit**
27. API 文件：**OpenAPI/Swagger**
28. License：**未定**
