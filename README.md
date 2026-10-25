# 台灣颱風警報 LINE 通知

透過中央氣象署（CWA）開放資料與 GitHub Actions，定期檢查颱風警報資訊，並在有需要時使用 LINE Messaging API 推送個人通知。

## 功能

- 從中央氣象署 API 取得颱風警報資料。
- 讀取氣象署網頁資料中的「下次警報預定發布時間」。
- 透過 LINE Messaging API 推送警報訊息。
- 通知內容包含：
  - 警報標題
  - 發布時間
  - 颱風動態
  - 警戒區域及事項
  - 下次警報預定發布時間
  - 氣象署發布網址
- 以警報報數及內容雜湊判斷是否需要再次通知，避免相同內容重複推播。
- 解除颱風警報以報數記錄，避免同一解除警報重複通知。
- 使用 GitHub Actions 每週四台灣時間 21:00 執行固定檢查。
- 程式包含動態排程更新與執行時間檢查邏輯；動態排程尚待有實際的氣象署預定發布時間時驗證。

## 資料來源

- 颱風警報資訊 API：  
  `https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001`
- 氣象署颱風警報頁面：  
  `https://www.cwa.gov.tw/V8/C/P/Typhoon/TY_WARN.html`
- 下次預定發布時間資料：  
  `https://www.cwa.gov.tw/Data/js/typhoon/TY_WARN-Data.js`

## 專案檔案

```text
.
├── .github/
│   └── workflows/
│       └── typhoon-alert.yml
├── data/
│   └── state.json
├── W-C0034-001_histroy_datas.json
└── typhoon_alert.py
```

* `data/state.json` 用來保存通知狀態，避免重複推播。若檔案尚未建立，程式會以空狀態開始。
* `W-C0034-001_histroy_datas.json` 是多筆相異日期的 API 歷史回傳 `json` 數據，內含有颱風到無颱風的格式變化。

## 必要設定

### 1. 建立 CWA API 金鑰

前往中央氣象署開放資料平台申請 API 金鑰，並將金鑰設為 GitHub repository secret。

### 2. 設定 LINE Messaging API

在 LINE Developers Console 建立或設定 Messaging API channel，取得 Channel access token，並準備接收通知的個人 LINE 使用者 ID。

請確認 LINE 官方帳號已能向該使用者傳送訊息，且使用者符合 LINE Messaging API 的推播條件。

### 3. 設定 GitHub Repository Secrets

在 GitHub repository 開啟：

**Settings → Secrets and variables → Actions → Repository secrets**

新增以下 Secrets：

| Secret 名稱 | 用途 |
|---|---|
| `CWA_API_KEY` | 中央氣象署 API 金鑰 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API Channel access token |
| `LINE_USER_ID` | 接收通知的 LINE 使用者 ID |
| `WORKFLOW_UPDATE_TOKEN` | 用來更新 Workflow 檔案中動態排程的 GitHub Personal Access Token |

`WORKFLOW_UPDATE_TOKEN` 需要能讀取及更新此 repository 的 `.github/workflows/typhoon-alert.yml`。依 GitHub Token 類型與 repository 設定，授予所需的最小權限；若使用 fine-grained token，通常需設定 Contents 讀寫權限，並允許 Workflows 權限。請勿將 Token 寫進程式碼或提交至 repository。

Workflow 也會使用 GitHub Actions 提供的 `GITHUB_TOKEN` 保存通知狀態。Workflow 目前設定 `contents: write`。

## GitHub Actions 排程

Workflow 檔案為 `.github/workflows/typhoon-alert.yml`。

### 固定排程

目前固定排程為：

```yaml
- cron: "0 13 * * 4"
```

GitHub Actions 的 cron 使用 UTC，因此 `0 13 * * 4` 對應台灣時間每週四 21:00。

### 動態排程

程式會嘗試讀取氣象署提供的下次預定發布時間，並把對應的 UTC cron 寫入 Workflow，標記為 `CWA_DYNAMIC_SCHEDULE`，同時記錄包含年份的 `target_utc`。

動態排程執行時，程式會在呼叫氣象署 API 前檢查排程來源及目標時間，避免在目標時間之前查詢。GitHub Actions 的排程可能延遲，且 cron 本身不支援年份，也不是一次性排程；程式會以額外的目標時間檢查降低誤觸發風險。

**目前動態排程尚未在有實際預定發布時間的情況下完成端到端驗證。** 若氣象署資料沒有提供下一次預定時間，例如資料為 `NoteText = [];`，程式不會新增動態排程；若資料來源讀取失敗，程式會保留既有動態排程。

## 手動執行與測試

1. 開啟 repository 的 **Actions**。
2. 選擇 **Typhoon Alert**。
3. 點選 **Run workflow**。
4. 選擇 `test_line`：
   - `true`：只傳送 LINE 測試訊息，不執行正式颱風資料檢查。
   - `false`：執行正式程式，會查詢氣象署資料；若偵測到符合通知條件的警報，可能傳送真實 LINE 通知。
5. 點選 **Run workflow**，並查看執行紀錄。

第一次測試 LINE 推播時，建議使用 `test_line = true`。

## 通知判斷與去重

- 一般警報：警報報數改變，或納入雜湊的內容有變更時，才會通知。
- 解除警報（`END`）：同一警報報數只通知一次。
- LINE 推播成功後才更新通知狀態。
- 通知狀態會寫入 `data/state.json`，並透過 GitHub API 保存回 repository。

雜湊判斷所使用的欄位包括標題、發布時間、颱風動態、警戒區域及事項、下次預定發布時間、網址與警報類別。

## 訊息格式

通知大致如下：

```text
【颱風警報標題】
發布時間：YYYY-MM-DD HH:MM

【颱風動態】
...

【警戒區域及事項】
...

下次警報預定發布時間：...

發布網址：...
```

若氣象署沒有提供部分欄位，訊息會以「未提供」或「氣象署尚未提供」呈現。

## 常見狀況

### 沒有收到通知

- 檢查 Actions 執行紀錄是否成功。
- 確認 `CWA_API_KEY`、`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID` 等 Secrets 已設定。
- 若警報內容與上次相同，程式會略過重複通知。
- 若目前是解除警報且該報數已通知過，也會略過。
- `test_line = true` 只傳送測試訊息，不執行正式警報檢查。

### 沒有新增動態排程

如果氣象署的 `NoteText` 沒有下次預定發布時間，沒有動態 cron 是預期行為。請確認執行紀錄中的「下次警報時間解析結果」及「動態排程」訊息。

### 動態排程更新失敗

檢查 `WORKFLOW_UPDATE_TOKEN` 是否有效、是否有權限讀取及更新 `.github/workflows/typhoon-alert.yml`，以及 Workflow 固定排程是否仍存在。動態排程更新失敗時，程式會記錄錯誤並繼續原有的警報通知流程。

## 安全提醒

- 不要把 API 金鑰、LINE Token、使用者 ID 或其他 Secret 提交到公開 repository。
- 若 Token 外洩，請立即撤銷並重新建立。
- 定期檢查 `WORKFLOW_UPDATE_TOKEN` 的有效期限。
- 此專案是通知輔助工具，請以中央氣象署正式公告為準，不應將 GitHub Actions 的執行時間視為即時或準時保證。

## 授權

本專案採用 [MIT License](LICENSE) 授權。

你可以自由使用、複製、修改、合併、發布、散布、再授權及販售本專案的副本，但須遵守 MIT License 中的條款與條件。

完整授權內容請參閱 [`LICENSE`](LICENSE) 檔案。
