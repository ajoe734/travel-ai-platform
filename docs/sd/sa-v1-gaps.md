# 原始 SA 與本次 SD 差異及缺口

版本：2026-11-22。目的：將真正找到的來源、來源聲稱的附件、本次新增設計與後續工程區分，供 HerdR 直接拆工。本文件不把 README 連結或研究報告中的「已編寫」當成工程本體存在的證明。

## 1. 已核對來源

| 來源 | 本次可讀內容 | 適用方式 |
|---|---|---|
| [SA v1.0](../sa/sa-v1.0.md) | 原 Word 主文與表格；32 FR、15 UC、BR/SM/UI、64驗收；主文聲稱附46表/58 API/28事件 | 保留原語意與案例；主文不等於附件每個欄位本體 |
| [系統規劃 v1.0](../requirements/product-plan-v1.0.md) | 商家工具共融、三條業務流程、交易/渠道/計費設計 | 保留產品範圍與商業設定不預設原則 |
| [執行角色 v1.1](../requirements/execution-role-v1.1.md) | 語音、客訴、素材、渠道執行與A25–44 | 不把它們降成只回答或未來附加功能 |
| [2026-11-20 重建報告](../research/2026-11-20-rebuilt-sasd.md) | 系統目標、Task概念、資料模型概要 | 標題雖稱完整，內文明確只完成前三主題，後半仍待續寫 |
| [2026-11-21 第一批工程報告](../research/2026-11-21-engineering-batch1.md) | SQL/API/SDK/workflow/UX片段、歷史ZIP路徑、驗證限制 | 僅作已知片段及設計意圖；不能推定全包仍存在 |

原始 SA 比後來簡化片段更完整地定義同租戶 FK、owner_revision、lease/fence、原子退款及授權 manifest。後文省略不代表這些要求被取消。

## 2. 歷史工程附件的狀態

SA 主文提到 `openapi.yaml/json`、`01_schema.sql`、`02_atomic_refund.sql`、資料字典、tables.metadata.json、events schemas、requirements_traceability.json、use_cases、state_transitions、acceptance.feature/cases、diagrams、validate_package.py/validation_report.json。主文聲稱它們做過結構/參照檢查，並明說未做 PostgreSQL 實機與外部整合測試。

後續工程報告的歷史包為 `sandbox:/mnt/data/travel-platform-engineering.zip`，內列四個 migration、OpenAPI/AsyncAPI、Connector SDK、三個 mock、兩個 workflow及React App。報告明說只解析 YAML，TS未compile、DB未實跑、Worker未接、外部全mock。

**這些路徑是找回原檔的線索，不是目前已取得檔案的承諾。** 若後續找回本體，需記錄來源與 checksum、逐檔檢查再併入；若自行補寫，標本次新建版本，不能沿用「原檔已復原」說法。GitHub 目前實際檔案與已驗證範圍以根README/驗收紀錄為準。

## 3. 本次統一設計

| 議題 | 原始基線／衝突 | 本次處理 | 實作需求 |
|---|---|---|---|
| Case語意 | SA是接單/營運案件，Complaint另表；後續報告未完整重述 | 保留Case，新增Work業務責任，不將Case改成客訴 | Case/Work關聯與既有API相容 |
| Task/Work | 重建版Task與第一批Work指業務責任；SA ExecutionTask較低層 | Work→ExecutionTask→Attempt；root GROUP與子ACTION明列 | schema、狀態reducer、read model |
| 狀態 | Task/Work/Execution名稱與enum不同 | 業務/執行/外部結果分層，舊值有映射 | 不明舊值需核對，不直接重送 |
| Approval | SA要求版本/內容綁定；新片段revoked_at與immutable衝突 | 原批准不可變、撤回append-only、AuthorizationUse唯一root | encoder、nonce、hash、revoke競態 |
| 租戶隔離 | SA複合FK較完整，新片段多為單id FK | 所有業務parent/child保留tenant複合FK及RLS | 真DB角色、直接FK、pool隔離測試 |
| UNKNOWN/PENDING | SA範例混能力與結果；新三態缺已知pending | Capability獨立；結果四態；UNKNOWN不等失敗 | SDK、adapter、reconcile策略 |
| 工作完成 | SA及後續均要求證據，原型仍可直接切state | domain verifier檢查postcondition與正式evidence | UI不任意改COMPLETED |
| 發布 | SA desired/submitted/observed、每渠道獨立 | 保留每渠道任務與manifest，不全體重跑 | 衝突、部分成功、字段能力驗收 |
| 退款 | SA已要求原子保留、policy budget與外部餘額 | 保留並補全狀態/鎖順序/核對/沖回 | 實機併發、kill/replay、provider測試 |
| Credit | 後續只有500範例checkbox與流程 | 新增Grant/ledger/usage reservation；未核定條款不啟用 | 權限/台帳/adapter/UI/併發驗收 |
| runtime | SA採模組化單體/耐久任務，後續建議Temporal | 業務ID與實作run分開；選型不改語意 | Worker/Activity/DB repository待建 |
| DB版本 | SA以PostgreSQL17語意，後續片段寫16+ | 本輪不宣稱選型升降或已測兼容 | 正式runtime版本寫入工程設定再做migration驗收 |

