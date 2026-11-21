; 精核 · NSIS 安装/卸载补强
; ---------------------------------------------------------------------------
; 1) electron-builder 默认卸载清单在实测中漏删 resources\app.asar（v1.1.5 静默
;    卸载后整个安装目录只剩这一个文件）。这里显式补删，并回收空目录。
; 2) v1.1.9：卸载时询问用户是否删除个人数据（知识库 / 设置 / 日志）。
;    - 交互式卸载：弹窗询问；默认按钮为「否」；选「是」才删除。
;    - 静默卸载（/S，CI / 自动化）：一律保留数据，杜绝无人值守误删。
;    只碰应用自身数据目录，不动其它任何文件。

!macro customUnInstall
  ; 补删 electron-builder 漏删的应用包（只删安装目录内自身文件）
  Delete "$INSTDIR\resources\app.asar"
  RMDir "$INSTDIR\resources"

  ; 询问是否删除个人数据。IfSilent：静跳到保留标签，不弹窗、不删数据。
  IfSilent jinghe_skip_data_prompt 0
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
    "是否同时删除精核的个人数据？$\r$\n$\r$\n包括：知识库、设置、运行日志。$\r$\n删除后不可恢复；选择【否】将保留数据，下次安装仍可读取。" \
    IDYES jinghe_delete_personal_data
  Goto jinghe_skip_data_prompt
  jinghe_delete_personal_data:
    ; 业务数据（设置 + 知识库 + 日志）
    RMDir /r "$LOCALAPPDATA\Jinghe"
    ; Chromium 用户数据（electron-builder 内置逻辑只覆盖 --delete-app-data，
    ; 这里在用户明确选「是」时兜底清理）
    RMDir /r "$APPDATA\jinghe-desktop-shell"
  jinghe_skip_data_prompt:
!macroend
