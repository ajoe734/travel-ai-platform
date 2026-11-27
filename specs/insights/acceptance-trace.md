# ENG-11 驗收對照

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| F1：migration lifecycle | `0011_insight_rights_integrity.*`；workflow migration count | 584cbbd 的 CI 腳本固定預期 8、實際已有 10；現在與 11 個 checked-in migrations 一致 | 靜態核對 `.github/workflows/repository-validation.yml`；hosted job 待候選後啟動 | 本 VM 無 PostgreSQL／psycopg，未本機跑 upgrade/rebuild |
| A35 / F5：可重現觀察 | `InsightService.record_observation`；不將 hypothesis 放入 `result_hash` | 同查詢結果配不同假說不再改變 result hash；空 query/metric/dedupe 或三個量測結構被拒絕 | `python3 -m unittest discover -s tests -p '*test.py' -v`：179 passed | 無真實 BI query source；PG immutable trigger 待 hosted |
| A36 / F2：只問真正缺口 | `find_usable_assets`、`ask_missing_material`；匹配 `(content_hash?, purpose, channel, language)` | 舊版只比 content hash，缺 hash 時能繞過；現僅同用途/渠道/語言的有效素材滿足需求 | 同上；`MaterialRequestTests` | tenant catalog 實跑與 RLS 待 hosted PG |
| A37/A38 / F3：掃描、權利、撤回、衍生檔 | `record_scan`、`approve_rights`、`revoke_*`、recursive ancestor check；0011 FK/CHECK | 舊版 rights revision 固定 1、撤回與祖先失效未封鎖；現改為遞增 revision、撤回及祖先狀態排除 | 同上；`AssetRightsTests` | 未連真實防毒／內容掃描器；DB constraint probes 待 hosted PG |
| A39 / F4：提案修訂與 ENG-03/08 接續 | `revise_proposal`、guarded state update、`create_and_prepare_publications` | 舊版可直接標 `APPROVED`；現先 `AWAITING_APPROVAL`，僅帶 `ApprovalRecord` id 呼叫 ENG-08 建 version/兩渠道 publication 後才標 `APPROVED` | 同上；`ProposalToPublicationTests` | 整合測試以 PublicationService mock 驗證邊界，未建立真實 ApprovalRecord／渠道帳號 |
| R2 hosted CI：素材權利 DB probes | `insight_repository.usable_asset_uses`；`test_complaint_asset_cannot_be_marketed_even_by_direct_db_write` | `ad1650a` 的 hosted run 45996777656：遞迴查詢有 6 個 placeholder 卻只傳 4 個值；預期失敗使同一 transaction 回滾，後續 admin probe 查不到素材而假陰性。`641f979` 已使 expiry probe 通過，但把例外捕捉在 savepoint 內仍使 transaction 保持 aborted（run 45997445564：39 passed / 1 failed）。現讓例外穿過 savepoint，由 pytest 在外層捕捉，使 fixture 保留後再驗 admin 直寫遭約束拒絕。 | hosted jobs：140498023437（舊候選 38 passed / 2 failed）、140500295797（中間候選 39 passed / 1 failed）；本修正版需新候選 CI 完成後填寫。 | 本 VM 不啟動 PostgreSQL/Docker；本機只做 Python/unit 與靜態檢查，正式 migration/repository 證據由 hosted CI 產生。 |

本切面不把 LLM 文字、附件本身或掃描成功視作商家批准；也不把本機／mock 結果宣稱為真實渠道上線。