對應詳規：[Work](work-execution-contract.md)、[授權](authorization-and-approval.md)、[Connector](connector-result-and-reconciliation.md)、[金額](credit-and-refund.md)、[ADR](../adr/README.md)。

## 4. HerdR 可立即拆解的工作

| 工作 | 具體產出 | 依賴與放行證據 |
|---|---|---|
| SD-I01 契約整理 | 將本SD欄位變成具名schema、正式OpenAPI與事件schema；每個operationId唯一 | 來源映射完整；examples、refs、相容對照通過；不冒稱部署 |
| SD-I02 業務資料 | Case/Work/Execution/Attempt/Decision/Approval/Use/Revocation/evidence schema及migration | 同tenant FK、unique/check、append-only、migration/rollback實跑 |
| SD-I03 共用執行 | command→transaction/outbox→worker→外部結果→verifier→read model | 穩定business key、lease/fence、重啟/晚事件/人員接手 |
| SD-I04 授權 | canonical payload、nonce、可信確認、policy evaluator、父子manifest、撤回 | SD-A全部與SA-AT-013/039/051/057/064 |
| SD-I05 Connector | 四態SDK、capability登錄、三個不同能力mock、reconciliation worker | SD-C全部，不能以成功mock當實際帳號權限 |
| SD-I06 金額 | Refund/Policy/Credit reservations、Credit ledger、settlement reversal | 實際DB併發、幣別與重送測試；SD-M全部 |
| SD-I07 工作台 | 今日需要決定/補資料/進行中/完成、Work detail、decision差異、每渠道狀態 | 前後端同狀態；404/409/202/UNKNOWN與partial真路徑 |
| SD-I08 原業務接續 | 語音/文字接單、標準改退、素材權利與改版、兩個授權入口 | 原SA-AT-001–064回歸及完整經營循環演示 |

這些是工程拆工順序，不是承諾工期或費用。不能因新增 SD 只聚焦共用核心，就把語音、素材、數據討論或既有標準售後從首輪範圍刪掉。

## 5. 不能由文件替代的驗收

### 契約與程式

OpenAPI/JSON/YAML能解析、TypeScript可compile、單元測試、資料庫實機migration/鎖/RLS、mock契約與真實第三方整合分開記錄。每層只報實際做過的項目。原型切換畫面不驗證退款，報告內code block不證明完整SDK可執行。

### 真實整合

外部帳號、sandbox/production、API產品版本、scope、原收款與通知主體、查單/冪等/資源策略、正式證據、錯誤接續逐能力驗證。未驗證能力保持feature flag關閉，其餘共用開發繼續。

### 既有承諾

原訂單的付款確認、查單、取消退款、安全與必要通知不能因方案用量用完而停止。沒有自動權限時由指定責任人接續，不能藉此把案件標完成或拒絕處理。

## 6. 設計中仍保留的可配置缺口

商家政策額度、Credit條款、商業費率、渠道合約、來源權限、正式DB/Worker版本、通知責任、資料保存、各operation deadline與值班人需按實際部署補齊。尚未取得的值不填想像數字；schema要能表達 UNCONFIGURED，UI說清缺什麼與找誰，測試用值明確屬fixture。

需要進一步產品/架構設計的項目包括多供應商整段旅程的跨主體交易、跨tenant組合訂單與複雜供應鏈結算。原SA明列首輪以單商家預約制體驗為主，本次不偷偷擴成全旅程原子交易。

## 7. 變更與完成紀錄

每個PR列：來源FR/UC/BR/SA-AT、對應SD案例、改動欄位/命令/事件、migration與相容影響、實際測試證據、尚未啟用能力。發現衝突先更新ADR/SD並同步schema/測試，不讓工程師在兩份互斥規則中自行選一份。

目前本目錄交付的是新增設計文字與驗收要求；歷史來源保持不變。沒有發生的migration、對帳、正式退款、Credit發放或外部渠道發布，不列為完成。
