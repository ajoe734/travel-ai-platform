# ENG-11 驗收對照

| 驗收 | 正式實作 | 本機證據 | PostgreSQL／外部限制 |
| --- | --- | --- | --- |
| A35：數字可重現，未知不捏造成原因 | `InsightService.record_observation` 與 `operating_insight.result_hash` | `tests.insight_service_test.ObservationTests` | `tests/db/test_insight_workflow.py` 用正式 migration 驗證 RLS 與 FK；沒有真實報表來源 |
| A36：只問素材缺口 | `ask_missing_material` + `usable_asset_uses` | `MaterialRequestTests` | DB test 驗證 rights/channel/language/expiry 後才列為可用 |
| A37/A38：素材掃描、權利與客訴隔離 | `record_scan`、`approve_rights`、asset CHECK constraint | `AssetRightsTests` | hosted PG 驗證 constraint；無真實防毒／媒體掃描器 |
| A39 + ENG-08 接續 | `approve_proposal_for_service_version` 輸出 immutable content，再交 `PublicationService` | `ProposalToPublicationTests` | DB/connector mock 僅驗證流程，不代表 OTA/PMS 權利或真實發布 |

本切面不把 LLM 文字、附件本身或掃描成功視作商家批准；也不把本機／mock 結果宣稱為真實渠道上線。
