# 0006 ServiceVersion 與渠道發布

ENG-08 新增不可變 `service_version`、獨立的渠道帳號使用權與每渠道
`channel_publication` 投影。`desired_version`、`submitted_version`、
`observed_version` 不可互相推定；只有讀回同一 desired 版的正式外部參照才能成為
`LIVE`。這不會更新既有 `order_record`，因此不會改寫舊訂單承諾。

降版僅適用尚未有此類資料的開發環境；正式環境以 forward fix 取代刪除已留存的發布稽核。
