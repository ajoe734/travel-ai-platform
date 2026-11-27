# ENG-08 驗收對照

| 驗收 | 實作依據 | 檢查 |
| --- | --- | --- |
| 官網成功不使 OTA 成功；部分成功可呈現 | `channel_publication` 每渠道獨立主列與 business key | DB repository / migration lifecycle（待 hosted PostgreSQL） |
| 審核中不當 UNKNOWN | status check constraint 與 `record_connector_result(Pending)` | `tests/publication_service_test.py` |
| 新版不改寫舊訂單承諾 | immutable `service_version`；未修改 `order_record` | migration review / static check |
| 讀回正式版本才 LIVE；舊事件不覆蓋新版 | `source_revision == desired_version` / optimistic revision | `tests/publication_service_test.py` |
| 不支援／權限失效的待處理原因 | `channel_publication_access` → `BLOCKED` | DB repository / hosted PostgreSQL 待驗 |
