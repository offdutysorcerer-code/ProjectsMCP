# AGENTS.md / ProjectsMCP Platform

本文件補充上層專案的 `AGENTS.md`。若存在多層 AGENTS，越接近目前專案目錄者優先；本文件對此專案的規則優先。
This file supplements the parent project's `AGENTS.md`. If multiple AGENTS files exist, the one closest to the current project takes precedence. This file defines the project-specific rules for ProjectsMCP.

## 專案範圍 / Project Scope

Plugin-based MCP 平台。`server.py` 僅負責啟動；功能放在 `plugins/`，共用邏輯放在 `services/`。

## 開始前必讀 / Required Reading

- `README.md`
- `config.json`、`server.py`、`mcp_platform/`，以及受影響 plugin 與 service。

開始修改前，先回報已閱讀文件、目前 Git branch／狀態，以及預計修改範圍。若此目錄不是 Git repository，請明確說明。
Before editing, report documents read, current Git branch/status, and intended scope. If this directory is not a Git repository, say so explicitly.

## 專案規則 / Project Rules

- 維持 Plugin／Service 分離；新增 plugin 必須提供 `create_plugin()` 並在設定的 enabled 清單註冊。
- 所有專案檔案操作必須限制在設定 root，阻擋 traversal；保留副檔名 allowlist、讀取大小與命令輸出上限。
- `replace_text` 預設保持 `dry_run=true`；高風險 Git remote、任意 command 或寫入能力必須有人機確認與最小權限。
- 修改 tool 名稱、參數或回傳結構前，先更新 README／契約並考慮既有 connector 相容性。
- `config.json` 的本機設定、ngrok URL、憑證、browser artifacts、cache 與執行輸出不得提交。

## 測試與驗證 / Testing

- 安裝 `requirements.txt` 後啟動 `StartProjectsMCP.bat`，逐項 smoke-test 受影響工具。
- 檔案功能測試合法路徑與 traversal；命令功能測試 timeout、process-tree 終止與 output cap；Browser 功能測試啟閉與 artifact 路徑。
- 修改 Python 後重新啟動 server 並刷新 connector，再驗證 tool schema。

## 完成條件 / Definition of Done

- 修改保持在任務範圍內，且未覆蓋其他協作者或使用者的變更。
- 更新受影響的 README、契約、設定範例或狀態文件。
- 列出修改檔案、實際測試結果、未驗證項目與風險。
- 說明是否建立 commit；若有，使用上層規定的中英雙語 `[Agent]` 格式。
