# ENG-10 驗收對照表

R2 修正基線為 `f277824f5ca7fdc5f87559ec52e45b260a644f27`（退修候選
`39753dbe9d31f413aebf39df858558ad890f6302`；前輪
`200a8f0938195c093c44bc30997c0722e7b917ad`）。本機沒有 `pytest`／`psycopg`
或 PostgreSQL；下列 DB 案例已寫入正式 repository 路徑，但僅能由 hosted
`pytest tests/db/test_voice_multimedia.py -v` 取得 migration、RLS、FK、trigger
與列鎖的實際證據。沒有真實電信或支付帳號，故不把 mock／資料庫結果稱為供應商連通。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| F1 改口併發、播放／交易分離（SA-AT-026、BR-15） | `lock_session_and_case` 先鎖 session＋Case；`record_turn` 重讀 revision；中斷僅 ACTIVE；supersede 改 `demand_revision<=prior` | `39753db` 先無鎖讀，終態仍能 revise。`f277824` 在同一列鎖範圍核驗、拒絕終態改口，且只將 playback 設為 INTERRUPTED；`execution_task` 仍為 WAITING。 | `py_compile` exit 0；DB：`test_correction_supersedes_old_voice_turn_without_cancelling_the_case`。 | hosted PostgreSQL 尚未執行。 |
| F2 重撥驗證、鎖定持久化與 NotFound 映射（SA-AT-027、SM-03） | challenge 僅 DISCONNECTED 且鎖定後拒發；`resume_session` 以 `None` 回傳拒絕結果保留 failed_attempts；session not found 映射 | `39753db` raise 導致 transaction rollback 吞計數且可重發繞鎖。`f277824` 覆蓋過期、五次鎖定、非 DISCONNECTED 與重放。 | DB：`test_resume_requires_verified_original_case_and_audio_message_dedupes`、`test_resume_challenge_expiry_lock_replay_and_state_guards`。 | `python3 -m pytest ...` exit 1：無 pytest；無 PostgreSQL/OTP provider。 |
| F3 轉接競態與 owner revision（SA-AT-028、UC-04） | 原子建立＋TRANSFERRING；鎖 transfer/session/case，只允許 TRANSFERRING；CONNECTED 僅首次接手 | `39753db` DISCONNECTED 可被 FAILED 倒回 ACTIVE，CLOSED 漏裸錯誤。`f277824` 阻止終態倒退，RINGING→CONNECTED 後舊 owner 回合被拒。 | DB：`test_transfer_connected_takes_over_and_terminal_state_cannot_regress`。 | 真實 PBX/SIP provider 未連通。 |
| F4 非同步媒體（FR-12、SA-AT-030/055） | `VoiceService.set_media_status`；payload hash 改 canonical JSON；沿用 no-delete trigger | `39753db` service 無狀態入口且 hash 採 `|` 拼接。`f277824` 可走 RECEIVED→SCANNING→READY／REJECTED，拒絕 DELETE，會話只接受 WEBRTC/SIP_TEST。 | DB：`test_media_recording_payment_ownership_and_transport_rejections`。 | trigger、RLS／FK 與掃描待 hosted PostgreSQL。 |
| F5 付款連結與歸屬（UC-03、FR-10） | `payment_link_is_safe` 驗 netloc、userinfo、query/fragment 敏感鍵及去分隔符 PAN；同 case order guard | `39753db` 放行 fragment、security_code、password userinfo、無 host 與分隔卡號。`f277824` 全拒，跨 Case／不存在 session 回 domain error。 | `python3 -m unittest tests.voice_validation_test -v` exit 0（3 tests）；DB 同 F4。 | 無支付 provider。 |
| F6 錯誤契約、覆誦確認、錄音與租戶隔離（SA-AT-025/029） | registry 去重＋補兩碼；`confirmed_fields_are_valid`；`append_turn(confirmed_fields)`；錄音狀態 | `39753db` error registry 重複／漏碼，且 CONFIRMED 未驗日期、IANA timezone、人數、金額。`f277824` 全數要求並測 tenant_b 讀 tenant_a session 被拒。 | unit exit 0；`python3 scripts/validate_repository.py` exit 0（249 links）；DB 同 F4。 | 本機無 pytest/PG，跨 tenant RLS／FK 待 hosted DB。 |
