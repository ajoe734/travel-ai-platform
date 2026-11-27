# ENG-10 語音、電話與多媒體接續

實作在 `services/voice/`、`db/repository/voice_repository.py` 及 migration `0006`。WebRTC 與
`SIP_TEST` 共用既有 Case；非即時音訊用 `asynchronous_media_intake` 收件，不能標成原生即時通話。
錄音政策、轉接 provider 結果與付款連結交接均為可查紀錄。付款交接拒絕任何卡號／安全碼樣式。

真實 SIP／電話帳號、錄音保存服務、STT、支付 provider 與 WebRTC signaling 皆不在本輪；`SIP_TEST`
是測試 transport，不能當作已連通的電信能力。

驗證：`pytest tests/db/test_voice_multimedia.py -v`（需要 hosted Postgres，見 `db/README.md`）及
`python3 -m py_compile db/repository/voice_repository.py services/voice/*.py tests/db/test_voice_multimedia.py`。
