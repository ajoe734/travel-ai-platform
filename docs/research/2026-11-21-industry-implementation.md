# 同業實作研究：AI 接單、商家營運 Agent、旅遊分銷與 Agent 系統架構

> 來源轉存：本檔為既有研究報告的主文，原報告中的交付與測試描述代表當時說法。2026-11-22 接手時的實際檔案與驗證狀態，請以 [原檔匯入紀錄](../provenance/README.md) 及 [驗證說明](../verification/README.md) 為準。歷史 sandbox 路徑不代表 repository 中已有對應工程檔案。來源引用已由原報告所附網址轉為一般連結。


截至 **2026 年 11 月 21 日**，我重新從產品文件、API 規格、正式產品流程與公開案例往回研究，而不是先替我們自己的旅行平台找答案。這一輪最重要的結論是：**市場上真正成熟的產品，幾乎都沒有採用「一個萬能 AI Agent 直接接管所有事情」的架構；成功產品反而把 AI 對話、業務工具、正式交易系統、權限、人工介入與長時間工作切得相當清楚。**  [Overview | Intercom and Fin Developer Platform](https://developers.intercom.com/docs/guides/fin-agent-api?utm_source=chatgpt.com)

另一個很重要的發現是：**我們先前討論的「商家不用操作一堆後台，而是把事情交給 AI」方向確實有市場佐證，但 Shopify Sidekick、Salesforce Agentforce、Intercom Fin 等產品目前仍普遍保留「AI 準備／建議／執行部分工作，人對新的商業承諾或高風險修改確認」這一道界線。**真正接近全自動的地方，主要集中在已被明確授權、邊界清楚的客服、訂位、查詢、標準取消退款與渠道同步，而不是任意修改商家的服務內容與經營策略。  [Shopify Help Center | Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick?utm_source=chatgpt.com)

## 客服與語音產品實際怎麼完成工作

### Intercom Fin：從「回答問題」走向「執行 Procedure」

Intercom Fin 已經不是單純 RAG 客服。Fin 可以跨聊天、Email、電話等渠道工作，讀取 Help Center、內部內容、PDF、網頁等知識來源，也可以透過 **Data Connectors** 取得外部系統資料，並透過 **Procedures** 執行企業定義好的業務程序。Intercom 官方甚至直接以「取消訂單、退款訂閱」作為需要連接外部系統並可靠遵循商業規則的例子。  [Fin AI Agent explained | Intercom Help](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained?utm_source=chatgpt.com)

它的產品邏輯值得我們注意：**AI 並不是因為「知道答案」就取得操作權。**Fin Agent API 會先列出針對該使用者可用的 capability，再決定是回答問題、執行特定 procedure，還是轉真人。這代表「能力發現」與「是否有權使用能力」被做成執行層的一部分，而不是只靠 system prompt。  [Overview | Intercom and Fin Developer Platform](https://developers.intercom.com/docs/guides/fin-agent-api?utm_source=chatgpt.com)

Fin 的真人介入不是失敗後才臨時想辦法。產品本身可設定什麼時候交給真人、交給哪個 team，並且在某些高風險情境自動 handoff。它也保留 Answer Inspection，可以看回答使用了哪些資料與設定。這對我們將來做商家助理很重要：**商家如果問「你為什麼答應客戶這件事？」系統必須能回溯依據。**  [Fin AI Agent explained | Intercom Help](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained?utm_source=chatgpt.com)

Intercom 目前 Fin 的公開計價也反映產品定義的改變。2026 年方案以 **outcome** 為單位，一般 resolution、procedure handoff 等公開價格為每個 outcome 0.99 美元；也就是它不是只為 token 或 chatbot session 收費，而是在往「完成一件客戶服務結果」收費。  [Fin AI Agent outcomes | Intercom Help](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes?trk=article-ssr-frontend-pulse_little-text-block&utm_source=chatgpt.com)

但 Fin 還不是我們想像中的「商家經營代理人」。它很強於**客戶服務 resolution**，而不是自主觀察營運資料後修改一個商家的商品策略、價格、渠道組合。後者仍需要企業自行配置 Procedure、資料連接與業務系統。  [Fin AI Agent explained | Intercom Help](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained?utm_source=chatgpt.com)

### Zendesk AI Agents：把「完成」做成正式產品指標

Zendesk 2026 年的 AI Agent 已經可以在 messaging、email、web form 與 voice 中工作，也可以執行企業授權的外部系統操作。其架構把 **use case → generative procedure / dialogue → authorized action / API integration** 分開，而不是讓模型看到 API 就自行呼叫。  [About AI agents – Zendesk help](https://support.zendesk.com/hc/en-us/articles/6970583409690-About-AI-agents?utm_source=chatgpt.com)

這裡有一個很值得我們採用的設計：Zendesk 不只統計「AI 有沒有回覆」，而是把 resolution 分成 assisted escalation、contained resolution 與 verified resolution。對話結束後還可以再由驗證程序判斷是否真的解決。也就是說，**Agent 說「處理好了」和「系統確認這件事真的解決」是兩件事情。**  [About automated resolution tiers – Zendesk help](https://support.zendesk.com/hc/en-us/articles/9570369117338-About-automated-resolution-tiers?trk=article-ssr-frontend-pulse_little-text-block&utm_source=chatgpt.com)

Zendesk 的公開價格也已經以 automated resolution 為單位；2026 年公開方案中，可另購 committed automated resolution，也有 pay-as-you-go resolution。這再次證明客服市場正在把 AI 從「聊天座席」改成「工作結果單位」。  [Zendesk Pricing Plans | Starting from $19/month](https://www.zendesk.com/pricing/?utm_source=chatgpt.com)

### Salesforce Agentforce：Agent 可以做很多事，但 action 還是正式系統的 action

Agentforce 可以透過 Flow 或 Apex action 執行查訂單、更新 fulfillment、建立商品等正式 Salesforce 動作；Salesforce 也提供 Commerce 的標準 Agent Action，例如 Create Product、Create Promotion、Look Up Order Summary 等。  [Build Agentforce Actions](https://help.salesforce.com/s/articleView?id=service.build_agentforce_actions.htm&language=en_US&type=5&utm_source=chatgpt.com)

但它在「經營建議 → 修改」這一段的做法非常值得看。B2B Commerce 的 merchandising agent 會掃描 catalog，找出缺商品說明、圖片、SEO slug 等問題，也會分析 search merchandising opportunity；可是官方流程仍是**先提出 recommendation，由人 review，再 apply**，catalog change 不會因為 AI 覺得合理就直接發布。  [Agentforce for B2B Commerce](https://help.salesforce.com/s/articleView?id=commerce.comm_agent.htm&language=en_US&type=5&utm_source=chatgpt.com)

Salesforce 在 approval 上更明確。Approval Agent 可以在 Salesforce 或 Slack 裡整理待審資料、產生摘要、讓 reviewer approve/reject；真正的 routing、approver、approval record 還是原本的正式 approval workflow。也就是：**AI 把審批變得非常輕，但不把核准語意偷換成模型自行決定。**  [Agentforce for Advanced Approval](https://help.salesforce.com/s/articleView?id=ind.rev_agent_approval_agent.htm&language=en_US&type=5&utm_source=chatgpt.com)

### Ada：客服 AI 與真人交接的責任邊界很清楚

Ada 的產品模型也是 AI Agent 先處理，超出能力時透過 handoff integrations 接到 Zendesk、Salesforce、Amazon Connect 等人工系統。不同 handoff 可能是 live chat，也可能只是建 ticket；交接條件則可以依企業設定。  [Key concepts | Ada](https://docs.ada.cx/docs/welcome/key-concepts?utm_source=chatgpt.com)

這對我們的客訴設計有直接啟示：**「AI 無法處理」不應等於丟一個通知給老闆；應該有正式的接手目標、接手角色、案件上下文與回到流程的方式。**

### PolyAI、Retell、Vapi、Twilio：語音層本身已經相當成熟

PolyAI 的正式產品可以接企業原有電話線、SIP 與 contact center，並可把通話轉給真人。官方產品把「voice agent」和更進一步能操作企業系統完成 task 的「dialog agent」區分，例子包含訂位、order management 與 payment。其產品流程也強調交接時把已取得的資訊交給真人，而不是叫顧客重講一次。  [All Channels: One Adaptive Agent on Voice, Chat, SMS and Email | PolyAI](https://poly.ai/all-channels?utm_source=chatgpt.com)

Vapi 更像開發平台：Agent 可以在通話中使用 tool 查客戶、訂 appointment、轉接電話、呼叫 HTTPS API 或呼叫企業自己的 function server。值得注意的是，Vapi 文件明確警告：因為模型會決定何時呼叫 tool 與 arguments，**敏感操作仍必須在目的端重新驗證 caller-influenced values。**這正是我們未來預訂、退款、改價應採用的模式。  [Tools | Vapi](https://docs.vapi.ai/tools/?utm_source=chatgpt.com)

Vapi 對轉接失敗也有正式狀態：busy、no answer、transfer failed 都不是抽象的「出了問題」，而是可被 workflow 處理的結果；warm transfer 還能先把摘要說給真人，再接通客戶。  [Transfer Call tool | Vapi](https://docs.vapi.ai/tools/transfer-call?utm_source=chatgpt.com)

Retell 提供 voice/chat widget、WebRTC、電話回撥與 API；它比較接近「語音基礎設施＋Agent runtime」，而不是垂直產業訂位系統。2026 年公開價格約每分鐘 0.07–0.31 美元，實際成本依模型、voice 與 add-on 組成。  [Retell Website Widget - Retell AI](https://docs.retellai.com/deploy/chat-widget?utm_source=chatgpt.com)

Vapi 2026 年公開基礎 hosting 價格為每分鐘 0.05 美元，模型與其他 provider 費用另計；高階方案增加 concurrency、RBAC、ZDR、SLA 等能力。這也說明一件事：**語音 Agent runtime 本身已經商品化，我們沒有理由自己重建完整 telephony stack。**  [Vapi - Build Advanced Voice AI Agents](https://vapi.ai/pricing?utm_source=chatgpt.com)

Twilio 的角色則是 telephony/contact-center infrastructure。它有正式的 AI-to-human handoff blueprint，可以把 virtual agent 的上下文與摘要交給 Flex 真人；其電話基礎設施還有 PCI-oriented payment flow。這種能力適合當底層電話與交接基礎，而不是我們產品的差異化核心。  [AI to human handoff | Twilio](https://www.twilio.com/docs/conversations/solution-blueprints/ai-to-human-handoff?utm_source=chatgpt.com)

### 台灣最重要的實際案例：LINE AI 語音預約

這一輪研究中，跟我們台灣場景最接近的產品不是美國的新創，而是 **LINE AI 語音預約**。截至 2026 年，LINE 已與 inline 等合作夥伴把 LINE Call／市話、AI 語音及 inline 訂位整合成正式商用產品；顧客打電話後，AI 可以完成訂位，結果寫入 inline，之後再由 LINE OA 發通知。  [LINE AI 語音訂位｜LINE Biz-Solutions](https://tw.linebiz.com/service/other-solutions/ai-reservation/?utm_source=chatgpt.com)

這不是產品 demo。LINE 公開的貳樓案例顯示餐廳實際導入，核心目的就是讓現場人員不要再一直接訂位電話，而把注意力放回現場服務。LINE 亦公開描述 AI 訂位完成後同步進 inline，而不是只由模型口頭「記下預約」。  [台灣大哥大攜手LINE台灣、inline AI賦能餐飲業升級 「AI語音預約服務」助業者降本增效 貳樓餐飲集團分享應用成效｜LINE Biz-Solutions](https://tw.linebiz.com/news/ai-reservation-seminar-2025/?utm_source=chatgpt.com)

這個案例對我們極重要，因為它直接證明了：

> **AI 語音接待 → 正式預約系統 → LINE 通知 → 商家不介入正常訂位**

在台灣市場已經不是理論。

但它仍主要是**訂位垂直流程**，不是完整的「商家營運 Agent」。它沒有公開證據顯示會因為電話內容觀察到新的服務需求、自己與商家討論新產品、整理素材，再把新產品發布到多個 OTA。

## 商家 AI 助理真正如何減少後台操作

### Shopify Sidekick 是目前最值得借鑑的商家 UX

Shopify Sidekick 的核心不是「AI chatbot 放在後台右下角」，而是讓商家用自然語言交代工作；Sidekick 可以讀取目前 store context、跨頁工作、執行多步驟任務，甚至較長的工作可以在商家離開聊天後繼續執行，完成後再通知商家 review。  [Shopify Help Center | Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick?utm_source=chatgpt.com)

它可以建立或修改 product、discount、collection、customer、draft order，甚至編輯既有 order 的商品數量與 discount。Sidekick 會先準備修改，讓使用者 review；表單欄位被 AI 修改後會特別標示，避免「AI 到底改了什麼」不透明。  [Shopify Help Center | Getting help and guidance from Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick/help-and-guidance?utm_source=chatgpt.com)

更值得注意的是 Shopify 明確寫出 Sidekick 的限制：**它不能未經 merchant approval 修改 live store，也不能代表商家跟客戶做客服對話。**因此 Shopify 將「商家營運副駕」和「客戶-facing AI」分開。  [Shopify Help Center | Getting started with Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick/set-up?utm_source=chatgpt.com)

2026 年 Shopify 又把 Sidekick extension 開給第三方 app。第三方 app 可以把 data 或 action 暴露給 Sidekick，但目前很重要的一種 interaction model 仍是：Sidekick 找到正確 action，帶商家進一個 focused UI，預先帶入 context，讓商家確認後執行。這比逼老闆自己進 App 找功能簡單很多，但它仍不是無限制自動化。  [Use extensions to surface app actions](https://shopify.dev/docs/apps/build/sidekick/build-app-actions?utm_source=chatgpt.com)

這正是我們前面 UX 爭論中最重要的參照：**真正好的 AI-first UX 不是「沒有 UI」，而是把 UI 壓縮成必要的 decision surface。**

### HubSpot Breeze：AI 幫你組 Agent，但權限仍跟原 CRM 一致

HubSpot 2026 年的 Breeze 已可以用自然語言描述「我要一個什麼 Agent」，Breeze 會先產生 goal、tools、knowledge sources 等設定，再讓管理者 review/refine。每個 Agent 的可執行操作仍受 HubSpot 使用者本身的權限約束，例如要發布 landing page，使用者還是必須有相應的 edit/publish permission。  [Build agents with Breeze Assistant](https://knowledge.hubspot.com/ai/create-agents-with-breeze-assistant?obref=obinsite&utm_source=chatgpt.com)

這種模式非常適合我們的平台管理層：**AI 不創造新的權限；AI 只是更容易使用既有授權。**

### Salesforce Merchant Agent：會主動找 catalog 問題，但不替人作最後商業決定

Salesforce Merchant Agent 可以主動 audit catalog、找缺內容、給 merchandising recommendation。這已接近我們「AI 發現商家經營改善機會」的方向。  [Agentforce for B2B Commerce](https://help.salesforce.com/s/articleView?id=commerce.comm_agent.htm&language=en_US&type=5&utm_source=chatgpt.com)

可是市場領先者目前仍將最後一步設計成 review/approve。這表示我們如果一開始就設計「AI 自己看到轉換率不好 → 自行改價格與服務」，不是先進，而是跨越了成熟產品目前刻意保留的治理邊界。

### 市場目前尚未完整做到的事情

我沒有找到有可信官方文件證明某個成熟 SMB 商家產品能完整完成以下閉環：

**讀取客服／交易資料 → 發現服務缺口 → 主動跟經營者討論新服務 → 收集缺少素材 → 建立新的服務產品與資源規則 → 一次核准 → 自動發布到多渠道 → 驗證各渠道生效 → 接續新訂單 → 衡量改善效果。**

市場上每一段都有成熟產品，但**整條鏈仍然割裂**。這反而是我們真正可能建立的產品價值。

## 旅遊供應與多渠道分銷實際怎麼做

### Bókun：真正的中心不是 OTA，而是可售庫存

Bókun 的 channel manager 做法非常典型：商家在中央系統管理 product、availability、booking，各 sales channel 即時使用同一套 availability。一個渠道賣掉兩個 seat 後，其他渠道可售庫存立即下降。  [Bókun as a channel manager | Help Center](https://docs.bokun.io/en/articles/299-booking-channels-bokun-as-a-channel-manager?utm_source=chatgpt.com)

Bókun 產品本身包含產品設定、availability rules、start time、語言 label、外部庫存服務等。它並不是把所有渠道都變成同一頁；而是建立中央供應模型，再讓 channel connector 做轉換。  [How to Create an Experience using new Product Creation Flow | Help Center](https://docs.bokun.io/en/articles/409-how-to-create-an-experience-using-new-product-creation-flow?utm_source=chatgpt.com)

2026 年更值得注意的新變化是：Bókun 已推出 MCP Server，明確允許 LLM／AI assistant 直接查產品、availability、price 並 reserve booking。這是目前非常接近我們產品想法的市場證據：**旅遊供應系統本身開始把正式 booking capability 暴露給 AI。**  [Bókun MCP Server | Help Center](https://docs.bokun.io/en/articles/424-bokun-mcp-server?utm_source=chatgpt.com)

但這也顯示我們不該自己重建整個 booking engine：如果商家本來就使用 Bókun，AI 應該用它的正式供應能力，不是另外建立一套影子庫存。

### Rezdy：真正困難的是兩階段 booking 與同步一致性

RezdyConnect 的規格非常值得我們直接拿來當 SD 參考。它要求 OTA 與供應系統在 booking 時走 availability refresh、reservation、payment、confirmation；若 payment 或 confirmation 中間發生錯誤，還有 cancellation/cleanup。它明確要求 reservation、booking、cancellation 有 idempotent 行為。  [RezdyConnect Specification](https://developers.rezdy.com/rezdyconnect/index.html?utm_source=chatgpt.com)

Rezdy 也清楚區分 product、availability、booking、cancellation 與 webhook/update notification。這證明「旅遊商品上架」不是一個 POST product 就結束，而是**長期保持商品內容、價格、可售庫存、訂單與取消一致的同步問題**。  [RezdyConnect Specification](https://developers.rezdy.com/rezdyconnect/index.html?utm_source=chatgpt.com)

更重要的是，RezdyConnect 並不支援所有事情。例如 OTA-originated booking amendment 在它的規格中通常不是原地修改，而是新 booking 加 cancellation；coupon 也不是自動同步。這類限制正是我們的 Agent 必須知道的，不可以因為 API 有 booking endpoint 就假設「所有修改都能自動完成」。  [RezdyConnect Specification](https://developers.rezdy.com/rezdyconnect/index.html?utm_source=chatgpt.com)

### FareHarbor：API 有能力，但不是誰都能拿來用

FareHarbor External API 可以查即時 availability、pricing、建立 booking，software partner 也可透過 webhook 同步 booking/customer/payment 等資料。  [FareHarbor Integration Center](https://developer.fareharbor.com/api/external/v1/?utm_source=chatgpt.com)

但 FareHarbor 官方同時明確寫出 API access 要經 eligibility review。這正好回答我們之前的一個架構原則：**API 存在 ≠ 我們已取得使用權。**未來 SA 中 Connector Capability 必須同時記錄「技術可行」與「此商家／此平台實際已授權」兩個不同狀態。  [FareHarbor Integration Center](https://developer.fareharbor.com/api/external/v1/?utm_source=chatgpt.com)

### rezio：台灣與亞洲市場最重要的本地參考之一

rezio 提供商品、訂單、resource、booking site 與 OTA channel manager。其官方文件顯示可連 KKday、Viator、GetYourGuide 等渠道；有些 integration 可同步 order 與 inventory，但並非每個渠道都能完整同步 product。  [Admin Channel Manager | Channel : rezio help center](https://help.rezio.io/en/support/solutions/articles/67000576141?utm_source=chatgpt.com)

這點非常實際。例如 rezio 與 GetYourGuide 的某些模式需要商家先在兩邊建立相同 product，再做 mapping，之後主要同步 availability/order。也就是說「channel manager」四個字不代表「新產品可以一次建立到所有 OTA」。  [Channel Manager | GetYourGuide: Manage Channel and Products | Rezio Help Center](https://kb.rezio.io/en/article/channel-manager-getyourguide-manage-channel-and-products-fpm1fn/?utm_source=chatgpt.com)

rezio 的文件甚至顯示某些更新仍需要使用者按 Sync Availability to Channel，某些 MySite 更新則會自動同步。這就是我們未來 Agent Connector Registry 必須保存的差異：**哪個 channel 支援 auto-sync、哪個支援 API write、哪個只能 mapping、哪個仍需人工操作。**  [Product Settings | How to edit session availability? : rezio help center](https://help.rezio.io/en/support/solutions/articles/67000723997-product-settings-how-to-edit-session-availability-?utm_source=chatgpt.com)

2026 年 rezio 公開方案約從每月 49.9 美元起，Channel Manager 位於較高方案。這反映旅遊供應管理本身已經是可購買的成熟 SaaS，我們應優先整合，不應把 PMS／booking engine 當自己的核心重做。  [rezio｜Asia’s Best Online Booking System for Tours and Activities](https://rezio.io/home?utm_source=chatgpt.com)

### Mews／Cloudbeds：旅宿比體驗更加證明「source of truth」的重要

Mews Channel Manager API 的設計是雙向的：Mews 對 channel manager 推 availability/rate/restriction，channel manager 則把 reservation 傳回。API 還特別有 full inventory update 與 delta inventory update。  [Mews Channel Manager API | Channel Manager API | Mews Open API](https://docs.mews.com/channel-manager-api?utm_source=chatgpt.com)

Cloudbeds 也把 PMS、reservation、rate、guest 等資料作為正式 property system 的資料來源；API 可以操作多種 booking/guest use case，但部分 rate 設定並不是所有內容都可透過 API 建立。  [getRatePlans](https://developers.cloudbeds.com/reference/get_getrateplans-2?utm_source=chatgpt.com)

這兩個案例都支持我們的架構：**AI 不應自己維護另一套「看起來像正式庫存」的資料。它可以 cache、index、summarize，但真正成交前還是查 source of truth。**

## 商家知識、素材與內容協作的真實模式

目前市場上最成熟的模式並不是「AI 自己閱讀所有資料，然後永久學會」，而是三層：

**來源資料 → AI 找缺口／提出候選 → 人或既有權限流程核准 → 正式知識／商品內容。**

Intercom Fin 的 Content Library 允許企業集中管理 AI 可使用的內容，而 Suggestions 會根據 Fin 無法解決的 conversation，推薦更新內容、建立新內容或找 duplicate。這是目前最接近我們「AI 從實際詢問發現知識缺口」的成熟產品模式之一。  [Fin AI Agent explained | Intercom Help](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained?utm_source=chatgpt.com)

Shopify Sidekick 則可以使用 merchant 的 store data、目前 admin page、檔案、圖片與 installed apps 作為 context，缺資料時再問使用者；但修改 live store 仍需要 review。  [Shopify Help Center | Getting help and guidance from Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick/help-and-guidance?utm_source=chatgpt.com)

Salesforce Merchant Agent 可以找 catalog 中缺 description、image、SEO slug 的商品，並生成 recommendation；依然先 review 再 apply。  [Agentforce for B2B Commerce](https://help.salesforce.com/s/articleView?id=commerce.comm_agent.htm&language=en_US&type=5&utm_source=chatgpt.com)

因此我們原本「AI 找出資料缺口 → 向商家追問 → 整理素材 → 變成商品內容」這個方向是對的；但要補上一個重要模型：

> **商家傳進來的東西不是立即成為事實，而是 candidate knowledge / candidate asset。**

只有經過 provenance、權利、適用商品與 approval 判定後，才成為可對客戶使用的正式資料。

跨語言內容也是如此。AI 可以翻譯與整理，但真正商品承諾仍要連到同一個 canonical service fact，而不是每個語言獨立維護一份自由文案。這是我們需要自行設計的層，現有客服產品與 OTA channel manager 都沒有完整解決。

## Agent 系統架構的市場共識

Anthropic 在實務指南中把 **workflow** 與 **agent** 明確分開：workflow 是程式預先定義路徑，agent 則由模型動態決定工具與步驟；他們的建議是只在真正需要彈性時才使用 agent，而不是把所有流程 agent 化。  [Building Effective AI Agents \ Anthropic](https://www.anthropic.com/engineering/building-effective-agents?slug=helpful-honest-harmless-ai&utm_source=chatgpt.com)

這與我們的場景完全吻合。像「根據店家一句描述判斷缺什麼資料」適合 agent；但「退款最高只能退多少」「扣款是否真的完成」「OTA reservation confirmation 是否成立」應該是 deterministic workflow。

OpenAI Agents SDK 同樣把 tool、handoff、guardrail、session、human-in-the-loop 與 tracing 分成不同 primitives，而不是全部塞進 prompt。SDK 的 tracing 能記錄 generation、tool call、handoff 與 guardrail event。  [OpenAI Agents SDK TypeScript | OpenAI Agents SDK](https://openai.github.io/openai-agents-js/?utm_source=chatgpt.com)

更重要的是，OpenAI 的 handoff 文件明確指出：即使一個 handoff 在模型眼中「available」，若真正 authorization 依賴 handoff arguments，仍要在 application code 中再次驗證。**模型看得到某個工具，不代表那個工具此次一定有權執行。**  [Handoffs | OpenAI Agents SDK](https://openai.github.io/openai-agents-js/guides/handoffs/?utm_source=chatgpt.com)

Temporal 解決的則是另外一個問題：不是 AI 思考，而是**工作不能因 process crash、timeout 或等待數天就消失**。Temporal 以 Workflow、Activity、Timer、Signal/Update 保存 long-running work 的進度；已完成 activity 的結果會記錄，不因 worker restart 就全部重跑。  [What is Durable Execution? | Temporal Documentation](https://docs.temporal.io/durable-execution?utm_source=chatgpt.com)

它也特別把「transient failure」「permanent failure」「negative business result」分開。沒有庫存、信用卡餘額不足不是 infrastructure failure，而是 workflow 需要理解的業務結果。這對我們非常重要：**Agent 不能看到 tool 返回 error 就一律 retry。**  [What is Durable Execution? | Temporal Documentation](https://docs.temporal.io/durable-execution?utm_source=chatgpt.com)

LangGraph 的方向類似，但它把 workflow 更明確表示成有 state 的 graph。其 human-in-the-loop `interrupt()` 可以保存 state 後暫停，等人補資料再從原位置繼續；文件也強調 smaller nodes 對 observability 與 recovery 比較有利。  [Thinking in LangGraph - Docs by LangChain](https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph?utm_source=chatgpt.com)

所以市場實務其實相當一致：

**LLM／Agent 負責不確定性的理解與規劃；durable workflow 負責長時間可靠執行；business service 負責正式規則；connector 負責第三方差異；authorization 在執行端重新驗證；trace/audit 負責證明發生什麼事。**

## 跨產品比較與市場缺口

下面這張表不是比較「有沒有 AI」，而是比較**真正做到工作哪一層**。

| 產品 | AI 接待 | 直接工具操作 | 正式交易完成 | 自動營運改善 | 多渠道商品同步 | Human model |
|---|---|---|---|---|---|---|
| **Intercom Fin** | 強 | Procedures / connectors | 可做企業配置好的 transaction | 知識改善強、商品改善弱 | 非核心 | 規則化 handoff |
| **Zendesk AI Agent** | 強 | authorized actions/API | 可完成配置好的客服 transaction | 客服流程優化 | 非核心 | escalation / verification |
| **Salesforce Agentforce** | 強 | Flow/Apex/標準 action | CRM/Commerce 內可很深 | recommendation 強 | Salesforce 生態強 | approval workflow |
| **Shopify Sidekick** | 商家內部，不面客 | 商品、訂單、折扣等 | 商家 admin 操作很深 | 有分析與建議 | Shopify app 生態 | live change 前 review |
| **PolyAI** | 語音非常強 | backend integrations | 在配置場景可做到 booking/payment | 非核心 | 非核心 | warm/context handoff |
| **Vapi / Retell** | 語音 runtime 強 | 任意 API/function | 取決於你自己的 backend | 無垂直營運 intelligence | 無 | 由開發者設計 |
| **Bókun** | 無 AI-first 接待核心 | 2026 已有 MCP | booking 很強 | 弱 | OTA/channel 強 | 商家供應管理 |
| **Rezdy** | 無 | booking/distribution API | reservation/booking/cancel 強 | 無 | 強 | 商家／channel manager |
| **rezio** | 無完整 AI agent | booking/channel capabilities | booking 強 | 有營運 SaaS，但非 Agent | 亞洲 OTA 很重要 | 商家後台 |
| **LINE AI 語音預約** | 台灣語音很強 | inline booking | 訂位可直接完成 | 無完整營運 Agent | 非 OTA channel manager | 例外回店家/既有流程 |

以上能力分別可由各產品的正式文件驗證。  [Fin AI Agent explained | Intercom Help](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained?utm_source=chatgpt.com)

### 哪些已經做到「AI 自己接待並完成交易」？

**有，但都是在事先定義好的業務範圍。**

LINE AI 語音預約可以讓來電客戶直接完成 inline 訂位；PolyAI 可透過 enterprise integration 做 booking/payment；Vapi 可以呼叫 appointment/API tool；Bókun MCP 已可讓 AI 查 availability、pricing 並 reserve。  [LINE AI 語音訂位｜LINE Biz-Solutions](https://tw.linebiz.com/service/other-solutions/ai-reservation/?utm_source=chatgpt.com)

但 payment processor、booking/PMS、inventory system 仍然是正式交易來源。AI 負責 conversational orchestration，不取代交易 ledger。

### 哪些已經做到「根據營運資料建議後直接改商品」？

最接近的是 Shopify Sidekick 與 Salesforce Merchant Agent。

Shopify Sidekick 可以直接準備 product/collection/discount/order 修改，但 live change 要 merchant review。Salesforce Merchant Agent 可以根據 catalog/search data 提出具體修改，但 recommendation 要 apply/approve。  [Shopify Help Center | Getting help and guidance from Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick/help-and-guidance?utm_source=chatgpt.com)

**我沒有找到可信成熟產品會從營運指標直接自主創造新服務承諾並無人核准發布。**

因此我們應該做得比現有後台簡單，但不應把這一步取消。

### 哪些真的做到跨渠道商品、庫存、價格與訂單同步？

Bókun、Rezdy、rezio、Mews 等 channel manager 已經很成熟，但**同步能力不是全或無。**某些是完整 product sync；某些只有 availability/order；某些新 product 仍需在 OTA 先建立再 mapping。  [Bókun as a channel manager | Help Center](https://docs.bokun.io/en/articles/299-booking-channels-bokun-as-a-channel-manager?utm_source=chatgpt.com)

所以我們不能設計一個虛假的「Publish to all」按鈕，背後假設所有渠道都一樣。

正確設計應是：

```text
Service Version
      │
      ├─ Channel A：create + update + inventory + booking
      ├─ Channel B：mapping + inventory + booking
      ├─ Channel C：manual product + API availability
      └─ Channel D：browser / operator assisted
```

Agent 可以讓使用者感覺是一項工作，但內部必須知道不同 fulfillment path。

### 市場目前最明顯的斷裂點

**客服平台懂 conversation，但通常不懂旅遊供應。**

**booking/channel manager 懂供應與 OTA，但通常沒有真正的商家經營 Agent。**

**Shopify/Salesforce 的 merchant AI 很強，但不是旅遊體驗的 resource/availability/channel model。**

**Voice AI 很成熟，但只是 conversation runtime，不是營運 source of truth。**

**知識 AI 可以找缺口，但很少會把缺口一路變成新的可售服務並分發到 OTA。**

這個斷裂正是我們的產品空間。

## 台灣市場：哪些地方不能照搬海外產品

LINE 在台灣不能被當作「另一個 chat channel」。Messaging API 支援 webhook、文字、圖片、影音、audio message、Flex Message，也支援安全的 account linking；如果使用者傳 audio message，服務端可以用 message ID 取得實際音訊檔。  [Message types | LINE Developers](https://developers.line.biz/en/docs/messaging-api/message-types/?utm_source=chatgpt.com)

但 LINE Messaging API 的 audio message 與 LINE Call 是不同的能力。不能因為 Messaging API 可以收音訊，就宣稱我們可以接 LINE 原生電話。台灣真正的 LINE AI 語音預約是 LINE 與電信／inline 等夥伴所提供的正式方案。  [Messaging API reference | LINE Developers](https://developers.line.biz/en/reference/messaging-api/nojs?utm_source=chatgpt.com)

台灣 POS／預約系統的 API 開放程度也差異很大。iCHEF 有 ERP 資料接合與第三方外送整合；inline 有訂位與多平台同步，但其公開 developer surface 不像 Shopify/Bókun 那麼開放；ezPretty 則公開提供預約、POS、商城等 API 合作。這代表我們在台灣不能預設「每家 SaaS 都能 OAuth 後完整操作」。  [[Item Management] iCHEF API Service – iCHEF Support](https://support.ichefpos.com/?lang=en&p=19624&utm_source=chatgpt.com)

如果商家是電商型態，EasyStore 的 developer model 就相對完整：merchant 安裝 app 後用 access token 與 scopes 授權，API 可處理 product、order、inventory、customer、webhook。官方甚至特別提醒 write_products scope 不只改庫存，也能改整個商品，因此 app 應說明為什麼需要該 scope。這種 permission granularity 很值得我們照著設計。  [Getting Started | EasyStore Developers](https://developers.easystore.co/docs/api/getting-started?utm_source=chatgpt.com)

台灣金流也同樣不能由 AI 猜。綠界有正式 refund API；藍新的退款與請款也有既定限制，而且某些支付方式的退款時效、餘額條件與全額退款限制都不同。AI 可以決定「應執行退款流程」，但金額、可退款條件與最終狀態必須由 payment adapter 查正式來源。  [退款功能 - ECPay Developers](https://developers.ecpay.com.tw/64711/?utm_source=chatgpt.com)

台灣旅遊體驗端則應優先驗證 **rezio／KKday／Viator／GetYourGuide** 的實際 connection type，而不是直接照抄 Bókun/Rezdy 的歐美模型。rezio 的文件已經證明即使同一套 channel manager，不同 OTA 也可能只是部分同步。  [Admin Channel Manager | Channel : rezio help center](https://help.rezio.io/en/support/solutions/articles/67000576141?utm_source=chatgpt.com)

## 映射回我們的平台：SA、SD 與初步 UX 應怎麼改

這輪研究後，我認為之前確立的方向是對的，但系統架構還可以再收斂。

### 產品核心應從「AI 後台」改成「Work Delegation Platform」

我們真正要建的不是 chatbot，也不是另一套 booking/channel manager。

核心應是：

```text
                   ┌─────────────────────────┐
                   │     Merchant / Staff     │
                   │  LINE / Web / Voice UI  │
                   └────────────┬────────────┘
                                │
                         Delegate / Decide
                                │
                                ▼
┌─────────────────────────────────────────────────────────┐
│                  AI WORK COORDINATOR                    │
│                                                         │
│  Understand goal ─ Plan ─ Ask missing info ─ Re-plan   │
│          │                  │                 │          │
│          └──────────────────┴─────────────────┘          │
└───────────────────────┬─────────────────────────────────┘
                        │
                 Proposed Business Action
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                 CAPABILITY / POLICY LAYER               │
│                                                         │
│ identity │ permission │ policy │ approval │ limits      │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  DURABLE WORK ENGINE                    │
│                                                         │
│ execute │ wait │ retry │ compensate │ verify │ resume   │
└──────────────┬─────────────────────────┬────────────────┘
               │                         │
               ▼                         ▼
      Business Services             Human Decision
    quote / booking / refund        merchant / staff /
    service / publication           operator / partner
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│                    CONNECTOR LAYER                      │
│                                                         │
│ LINE │ rezio │ Bókun │ PMS │ POS │ CRM │ Payment │ OTA │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
               AUTHORITATIVE SYSTEMS
```

這個架構直接吸收 Intercom 的 capability 概念、Shopify 的 review model、Rezdy 的 transaction model，以及 Temporal 的 durable execution。  [Overview | Intercom and Fin Developer Platform](https://developers.intercom.com/docs/guides/fin-agent-api?utm_source=chatgpt.com)

### SA 最核心的 entity 不應再是畫面或 conversation

第一版 Domain Model 我建議改為：

```text
Merchant
 ├── OperatingPolicy
 ├── BusinessGoal
 ├── CapabilityGrant
 ├── Service
 │    └── ServiceVersion
 │          ├── ResourceRequirement
 │          ├── CommercialTerms
 │          ├── Content
 │          └── ChannelProjection
 │
 ├── Customer
 │    └── Conversation
 │
 ├── Work
 │    ├── Goal
 │    ├── Plan
 │    ├── WorkStep
 │    ├── Dependency
 │    ├── DecisionRequest
 │    ├── ToolExecution
 │    └── CompletionEvidence
 │
 ├── Quote
 ├── Booking
 ├── Payment
 ├── Refund
 ├── Complaint
 │
 └── ConnectorAccount
      └── ConnectorCapability
```

其中最重要的新物件是 **Work**。

例如老闆說：

> 「把我們剛討論的 60 分鐘茶體驗，下個月先在官網和合作旅宿試賣。」

不是建立一個 Product Form。

它先建立：

```text
Work
goal:
  "Launch 60-minute tea experience"

scope:
  start_date = 2026-12-01
  channels = [website, partner_hotel]

constraints:
  keep_existing_full_experience = true

completion:
  website_version_verified = true
  partner_hotel_status in [published, accepted]
```

再由 Agent 自己產生 work plan。

### Agent Plan 與 Durable Workflow 不應混在一起

這輪研究後我會明確把兩層分開：

```text
Agent Plan
"What should I do next?"

          ↓

Workflow Execution
"How do I make sure this exact action eventually finishes?"
```

例如：

```text
Agent:
缺英文服務說明 → 應向商家取得

Workflow:
create Decision/Data Request
wait 7 days
remind once
receive attachment
resume work
```

或：

```text
Agent:
新版應發布至 rezio

Workflow:
validate grant
prepare payload
submit
store external id
wait for channel result
reconcile
retry if safe
escalate if auth expired
```

Anthropic 的 workflow/agent 分工與 Temporal 的 durable execution 都支持這種分層。  [Building Effective AI Agents \ Anthropic](https://www.anthropic.com/engineering/building-effective-agents?slug=helpful-honest-harmless-ai&utm_source=chatgpt.com)

### Connector 不只是 API Adapter，而要有 Capability Profile

這是這次旅遊產品研究後最重要的新 SA 需求。

每一個 connector 必須說明：

```text
ConnectorCapability

product_create
product_update
content_update
price_update
availability_read
availability_write
reservation_create
reservation_modify
reservation_cancel
refund
webhook
idempotency
async_confirmation
manual_mapping_required
```

例如 rezio → GetYourGuide 可能是：

```text
product_create: false
product_mapping: manual
availability_sync: true
booking_sync: true
```

而 Bókun 自有 API/MCP 可能又是另一個 profile。這樣 Agent 才不會幻想每個渠道的能力都一樣。  [Channel Manager | GetYourGuide: Manage Channel and Products | Rezio Help Center](https://kb.rezio.io/en/article/channel-manager-getyourguide-manage-channel-and-products-fpm1fn/?utm_source=chatgpt.com)

### Knowledge Architecture 不應只有 Vector DB

我建議正式拆成：

```text
Candidate Knowledge
        ↓
validation / provenance / merchant confirmation
        ↓
Canonical Business Fact
        ↓
language/content generation
        ↓
Channel Projection
```

例如：

```text
Canonical Fact
service_id: TEA60
fact: live_english_host = false
valid_from: 2026-12-01
confirmed_by: merchant_owner

       ↓

Website zh-TW
Website en-US
LINE answer
Viator description
Hotel partner sheet
```

這樣商家後來說：

> 「從 12 月開始會有英文老師。」

我們修改的是 **fact/version**，不是請 AI 全站搜尋取代文字。

### 正式交易仍需要 Verification Layer

Zendesk 的 verified resolution、Rezdy 的 reservation-confirmation flow 與 Temporal 的 failure model 都支持同一個原則：

```text
AI said it
    ≠
API accepted it
    ≠
business completed
```

因此所有敏感 work step 需要：

```text
INTENDED
SUBMITTED
EXTERNAL_ACCEPTED
VERIFIED
```

例如退款：

```text
refund_requested
↓
payment_api_accepted
↓
refund_processing
↓
payment_provider_refunded
↓
customer_notified
```

只有最後幾個狀態成立，客訴才可能真正完成。  [About automated resolution tiers – Zendesk help](https://support.zendesk.com/hc/en-us/articles/9570369117338-About-automated-resolution-tiers?trk=article-ssr-frontend-pulse_little-text-block&utm_source=chatgpt.com)

### 初步 UX：商家不應看到「模組」，應看到三件事

這輪研究後，我會把前面的 UX 大幅收斂。

商家主要介面其實只需要三個概念：

```text
┌─────────────────────────────────────┐
│ 商家助理                            │
│                                     │
│  今天需要你決定  2                  │
│                                     │
│  AI 正在處理     6                  │
│                                     │
│  最近完成       14                  │
│                                     │
│ ┌─────────────────────────────────┐ │
│ │ 有旅客多次詢問 60 分鐘體驗      │ │
│ │                                 │ │
│ │ 我查過目前商品與人力配置：      │ │
│ │ 可以與完整版共用場地，但老師    │ │
│ │ 不能同時帶兩場。                │ │
│ │                                 │ │
│ │ 建議先試：平日 14:00            │ │
│ │ NT$680 / 人                     │ │
│ │                                 │ │
│ │ [修改]    [採用並交給我]       │ │
│ └─────────────────────────────────┘ │
│                                     │
│  想交代什麼事情？                  │
│ [________________________________] │
└─────────────────────────────────────┘
```

這裡借鑑的是 Sidekick 的 conversational delegation 與 focused review，而不是 Salesforce 式大後台。  [Shopify Help Center | Sidekick](https://help.shopify.com/en/manual/ai-powered-tools/sidekick?utm_source=chatgpt.com)

AI 正在處理的事情不應形成另一個巨大 task management SaaS。預設只看到簡短狀態：

```text
正在處理

60 分鐘體驗
官網            ✓ 已更新
合作旅宿        ◌ 等對方審核
GetYourGuide    — 本次未發布

不需要你操作
```

只有需要 debug 或營運人員才進完整 trace。

### Decision Request 應是整個 UX 的核心元件

不是「Approval Inbox」，而是一個極小的 decision surface：

```text
┌────────────────────────────────────┐
│ 需要你的決定                       │
│                                    │
│ 客人要求另外補償 NT$1,200 車資     │
│                                    │
│ 已確認                              │
│ • 原訂單 NT$2,400                  │
│ • 標準退款 NT$2,400 已完成         │
│ • 現行政策沒有交通費補償           │
│                                    │
│ 建議                               │
│ ○ 不額外補償                       │
│ ○ 提供 NT$500 下次折抵             │
│ ○ 自訂其他方案                     │
│                                    │
│ [交給助理繼續處理]                 │
└────────────────────────────────────┘
```

經營者決定的是**政策外的新承諾**。

不是按：

> Refund API  
> Send LINE  
> Close ticket

後三件事應由 Agent + workflow 執行。

### 客戶端 UX 也不應是「AI 聊天機器人」

旅行端更適合：

```text
需求
「週日下午兩小時，兩個大人一個八歲小孩，
想做比較在地、不想太觀光的事情」

        ↓ AI

候選體驗 + 為什麼適合

        ↓

正式可售條件
12/6 14:00
3 人
NT$2,040
中文體驗，英文說明材料

        ↓

[確認預訂]

        ↓

正式 booking result
```

Chat 是理解需求的入口。

**Quote、Consent、Booking Result 應該是結構化 transaction UI。**

這與成熟客服／booking 產品目前的分工一致：模型負責理解，正式交易用 tool/service 完成。  [Tools | Vapi](https://docs.vapi.ai/tools/?utm_source=chatgpt.com)

### 我們真正該自己做與不該自己做的東西

| 能力 | 自建／依賴 | 原因 |
|---|---|---|
| **AI Work Coordinator** | **自建核心** | 這是產品真正差異 |
| **Merchant Operating Context** | **自建核心** | 市場沒有適合旅遊 SMB 的完整模型 |
| **Work / Decision / Evidence model** | **自建核心** | 跨客服、交易、改善與發布 |
| **Service Version / Channel Projection** | **自建核心** | 解決跨渠道內容與承諾一致性 |
| **Connector Capability Registry** | **自建核心** | 渠道能力差異是產品核心問題 |
| **Voice runtime / telephony** | 第三方 | Vapi、Retell、Twilio、LINE 等已成熟 |
| **Payment processing** | 第三方 | 綠界、藍新、Stripe 等 |
| **Booking/PMS** | 優先整合 | rezio、Bókun、Mews、Cloudbeds 等已有 source of truth |
| **OTA inventory distribution** | 優先整合 channel manager | 不應自己重建全球 OTA network |
| **LLM runtime** | 第三方模型 | 非核心 moat |
| **Durable execution** | Temporal 等成熟技術 | 沒必要自己發明 workflow durability |
| **LINE OA / messaging** | LINE API | 台灣必要基礎設施 |

這不是單純為了降低開發量，而是市場產品已經證明這些層各自是獨立能力。  [Tools | Vapi](https://docs.vapi.ai/tools/?utm_source=chatgpt.com)

## 最終產品定位

這輪真正看過同業之後，我會重新描述我們的產品。

**不是：**

> AI 旅遊客服 + 商家後台 + OTA 管理工具。

而是：

> **一個代表旅遊服務商家承接工作、協調既有系統並把事情完成的 AI Operating Layer。**

它坐在商家、客戶與既有 SaaS 中間。

```text
Customer
   ↓
Conversation / Voice
   ↓
AI understands work
   ↓
Business capability
   ↓
Existing system executes truth
   ↓
AI verifies result
   ↓
Customer / Merchant gets outcome
```

商家端則是：

```text
Merchant:
「我要做這件事」
       ↓
AI:
理解 → 規劃 → 找資料 → 缺什麼才問
       ↓
Merchant:
只做必要的商業判斷
       ↓
AI:
執行 → 等待 → 重試 → 發布 → 驗證
       ↓
Merchant:
看到結果
```

**目前市場已有幾乎所有單點能力，但還沒有人把「客戶接待 → 商家知識 → 經營改善 → 新服務形成 → 多渠道發布 → 交易 → 售後 → 效果回饋」做成一個真正以工作委派為中心、又適合小型旅遊商家的完整產品。**

這才是我們接下來 SA／SD 應該抓住的系統邊界，而不是再去畫一套更漂亮的後台。