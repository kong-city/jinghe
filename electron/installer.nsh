; 精核 · NSIS 安装/卸载补强
; ---------------------------------------------------------------------------
; electron-builder 默认卸载清单在实测中漏删 resources\app.asar（v1.1.5 静默
; 卸载后整个安装目录只剩这一个 14KB 文件）。这里显式补删，并回收空目录。
; 只删除安装目录内的应用自身文件，不碰 %APPDATA% 下的用户设置与日志。

!macro customUnInstall
  Delete "$INSTDIR\resources\app.asar"
  RMDir "$INSTDIR\resources"
!macroend
