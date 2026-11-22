# Trusted ingress 與客戶確認契約 v0.1.0

本文件補足 OpenAPI v0.1.0 的 booking request 所需 customerConfirmationRef。客戶確認不是由模型文字產生，而是由可信渠道事件、登入後 UI action 或人工核實紀錄建立。

## 1. Customer confirmation 的來源

允許來源：
1. AUTHENTICATED_UI：已驗證旅客 session，對特定 Quote 按下確認。
2. SIGNED_ACTION：平台簽發一次性、短效、綁定 Quote revision/hash 的簽名 action token。
3. VERIFIED_MESSAGE：渠道提供可驗證的 message/action callback，且事件簽章與重放防護通過。
4. HUMAN_RECORDED：授權營運人員依可追溯通話／客服記錄登錄，必須記 actor、原因及證據。

不允許來源：
- LLM 摘要中寫「客人同意」。
- 未驗證 webhook body。
- 無法對應 quote revision/hash 的「好」「可以」等孤立訊息。
- 代理自行填入 UUID 或偽造 callback。

## 2. Ingress endpoint

對外渠道 webhook 先由 channel adapter 驗證簽章、timestamp、nonce、channel account 與 tenant mapping。驗證成功後轉成內部 command；不讓外部呼叫者直接指定 tenant_id。

內部 endpoint（不公開給旅客或模型）：

POST /internal/v1/channel-events/{channel}/customer-confirmations

Headers:
- X-Channel-Account：已註冊 account ref
- X-Event-Id：渠道唯一事件 ID
- X-Event-Timestamp：RFC3339
- X-Verified-Signature：由 adapter 驗證後的結果標記；此 header 只可由可信 gateway 注入，不可接受 internet client 自行提供

Body:
- caseId
- quoteId
- quoteRevision
- quotePayloadHash
- customerRef
- confirmationMethod
- verifiedAt
- evidenceRef

處理順序：
1. 驗證來源 gateway 身分與渠道簽章結果。
2. 由 channel account 查出 tenant／branch；忽略 body 中任何 tenant_id。
3. 以 tenant + channel + event id 去重。
4. 確認 Quote 屬同 tenant、未過期、revision/hash 相符。
5. 確認 customerRef 與 Case 客戶身分對應；不確定時建立 WAITING_CUSTOMER。
6. 建立 append-only customer confirmation record，產生 confirmation id。
7. 回傳 confirmation id；Booking API 只接受該 id，不接受自由文字。

## 3. 使用確認

POST /v1/bookings 的 customerConfirmationRef 必須存在、屬同 tenant、綁定相同 quote、revision 與 hash、尚未過期、未被消耗或撤銷。成功建立 booking intent 時以 DB transaction 將 confirmation 標記為 consumed 或以 booking 唯一關聯限制重複使用。

## 4. 競態與撤回

- 同一事件重送回傳既有 confirmation id。
- 同一 Quote 有兩筆相衝突的客戶確認時，依渠道事件序列與撤回政策判定；不允許後到的舊訊息覆蓋新決策。
- 若客戶在 booking 副作用開始前撤回，取消執行並留下稽核。
- 若副作用已送出，不能假裝撤回已取消供應商預訂；進入 reconciliation，必要時建立 cancellation Work。
- 客戶確認只表示同意該報價／條件，不代表商家批准、供應商確認或付款完成。

## 5. 可驗收測試

- 偽造 signature、過期 timestamp、重放 nonce：拒絕。
- 相同 event id 重送：只建立一筆 confirmation。
- quote revision/hash 不符：拒絕並要求重新確認。
- quote 已過期：拒絕。
- 跨 tenant quote id：不得洩漏是否存在。
- LLM 自行聲稱同意：不產生 confirmation。
- 確認後 quote 金額／日期變更：原 confirmation 失效。
- 確認已使用：不可建立第二筆 booking。
