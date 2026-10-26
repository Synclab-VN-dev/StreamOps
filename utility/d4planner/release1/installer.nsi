; One installer and one transaction engine. Tauri's FE stays unchanged.
Unicode true
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor lzma
CRCCheck force
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

!define APPKEY "Software\Synclab\D4Planner"
!define UNINSTALLKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner"
Name "D4Planner ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\D4Planner"
InstallDirRegKey HKCU "${APPKEY}" "InstallRoot"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "D4Planner"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "D4Planner per-user Setup"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Synclab"

Var DataRoot
Var Result
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  SetRegView 64
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "D4Planner requires 64-bit Windows." /SD IDOK
    Abort
  ${EndIf}
  StrCpy $DataRoot "$LOCALAPPDATA\StreamOps\D4Planner"
  ReadRegStr $0 HKCU "${APPKEY}" "InstallRoot"
  ${If} $0 != ""
    StrCpy $INSTDIR $0
  ${EndIf}
  ReadRegStr $0 HKCU "${APPKEY}" "DataRoot"
  ${If} $0 != ""
    StrCpy $DataRoot $0
  ${EndIf}
  ${GetParameters} $0
  ${GetOptions} $0 "/INSTALLROOT=" $1
  ${If} $1 != ""
    StrCpy $INSTDIR $1
  ${EndIf}
  ${GetOptions} $0 "/ISOLATED=" $2
  ${GetOptions} $0 "/DATADIR=" $1
  ${If} $1 != ""
    StrCpy $DataRoot $1
  ${EndIf}
  ${If} $2 == "1"
    ${If} $1 == ""
      SetErrorLevel 1
      Abort
    ${EndIf}
    ${GetOptions} $0 "/INSTALLROOT=" $1
    ${If} $1 == ""
      SetErrorLevel 1
      Abort
    ${EndIf}
  ${EndIf}
  ; Stop the registered owned app before unpacking the large embedded payload.
  ; A manual directory selection is not authority to execute an unrelated EXE.
  ReadRegStr $1 HKCU "${APPKEY}" "InstallRoot"
  ${If} $1 == $INSTDIR
  ${AndIf} $1 != ""
    ExecWait '"$INSTDIR\D4Planner.exe" --stop' $Result
    ${If} $Result != 0
      SetErrorLevel 1
      Abort
    ${EndIf}
  ${EndIf}
  ; Evergreen prerequisite is checked locally. Setup never downloads it or
  ; elevates to install prerequisites. Same registry probes as Tauri bundler.
  SetRegView 32
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${If} $0 == ""
    ReadRegStr $0 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${EndIf}
  ${If} $0 == ""
    SetRegView 64
    ReadRegStr $0 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ${EndIf}
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    MessageBox MB_ICONSTOP "Microsoft Edge WebView2 Runtime is required. Setup will not download or install it. Install an approved WebView2 runtime before continuing." /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "D4Planner" SEC_MAIN
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\python"
  File /r "${PYTHON_ROOT}/*"
  SetOutPath "$PLUGINSDIR"
  File /oname=windows_install.py "${ENGINE}"
  File /oname=release1_delivery.py "${DELIVERY}"
  SetCompress off
  File /oname=payload.zip "${PACKAGE}"
  SetCompress auto
  DetailPrint "Verifying payload, stopping owned D4Planner and activating ${VERSION}..."
  ExecWait '"$PLUGINSDIR\python\python.exe" "$PLUGINSDIR\windows_install.py" install --root "$INSTDIR" --data "$DataRoot" --package "$PLUGINSDIR\payload.zip" --sha256 ${PACKAGE_SHA256} --report "$TEMP\D4Planner-setup-${VERSION}.json"' $Result
  ${If} $Result != 0
    MessageBox MB_ICONSTOP "Installation failed or was rolled back. See $TEMP\D4Planner-setup-${VERSION}.json. User data was preserved." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  ; Maintenance helpers are separate from the active immutable payload so an
  ; uninstall can copy them to TEMP before removing application files.
  SetOutPath "$INSTDIR\maintenance\python"
  File /r "${PYTHON_ROOT}/*"
  SetOutPath "$INSTDIR\maintenance"
  File /oname=windows_install.py "${ENGINE}"
  File /oname=release1_delivery.py "${DELIVERY}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\D4Planner"
  CreateShortcut "$SMPROGRAMS\D4Planner\D4Planner.lnk" "$INSTDIR\D4Planner.exe"
  CreateShortcut "$SMPROGRAMS\D4Planner\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\D4Planner.lnk" "$INSTDIR\D4Planner.exe"
  WriteRegStr HKCU "${APPKEY}" "InstallRoot" "$INSTDIR"
  WriteRegStr HKCU "${APPKEY}" "DataRoot" "$DataRoot"
  WriteRegStr HKCU "${UNINSTALLKEY}" "DisplayName" "D4Planner"
  WriteRegStr HKCU "${UNINSTALLKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALLKEY}" "Publisher" "Synclab"
  WriteRegStr HKCU "${UNINSTALLKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALLKEY}" "DisplayIcon" "$INSTDIR\D4Planner.exe"
  WriteRegStr HKCU "${UNINSTALLKEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${UNINSTALLKEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "${UNINSTALLKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALLKEY}" "NoRepair" 1
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  ReadRegStr $0 HKCU "${APPKEY}" "InstallRoot"
  ${If} $0 != $INSTDIR
    MessageBox MB_ICONSTOP "Application registration does not match this installation. Refusing uninstall." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  InitPluginsDir
  CopyFiles /SILENT "$INSTDIR\maintenance" "$PLUGINSDIR"
  ExecWait '"$PLUGINSDIR\maintenance\python\python.exe" "$PLUGINSDIR\maintenance\windows_install.py" uninstall --root "$INSTDIR" --report "$TEMP\D4Planner-uninstall.json"' $Result
  ${If} $Result != 0
    MessageBox MB_ICONSTOP "Uninstall failed safely. See $TEMP\D4Planner-uninstall.json." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  ; Generated exact maintenance deletion list, never recursive user data removal.
  !include "${MAINTENANCE_DELETE}"
  Delete "$DESKTOP\D4Planner.lnk"
  Delete "$SMPROGRAMS\D4Planner\D4Planner.lnk"
  Delete "$SMPROGRAMS\D4Planner\Uninstall.lnk"
  RMDir "$SMPROGRAMS\D4Planner"
  DeleteRegKey HKCU "${UNINSTALLKEY}"
  DeleteRegKey HKCU "${APPKEY}"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\.setup.lock"
  RMDir "$INSTDIR\versions"
  RMDir "$INSTDIR"
SectionEnd
