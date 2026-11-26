# ENG-03：授權、決策版本與撤回

來源：[backlog ENG-03](../../docs/collaboration/backlog.md#eng-03授權決策版本與撤回)、
[docs/sd/authorization-and-approval.md](../../docs/sd/authorization-and-approval.md)、
[ADR 0003](../../docs/adr/0003-immutable-approval-and-reservations.md)，建於
[ENG-01 的 specs/domain 契約](../domain/README.md)之上。

依 task brief「持久化部分待 ENG-02 合併後再接上」：本輪的「授權判定服務」是
[`services/authorization/`](../../services/authorization/) 下的純 Python 實作，透過
`AuthorizationRepository` 介面（見
[`repository.py`](../../services/authorization/repository.py)）存取狀態；今天只有
`InMemoryAuthorizationRepository` 這一個實作。等 ENG-02 的 Postgres 持久層落地後，換上符合同一介面的
實作即可，`AuthorizationService` 本身不需要改。

## 本輪產出對照 backlog「產出」欄

| backlog 產出項 | 本輪實際位置 |
|---|---|
| 授權判定服務 | `services/authorization/service.py` 的 `AuthorizationService` |
| DecisionRequest API | [`api-contract.md`](api-contract.md)（契約層；實際 HTTP handler 是 ENG-05 範圍） |
| 版本與 payload hash | `services/authorization/canonical_json.py`（SD §3.2 canonical encoder + SHA-256） |
| 批准／拒絕／過期／撤回紀錄 | `AuthorizationService.approve_decision`／`reject_decision`／`expire_decisions`／`revoke_approval` |
| 執行前再檢查及競態處理 | `AuthorizationService.precheck_before_dispatch`／`consume_authorization_use`／`revoke_approval` 共用的 `repository.lock_for` |

## 不在本輪範圍

- 真正的資料庫 UNIQUE／RLS／trigger（ENG-02）。
- `AuthorityGrant`／`PolicyVersion` 的正式 schema 與完整政策管理生命週期；本輪只在
  `InMemoryAuthorizationRepository` 內用一個最小 dict 形狀當作「存在一筆可核對的政策授與」的替身，
  不是最終契約（見 `repository.py` 模組說明）。
- nonce／語音確認入口本身的使用者介面與傳輸協定；本輪只固定「approve 必須消耗一個由本服務（代表受信任
  UI／語音確認端點）核發的 nonce」這個規則與其資料結構。
- SD-A-09 的跨語言 canonicalization 測試向量交叉驗證（需要第二語言實作）。
- SD-A-11（break-glass 存取）、SD-A-12（退款 UNKNOWN 後撤回）：分別是語音/錄音與退款額度範圍，
  屬 ENG-07／ENG-10。

## 驗證

```bash
python3 -m unittest tests.authorization_service_test -v
python3 -m unittest tests.domain_contract_test -v
python3 scripts/validate_repository.py
```

逐項對照 backlog 驗收與 SD §8 負向驗收表見 [`acceptance-trace.md`](acceptance-trace.md)。
