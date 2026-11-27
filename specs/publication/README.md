# ENG-08 ServiceVersion 與多渠道發布

此垂直切面保存不可變 `service_version`，然後為每個渠道帳號建立各自的
`channel_publication`。`PublicationService.prepare_publications()` 在短交易內產生
持久化 dispatch intent；connector I/O 必須在 commit 後發生，再由
`record_connector_result()` 以新交易保存結果。

渠道狀態不聚合推定：`PENDING` 是渠道已受理審核，`UNKNOWN` 是結果待核對；
僅 `source_revision == desired_version` 的正式讀回會寫成 `LIVE`。其他渠道的成功、
舊版事件、或 connector capability 都不會替代該渠道的結果或使用權。

尚未接入 HTTP handler、worker scheduler、真實供應商；connector 範圍為既有 mock。
