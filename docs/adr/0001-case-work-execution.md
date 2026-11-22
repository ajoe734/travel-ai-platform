# ADR 0001 保留 Case 並以 Work 表達業務責任

日期：2026-11-22。狀態：本次補充設計，待實作驗收。

## 依據

[SA v1.0](../sa/sa-v1.0.md)的 FR-03、UC-01、08.4 定義 Case 為接單或營運案件，保存需求版、下一步與回覆所有權；客訴另有 Complaint。SA 03／08.2 定義 ExecutionTask、ExecutionAttempt、lease、fence、business key 及完成證據。後續[重建報告](../research/2026-11-20-rebuilt-sasd.md)使用 Task 代表業務責任，[第一批工程報告](../research/2026-11-21-engineering-batch1.md)又稱 Work。直接把三種名稱等同會遺失需求接續或造成兩套執行核心。

## 決策

- `Case` 保留為需求、溝通與營運接續的案件容器；它不限客訴。一個 Case 可有數個 Work，並保留 `owner_revision`、需求版本與存取驗證。
- `Complaint` 保留為客訴領域物件，關聯 Case／Order；其解決與關案條件獨立於補救成功。
- `Work` 是案件內被系統承接的一個業務目標及完成契約。後續報告中的 Task 在此層映射到 Work。
- `ExecutionTask` 是 Work 內可排程、可授權、具穩定業務鍵的操作。對外 `execution_id` 指向它；原 SA `/tasks/{id}` 保持此語意。
- `ExecutionAttempt` 保存每次實際 I/O 嘗試；查核既有結果也是 attempt，但不可變成第二個業務操作。
- root ExecutionTask 可以是 `GROUP`，只協調已批准 manifest 的子操作；每個真正外部副作用由 `ACTION` task 負責。授權使用綁唯一 root task，Work 不再建立另一套獨立消耗。
- `Work.status` 使用 [Work 契約](../sd/work-execution-contract.md)的業務狀態；UNKNOWN 是 ExecutionTask 的不確定結果，Work 顯示 WAITING_EXTERNAL 加 RESULT_UNKNOWN 原因，保留原始狀態來源供追溯。

## 結果與相容

Case 既有 API 不改成 `/works` 的別名；新增 Work API 不能讓相同案件被重建。舊 `consumed_task` 關聯 root task，新 `authorization_use` 是其不可變使用紀錄；兩者不得各自消耗一次。

若日後找回舊 schema，先比較欄位與資料再寫 migration。本次沒有資料庫實例證據，不宣稱已完成資料遷移。不能因最新範例少了同租戶 FK、原子退款或 owner_revision 就刪除 SA 的要求。

## 否定的做法

Case 全部改成客訴會破壞接單與經營流程；以每個對話建一個 Work 會造成跨通路重複操作；以 Temporal run ID 取代業務 ID 會使工作歷史依實作重啟而變；另建 `Task` 與 `Work` 兩套同義表會讓狀態難以核對。
