# ENG-10 驗收對照表

本機 VM 沒有 `psycopg` 或 PostgreSQL；以下 DB probes 由既有 hosted `pytest tests/db -v` 執行。沒有
真實電信或支付帳號，所以任何通過只表示資料庫／mock 邊界，不表示供應商已連通。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| 改口後晚到結果不覆蓋新需求（SA-AT-026） | `VoiceService.interrupt_for_correction` → `case_repository.revise_demand` 與 `voice_repository.interrupt_for_new_demand` | 舊基線沒有語音回合／demand revision 接續紀錄；修正版將舊 FINAL/PARTIAL 回合標為 SUPERSEDED，播放只中斷，不取消已送出的交易 | `pytest tests/db/test_voice_multimedia.py::test_correction_supersedes_old_voice_turn_without_cancelling_the_case -v`；本機未執行，待 hosted PostgreSQL | 不直接呼叫 connector；已送出交易仍由 ENG-05 核對，未聲稱語音中斷可取消它 |
| 重撥驗證與音訊訊息去重（SA-AT-027/030） | `VoiceService.resume_session`、`receive_audio_message`；`asynchronous_media_intake` unique `(tenant_id, source_event_id)` | 舊基線無語音接續資料；修正版錯 case 拒絕，重送音訊只回放既有 intake | `pytest tests/db/test_voice_multimedia.py::test_resume_requires_verified_original_case_and_audio_message_dedupes -v`；本機未執行，待 hosted PostgreSQL | 驗證 challenge/OTP transport 尚未實作；此服務只消耗上游已驗證的 case ID |
| 轉接、錄音政策與安全付款接續（SA-AT-028、FR-10） | `voice_session.recording_policy`、`voice_transfer.provider_result_ref`、`VoiceService.create_payment_link_handoff` | 舊基線沒有這些證據；修正版記錄 FAILED/CONNECTED 的 provider 結果，不把 REQUESTED 當真人已接手，且拒絕 card/PAN/CVV 前綴 | `pytest tests/db/test_voice_multimedia.py::test_transfer_outcome_and_payment_link_are_recorded_without_card_data -v`；本機未執行，待 hosted PostgreSQL | 無真實 PBX/SIP、支付或錄音供應商；`SIP_TEST` 不代表電話已連通 |
