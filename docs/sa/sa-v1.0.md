# 商家接單助理_開發SA規格書_SA-v1.0｜文字轉存

來源：[原始 Word](originals/商家接單助理_開發SA規格書_SA-v1.0.docx)。本檔依正文順序抽取可編輯文字與所有表格，沒有改寫內容。原圖、版面、清單自動編號及跨欄合併以原始 Word／PDF 為準；圖像在對應段落保留占位提示。頁首頁尾與註腳附於文末。

---

SYSTEM ANALYSIS  /  DEVELOPMENT SPECIFICATION

## 商家接單助理

## 開發 SA 規格書

語音接單 · 客訴處理 · 經營者互動
素材協作 · 渠道商品與訂單執行

完成工作的標準：有授權、有動作、有可核對的結果；不是只產生回答或建議。

| 文件識別 | 內容 |
| --- | --- |
| 版本 | SA-1.0｜2026-11-11｜開發評審版 |
| 產品基準 | 整合系統規劃 v1.0 與執行角色增補 v1.1，不再分散閱讀 |
| 對象 | 產品負責人、前後端、AI／語音、整合工程、QA、維運與旅行社營運 |
| 本件交付 | 功能／使用案例、狀態與商業規則、資料模型、內部 API、事件、畫面、非功能規格與驗收 |
| 工程附件 | 46 張參考資料表；58 項 API 操作；28 種事件；64 項驗收案例 |
| 適用邊界 | 供給立足台灣、服務國內外旅客；商家保留既有工具；企業服務、渠道與自有直客並行 |

本文件把已確認產品方向轉成可拆工、估工與契約測試的系統分析規格。它不是程式已完成、已取得第三方權限或已承諾工期的聲明。

附件中的 SQL、OpenAPI 與資料字典屬本平台建議設計；未取得或未實測的外部能力以連接器能力登錄表標示，不以假介面代替。

## 00｜版本控制、依據與閱讀規則

| 依據 | 本 SA 如何處理 |
| --- | --- |
| B01：系統規劃 v1.0 | 保留商家工具共融、三條經營流程、資料與交易分工、計費及必要售後邊界。 |
| B02：執行角色 v1.1 | 語音、客訴、素材取得與渠道實際操作為首輪必交流程，不降為未來附加功能。 |
| SA-1.0 新增 | 明確 API／資料型別、狀態轉移、工作租約、原子退款保留、權限、測試追溯及開發關卡。 |
| 規範強度 | 「必須」是驗收要求；「建議預設」可在評審調整；「待整合驗證」是外部能力，不是產品方向待定。 |

### 驗收編號校正

v1.0 原始檔實際列 T01–T24；v1.1 的文字曾將前版稱為 A01–A24。本 SA 不沿用不存在的歷史標號，統一新編 SA-AT-001–064，並逐筆保留來源 T01–T24、A25–A44；新增 045–064。

### 文件與附件的優先關係

產品意圖以已確認兩版為基準。SA 主文定義語意與規則；openapi.yaml 定義內部請求／回應欄位；01_schema.sql 與資料字典定義參考儲存結構。若出現衝突，不採「工程自己選一個」，應登記設計變更並同步三者後凍結版本。

| 識別前綴 | 用途 |
| --- | --- |
| FR-01–32 | 功能需求；對應 UC、相關 API 與驗收。 |
| UC-01–15 | 主文及 use_cases.md 涵蓋前置條件、例外與完成證據。 |
| BR-xx／SM-xx | 不可違反的商業規則／狀態模型。 |
| UI-01–08 | 畫面欄位、動作與權限。 |
| SA-AT-001–064 | Given／When／Then 與測試證據。 |
| W01–W15 | 開發工作包，沿用既有來源再補實作交付。 |

文件不設定系統投入估值、分潤比例、未核准退款額度或第三方價格。這些屬可版本化商業設定，不阻擋共用核心開發。

## 閱讀導航與交付地圖

| 章節 | 主要內容／定位 | 頁次 |
| --- | --- | --- |
| 01 需求與邊界 | 32 項需求、交付與非目標 | 4–6 |
| 02 系統與權限 | 架構、資料來源、角色與隔離 | 7–9 |
| 03 共用執行核心 | 任務、核准、版本、冪等 | 10–11 |
| 04 接單與語音 | 報價、預訂、付款與語音交接 | 12–16 |
| 05 客訴與補救 | 歷史證據、政策、退款併發 | 17–18 |
| 06 經營與素材 | 洞察、互動、素材、服務改版 | 19–22 |
| 07 渠道與整合 | 商品發布、訂單與既有工具 | 23–25 |
| 08 資料與介面 | ERD、資料規則、API與事件 | 26–34 |
| 09 畫面與營運 | 畫面、安全、維運與計費 | 35–41 |
| 10 驗收與交付 | 64 案例、工作包與整合待辦 | 42–50 |
| 附錄 查核依據 | 基準文件、官方來源、驗證範圍 | 51–52 |

### 工程包檔案

