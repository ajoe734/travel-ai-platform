# 0010 提案 Case lineage

ENG-11 的 proposal 同時關聯 Case、Work 與可選 Insight。此 forward fix 以複合 FK 保證三者在同一 tenant **與同一 Case**，避免只靠 API 層將洞察或服務改版誤綁到別案。
