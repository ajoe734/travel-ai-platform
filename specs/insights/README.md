# ENG-11 經營洞察、商家討論與素材權利

這個切面實作 SA FR-16～19、UC-07～09、執行角色 v1.1 W07／W13 與 A35～A39。

`operating_insight` 的 `result_hash` 由 query 版本、期間、分子、分母、coverage、案件去重版本及結果一併計算；觀察（帶 `source_ref`）與假說分開保存。沉默原因必須表達為 `UNKNOWN` 或假說，不能偽裝成有來源的觀察。

`change_proposal` 必含成本及共享資源影響。商家訊息只追加；`material_request` 會在同租戶 catalog 搜尋有效且用途／渠道／語言相符的素材（不只搜尋已綁定 `proposal_asset_use`），只要求真正缺口。

素材先收件、掃描，再以明確權利 grant 指定用途／渠道／語言與期限。客訴證據的 `source_scope=COMPLAINT_EVIDENCE` 永遠不能變為可發布素材；掃描完成也不是公開授權。`approve_proposal_for_service_version` 只在每項必要素材仍可用時產生含提案、成本、共享資源與素材權利快照的 content；該 content 仍須走 ENG-03 的正式 ApprovalRecord，才可傳給 ENG-08 `create_approved_version()`／兩渠道發布。

本機純服務驗證：

```bash
python3 -m unittest tests.insight_service_test -v
```

資料庫驗收（正式 migration + repository path）在 `tests/db/test_insight_workflow.py`，需要 PostgreSQL 與 `db/requirements.txt`；VM 無此環境時由 hosted CI 執行，不能把 mock 當作 DB 驗證。