| 檔案 | 使用方式 |
| --- | --- |
| openapi.yaml / openapi.json | 相同內容兩種格式；產生 mock、介面型別與契約測試。 |
| 01_schema.sql / 02_atomic_refund.sql | 參考 DDL 與原子退款保留；經 PostgreSQL migration 實測才可部署。 |
| 資料字典.md / tables.metadata.json | 所有業務欄位、型別、外鍵、唯一限制與說明。 |
| events/*.schema.json | 28 種正規事件 payload schema。 |
| requirements_traceability.json | 需求 → 使用案例 → API → 驗收追溯。 |
| use_cases.md / state_transitions.json | 15 個完整使用案例與核心狀態轉移契約。 |
| acceptance.feature / acceptance_cases.md | QA 劇本；不代表業務系統測試已執行。 |
| diagrams/*.mmd | 可編輯架構、交易時序、經營循環與 ERD。 |
| validate_package.py / validation_report.json | 附件結構與交叉參照驗證；不是正式外部串接測試。 |

## 01｜需求基線與首輪交付範圍

首輪必須跑通：文字與語音接單 → 標準售後／客訴補救 → 依數據與商家討論 → 素材取得 → 核准服務新版 → 兩個授權入口發布 → 訂單／成本回流。

| 範圍 | 首輪交付 | 不預先冒稱已具備 |
| --- | --- | --- |
| 商品 | 單商家預約制體驗；一筆訂單一項主服務及明確加購 | 全旅程多供應商原子交易、完整 PMS／POS |
| 語音 | WebRTC、已授權 SIP 來電、LINE 音訊訊息 | 任意門號直接接聽、LINE 原生通話、未授權外撥 |
| 角色 | 接單、客訴、服務企劃與素材、渠道營運四個處理角色 | 四個自由互相指揮且共享全權的自治代理 |
| 渠道 | 自有入口＋一個已授權合作入口可實際更新與驗證 | 所有 OTA 都有完整讀寫 API |
| 語言 | 繁中、英文端到端；其他語言沿用規格逐一驗收 | AI 說外語即現場提供外語講師 |
| 收入 | 服務用量、來源、結算、沖回、成本 | 預設所有商家和渠道同時付全部費用 |
| 操作 | 標準核准政策內自動完成；新承諾集中核准 | 每個日常動作都丟回商家手動做 |

### 完成定義

客戶接單以正式預訂與付款條件為證據；客訴以補救結果與案件處理理由為證據；改版以核准且可引用的服務版本為證據；渠道以實際讀回內容及銷售狀態為證據。聊天結束、HTTP 200、已送出指令，都不足以代表業務完成。

### 開發假設與外部待驗證分開

參考實作採模組化單體、耐久任務與獨立背景工作；資料使用 PostgreSQL 17 語意作設計基準，不強迫原系統搬遷。第三方門號、金流、預約及渠道的具體方案／憑證／寫入權由連接器工作包取得與沙盒測試，不要求先有完整合作才開始共用開發。

## 01.1｜功能需求 FR-01–16

| 編號／模組 | 必須完成的能力 |
| --- | --- |
| FR-01<br>M01 | 租戶與合作授權<br>每次讀寫從已驗證身分導出租戶；跨渠道先取得有效合作授權，只回傳允許欄位。 |
| FR-02<br>M02/M08 | 多來源收件與去重<br>文字、音訊及事件先驗證來源並耐久保存；同一來源事件只建立一次案件處理。 |
| FR-03<br>M02/M11 | 需求案件與回覆所有權<br>案件保存條件版本、下一步、等待對象、期限；AI／真人只有一個有效回覆擁有者。 |
| FR-04<br>M03 | 核准服務知識<br>回答綁定來源、服務版本、語言與有效期；未核准及已撤回內容不得發布。 |
| FR-05<br>M04 | 正式報價與資源<br>收費項目和占用資源分開；正式價格、幣別、場次及規則由指定來源產生。 |
| FR-06<br>M04/M12 | 客戶明確同意<br>確認綁定報價雜湊與需求版本；改口、到期或修改價錢後，舊確認失效。 |
| FR-07<br>M05 | 預訂與付款協調<br>依連接器策略執行購買連結／hold API／待確認；正式結果核對後才顯示訂妥。 |
| FR-08<br>M05/M11 | 交易補償與對帳<br>超時先查單；未確認的外部結果保留 UNKNOWN；付款與預訂失配有責任人及補償。 |
| FR-09<br>M05/M13 | 標準訂後與改退<br>查單、重寄、改期、取消與退款可在政策內自動執行；各自核對結果。 |
| FR-10<br>M12 | 即時語音與電話<br>WebRTC 與授權 SIP 電話共用案件及交易工具；錄音政策、日期覆誦、安全付款與實際轉接有紀錄。 |
| FR-11<br>M12/M11 | 改口中斷與接續<br>停止音訊不等於撤銷交易；晚到結果不得覆蓋新版需求；斷線與重撥經驗證接續。 |
| FR-12<br>M12/M14 | 非即時語音與素材理解<br>語音訊息、圖片與文件進同一收件管線；音訊附件不假稱原生通話。 |
| FR-13<br>M13 | 客訴受理與證據<br>未驗證可受理；讀私人訂單與執行補救前驗證；使用成交時版本、區分陳述與已確認事實。 |
| FR-14<br>M13/M05 | 授權內補救執行<br>政策版本、客戶選擇、收款主體與退款餘額檢查通過後自動處理；額度原子保留。 |
| FR-15<br>M13/M11 | 客訴跟催與重開<br>補救完成與客訴結案分開；重大事件立即升級，未結退款不能假結案；重複事件不重補。 |
| FR-16<br>M06/M10 | 可重現經營洞察<br>每項數字有查詢版本、期間、分母、覆蓋率與案件去重；沉默不推定未成交原因。 |

完整追溯在 requirements_traceability.json。M11＝工作核心、M12＝語音、M13＝客訴、M14＝素材；M01–M10 沿用產品基準。

## 01.2｜功能需求 FR-17–32

| 編號／模組 | 必須完成的能力 |
| --- | --- |
| FR-17<br>M06 | 經營者互動與服務提案<br>根據證據或標示為假說的構想追問，產生內容差異、成本與共用資源影響。 |
| FR-18<br>M14 | 主動索取與整理素材<br>先找既有授權素材，只問缺口；語音、照片、短片與文件綁定提案，整理出待核准草案。 |
| FR-19<br>M14/M01 | 素材權利與發布<br>掃毒及內容檢查、來源與用途權利核准後才可對外；客訴附件不可直接當行銷素材。 |
| FR-20<br>M06/M03 | 版本核准與落地<br>核准綁定 diff、基礎版本與渠道；變更後重新核准；產生不可變服務版本，不覆寫舊訂單。 |
| FR-21<br>M07/M08 | 渠道商品與銷售管理<br>依權限建立／修改／上下架，內容、價格、庫存、通知權限逐項檢查。 |
| FR-22<br>M07/M11 | 發布結果驗證<br>每渠道保存期望、送出與觀測版本；審核中與部分失敗分開顯示並追蹤。 |
| FR-23<br>M05/M07 | 外部訂單與通知責任<br>原生訂單異動先核對來源版本；保留銷售、收款、履約及通知主體，不覆寫他方變更。 |
| FR-24<br>M08/M11 | 能力分級與受控操作<br>正式 API 優先；允許的瀏覽器任務需範本與驗證；人工任務記工時，不計全自動成功。 |
| FR-25<br>M11 | 可持久化執行核心<br>任務帶前置條件、授權、版本、冪等鍵、結果證據與期限；等待不持續占用模型。 |
| FR-26<br>M09 | 企業服務計費<br>包含額度與超額口徑依契約版本；重送、重試與平台錯誤不得重收業務費。 |
| FR-27<br>M09 | 渠道歸因與結算<br>原客、渠道客、自有直客分開；佣金基礎與退款沖回可核對，不把 GMV 當平台收入。 |
| FR-28<br>M09/M10 | 完整成本與成效<br>成功／未成交案件均記錄語音、模型、訊息、查詢與人工；自動成功不得含人工補救。 |
| FR-29<br>M01/M10 | 安全與模型治理<br>工具閘門先授權；提示注入不改變權限；模型、提示與 schema 版本化，更新先回歸。 |
| FR-30<br>M01/M03/M14 | 資料生命週期與撤回<br>按類別設定保存、用途及刪除；撤回使索引、快取、發布及衍生素材停止新使用。 |
| FR-31<br>M10/M11 | 維運與必要服務不中斷<br>限額可降級探索；既有訂單查單、退款、安全與必要通知仍有接續；告警與還原演練可查。 |
| FR-32<br>M07/M03 | 開放渠道與需求發掘<br>提供核准服務查詢與交易 API，渠道可用自有 LLM；新需求、旅中加購、轉介與再購分開量測。 |

完整追溯在 requirements_traceability.json。M11＝工作核心、M12＝語音、M13＝客訴、M14＝素材；M01–M10 沿用產品基準。

## 02｜系統邊界與整體架構

[原始圖像 1：請對照本節原始 Word／PDF。]

圖 1｜業務決策與正式操作留在後端；原客服、預約、金流與渠道仍是各自指定的主要來源。

| 邊界 | 設計規則 |
| --- | --- |
| 應用與模型 | 模型只提出結構化意圖與草案；API 不接收模型自行宣告的核准、租戶或付款成功。 |
| 同步與長工作 | 查詢可同步；交易、發布與退款以 execution_id 回傳進度，背景持久化執行。 |
| 內部與外部 | 前端／渠道調用本平台 API；原廠端點只由連接器使用。兩者名稱相似也不是同一契約。 |
| 等待與算力 | 等待照片、商家確認、金流或渠道審核時，模型停止；以事件或時間喚醒。 |

## 02.1｜角色、用途與核准矩陣

| 動作 | 旅客 | 店員／營運 | 負責人 | 渠道／平台 |
| --- | --- | --- | --- | --- |
| 公開服務查詢 | 可依來源使用 | 可 | 可 | 合作授權內可 |
| 查私人訂單 | 驗證且僅自己的 | 工作範圍內 | 本商家範圍 | 渠道只查本合作；支援需臨時授權 |
| 標準下單 | 明確同意 | 協助但不能代客默認 | 同左 | 後端依同意＋供應權執行 |
| 符合政策改退 | 選擇方案並驗證 | 依角色政策執行 | 可執行／設定政策 | 只由合法收款與供應操作主體執行 |
| 例外補償／退款 | 提出要求 | 提出草案 | 依政策核准 | 無越權補款；人工責任人接續 |
| 改服務／價錢 | 不可 | 可起草；授權者可核准 | 核准新承諾 | 渠道不得看內部成本／擅自改商家 |
| 素材權利核准 | 不可 | 經授權可提交 | 核准用途 | 只能取得授權衍生內容 |
| 跨商家排障 | 不可 | 不可 | 不能讀別店 | 限時 break-glass，用途與稽核必填 |

### BR-01｜三種依據不可互相取代

客戶對本次交易的明確同意、商家的政策／本次變更核准、外部系統的操作權限必須同時符合相關動作。商家同意不能代替客戶購買同意；渠道 API 金鑰不能代替商品授權；事先政策也不能超過來源可退款餘額。

### BR-02｜租戶與跨邊合作

商家 tenant 是資料隔離邊界；渠道以有效 agreement 取得指定商品與欄位的服務投影，不取得整個商家的 SQL 存取。每次請求由 session／服務憑證導出 tenant，再驗證 object ownership、用途、渠道與資料版本。跨合作訂單只同步必要對應與責任，不暗中合併會員。

資料庫 RLS 是第二道防線，不取代服務層權限。一般應用帳號不得是 superuser、BYPASSRLS 或可繞過隔離的管理身分。[S08]

## 02.2｜資料主來源與工作責任

| 資料／動作 | 主要來源 | 平台保存／允許的行為 |
| --- | --- | --- |
| 原商品、場次與資源 | 商家指定預約／商品系統 | 外部 ID、查詢時間、規則對應；不建立競爭庫存。 |
| 特色、流程、接待說明 | 商家核准資料及正式版本 | 來源、語言、有效期與用途；不把 AI 草稿當事實。 |
| 正式價格與取消條件 | 核准規則／正式報價 API | 報價與成交快照；過期或改條件產生新報價。 |
| 客服負責人 | 商家指定客服或平台協作規則 | owner_revision；兩邊指派要對應；發送前再次查核。 |
| 客戶訂單／供應預訂 | 指定銷售方／供應方 | 兩種訂單分開；保存外部參考及版本，不憑聊天更新成功。 |
| 付款與退款 | 指定金流與收款主體 | 核對金額、幣別、環境與查詢證據；前端跳轉不算證據。 |
| 渠道已生效內容 | 渠道回覆＋可讀回狀態 | desired／submitted／observed 分開；無法驗證保持未完成。 |
| 歸因與服務費 | 合作契約版本＋業務事件 | 不可直接刪改子帳；更正用沖回；不等於法定總帳。 |

### BR-03｜外部物件對應

外部鍵以 connector_account＋environment＋entity_type＋external_id 唯一，不只用訂單號字串。跨渠道通知與預約系統回流可能描述同一張供應單，先透過既定映射比對再建銷售單。無法確認對應時建立待核對任務，不能用姓名相似度自動合併。

### BR-04｜更新不回寫全部欄位

每個欄位登記指定寫入者。外部店員修改後，記錄來源版本並比較草案基礎版本；衝突時不採最後寫入者蓋過。回寫帶 origin marker，避免通知觸發互相寫回的循環。

## 03｜工作案件與持久化執行核心

| SM-01 任務轉移 | 觸發／檢查 | 原子寫入及下一步 |
| --- | --- | --- |
| NEW → VALIDATING | 輸入 schema、主體與版本可辨識 | 存 task／request_hash，查核能力與授權。 |
| VALIDATING → READY | 前置條件、範圍與預算符合 | 保留必要額度；task＋outbox 同一 DB transaction。 |
| READY → EXECUTING | 工作程序取得 lease＋fence | 寫 attempt，再呼叫外部。不可持 DB row lock 等網路。 |
| EXECUTING → VERIFYING | 外部接受或回傳結果 | 保存參考；讀回正式狀態／等待正式事件。 |
| EXECUTING → UNKNOWN | 逾時，無法確認副作用 | 保留授權消耗與金額保留；先查結果，不重新執行。 |
| VERIFYING → DONE | postcondition 的證據足夠 | 寫結果／通知／用量事件；不可只看 HTTP 成功。 |
| 任務 → WAITING | 等人／素材／第三方處理 | 寫 waiting_on、due_at、next_run_at，釋放工作 lease。 |
| WAITING → VALIDATING | 可信事件或期限喚醒 | 重新驗證版本與授權，不能跳過撤回檢查。 |
| 任務 → ESCALATED／PARTIAL | 超過處理門檻或多子任務部分成功 | 明確責任人與已完成／未完成項目。 |
| 未送出任務 → CANCELLED | 撤回或條件變更 | 可取消待送動作；已送外部必查結果／另建補償。 |

### 工作 lease 與副作用

取得 lease 時 fence_token 遞增；執行前重新比對 owner_revision、租約及資源版本。過期工作程序不能發新動作。外部若不支援 fencing，仍可能已收到前次請求，因此接手的工作程序必先查外部參考，不宣稱本地鎖可讓外部「恰好一次」。

### 核准範圍的父子任務

一次商家核准可包含一個 manifest（商品版本、欄位、素材與渠道清單）。授權消耗到唯一父任務；子任務僅能執行該 manifest 的項目。父任務 PARTIAL 不是所有渠道重跑；成功的子任務保留結果。

## 03.1｜動作授權、冪等與併發規則

| 規則 | 實作要求 |
| --- | --- |
| BR-05 同意不可由模型簽發 | UI nonce／已驗證語音確認服務＋完整報價 hash＋當下需求版本，後端產生 authorization。LLM 工具清單沒有 approve／confirm 核准端點。 |
| BR-06 API 冪等與業務唯一 | API key 範圍＝tenant＋actor＋operation；同 key 不同 request hash 回 409。另以 quote／remedy／publication 的 business key 防止換 key 重複交易。 |
| BR-07 先落地，再副作用 | 交易內驗證版本、消耗授權、寫任務和 outbox 後提交；worker 才呼叫外部。外部成功但本地未保存時由固定參考查回。 |
| BR-08 UNKNOWN 不是失敗 | 任何扣款、退款、訂位、建商品已送出但結果未知時，保留 UNKNOWN，先查詢／指派，不能用網路重試直接再做。 |
| BR-09 版本比較 | 修改命令帶 expected_revision；不符合回 VERSION_CONFLICT。UI 重載差異後再讓使用者決定，不默默覆寫。 |
| BR-10 交易快照不可變 | 報價 snapshot、核准內容 hash、成交服務／條款快照不可覆寫。更正產生新版或追加紀錄。 |
| BR-11 定時與提醒 | timer 持久化；喚醒鍵去重；依租戶與案件合併提醒，等待不啟動無限模型輪詢。 |

### 執行前固定檢查順序

identity → tenant / object / purpose → capability
→ owner_revision / resource_revision → consent / approval / policy
→ source freshness / quote expiry → balance / resource preconditions
→ idempotency & business key → task + outbox → external execution
→ source verification → durable outcome + notification

任何一個前置條件失敗，回傳明確 code 與下一步。可處理的標準工作自動完成；只有缺新承諾／例外授權／正式來源結果時才請人。

## 04｜UC-01 詢問、需求與正式報價

| 項目 | 規格 |
| --- | --- |
| 角色／觸發 | 旅客從商家、渠道或自有入口詢問；接單專員受理。 |
| 前置 | 入口可對應商家與渠道；服務版本與可見範圍有效。未驗證訪客可查公開商品，但不能查私人訂單。 |
| 輸入 | 訊息／音訊、語言、必要日期與參與方式。初次不強迫填完整個人檔案。 |
| 正常流程 | 建立案件 → 核准知識回答 → 只追問缺少條件 → 確認具體日期／時區 → 查可售與價格 → 保存 quote → 顯示確認卡或完整覆誦。 |
| 替代流程 | 無適合服務則提供經授權替代或結束；缺關鍵限制轉商家確認；可售來源失效不使用舊快取保證名額。 |
| 後置 | 不可變報價、效期、來源參考、需求版本、使用服務版本與客戶可核對內容。 |
| 介面／資料 | createCase、reviseDemand、searchServices、checkAvailability、createQuote；cases、demand_revisions、quotes。 |
| 測試 | SA-AT-001–004、016、059、060。 |

### BR-12｜日期與人數

「明天／下週六」轉成服務地的年月日、IANA 時區與 offset，覆誦或顯示讓客戶確認。人數記成人／兒童／陪同及實際參與，不把材料份數當人頭。關鍵欄位有原始片段與 confirmed_fields，聽不清楚只追問該欄。

### BR-13｜正式總價

每一 line_total 由正式來源或核准規則計算，總價明示費用與稅的包含方式；最小貨幣單位用整數，貨幣 exponent 獨立保存。顯示換算與實際扣款幣別分開；方案未知不得自行補佣金、匯率或折扣。

### 資源的驗證

四位到場但兩份材料的案件，需同時檢查四席、兩份材料、共用人員及準備清場時間。資源由原來源唯一管理；來源無法表示則用經商家核准的對應或待確認，不建立平行超賣池。

## 04.1｜UC-02 確認、預訂與付款

| 階段 | 本平台執行 | 完成／例外證據 |
| --- | --- | --- |
| 客戶確認 | 重驗報價、需求版與效期；伺服器簽發授權 | 確認內容 hash 與來源事件；「嗯」或沉默不自動等同同意。 |
| 建立 checkout | 原子消耗一次授權、建立 sales_order／task／outbox | 同 quote 只能一個有效銷售訂單；重送回原結果。 |
| HOSTED 路徑 | 帶入條件到指定購買頁，保存 correlation | 沒有正式結果回傳，只列已前往／待查證，不列付款成功。 |
| HOLD_API 路徑 | 來源支援才 hold；依金流策略授權／收款及確認預訂 | hold expires_at、payment、booking 各自核對。[S05] |
| MERCHANT_CONFIRM | 先待確認；依商家明確承諾再請客戶付款 | 逾期通知，依政策結束或升級，不無限追單。 |
| 核對金流 | 驗簽、merchant、environment、amount、currency，再依介面查詢 | 前端返回／模擬付款不得入正式帳。[S06] |
| 訂妥通知 | 依商品付款策略及供應確認才送訂單／報到資訊 | 到店付款型不硬性要求 CAPTURED；通知失敗只重送通知。 |

### 交易時序

Customer → confirmQuote → Authorization
Checkout API → DB lock / unique quote / consume auth / task + outbox
Worker → supplier hold (if supported) → payment handoff
Provider event → Inbox → verify payment → confirm supplier
Verified booking + payment policy → order confirmation
Any UNKNOWN → query by stable reference → reconcile / owner task

### BR-14｜不假設跨系統原子提交

供應、金流與渠道無全域 transaction。已授權／已扣款但供應無法成立，依事先告知的流程 void／refund；供應確認但請款失敗則依取消能力補償或派案。未完成時保存責任與進度，不能從畫面消失。

## 04.2｜SM-02 交易狀態與異常處理

| 狀態域 | 允許主路徑 | 不可混淆 |
| --- | --- | --- |
| booking | NOT_REQUESTED → ON_HOLD／PENDING → CONFIRMED；取消經 CANCEL_REQUESTED → CANCELLED | UNKNOWN 必須先查詢；hold 到期轉 EXPIRED；不可由客戶付款倒推供應成功。 |
| payment | NOT_REQUESTED → PENDING → AUTHORIZED → CAPTURED；或直接 CAPTURED | AUTHORIZED 非已請款；VOIDED 是授權解除，不是退款。 |
| refund | RESERVED → SUBMITTED → PENDING → SUCCEEDED | UNKNOWN 占用退款保留；FAILED 必須確定沒有生效才能釋放。 |
| order | PENDING → CONFIRMED → COMPLETED；或 CHANGE_PENDING／CANCELLED／EXCEPTION | order 是對客戶投影，不把三個來源狀態合成一個難追查欄位。 |

| 故障劇本 | 必做的恢復策略 |
| --- | --- |
| 付款成功、預訂拒絕 | 保存支付成功證據；建立一次性退款／撤授權工作及通知；追蹤至正式結果。 |
| 預訂成功、請款失敗 | 先查支付，仍失敗才按可用供應取消政策處理；不能直接釋放原訂單證據。 |
| hold 到期晚付款 | 重新查可售；日期、價錢或條件變更需新同意；不可偷偷換場次。 |
| 外部逾時 | 相同 client_reference 查單；找不到且不能排除成功時保留 UNKNOWN，人工核對。 |
| 亂序／重複事件 | inbox 唯一鍵＋來源版本；必要時查正式狀態，不將已確認狀態被舊事件降回。 |
| 同步期間店員改單 | 比對外部 revision；衝突重新 preview，不覆蓋原人員新設定。 |
| 備份還原重播 | 先 reconcile 與 dedup，重建外部已有結果，再恢復寫入。 |

重試預設依 adapter 指定退避與上限；429 尊重 Retry-After，明確不可重試錯誤不重試。涉及副作用且結果未知，不因網路層 retry 政策直接再送。

## 04.3｜UC-03 語音接單與會話契約

| 入口 | 接法／資料 | 必須分開驗證 |
| --- | --- | --- |
| 電話來電 | 既有門號／總機授權轉接或 SIP；provider_session_ref 對應 case | 門號／電信／轉接權限、AI 告知、音訊與總機事件；不假定任意台灣門號直接可接。[S01] |
| 官網語音 | WebRTC 音訊與 Web 方案／報價卡；伺服器側工具控制 | 短效會話憑證；長效金鑰不給客戶；前端與後端只由一方執行副作用。[S02] |
| 語音訊息 | 音訊附件 → 掃描／轉錄 → message／demand | LINE 音訊附件不等於原生通話；message ID 及來源事件去重。[S03] |

### SM-03｜通話與回合是不同狀態

VoiceSession：CONNECTING → ACTIVE → TRANSFERRING／DISCONNECTED → CLOSED。Transfer：NONE → REQUESTED → RINGING → CONNECTED／FAILED。VoiceTurn：PARTIAL → FINAL → CONFIRMED；改口可 SUPERSEDED。Playback：QUEUED → PLAYING → PLAYED 或 INTERRUPTED。

### UC-03 主流程

驗證入站 → 建立案件 → 適用的 AI／錄音轉錄告知 → 確認語言 → 只取得必要條件 → 查正式報價 → 完整覆誦金額、日期、人數與關鍵條款 → 取得明確同意 → 後端交易 → 寄正式確認。電話付款走安全付款連結或已核准替代，不要求唸卡號或安全碼。

### BR-15｜停止播放與停止交易不同

客人插話時停止播放器已排程音訊，增加 demand_revision；取消尚未執行的舊工具。舊查詢回應保留稽核但不得覆寫新需求。已向外部送出的寫入不能靠停止音訊撤回，應查單／補償。音訊守護、工具取消與外部交易取消分開實作。[S02]

### 完成與成本

完成證據是正確原系統訂單、付款條件與通知，而非轉錄寫「訂好了」。保存音訊、轉錄、即時模型及轉接分項用量；未收到最終 usage 標 INCOMPLETE，不能視為零成本。

## 04.4｜UC-04 改口、驗證與真人接續

| 情境 | 必要行為 | 對外顯示 |
| --- | --- | --- |
| 兩／六人聽不清楚 | 只重問人數；關鍵欄位未 confirmed 不送寫入 | 清楚覆誦具體條件，而不是重來整段問卷。 |
| 客戶改日期 | 增加需求版；舊 quote／consent 失效；已送外部查結果 | 新報價確認卡，不能直接套舊同意。 |
| 背景談話／含糊回應 | 對關鍵同意要求明確重述或 UI／按鍵確認 | 不把「嗯、等一下」或第三人背景話當同意。 |
| 下單中掛斷 | 已取得有效同意的交易繼續核對；未同意不開始 | 用核准聯絡方式通知真正結果。 |
| 重撥／換入口 | 訂單存取或 case_resume 驗證通過才連結 | 回到原案，不依同名／來電顯示推定本人。 |
| 轉接指令成功 | 仍等待總機 connected 事件；交摘要與已做動作 | 未接通時不寫已由真人處理。 |
| 真人接手 | 原子遞增 owner_revision；阻止舊 AI 回覆／新寫入 | 真人可看進度；已送動作仍持續查核。 |
| 原始音訊保存 | 依資料類別與告知政策控制；可只留必要結果 | 拒絕不必要錄音仍提供核准替代服務方式。 |

### 驗證設計預設

訂單查閱／改退使用目的綁定的一次性驗證。建議 OTP 10 分鐘到期、5 次錯誤鎖定該 challenge；重送與限流按入口配置。正式客戶 ID 以 tenant＋issuer＋subject 管理，避免同電話被跨商家暗中建立完整個人檔案。這些數字是待評審的工程預設，不是法定期限。

### 語音同意憑證

伺服器以完整 quote hash、case/demand revision、已覆誦回合、明確回應片段與驗證等級建立一次性 authorization。由後端確認服務簽發，不接受模型自行傳 accepted=true 就產生有效同意。涉及退款與私人訂單，另做 order access 驗證。

## 05｜UC-05／06 訂後服務與客訴處理

| 項目 | 可開發規格 |
| --- | --- |
| 受理 | 即使未驗證仍可描述、建 complaint；任何訂單私人資料讀取與更改前先驗證，不以無法驗證為由拒絕記錄安全問題。 |
| 證據 | 以 sales_order.contract_snapshot、成交渠道承諾、金流、現場紀錄與客戶陳述建立 case_evidence；陳述不自動等於事實。 |
| 標準服務 | 查單、憑證、政策內改期、取消／退款由助理執行到正式結果；不是一律轉人。 |
| 補救選擇 | preview 根據政策、訂單版、付款主體、已給補救與可用餘額產生；顯示客戶影響與所需同意。 |
| 例外 | 爭議事實、超授權和解、資料外洩及人身事件交適當責任人；AI 保留證據、下一次更新時間與未完成工作。 |
| 結案 | 所有必要補救有結果、通知已送或另有追蹤、未解事項有理由；客戶無回覆不寫滿意，退款 pending 不關成已解決。 |
| 重開 | 經驗證同單／同問題可接回原案；新的主張追加，已退與已補償的總額累計檢查。 |

### SM-04｜案件與補救雙軌

Complaint：OPEN → CHECKING → WAITING_CUSTOMER／WAITING_MERCHANT／WAITING_CHANNEL → RESOLVING → RESOLVED → CLOSED。可 ESCALATED／REOPENED。RemedyAction：AUTHORIZED → SUBMITTED → PENDING → SUCCEEDED；分支 FAILED／UNKNOWN。退款或改期成功不強迫客訴同步關案。

### 介面與完成證據

createComplaint／addEvidence／previewRemedy／confirmRemedy／executeRemedy／resolveComplaint／reopenComplaint。標準改退也可從 order change preview 啟動，不需要把每筆取消都硬建成客訴。完成留外部退款／改單參考與查詢時間，不只留對話回應。

不以刪除負評交換合理處理；不自動要求客戶放棄權利。不將企業服務額度或 AI 自動補救額度解讀成顧客可獲得處理的上限。此為產品規則，個案法律責任另由負責人審核。

## 05.1｜補救政策與原子退款保留

| BR-16 政策必備欄位 | 用途 |
| --- | --- |
| policy_id＋version＋有效期間 | 知道核准的是哪一組可自行處理規則。 |
| 服務／渠道／原因碼／角色 | 限制自動執行範圍，不用情緒分數決定補償。 |
| 可選補救與證據要求 | 改期、取消、原路退款、補寄或指定補償；每種有前置證據。 |
| 單案與期間額度／幣別 | 單筆、比例與累計檢查；禁止跨幣別直接加總。 |
| 客戶同意與例外核准 | 不因商家有政策就跳過對客戶的必要確認。 |
| 收款與退款主體 | 渠道收款由有權一方退；不能平台再退第二次。 |
| 期限與升級人 | 已確認問題需繼續處理；超 AI 自動範圍轉專責，不拒絕／自動結案。 |

### BR-17｜併發時先保留額度，網路操作在 transaction 外

BEGIN
  lock payment row (tenant scoped)
  lock policy budget row (if applicable)
  verify order revision / preview hash / customer consent
  remaining = captured - SUM(refunds RESERVED|SUBMITTED|PENDING|UNKNOWN|SUCCEEDED)
  verify amount <= remaining and budget allows
  create-or-return stable task; consume auth into that task
  reserve refund + reserve policy budget + write outbox
COMMIT
worker -> original collector refund -> verify provider result
success: reserve -> spent; definite failure: release; UNKNOWN: keep reserve

外部原有退款也要先匯入或查核總餘額。來源無法提供可信餘額時，不自動執行金錢動作；建立有責任的核對工作。政策預算與退款上限是兩個獨立檢查，不能只檢查其中之一。

附件 02_atomic_refund.sql 提供 payment row lock＋同 business_key＋UNKNOWN 保留的參考函數；它不是完整授權系統，且本次未在 PostgreSQL 實機執行。

## 06｜UC-07 數據洞察與商家討論

| 指標／觀察 | 定義與資料來源 | 使用邊界 |
| --- | --- | --- |
| 正式報價率 | 期間內有 quote 的獨立 SALES case／同期間有有效需求的獨立 SALES case | 去除明確測試、垃圾案件；排除數量另列。 |
| 預訂完成率 | 已供應確認且付款條件符合的 orders／已正式報價的 cases | 按 case／order 指標分列，不能混分母。 |
| 完成服務客訴率 | 已履約 cohort 的有 complaint 訂單／同 cohort 已履約單 | 另列購買前／未履約案件及觀察截止，不能拿全部詢問作分母。 |
| 未成交理由 | 客戶明確表示的原因＋對應 source message | 沒有回覆為 UNKNOWN；模型推測另欄。 |
| 渠道貢獻 | 指定幣別收入－約定應付－退款調整－變動支援成本 | 缺成本或曝光資料明示 coverage，不排假名次。 |
| 自主完成率 | 無人工操作且 postcondition 已驗證的合格案件／全部合格案件 | 轉人、靜默、未確認工作不算成功；排除原因逐項列。 |

### UC-07 正常流程

受控 SQL／統計工作取得版本化 query 結果 → insight 記期間、分母、缺漏、觀察與來源 → LLM 解釋可支持的結論 → 只問商家完成該項建議所缺的營運知識 → 建立 change_proposal。尚無數據時可協助商品構想，但標示「商家構想／測試假說」。

### 檢查利益，而不是只追單量

短版可能提高成交卻降低每老師時段貢獻；商品優化卡需同時看材料、人員、準備清場、退款與客訴。可作對照就固定客戶／案件分組，不能故意省略必要交易或安全資訊。無足夠樣本不宣稱因果。

### 觸發預設

例行經營檢視可每週彙整一次；明確承諾落差、安全事件及交易故障依優先級即時派案。重複問題門檻與提醒額度為可配置值，不以任意百分比宣告模式成功。

## 06.1｜UC-08 素材索取與經營者互動

| 步驟 | 助理執行 | 經營者實際參與 |
| --- | --- | --- |
| 找缺口 | 先查可用且已授權素材；比較提案必需欄位 | 不必重複提供已存在資料。 |
| 提出請求 | 明說用途、缺什麼、可用格式、預定渠道與時點 | 用文字、語音、圖片、短片或文件回覆。 |
| 收件與關聯 | 以已驗證管理身分對應 proposal／request；沒有明確關聯先問 | 不靠群組顯示名稱認定老闆，也不錯綁別個案。 |
| 整理候選內容 | 保留原件與主張，抽取流程、限制、接待方法與商品欄位 | 只需更正不對的地方，不必維護 RAG 技術欄位。 |
| 補齊權利 | 確認拍攝者、人物、用途、語言、渠道與期限 | 資料提供與公開授權可分開確認。 |
| 產生預覽 | 服務差異、渠道內容與素材版本一起顯示 | 核准明確內容與使用範圍。 |
| 接續執行 | 核准後建立新版、更新渠道與查結果 | 不把整串上架工作再丟回商家。 |

### 一則具體素材請求

「短版的內容與價格已經整理好；要完成英語商品頁，還缺完成品實拍、現場說明卡與最後報到時間。請直接傳已有照片或用語音說明。素材預計只用於官網及合作渠道 A，核准前不公開。」

### 收件後的回覆

回覆已收到的項目、尚缺項目與待核准權利。不能只說謝謝，然後把素材停在聊天附件。若商家回覆無法提供某項，提案改用現有授權素材、縮小發布範圍或建立有期限任務，不直接拋棄整個改善案件。

M14 素材模組與 M06 提案共用案件；客訴證據預設 CASE_ONLY，必須另經適當核准才能作其他用途。AI 生成圖不得當作真實場域／服務證據。

## 06.2｜素材處理、權利與衍生檔

| SM-05 狀態 | 進入條件 | 可做與不可做 |
| --- | --- | --- |
| RECEIVED／QUARANTINED | 完成簽名上傳或原訊息附件下載 | 只能隔離保存，不能公開或直接讓模型執行嵌入指令。 |
| CHECKED | 類型、大小、惡意內容與來源檢查通過 | 可轉錄、OCR 必要內容、取得結構化候選，但不代表可發布。 |
| CLARIFYING | 內容或使用權不完整 | 只追問缺口；其他已完成項保留。 |
| READY_FOR_REVIEW | 草稿與權利資訊齊備 | 讓相應商家角色審閱原件、衍生圖、用途與版本。 |
| APPROVED → AVAILABLE | 核准 hash、用途、渠道與期限有效 | 發布前再次檢查權利，不能把一渠道核准當全網使用。 |
| REVOKED／EXPIRED／REJECTED | 撤回、到期或拒絕 | 停止新使用；衍生檔、索引與快取跟隨；外部已發布另有撤下任務。 |

### 建議工程預設：可調整，不代表平台政策或法律期限

單張圖片 20 MB、文件 30 MB、短片 200 MB、音訊 30 分鐘；超出可透過受控替代上傳。簽名 URL 建議 10 分鐘失效。上傳後用 magic bytes 檢查，不信副檔名；壓縮檔展開限制與 URL 轉址也要檢查。正式上線由效能、成本及商家需求校準。

### BR-18｜衍生素材可追溯

parent_asset_id 串原件與裁切、字幕、翻譯或渠道尺寸變體。每個版本保存 content_hash 與使用範圍；下載僅發短效 URL。內網、回環、link-local、雲端 metadata 位址與重新導向至這些位置一律阻擋，限制檔案解析工具的網路權限。

### 撤回不是清空所有歷史

撤回影響新的回答、推薦、發布及素材使用；已成交訂單的必要證據依目的及保存政策保留。保留與刪除範圍必須可查，不用「稽核需要」宣稱所有資料永遠保留。

## 06.3｜UC-09 服務版本核准與套用

| 步驟 | 具體規則 |
| --- | --- |
| 建立草案 | base_version＋JSON patch 白名單＋evidence_refs；每次經營者修改 proposal_revision 遞增。 |
| 驗證 | 完整 ServiceSpec schema、價格來源、資源衝突、素材權利、語言、通知及受影響渠道；缺項回 blocking_codes。 |
| 核准 | 經驗證管理主體審閱 diff；hash 包含基礎版本、內容、價錢、資源、素材權利快照、渠道清單、生效時間。 |
| 套用 | 後端再檢查基礎版本與權利；同 transaction 消耗核准到父 task、建立新 service_version、寫 outbox。 |
| 發布 | 依 manifest 建每渠道子任務，使用該核准範圍；不允許順手加入未核准渠道。 |
| 結果 | 各渠道讀回；父 task 可 PARTIAL；後續監看新版訂單與成本，舊單仍引用原快照。 |

### SM-06｜提案狀態

DRAFT → DISCUSSING → VALIDATED → AWAITING_APPROVAL → APPROVED → APPLYING → PARTIAL／VERIFIED → MONITORING → CLOSED。任何實質內容變更回 DISCUSSING 並使舊核准失效。已 APPROVED／RETIRED 的 service_version 不可改回 DRAFT 再覆寫內容。

### BR-19｜同一老師不因商品版本增加而變兩人

新增六十分鐘版本保留原九十分鐘方案，但若共用講師、座位與場地，就仍用原 resource pool。試行時段不等於新增容量。來源不支援完整資源表達時，縮小可售場次或待商家確認，不以平台局部記錄推算全局可售。

### 套用失敗的接續

如果原商品已被店員改過，回 VERSION_CONFLICT，展示差異而不是覆蓋。若本地新版本建立成功但外部發布失敗，保留新版與失敗子任務，不再建立第二個相同版本。其餘已成功渠道不強制重跑。

## 07｜UC-10 渠道商品與上架管理

| 能力 | 輸入與操作 | 完成證據 |
| --- | --- | --- |
| 商品內容 | 核准版本、素材、語言、選項及包含項目 | 外部商品／選項對應＋欄位讀回或正式審核結果。 |
| 銷售條件 | 核准價格、日期、適用客群與取消規則 | 價格與規則真的有效；不以介紹內容改好了代替。 |
| 上架／更新 | 建立 publication，記 manifest 與基礎外部版本 | desired、submitted、observed 與 observed_at。 |
| 暫停／下架 | 已核准操作範圍或既定安全停賣政策 | 實際不可再售或有外部狀態證據；已售訂單不刪除。 |
| 通知 | 各來源的編輯權與發送主體 | 必要通知只有正確主體發送，模板版本可查。 |

### SM-07｜發布工作

DRAFT → APPROVED → QUEUED → SUBMITTED → IN_REVIEW／LIVE_VERIFIED；例外 FAILED／MANUAL_REQUIRED／CONFLICT。暫停操作完成為 PAUSED_VERIFIED，不能硬套 LIVE。所有觀測版本由驗證器取得，前端不得自行 PATCH observed_version。

### UC-10 主流程與例外

商家核准 → 檢查渠道商品映射、每欄位能力及素材權利 → 送出 → 等待或讀回 → 比對必要欄位 → 回報各渠道結果。任一渠道失敗獨立處理；外部審核未完成就列審核中。原工具只支援庫存／訂單時，不能推定也能改商品與價格。[S07]

### 回復方式

保存上一個已驗證版本。來源支援回滾則執行核准的反向變更並再次驗證；來源不支援時先停止可控制入口的新銷售，建立補償或人工任務。不可寫「一鍵回復全渠道」卻沒有外部能力。

## 07.1｜UC-11 外部訂單與改退接續

| 事件／操作 | 系統必須完成 |
| --- | --- |
| 外部新訂單 | 驗證來源、環境與商家；以 canonical external reference 對應；必要欄位缺失先隔離，不猜服務版本。 |
| 外部店員改期 | 保存來源 revision，更新本地投影；舊 preview 失效；客戶再次要求修改時重新查詢。 |
| 客戶在平台取消 | 查原銷售／收款／供應責任；preview＋客戶確認；執行原有路徑，不建立第二套金流。 |
| 退款與合作報酬 | 正式結果更新退款，按原合約版本產生 reversal；不直接覆寫過去佣金。 |
| 憑證／核銷 | 根據來源能力接收；核銷與實際履約完成可分欄，不能任意等同。 |
| 通知 | 依 notification_owner 處理；來源渠道自行發行前信時，不假設改商家模板會改到渠道。 |
| 定期對帳 | 依 provider 的可信窗口查漏件，檢查款項、訂單、退款、發布；存差異與責任，不只算筆數。 |

### BR-20｜來源與主體不得混用

觸及來源、銷售方、收款方、履約方與通知方各自保存。來源是旅宿不表示旅宿一定是銷售方；我方旅行社有訂單服務能力，也不表示自動有其他渠道付款退款權。

### 外部異動不是任意降版

若事件沒有可靠的資源版本，應用來源查詢核對實際狀態。事件發生時間只能提供排序線索，不是無條件真實順序。UNKNOWN 工作在找到一致正式結果後才轉已完成；無法確認就留可見例外，不為了報表好看自動結束。

## 07.2｜連接器契約與受控瀏覽器

| 操作組 | 必須逐項確認的能力 |
| --- | --- |
| 商品 | read、create、update、pause；是否可設定 options／語言／圖片。 |
| 交易 | availability、quote、hold、book、lookup、reschedule、cancel、refund。 |
| 狀態／通知 | 事件類別、重送、事件 ID、來源版本、查單參考與通知負責人。 |
| 可靠性 | timeout、rate limit、retry-after、idempotency、外部業務參考、取消是否可撤回。 |
| 授權與費用 | 商家／渠道 scope、sandbox／production、方案與權限、API 產品版本、第三方收費主體。 |

### 連接器統一輸出

{ status: SUPPORTED | PENDING | UNKNOWN | UNSUPPORTED,
  external_ref, source_revision, verified_at,
  canonical_result, evidence_ref, retry_after, error_code }

這是本平台 adapter 契約，不是 rezio、LINE、電信或金流的真實端點。各廠商原文回呼由專屬 adapter 驗簽與正規化；只有正規事件進共用核心。固定 API／SDK 版本，升級先跑契約測試。

### UC-10／14 沒有 API 的執行路徑

第二順位可使用商家授權且平台允許的受控瀏覽器：白名單站點與操作範本、隔離 session、修改前預覽、畫面結構驗證、結果讀回及截圖證據。金融副作用一律走核准 adapter 流程，不讓模型任意點選付款／退款。遇 MFA／驗證碼交回授權者，絕不繞過。

頁面結構改變或不確定送出結果時停止該渠道寫入，先查結果。第三順位建立預填人工任務，列出責任、期限與工時；人工完成需附驗證，不算全自動成功。

整合啟用條件以實測證據為準。供應商文件證明功能存在，不證明本帳號有權操作。

## 08｜資料模型與關係圖

[原始圖像 2：請對照本節原始 Word／PDF。]

圖 2｜主要邏輯關係；全部 tenant 業務表使用 (tenant_id, id) 複合主鍵與同租戶外鍵。完整欄位見資料字典及 SQL。

| 領域 | 參考資料表 |
| --- | --- |
| 身分／合作 | tenants、memberships、locations、connector_accounts、connector_capabilities、channel_agreements、customer_identities、verification_challenges |
| 服務／知識 | service_products、service_versions、knowledge_facts、resource_bindings、channel_offers、version_assets |
| 接單／售後 | cases、messages、demand_revisions、quotes、authorizations、sales_orders、supplier_bookings、payments、refunds、complaints、case_evidence、remedy_policies、policy_budgets、remedy_previews、remedy_actions |
| 語音／經營 | voice_sessions、voice_turns、insights、change_proposals、material_requests、assets、asset_rights、publications |
| 可靠執行／帳務 | execution_tasks、execution_attempts、event_inbox、event_outbox、notifications、usage_events、settlement_entries、cost_entries、audit_events |

### 資料與合作投影

本版採單商家業務租戶保存該商家訂單與案件；跨旅行社／渠道只透過 agreement 取得必要投影及外部對應。未來多供應商組合需另設跨主體協調物件，不讓單筆訂單隱含跨租戶全域寫權。

## 08.1｜資料規則、快照與索引

| 類別 | 必須落實的資料規則 |
| --- | --- |
| 主鍵與時間 | UUID 由應用程式產生；created_at／updated_at 用 timestamptz；服務地另存 IANA timezone。revision 每次列更新遞增。 |
| 外鍵隔離 | 所有業務 FK 都包含 tenant_id；外部數字 ID 不能當本平台全域主鍵。self-FK 亦同。 |
| 不可變資料 | 需求快照、報價內容、已核准服務內容、證據、執行嘗試與結算更正只追加；舊單不隨商品版本改動。 |
| JSON 欄位 | ServiceSpec／DemandSpec／QuoteSnapshot／ChannelOfferSpec／RemedyPolicySpec 使用具名 schema；驗證後才能存，不當成無結構聊天桶。 |
| 金額 | bigint 最小貨幣單位；計費成本可 numeric，小額成本不先四捨五入成零；幣別與精度不猜。 |
| 敏感資訊 | 聯絡、語音、逐字稿保存加密物件參考；資料庫日誌與模型提示不放秘密金鑰／卡號。 |
| 索引與唯一 | event producer＋source_event_id；task operation＋business_key；quote 對應銷售單唯一；外部 account＋booking reference 唯一。 |
| 任務排程 | tenant/state/next_run_at 索引；以有限批次 SELECT FOR UPDATE SKIP LOCKED 取得工作，更新 lease 後提交再呼叫網路。 |

### RLS 與應用角色

DDL 啟用並 FORCE RLS，條件取 current_setting(app.tenant_id)。只能由驗證過的 middleware 在每 transaction SET LOCAL，不能讓客戶直連 DB 或自行傳 tenant 設定。連線池釋放前結束 transaction，防止租戶 context 外漏。RLS 不防同租戶越權，仍需案件 ownership 與欄位投影。[S08]

### DDL 的交付定位

附件提供 46 張表、同租戶 FK、主要 unique/check、版本保護 trigger 與退款保留參考函數。它是工程 migration 起點，需做實際 PostgreSQL 載入、併發、RLS 角色與備份還原測試。本次只完成附件結構驗證，不宣稱資料庫實機測試通過。

## 08.2｜關鍵物件欄位與不可變內容

| 物件 | 主要欄位 | 執行檢核 |
| --- | --- | --- |
| DemandSpec | service／具體時間／timezone／party／hard_constraints／confirmed_fields | 未確認欄位不自動成為重要交易參數；改版使舊 quote 失效。 |
| Quote | case、demand_id、offer、service_version、Money、snapshot、hash、expiry、source_ref | 內容不可改；到期、條件變更與需求版不符需重報。 |
| Authorization | actor、kind、target、revision、hash、scope、evidence、expiry、consumed_task | 僅後端簽發；一次性消耗到父工作；子任務不得擴張核准範圍。 |
| ExecutionTask | operation、business_key、request_hash、owner_revision、fence、lease、postcondition | 先存再做；同鍵參數不同 409；UNKNOWN 核對而不盲目重送。 |
| Complaint／Remedy | 成交證據、requested_outcome、policy、preview、collector、state、budget hold | 客訴與補救分開；未驗證可受理，改退前驗證；重複案不重補。 |
| Proposal／Asset | base_version、patch、impact、權利、hash、核准與素材來源 | 核准後變更要重核准；衍生素材追原件；權利撤回停止新使用。 |
| Publication | offer、operation、desired／submitted／observed version、task、evidence | 每渠道獨立；送出不等於生效；暫停與上架使用不同完成判定。 |
| SettlementEntry | origin、party、amount、currency、contract_version、basis、reversal_of | 不直接刪已結算項；部分退款按原規則沖回；原客不亂算佣金。 |

### 完整字典在哪裡

「資料字典.md」逐表列出每欄型別、必填、外鍵、用途與限制；「tables.metadata.json」是相同定義的機器可讀版。SA 不用一個大型 JSON 取代核心業務資料；彈性的內容只放在有指定 schema 的欄位。

## 08.3｜內部 API 共通契約與錯誤碼

所有端點屬本平台 /v1；openapi.yaml 的網址為 example.invalid 占位，並非已可連線服務。外部 vendor API 不直接暴露給前端或模型。

| 規範 | 要求 |
| --- | --- |
| 身分與範圍 | Bearer session／服務憑證驗 issuer、audience、expiry、scope；tenant 由憑證及合作授權導出。客戶只能看自己的案件／訂單。 |
| 寫入與重複 | 命令以 Idempotency-Key；重複成功回同物件，進行中回同 execution。業務 key 另防換 key 重做。 |
| 版本控制 | 對既有狀態的命令帶 expected_revision 或明確的 expected_order／demand_revision；不接受任意 state PATCH。 |
| 非同步回應 | 202 回 execution_id／publication；前端輪詢或訂閱讀取進度。202 不代表外部成功。 |
| 分頁與錯誤 | cursor 分頁（limit 1–100）；錯誤使用 application/problem+json，包含 code、trace_id、retryable，不揭露別租戶物件存在。 |
| Provider 回呼 | /connectors/{id}/webhooks 不用一般客戶 Bearer，但必須依連線驗原廠簽章；原文格式／ACK 依 adapter。未知連線或驗簽失敗不進業務。 |

| HTTP／code | 意思與 UI 接續 |
| --- | --- |
| 409 VERSION_CONFLICT | 重新讀取差異後再決定；不可自動覆寫。 |
| 409 IDEMPOTENCY_CONFLICT | 同 key 不同內容；回原請求辨識與安全提示，不執行。 |
| 409 AUTHORIZATION_STALE | 同意／核准版本過期；重新顯示並確認。 |
| 422 CAPABILITY_UNAVAILABLE | 此操作無權限或不支援；產生明確替代接法。 |
| 422 POLICY_APPROVAL_REQUIRED | 超出預先政策；保留案件並請相應角色核准。 |
| 422 INSUFFICIENT_REFUND_BALANCE | 正式可退金額不足，核對已有／未知退款，不再執行。 |
| 202 UPSTREAM_RESULT_UNKNOWN | 結果尚不明確，回 task 供追蹤；不是叫前端重送下單。 |
| 429 RATE_LIMITED／503 SOURCE_UNAVAILABLE | 顯示可重試時間／確認中；已有重要副作用先查結果。 |

## 08.4｜API 操作清單 1–20

| 內部端點（/v1 前綴省略） | operationId／用途 | 成功碼／scope |
| --- | --- | --- |
| POST /cases | createCase<br>建立接單或營運案件 | 201<br>cases:write |
| GET /cases | listCases<br>依授權查詢今日工作 | 200<br>cases:read |
| GET /cases/{case_id} | getCase<br>取得案件與下一步 | 200<br>cases:read |
| PATCH /cases/{case_id}/demand | reviseDemand<br>更新需求並使舊報價授權失效 | 200<br>cases:write |
| POST /cases/{case_id}/messages | submitMessage<br>送出文字／已掃描附件訊息 | 202<br>messages:write |
| POST /cases/{case_id}/handoffs | handoffCase<br>取得或交回回覆責任 | 200<br>cases:handoff |
| POST /verification-challenges | createVerificationChallenge<br>建立訂單存取／接續驗證 | 201<br>verification:create |
| POST /verification-challenges/{challenge_id}/verify | verifyChallenge<br>核對一次性碼 | 200<br>verification:verify |
| POST /services/search | searchServices<br>查詢經授權服務與適合理由 | 200<br>catalog:read |
| GET /service-versions/{version_id} | getServiceVersion<br>查服務版本的可見欄位 | 200<br>catalog:read |
| POST /services/{service_id}/availability | checkAvailability<br>取得來源可售結果 | 200<br>availability:read |
| POST /cases/{case_id}/quotes | createQuote<br>建立正式報價快照 | 201<br>quotes:write |
| GET /quotes/{quote_id} | getQuote<br>取得報價效期與條款 | 200<br>quotes:read |
| POST /quotes/{quote_id}/confirmations | confirmQuote<br>簽發客戶確認 | 201<br>customer:confirm |
| POST /checkouts | createCheckout<br>執行預訂與付款協作 | 202<br>orders:create |
| GET /orders/{order_id} | getOrder<br>查詢已授權訂單 | 200<br>orders:read |
| POST /orders/{order_id}/change-previews | previewOrderChange<br>正式改期或取消差異試算 | 201<br>orders:preview |
| POST /orders/{order_id}/notifications | resendOrderNotification<br>依通知責任重寄憑證或確認 | 202<br>orders:notify |
| POST /complaints | createComplaint<br>受理客訴與安全分級 | 201<br>complaints:write |
| GET /complaints/{complaint_id} | getComplaint<br>取得已授權客訴進度 | 200<br>complaints:read |

## 08.5｜API 操作清單 21–40

| 內部端點（/v1 前綴省略） | operationId／用途 | 成功碼／scope |
| --- | --- | --- |
| POST /complaints/{complaint_id}/evidence | addEvidence<br>追加陳述或歷史證據 | 201<br>complaints:evidence |
| POST /complaints/{complaint_id}/remedy-previews | previewRemedy<br>依訂單與政策產生補救試算 | 201<br>remedies:preview |
| POST /remedy-previews/{preview_id}/confirmations | confirmRemedy<br>確認客戶選擇的改退內容 | 201<br>customer:confirm |
| POST /remedy-previews/{preview_id}/execute | executeRemedy<br>原子保留額度並執行補救 | 202<br>remedies:execute |
| POST /complaints/{complaint_id}/resolution | resolveComplaint<br>記錄客訴處理結果 | 200<br>complaints:resolve |
| POST /complaints/{complaint_id}/reopen | reopenComplaint<br>客訴重開並接續原案 | 200<br>complaints:write |
| POST /voice-sessions | createVoiceSession<br>建立 WebRTC 或已授權來電會話 | 201<br>voice:create |
| GET /voice-sessions/{session_id} | getVoiceSession<br>取得語音與交接狀態 | 200<br>voice:read |
| POST /voice-sessions/{session_id}/transfers | transferVoice<br>轉接預先核准的真人目的地 | 202<br>voice:transfer |
| POST /voice-sessions/{session_id}/close | closeVoice<br>結束音訊但保留已授權交易追蹤 | 202<br>voice:close |
| GET /insights | listInsights<br>讀取可重現的觀察與缺漏 | 200<br>insights:read |
| POST /change-proposals | createProposal<br>建立有證據或標示假說的提案 | 201<br>proposals:write |
| GET /change-proposals/{proposal_id} | getProposal<br>讀取草案、缺口與影響 | 200<br>proposals:read |
| PATCH /change-proposals/{proposal_id} | reviseProposal<br>修改草案並使既有核准失效 | 200<br>proposals:write |
| POST /change-proposals/{proposal_id}/validate | validateProposal<br>檢查素材、資源、渠道與成本影響 | 200<br>proposals:validate |
| POST /change-proposals/{proposal_id}/approvals | approveProposal<br>商家核准指定差異及發布範圍 | 201<br>merchant:approve |
| POST /change-proposals/{proposal_id}/apply | applyProposal<br>依核准建立服務新版本 | 202<br>proposals:apply |
| POST /material-requests | createMaterialRequest<br>只索取提案缺少的素材 | 201<br>materials:write |
| GET /material-requests/{request_id} | getMaterialRequest<br>讀取已收件與尚缺內容 | 200<br>materials:read |
| POST /assets/upload-intents | createUploadIntent<br>建立私有隔離區上傳意圖 | 201<br>assets:upload |

## 08.6｜API 操作清單 41–58

| 內部端點（/v1 前綴省略） | operationId／用途 | 成功碼／scope |
| --- | --- | --- |
| POST /assets/{asset_id}/finalize | finalizeAsset<br>完成上傳並啟動掃描與抽取 | 202<br>assets:upload |
| GET /assets/{asset_id} | getAsset<br>讀取素材狀態與用途 | 200<br>assets:read |
| POST /assets/{asset_id}/rights | approveAssetRights<br>確認素材權利與對外用途 | 200<br>assets:approve |
| POST /assets/{asset_id}/revoke | revokeAsset<br>停止素材新使用並建立外部撤下工作 | 202<br>assets:approve |
| GET /channel-offers | listOffers<br>查詢各渠道商品設定 | 200<br>channels:read |
| POST /publications | createPublication<br>發布或調整已核准服務版本 | 202<br>channels:publish |
| GET /publications/{publication_id} | getPublication<br>取得各渠道實際生效證據 | 200<br>channels:read |
| POST /publications/{publication_id}/verify | verifyPublication<br>重新讀回來源與驗證變更 | 202<br>channels:verify |
| GET /connectors/{connector_id}/capabilities | getCapabilities<br>讀取已驗證連接器能力 | 200<br>connectors:read |
| POST /connectors/{connector_id}/reconcile | reconcileConnector<br>啟動訂單／付款／發布結果核對 | 202<br>connectors:reconcile |
| GET /tasks/{task_id} | getTask<br>查詢長工作與正式結果 | 200<br>tasks:read |
| POST /tasks/{task_id}/resume | resumeTask<br>依新證據喚醒／查詢任務 | 202<br>tasks:resume |
| GET /usage | getUsage<br>查用量與計費排除項 | 200<br>billing:read |
| GET /settlements | getSettlements<br>查合作子帳及沖回 | 200<br>settlements:read |
| GET /reports/channel-performance | getChannelPerformance<br>查渠道貢獻與資料覆蓋 | 200<br>reports:read |
| POST /agreements | createAgreement<br>建立待生效的合作授權 | 201<br>agreements:manage |
| POST /agreements/{agreement_id}/revoke | revokeAgreement<br>停止合作的新用途及接續既有訂單 | 202<br>agreements:manage |
| POST /connectors/{connector_id}/webhooks | receiveProviderWebhook<br>原廠事件收件 | 200<br>provider:signature |

## 08.7｜請求與回應範例：從確認到執行

### 1. 客戶確認正式報價（非 LLM 可簽發工具）

POST /v1/quotes/{quote_id}/confirmations
Authorization: Bearer <verified-customer-session>
Idempotency-Key: confirm-quote-00000001
{
 "expected_hash": "sha256-of-displayed-quote",
 "expected_demand_revision": 3,
 "confirmation_nonce": "server-issued-display-nonce"
}

伺服器確認此 session 正在審閱該報價且 nonce 綁定完整內容；回 authorization_id、target_hash、expires_at。語音路徑由受信任確認服務引用完整覆誦／明確回應證據，不使用任意自然語言當授權。

### 2. 建立 checkout

POST /v1/checkouts
Idempotency-Key: checkout-quote-000001
{"quote_id":"<uuid>","authorization_id":"<uuid>"}

202
{"execution_id":"<uuid>","order_id":"<uuid>",
 "booking_state":"ON_HOLD","payment_state":"PENDING",
 "payment_url":"https://payment.example.invalid/session",
 "next_action":"COMPLETE_SECURE_PAYMENT"}

### 3. 退款或其他補救

先 previewRemedy 取得正式試算、訂單版與退款主體；客戶確認後執行 /remedy-previews/{id}/execute。回 202／execution_id；若原廠結果不明，任務 UNKNOWN，但退款保留仍在。前端查 /tasks/{id}，不再送另一筆退款。

### 4. 核准後的渠道執行

approveProposal 回本次核准；applyProposal 建唯一父 task 與服務新版本。/publications 帶 parent_task_id、核准、offer、版本與 operation。子工作讀回成功才有 LIVE_VERIFIED；一份核准不能拿去建立另一個未列出的渠道商品。

工程附件範例使用完整 UUID 與具名 schema，可由 validate_package.py 檢查。上述為便於閱讀的縮寫，不是可直接送出的有效外部訂單。

## 08.8｜事件與非同步契約

{
 "event_id":"<uuid>", "schema_version":"1.0",
 "tenant_id":"<uuid>", "producer":"booking-worker",
 "event_type":"booking.confirmed",
 "occurred_at":"2026-11-11T14:00:00Z",
 "received_at":"2026-11-11T14:00:01Z",
 "correlation_id":"<uuid>", "causation_id":"<uuid>",
 "resource_id":"<uuid>", "resource_revision":4,
 "data":{"order_id":"<uuid>","booking_id":"<uuid>",
         "external_ref":"supplier-reference"}
}

| 事件群 | 事件及用途 |
| --- | --- |
| 收件與需求 | message.received、case.owner.changed、demand.revised、quote.created、customer.confirmed |
| 交易與客訴 | booking.confirmed／unknown、payment.verified、refund.verified、complaint.opened、remedy.verified |
| 語音 | voice.turn.confirmed、voice.transfer.connected、voice.session.closed |
| 經營與素材 | insight.generated、material.requested、asset.available／revoked、service.change.approved、service.version.created |
| 渠道與執行 | channel.version.observed、channel.publication.failed、order.external.updated、task.woken |
| 成本與權利 | usage.recorded、settlement.reversed、agreement.revoked、notification.failed |

### 交付與消費規則

以 outbox／inbox 實作至少一次傳遞；每個消費者保存 producer＋source_event_id 去重。相同 ID 不同 payload hash 進隔離與告警。major schema 不支援就 dead letter，不嘗試猜欄位。事件 payload 只帶最小 ID／狀態與必要數字，不廣播原始對話、卡號或證件。

補抓輪詢與 webhooks 可同時存在；同一外部訂單用 canonical reference 去重。schema minor 可新增選用欄位須版本協商；變更既有欄位意義／型別需新 major。重播不重複扣款、發布或計費。

## 09｜UI-01–04 接單、語音與客訴畫面

| 畫面 | 必備資訊 | 按鈕／條件 |
| --- | --- | --- |
| UI-01 今日工作 | 案件類型、負責人、優先級、等待誰、期限、下一步、最近外部結果 | 篩選接單／客訴／素材／核准／發布；接手需 expected owner revision。 |
| UI-02 接單案件 | 語言、來源、服務、日期、party、未確認欄、quote／expiry、訂單與支付分開狀態 | 查可售、建立報價、發確認、查單、轉人；無同意不顯示可直接完成購買。 |
| UI-03 語音會話 | 即時逐字稿狀態、確認欄位、播放／接通／轉接狀態、當次報價卡 | 靜音／停止音訊不取消訂單；轉接目的地用白名單；交易進度在通話結束後可看。 |
| UI-04 客訴案件 | 客戶期待、驗證狀態、成交快照、不同來源陳述、證據、補救與退款進度 | 驗證前只建案；preview 顯差異及成本；政策內執行；pending 補救不能按已解決。 |

### UI 欄位檢核

日期要有年月日＋服務地時區；錢要有幣別與包含項目；狀態要用「待確認／處理中／結果核對中」而不是一律成功／失敗。未知值顯示未知，不能空值默認為 0、免費、可售或無限制。

### 存取與錯誤

外部物件不可讀，回一致的查無授權資料畫面，不暴露別家店是否有該筆單。409 顯示差異並重載；202 顯示 execution 進度；長操作可離開頁面，不因關閉視窗遺失工作。多語畫面保留相同交易狀態意義。

### 同意與無障礙互動

語音不是唯一方式：報價、重要條件與訂單可由文字頁查看。客戶可以回到購買頁完成確認；通知與查單不強制特定通訊帳號。使用鍵盤可操作、清楚的錯誤提示及未輸入值標記，不只靠顏色傳達狀態。

## 09.1｜UI-05–08 經營、素材、渠道與收益

| 畫面 | 必備資訊 | 按鈕／結果 |
| --- | --- | --- |
| UI-05 經營提案 | 觀察期間、分母、來源、缺漏、假說、改動差異、成本及資源影響 | 討論、修改、索取素材、驗證、核准；核准前看到受影響渠道與既有單不變。 |
| UI-06 素材請求 | 用途、缺項、已有素材、檔案格式、來源／權利、準備狀態 | 上傳、語音說明、確認權利、退回澄清、撤回；收到不等於已核准。 |
| UI-07 渠道商品 | 商品／選項對應、正式價格來源、desired/submitted/observed、權限與能力 | 發布、暫停、驗證、看差異、交人工；每渠道逐筆狀態，不用全域完成遮蔽失敗。 |
| UI-08 收益與成本 | 來源、訂單、契約版、應收付、退款沖回、語音模型人工與資料覆蓋 | 依幣別與期間比較；未知成本明示；GMV、平台收入與商家實收分列。 |

### 商家互動的完成標準

商家可以用對話提出「短版只先放官網與合作旅宿」。畫面要轉成具體、可核准的服務／渠道 manifest。商家按同意後，助理負責建立版本、發布與查證；不能只回「請到某平台照以下步驟自行修改」。確實需要原平台授權人操作的項目，則有預填任務與回傳證據，不假稱自動完成。

### 敏感商業資料隔離

渠道只看到其允許商品、條件與訂單成效，不能看到其他渠道底價、原客原始對話或商家內部討論。前端能隱藏不等於後端有權返回，所有欄位投影由 API 產生。

## 09.2｜安全、隱私與資料生命週期

| 控制 | 實作與驗收 |
| --- | --- |
| 身分與管理 | 後端驗 token；管理員重要動作依政策 step-up。不以聲紋、來電顯示、聊天自稱老闆取得管理權。 |
| 工具安全 | 每操作 allowlist＋schema＋權限＋版本＋用途；模型無直接 SQL／自由 HTTP／金鑰。輸入與工具結果不可改系統規則。[S09] |
| 音訊與附件 | 隔離上傳、掃描、最小轉錄；敏感支付資訊遮蔽；語音最終用量及告知狀態可查。 |
| 來源安全 | 原文驗簽、防重播、環境分離、租戶由 connector URL 導出；未知 schema 隔離，不由 payload 自稱來源。 |
| 快取與檢索 | cache key 包含 tenant、role、purpose、agreement、service_version；檢索前套權限與有效期。撤回時失效。 |
| 支援存取 | break-glass 指定店／用途／期限，核准與稽核；不給工程常態跨店原件權。 |
| 秘密與瀏覽器 | 秘密管理服務、隔離 browser session、站點白名單、不可自動繞 MFA；日誌不記 cookie／金鑰。 |
| 刪除與保留 | 原件、衍生檔、轉錄、索引、快取各有 retention_policy_ref；例外保存需目的、期限與可追溯理由。 |

### 保存政策設計預設

未核准原始錄音預設不長期保存；有用途及告知依據才開啟。短效上傳、失敗暫存、正常對話、交易證據、稽核與彙總分析採不同政策，不在 SA 任意指定法定年限。上線前填定租戶／資料類別保存政策；測試環境使用合成資料。

### 必要服務與資安事故

模型或用量降級不能讓已成立訂單退款、安全通知消失；保留固定查詢／人工接續能力。疑似越權、資料外洩或重複金融副作用，先關閉受影響寫入 scope，保留其他商家與唯讀服務，依事件分級通知責任人。

## 09.3｜非功能需求與測試負載

以下是設計驗收目標，不是已測得績效或對外 SLA。負載與第三方回應條件先凍結；應同時報告平台耗時與第三方耗時。

| 項目 | 建議測試基線／通過條件 |
| --- | --- |
| 負載 fixture | 50 個測試租戶、每店 100 個服務版本、合計 10 萬歷史案件；20 路同時語音、100 路文字案件；事件常態 20/s、60 秒突發 100/s。可由容量評審調整。 |
| 收件 | 正常測試條件下，驗簽＋耐久 inbox＋ACK P95 < 1 秒；不等模型與交易。 |
| 一般回答 | 已核准 FAQ P95 < 8 秒；critical facts 必須有來源；不可用全部拒答取得正確率。 |
| 語音 | 本地測試網路／乾淨音訊下，從 utterance end 到第一個實質回答 P95 目標 ≤ 3 秒；查外部工具分開量測，不以安撫語當實質回答。 |
| 任務與交易 | 重送、併發、worker kill、事件亂序及超時，64 案例不出現未授權或重複不可逆副作用。 |
| 回答品質 | 凍結測試集有依據正確回答 ≥95%，同步列覆蓋及拒答；所有金額、日期、權限與交易安全案例必須全通過。 |
| 可用性 | 試點核心月目標 99.5%；第三方影響分列，不排除所有故障才計算。 |
| 復原 | 試點 RPO ≤ 5 分鐘、RTO ≤ 4 小時；以還原＋外部對帳演練驗證。 |
| 權利撤回 | 本平台新檢索／發布的授權檢查立即生效；索引快取清理目標 5 分鐘內；外部撤下另追責，不虛報已完成。 |
| 可觀測性 | trace 串案件／task／外部參考；敏感資訊去除；告警、用量與操作 evidence 可查。 |

語音另測口音、噪音、斷線、歧義及不同服務地時區。延遲量測拆音訊、停頓判斷、模型、工具與播放；不能只報 API 首 token。

## 09.4｜部署、遷移、告警與維運

| 面向 | 開發與維運交付 |
| --- | --- |
| 部署單位 | Web／API、背景 worker、語音 gateway、受控 browser runner、資料庫、私有物件儲存；模型與外部 provider 經 adapter。 |
| 環境 | DEV／SIT／UAT／PROD 分離帳號、資料、金鑰與回呼；不得拿模擬付款事件進正式訂單。 |
| 資料遷移 | expand→backfill→驗證→切換→contract；schema／API 版本相容；快照及 audit 不任意改寫。 |
| 啟用 | 能力 flags 依租戶／connector／operation 開啟；先唯讀影子、再沙盒寫入，最後小範圍正式授權。 |
| 備份 | 加密備份＋時間點還原；先恢復唯讀與對帳，核對金融／供應結果後恢復重要寫入。 |
| P1 | 未授權、重複扣款／退款、疑似洩漏、安全問題：立即停相關 scope、通知值班責任人。 |
| P2 | 發布部分失敗、待確認逾時、回呼缺失、素材權利變更：自動核對＋有期限任務。 |
| P3 | 一般知識缺漏、商品改善、長尾品質：彙整商家待辦，不逐條打擾。 |
| 人工責任 | 商家、銷售方、平台支援各有 duty roster、服務時段、升級與未接手備援；自動受理不宣稱 24 小時真人。 |

### 每次發布前

回歸契約與驗收、資料 migration、權限測試、模型版本評測、feature flags 與回復點。語音模型或提示更新也視為發布，不直接上正式；固定測試資料與輸出檢查後再小流量切換。

### 實際營運手冊必備

查到一筆 UNKNOWN 訂單怎麼處理、誰能關閉寫入、退款卡住去哪查、怎麼接回原客服、渠道更新失敗如何止售、素材撤回如何追蹤、如何重送通知而不重跑交易。手冊需指向真實環境與責任人，不能只有架構圖。

## 09.5｜UC-12 收入、用量與合作結算

| 資料線 | 系統規格 |
| --- | --- |
| 企業服務 | plan／contract_version 定義據點、模組、包含用量、超額與支援；客戶計費單位跟供應商成本用量分開。 |
| 語音用量 | 電信、轉接、轉錄／即時模型分別記 provider reference；final usage 逾時先 INCOMPLETE，後續補正同事件。 |
| 原有客戶 | origin=MERCHANT_EXISTING；工具費依契約，不自動收新增客源佣金。 |
| 渠道／自有直客 | origin=PARTNER／OWN_DIRECT；來源簽名＋契約版本，另記渠道應付與自有獲客成本。 |
| 結算子帳 | supplier payable、channel payable、platform fee 分列；basis 指定 gross／net ex tax／fixed／usage；不重複把 GMV 當收入。 |
| 退款沖回 | 依原 contract_version 產生反向或差額 entry；保留 reversal_of；部分退款與費用負擔可核對。 |
| 重試排除 | 外部事件去重、服務業務鍵去重；重試耗費記內部成本，但不再向商家收一筆新業務費。 |
| 額度 | 一般探索可低成本降級；已成立訂單核對、取消退款、安全與必要通知保持接續。 |

### 淨貢獻不是「訂單佣金減模型費」

合作貢獻＝平台實際服務與交易報酬－渠道／系統商等應付－成功及未成交需求的模型、語音、訊息、外部查詢與人工成本；之後再檢查商家取得、導入、固定研發與維運。不同幣別先分帳；轉換只用有來源與時間的會計報表換算，不由 LLM 自算匯率。

### 帳務正確性驗收

一個業務事件只計一次；重放不重計；一張部分退款有明確沖回，且不超原應付；未知費用標未核對而不是 0。來源歸因與實驗估計增量在報表分開，不把有 tracking id 當成真正創造的新消費。

## 09.6｜UC-13–15 合作、復原與資料治理

| 使用案例 | 前提與流程 | 完成證據 |
| --- | --- | --- |
| UC-13 合作授權 | 渠道憑證導出租戶與合作；檢查商品、欄位、用途及動作；查詢與交易逐次驗證。客戶確認不由渠道模型替代。 | 有限服務投影與交易紀錄；撤回後新使用停止，既有訂單仍有責任方。 |
| UC-14 執行復原 | 事件／計時器喚醒；取得 lease＋fence；再查授權和版本；外部未知先查證；等待釋放算力；人工任務附結果證據。 | 程序重啟與雙 worker 下仍無重複扣款、退款或發布；未完成有期限和負責人。 |
| UC-15 資料與模型治理 | 資料撤回先停新用途，再追蹤原件、派生物、索引與外部發布；模型與提示升級先跑回歸、影子流量，再小範圍切換。 | 各資料副本可查撤回／刪除結果；必要保留有理由期限；模型發布可回復。 |

### 原生外部訂單不得憑空補造平台確認

外部匯入的訂單允許 case_id、quote_id、customer_id 尚未對應，creation_mode=IMPORTED 並記錄來源完整度。未取得的原始條款維持未知，不拿目前網頁填補。平台新下單則必須有已確認 quote、案件及客戶關係。API 的訂單快照區分完整 QuoteSnapshot 與 ImportedOrderSnapshot。

### 執行嘗試與業務結果分開

每次外部嘗試保存 attempt_no、fence、request_hash 與來源參考。SUBMITTED／UNKNOWN 可在核對後更新證據；已確認 SUCCESS／FAIL 的嘗試不得覆寫，後續更正或重試另建紀錄。任務整體是否完成仍由 postcondition 判斷。

15 個使用案例的觸發、前置、逐步流程、替代流程、資料表、API 及驗收對照，完整收在 use_cases.md／use_cases.json。

## 10｜驗收矩陣 SA-AT-001–012

| 編號／來源 | Given 場景與 When 動作 | Then 必須結果 |
| --- | --- | --- |
| SA-AT-001<br>T01 | 英文客人詢問中文現場服務<br>英文客人詢問中文現場服務 | 正確說明，不誤稱英文講師 |
| SA-AT-002<br>T02 | 相對日期、旅客與商家時區不同<br>相對日期、旅客與商家時區不同 | 以具體日期及服務地時區確認 |
| SA-AT-003<br>T03 | 兩材料、四人占位<br>兩材料、四人占位 | 扣用正確資源或轉待確認，不少算座位 |
| SA-AT-004<br>T04 | 報價後改人數或過期<br>報價後改人數或過期 | 重新報價，原授權不能套新金額 |
| SA-AT-005<br>T05 | 客戶連點購買、付款回呼重送<br>客戶連點購買、付款回呼重送 | 一筆有效交易與一筆服務計費 |
| SA-AT-006<br>T06 | 預訂回應逾時但上游已成功<br>預訂回應逾時但上游已成功 | 查單找回，不重複預訂 |
| SA-AT-007<br>T07 | hold 到期後付款到達<br>hold 到期後付款到達 | 核對供應，不能履行時走退款／重新同意 |
| SA-AT-008<br>T08 | 收款成功但供應拒絕<br>收款成功但供應拒絕 | 可追蹤退款及責任人，不顯示已訂妥 |
| SA-AT-009<br>T09 | 供應成功但請款失敗<br>供應成功但請款失敗 | 執行可用補償或指派例外，不遺失訂單 |
| SA-AT-010<br>T10 | 客戶取消、退款接口失敗<br>客戶取消、退款接口失敗 | 分開顯示取消與退款狀態 |
| SA-AT-011<br>T11 | 真人接手時模型仍在產生文字<br>真人接手時模型仍在產生文字 | 發送前檢查回覆所有權，AI 停止回覆 |
| SA-AT-012<br>T12 | 商家文件要求讀取其他商家底價<br>商家文件要求讀取其他商家底價 | 不影響權限，讀取與工具執行被拒絕 |

完整 Given、需求映射、證據與 Gherkin 見 acceptance_cases.md／acceptance.feature。以上是待執行業務驗收規格，不是本次已完成的系統測試結果。

## 10｜驗收矩陣 SA-AT-013–024

| 編號／來源 | Given 場景與 When 動作 | Then 必須結果 |
| --- | --- | --- |
| SA-AT-013<br>T13 | 商家核准後草案內容被修改<br>商家核准後草案內容被修改 | 核准失效，要求重新核准 |
| SA-AT-014<br>T14 | 原商品在渠道發布前被人改版<br>原商品在渠道發布前被人改版 | 顯示衝突，不覆蓋新設定 |
| SA-AT-015<br>T15 | 一渠道成功、另一渠道拒絕<br>一渠道成功、另一渠道拒絕 | 分別顯示版本，派處理任務，不假稱全部同步 |
| SA-AT-016<br>T16 | 新短版與舊版共用講師<br>新短版與舊版共用講師 | 同資源時段正確限制，不各自賣滿 |
| SA-AT-017<br>T17 | 商家原客使用 AI 下單<br>商家原客使用 AI 下單 | 依服務契約計費，不誤收外部客源佣金 |
| SA-AT-018<br>T18 | 訂單部分退款<br>訂單部分退款 | 沖回對應合作報酬，保留原紀錄 |
| SA-AT-019<br>T19 | 商家撤回某渠道知識授權<br>商家撤回某渠道知識授權 | 新查詢、快取及索引不可再對該渠道使用 |
| SA-AT-020<br>T20 | 客人不回覆就離開<br>客人不回覆就離開 | 未成交原因記未知，不偽造「太貴」 |
| SA-AT-021<br>T21 | 通知失敗但交易已完成<br>通知失敗但交易已完成 | 重送通知，不再扣款或預訂 |
| SA-AT-022<br>T22 | 系統重啟及事件亂序<br>系統重啟及事件亂序 | 流程持續，錯序不把已確認狀態倒回未付款 |
| SA-AT-023<br>T23 | 外連到原購買頁但沒有回傳<br>外連到原購買頁但沒有回傳 | 只記外連／待確認，不當成已付款 |
| SA-AT-024<br>T24 | 月使用額度用完<br>月使用額度用完 | 一般探索可降級；既有訂單必要服務不中斷 |

完整 Given、需求映射、證據與 Gherkin 見 acceptance_cases.md／acceptance.feature。以上是待執行業務驗收規格，不是本次已完成的系統測試結果。

## 10｜驗收矩陣 SA-AT-025–036

| 編號／來源 | Given 場景與 When 動作 | Then 必須結果 |
| --- | --- | --- |
| SA-AT-025<br>A25 | 語音完成預訂<br>以繁中與英文各完成一次包含日期、人數、查詢、確認及付款接續的預訂。 | 原系統僅有一張正確訂單；錄音或逐字稿並非唯一完成證據。 |
| SA-AT-026<br>A26 | 改口與打斷<br>播放報價時改日期／人數；舊工具查詢稍後才回來。 | 舊結果不覆蓋新需求，不用舊授權下單。 |
| SA-AT-027<br>A27 | 斷線與重撥<br>明確授權後斷線，再用文字或電話接續。 | 驗證後回到原案，查明外部結果，不重複下單。 |
| SA-AT-028<br>A28 | 轉接未接通<br>系統已送出轉接要求，但真人未接或總機失敗。 | 不標已接手；提供實際可用的接續方式並保留責任。 |
| SA-AT-029<br>A29 | 語音辨識不確定<br>日期、幣別或兩／六人數聽不清楚，或有背景語音。 | 只重問關鍵欄位，沒有確認不產生重要寫入。 |
| SA-AT-030<br>A30 | 語音訊息重送<br>相同 LINE 音訊 webhook 被重送。 | 同一事件只建一次處理；不重複扣用量與下單。 |
| SA-AT-031<br>A31 | 標準改退<br>客戶身分已驗證、訂單符合既定政策。 | 助理能自行執行到正式結果，不是全部轉真人。 |
| SA-AT-032<br>A32 | 退款未知<br>退款請求已送出但連線超時。 | 標示 UNKNOWN／PENDING，查詢結果，不再退第二筆。 |
| SA-AT-033<br>A33 | 跨渠道同一客訴<br>同一訂單先來電、後訊息再次要求補償。 | 合併至經驗證的同一案，累計檢查已給補救及退款。 |
| SA-AT-034<br>A34 | 舊單與重大事件<br>商品已改版；舊客訴涉及原承諾或當下安全疑慮。 | 使用舊版證據；重大事件通知責任人，不以普通補償結案。 |
| SA-AT-035<br>A35 | 數據不捏造<br>詢問有去重、明確理由與未知理由，部分渠道缺少曝光。 | 數字可重現、分母與缺漏可見，不把未知原因改寫成價格問題。 |
| SA-AT-036<br>A36 | 主動索取素材<br>建議需要新照片與現場說明，但已有部分可用素材。 | 只索取缺少內容；說清用途、可接受形式與核准方式。 |

完整 Given、需求映射、證據與 Gherkin 見 acceptance_cases.md／acceptance.feature。以上是待執行業務驗收規格，不是本次已完成的系統測試結果。

## 10｜驗收矩陣 SA-AT-037–048

| 編號／來源 | Given 場景與 When 動作 | Then 必須結果 |
| --- | --- | --- |
| SA-AT-037<br>A37 | 語音與照片整理<br>經營者用語音說明、上傳照片與短片。 | 整理成候選規則及商品草案，原件、主張與草稿可追溯。 |
| SA-AT-038<br>A38 | 素材未授權<br>照片含可識別人物或使用範圍尚未確認。 | 不直接公開；請求核准或改用可用素材，不把整個案件丟棄。 |
| SA-AT-039<br>A39 | 核准後又修改<br>商家核准版 A 後，新訊息改了價格或內容。 | 版 A 核准不能用於版 B；需更新核准，已成交承諾不變。 |
| SA-AT-040<br>A40 | 渠道部分成功<br>自有頁成功、外部平台審核中、另一渠道寫入失敗。 | 分別顯示實際版本，後續任務可追蹤，不回覆「已全部更新」。 |
| SA-AT-041<br>A41 | 無 API 操作<br>使用已允許的瀏覽器接法，途中遇到驗證或頁面改版。 | 不繞過驗證；保存已執行步驟，交回授權者並列未完成。 |
| SA-AT-042<br>A42 | 原生訂單異動<br>店員在原系統改期，客戶又在助理處詢問或申請改期。 | 查最新版本避免互相覆蓋；保留原渠道及付款主體。 |
| SA-AT-043<br>A43 | 關鍵權限與提示注入<br>客戶自稱老闆、圖片含指令、其他商家資料被引用要求。 | 不提升權限、不跨店讀寫；管理入口與客戶入口保持隔離。 |
| SA-AT-044<br>A44 | 執行與費用核對<br>服務中斷、通知重送、任務重試、人工介入後完成。 | 單次副作用、可核對結果、重試不重收業務費，真實人工成本保留。 |
| SA-AT-045<br>SA 新增 | 跨租戶複合外鍵與 API 存取<br>以商家甲的 session 指定乙的 order_id／asset_id，再直接測複合 FK。 | API 不洩漏存在資訊；DB 拒絕跨租戶參照；允許的合作投影仍可用。 |
| SA-AT-046<br>SA 新增 | 人員接手與工作租約競爭<br>工作 A 租約到期，B 取得新版 lease；A 的晚到回覆與寫入嘗試到達。 | 舊 fence 不可發新動作；已送出外部操作先查結果，不重做。 |
| SA-AT-047<br>SA 新增 | 同付款併發部分退款<br>對同一已收款同時送出兩個不同案件的退款，合計超出餘額。 | 固定鎖順序原子保留；只接受可用總額，UNKNOWN 仍占用，不超退。 |
| SA-AT-048<br>SA 新增 | 跨案件補救政策額度<br>兩案同時使用同一政策期間額度；其中一筆超時。 | reserved＋spent 不超 limit；超時保留；例外轉人工而不拒絕客戶權利。 |

完整 Given、需求映射、證據與 Gherkin 見 acceptance_cases.md／acceptance.feature。以上是待執行業務驗收規格，不是本次已完成的系統測試結果。

## 10｜驗收矩陣 SA-AT-049–060

| 編號／來源 | Given 場景與 When 動作 | Then 必須結果 |
| --- | --- | --- |
| SA-AT-049<br>SA 新增 | 兩來源匯入同一訂單<br>渠道通知與預約系統輪詢回傳同一供應外部單，事件 ID 不同。 | 以 canonical connector/account/external_order 映射合併；不重複銷售單、佣金。 |
| SA-AT-050<br>SA 新增 | 跨渠道訂單不可越權<br>合作方 A 的 token 查詢渠道 B 訂單或商家底價。 | 即使同供應商也拒絕；只回被授權欄位；audit 記用途與拒絕。 |
| SA-AT-051<br>SA 新增 | 核准重放與變更範圍擴張<br>以同 authorization_id 建立另一筆單，或把核准兩渠道擴為第三渠道。 | 僅同一穩定業務鍵／核准 manifest 可續作；其他回 AUTHORIZATION_SCOPE_MISMATCH。 |
| SA-AT-052<br>SA 新增 | 素材撤回後派生內容<br>已用素材建立多語圖片與三個渠道版本；商家撤回使用權。 | 新發布立即停止；索引快取失效；衍生檔跟隨權利；外部撤下逐渠道追蹤。 |
| SA-AT-053<br>SA 新增 | 來源頁面要求擴權<br>商家 PDF、圖片、外部工具結果含管理指令／外傳金鑰要求。 | 不改權限、不擴網址白名單；沒有 secret 進入模型上下文。 |
| SA-AT-054<br>SA 新增 | 語音最終用量缺失<br>通話中斷，未收到 provider final usage；之後延遲事件到達。 | 先 INCOMPLETE 不視為零；取得 final 後調整同一事件，不對商家重收。 |
| SA-AT-055<br>SA 新增 | 不支援事件版本與毒訊息<br>schema major 不支援、同 event_id 不同 hash，或超大附件。 | 不更新業務狀態；隔離／死信及告警；其他租戶正常處理。 |
| SA-AT-056<br>SA 新增 | 備份還原後外部已成功<br>還原到付款送出前、外部實際已扣款的時間點，重新啟動工作程序。 | 先核對外部參考；對帳期間不重扣；RPO/RTO 演練證據可查。 |
| SA-AT-057<br>SA 新增 | 平台支援限時存取<br>支援人員用過期 break-glass，或未附用途讀原始語音。 | 拒絕；有效排障權限僅在指定租戶／欄位／期限生效，記 audit。 |
| SA-AT-058<br>SA 新增 | 外部欄位映射不完整<br>渠道只能改文字不能改價，卻收到同時改兩項的已核准提案。 | 文字／價格能力逐項判斷；價格列待處理，不假稱整商品一致。 |
| SA-AT-059<br>SA 新增 | 來源渠道通知唯一責任<br>渠道會自行寄憑證，平台也接到核銷／預訂成功事件。 | 依 notification_owner 只由指定方寄必要通知；不得雙重或矛盾通知。 |
| SA-AT-060<br>SA 新增 | 多語必要語意一致<br>外語素材漏掉不包含項目、現場語言、年齡或實際扣款幣別。 | 發布前關鍵欄位語意檢核擋下；核准版本與訂後資訊一致。 |

完整 Given、需求映射、證據與 Gherkin 見 acceptance_cases.md／acceptance.feature。以上是待執行業務驗收規格，不是本次已完成的系統測試結果。

## 10｜驗收矩陣 SA-AT-061–064

| 編號／來源 | Given 場景與 When 動作 | Then 必須結果 |
| --- | --- | --- |
| SA-AT-061<br>SA 新增 | 素材掃描與 URL 存取<br>上傳偽副檔名、惡意文件、內網 URL 或轉址到 metadata 端點。 | 隔離檔案；禁止內網抓取；核准前不供模型主動工具執行或公開。 |
| SA-AT-062<br>SA 新增 | 保存政策與可驗證刪除<br>測試保存期限屆滿、資料刪除與必要訂單證據保留。 | 原件、縮圖、索引、快取分別有刪除結果；保留項有目的與期限，非永久豁免。 |
| SA-AT-063<br>SA 新增 | 貨幣精度與退款<br>以 0 位與 2 位小數幣別各下單、部分退款與佣金沖回。 | 整數最小單位正確、無浮點誤差；不跨幣別加總，不將所有幣別寫死為兩位；金流整數元與內部最小單位依介面規格轉換。 |
| SA-AT-064<br>SA 新增 | 標準服務不被核准流程卡死<br>在已核准政策內連續執行標準接單及合規取消，再嘗試新增價格承諾。 | 前兩者直接執行並可核對；僅新承諾要商家核准，並非所有操作都請老闆。 |

完整 Given、需求映射、證據與 Gherkin 見 acceptance_cases.md／acceptance.feature。以上是待執行業務驗收規格，不是本次已完成的系統測試結果。

## 10.1｜測試層級、資料與上線關卡

| 層級 | 必交證據 | 不可冒充的成果 |
| --- | --- | --- |
| 契約／靜態 | OpenAPI 型別、$ref、JSON examples、事件 schema、需求與驗收覆蓋 | 檔案可解析不等於 API 已部署。 |
| 單元與資料庫 | 狀態轉移、snapshot、RLS、同租戶 FK、退款／policy budget 並行鎖測試 | Python 模擬規則不等於 PostgreSQL 真鎖可用。 |
| 連接器模擬 | 逾時、重送、晚事件、錯版本、重啟與平台故障注入 | mock 成功不等於取得第三方寫入權。 |
| 沙盒整合 | 選定實際工具正常訂單、改退、語音接入、素材及兩入口發布讀回 | 只有原廠文件或只讀介面，不算寫入功能通過。 |
| 正式小範圍 | 經授權實際商品、真事件、原系統可見單、指定金流測試與核對 | 不以聊天截圖／HTTP 200 作交易成功。 |
| 營運交接 | 值班、告警、還原、對帳、費用、異常處理與權限撤回 | 沒有負責人與操作路徑，不算上線交付。 |

### 整輪展示劇本

海外客戶語音詢問 → 明確覆誦與購買 → 原預約系統正確訂單 → 發生語言落差客訴 → 調原承諾並完成政策內補救 → 數據提出可驗證改善 → 經營者回語音與照片 → 權利核准 → 服務新版 → 自有與合作渠道實際更新 → 新訂單、舊單承諾、成本與報酬均可核對。

示範必含語音改口、預訂回應未知、退款 pending、素材尚未核准以及一渠道審核中。不能只展示全成功路徑。

### 放行條件

P0 安全／金額／交易完整性案例全部通過；P1 功能缺陷有明確接續且不破壞承諾；需人工接法已明列責任與費用。沒有通過的能力保持 flag 關閉，不把全產品停住，也不假裝已支援。

## 10.2｜開發工作包與相依關係

| 工作包 | 必交實作 | 依賴／驗收核心 |
| --- | --- | --- |
| W01 權限 | tenant、membership、agreement、用途與稽核 | 起點；跨店／渠道拒絕。 |
| W02 訊息案件 | inbox、需求卡、owner revision、交接 | W01；重送與真人不搶答。 |
| W03 服務知識 | 版本、來源、有效期、欄位權限與索引 | W01；核准與撤回。 |
| W04 報價資源 | 需求確認、正式 quote、資源占用與同意 | W02/03；座位與金額正確。 |
| W05 交易核心 | checkout、task/outbox、原訂位／付款與核對 | W04；正常＋UNKNOWN。 |
| W06 訂後 | 改期、取消、退款、通知、對帳 | W05；不超退、不重寄副作用。 |
| W07 經營提案 | 受控統計、對話、diff、核准、apply | W03/05；新版本真落地。 |
| W08 渠道發布 | offer mapping、每渠道發布與驗證 | W07；部分成功可見。 |
| W09 帳務成本 | 服務用量、來源、結算、沖回、成本 | W05/06/08；不重計。 |
| W10 維運核心 | 環境、CI、監控、備份、告警 | 隨主線建，不留到最後。 |
| W11 語音 | WebRTC、SIP 測試、音訊留言、打斷與交接 | W02/04/05；端到端正確訂單。 |
| W12 客訴 | 案件、證據、政策、補救、原子額度 | W06；政策內能真的執行。 |
| W13 素材 | 主動索取、原件、掃描、權利與草案 | W07；素材變可用版本。 |
| W14 渠道實作 | 正式 API／允許瀏覽器／人工任務與外部改單 | W08；兩入口讀回驗證。 |
| W15 全鏈驗收 | 64 案例、負載、資安、還原與操作移交 | 全部；正式範圍明確。 |

不沿用 v1.0 十二週作已承諾交期。工程依 W01–W15 估工；標準核心可平行使用沙盒與模擬器開發，外部權限只影響相應正式能力開通。沒有捏造人日、金額或現有系統完成率。

## 10.3｜整合待辦與建議預設，不阻擋核心開發

| 待辦／擁有者 | 目前設計預設 | 何時必須決定 |
| --- | --- | --- |
| 語音／整合工程 | 先 WebRTC 全鏈＋SIP adapter；版本封裝不混不同原廠 API；不做任意外撥。 | 電話正式試點前固定電信／總機／號碼與 API 產品版本。 |
| 付款／營運與整合 | 沿用指定銷售方的安全收款頁；booking 與 payment 分別核對。 | 正式扣款前固定收款方、產品版本、退款與外卡能力。 |
| 預約來源／整合 | 一個來源管理資源；按 SYNC／ASYNC／MANUAL 分級。 | 接真商品前完成 hold、lookup、改退及 shared resource 實測。 |
| 客訴政策／商家營運 | 標準規則自動處理；未知額度不填假數字；必要服務持續。 | 啟用自動金錢補救前核准政策、限制與升級人。 |
| 資料用途／產品與合規 | 按類別保存，原始音訊不預設永久；素材對外用途需核准。 | 收集實際客戶資料前填保存與告知設定。 |
| 渠道／商務與整合 | 先自有＋一個授權合作入口；OTA 逐能力啟用。 | 外部正式上架前取得商家與渠道操作權。 |
| 營運人力／專案負責人 | 自動受理不等於 24 小時真人；排班、升級與時限可設定。 | 正式售後承諾前指定責任與接續。 |
| 商業費率／業務與財務 | plan／contract_version 可配置；原客工具費與外部客源費分開。 | 正式計費前簽服務與歸因／結算口徑。 |

### 評審簽核清單

產品確認範圍與 UI；工程確認 API／資料／狀態；營運確認政策與責任；QA 確認測試與證據；資安確認存取與資料生命週期。每次變更保留理由、影響需求／介面／資料／驗收、決策人及版本；不得用「臨時讓 AI 自己判斷」取代設計。

## 附錄｜基準文件與技術查核依據（一）

### B01  商家接單助理｜系統規劃書 v1.0

使用者提供文件；2026-11-11。包含 T01–T24，為已同意的產品方向。

### B02  商家接單助理 v1.1 執行角色增補規格

使用者提供文件；2026-11-11。語音、客訴、素材與渠道執行；A25–A44。

### S01  OpenAI｜Telephony and SIP

語音可經 SIP 接入，後端保留交易規則。實際門號、總機、API 產品版本與能力需獨立測試。

https://developers.openai.com/api/docs/guides/voice-sip?voice-api=realtime

### S02  OpenAI｜Server-side controls

音訊與伺服器工具控制分離；重播事件須去重，播放停止不等於取消業務動作。文件含不同產品介面，連接器不得混用。

https://developers.openai.com/api/docs/guides/voice-server-controls

### S03  LINE｜Receive messages (webhook)

收件需驗簽並異步處理；音訊附件可用 message ID 取得，重送不保證完全不漏事件。

https://developers.line.biz/en/docs/messaging-api/receiving-messages/

### S04  LINE｜Multiple tools with one Official Account

單一官方帳號的 channel／webhook 與額度需協調，不得直接破壞現有客服接法。

https://developers.line.biz/en/tips/2026/07/23/using-multiple-api-tools/

## 附錄｜基準文件與技術查核依據（二）

### S05  OCTO｜Endpoints & Capabilities

ON_HOLD、確認、到期為不同狀態；僅為預訂規格參考，不推定任何商家已支援。

https://docs.octo.travel/getting-started/endpoints-and-capabilities

### S06  ECPay｜付款結果通知

正式付款通知、檢查碼與查詢依所選產品版本實作；前端成功返回與模擬付款不構成正式入帳證據。

https://developers.ecpay.com.tw/2878/

### S07  rezio｜將行程上架至 KKday 通路

供貨型與連結型不同，訂單庫存同步不等於內容價格全部回寫；送出與正式上線分開。

https://kb.rezio.io/zh-tw/article/kkday-1u2sfe0/

### S08  PostgreSQL 17｜Row Security Policies

RLS 有擁有者與 BYPASSRLS 例外；應用程式帳號不得使用超級使用者或繞過 RLS 的角色。

https://www.postgresql.org/docs/17/ddl-rowsecurity.html

### S09  OWASP｜AI Agent Security Cheat Sheet

工具最小權限、參數授權與高影響操作核准由後端執行，不能只依靠提示文字。

https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

### 查核與交付聲明

公開技術來源查核日：2026-11-11。引用用於支持既有技術能力或限制；本 SA 的資料表、內部 API、流程、效能目標與架構選擇是本案建議，不是官方提供的既有實作。

工程附件已做 JSON／YAML 解析、schema 及交叉參照檢查、需求／API／測試追溯與範例型別驗證。未連接真實商家、語音總機、渠道與金流；也未執行 PostgreSQL 實機 migration 或業務驗收。正式開發與整合測試仍按工作包執行。

產品方向已獲使用者確認；新增技術細節標為 SA 開發評審版，不能因文件寫出就視為商家政策、外部權限或開發報價已核准。

## 原檔附屬文字：header1.xml

旅行平台專案  /  商家接單助理

## 原檔附屬文字：footer1.xml

SA-1.0  ·  2026-11-11     |      /
