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

Var AppKey
Var UninstallKey
Var ShortcutName
Var InstallMode
Name "D4Planner ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\D4Planner"
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
  ${GetParameters} $0
  ${GetOptions} $0 "/ISOLATED=" $2
  StrCpy $InstallMode "production"
  StrCpy $AppKey "Software\Synclab\D4Planner"
  StrCpy $UninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner"
  StrCpy $ShortcutName "D4Planner"
  StrCpy $DataRoot "$LOCALAPPDATA\StreamOps\D4Planner"
  ${If} $2 == "1"
    StrCpy $InstallMode "uat"
    StrCpy $AppKey "Software\Synclab\D4Planner-UAT"
    StrCpy $UninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4PlannerUAT"
    StrCpy $ShortcutName "D4Planner UAT"
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\D4Planner-UAT"
    ${GetOptions} $0 "/DATADIR=" $1
    ${If} $1 == ""
      SetErrorLevel 1
      Abort
    ${EndIf}
    ${GetOptions} $0 "/INSTALLROOT=" $1
    ${If} $1 == ""
      SetErrorLevel 1
      Abort
    ${EndIf}
  ${ElseIf} $2 != ""
    SetErrorLevel 1
    Abort
  ${EndIf}
  ReadRegStr $1 HKCU "$AppKey" "InstallRoot"
  ${If} $1 != ""
    StrCpy $INSTDIR $1
  ${EndIf}
  ReadRegStr $1 HKCU "$AppKey" "DataRoot"
  ${If} $1 != ""
    StrCpy $DataRoot $1
  ${EndIf}
  ${GetOptions} $0 "/INSTALLROOT=" $1
  ${If} $1 != ""
    StrCpy $INSTDIR $1
  ${EndIf}
  ${GetOptions} $0 "/DATADIR=" $1
  ${If} $1 != ""
    StrCpy $DataRoot $1
  ${EndIf}
  ; A second root must not steal even the UAT registration/shortcuts.
  ReadRegStr $1 HKCU "$AppKey" "InstallRoot"
  ${If} $1 != ""
  ${AndIf} $1 != $INSTDIR
    MessageBox MB_ICONSTOP "This application identity belongs to a different installation root." /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  IfFileExists "$INSTDIR\installer-identity.ini" 0 identity_checked
  ReadINIStr $1 "$INSTDIR\installer-identity.ini" "Installation" "Mode"
  ${If} $1 != $InstallMode
    SetErrorLevel 1
    Abort
  ${EndIf}
  ReadINIStr $1 "$INSTDIR\installer-identity.ini" "Installation" "InstallRoot"
  ${If} $1 != $INSTDIR
    SetErrorLevel 1
    Abort
  ${EndIf}
  identity_checked:
  ; Stop the registered owned app before unpacking the large embedded payload.
  ; A manual directory selection is not authority to execute an unrelated EXE.
  ReadRegStr $1 HKCU "$AppKey" "InstallRoot"
  ${If} $1 == $INSTDIR
  ${AndIf} $1 != ""
    IfFileExists "$INSTDIR\installer-identity.ini" 0 owned_stop_done
    ExecWait '"$INSTDIR\D4Planner.exe" --stop' $Result
    ${If} $Result != 0
      SetErrorLevel 1
      Abort
    ${EndIf}
  ${EndIf}
  owned_stop_done:
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
  WriteINIStr "$INSTDIR\installer-identity.ini" "Installation" "Mode" "$InstallMode"
  WriteINIStr "$INSTDIR\installer-identity.ini" "Installation" "InstallRoot" "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\$ShortcutName"
  CreateShortcut "$SMPROGRAMS\$ShortcutName\D4Planner.lnk" "$INSTDIR\D4Planner.exe"
  CreateShortcut "$SMPROGRAMS\$ShortcutName\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\$ShortcutName.lnk" "$INSTDIR\D4Planner.exe"
  WriteRegStr HKCU "$AppKey" "InstallRoot" "$INSTDIR"
  WriteRegStr HKCU "$AppKey" "DataRoot" "$DataRoot"
  WriteRegStr HKCU "$UninstallKey" "DisplayName" "$ShortcutName"
  WriteRegStr HKCU "$UninstallKey" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "$UninstallKey" "Publisher" "Synclab"
  WriteRegStr HKCU "$UninstallKey" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "$UninstallKey" "DisplayIcon" "$INSTDIR\D4Planner.exe"
  WriteRegStr HKCU "$UninstallKey" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "$UninstallKey" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "$UninstallKey" "NoModify" 1
  WriteRegDWORD HKCU "$UninstallKey" "NoRepair" 1
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  ReadINIStr $InstallMode "$INSTDIR\installer-identity.ini" "Installation" "Mode"
  ReadINIStr $0 "$INSTDIR\installer-identity.ini" "Installation" "InstallRoot"
  ${If} $0 != $INSTDIR
    SetErrorLevel 1
    Abort
  ${EndIf}
  ${If} $InstallMode == "uat"
    StrCpy $AppKey "Software\Synclab\D4Planner-UAT"
    StrCpy $UninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4PlannerUAT"
    StrCpy $ShortcutName "D4Planner UAT"
  ${ElseIf} $InstallMode == "production"
    StrCpy $AppKey "Software\Synclab\D4Planner"
    StrCpy $UninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner"
    StrCpy $ShortcutName "D4Planner"
  ${Else}
    SetErrorLevel 1
    Abort
  ${EndIf}
  ReadRegStr $0 HKCU "$AppKey" "InstallRoot"
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
  Delete "$DESKTOP\$ShortcutName.lnk"
  Delete "$SMPROGRAMS\$ShortcutName\D4Planner.lnk"
  Delete "$SMPROGRAMS\$ShortcutName\Uninstall.lnk"
  RMDir "$SMPROGRAMS\$ShortcutName"
  DeleteRegKey HKCU "$UninstallKey"
  DeleteRegKey HKCU "$AppKey"
  Delete "$INSTDIR\installer-identity.ini"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\.setup.lock"
  RMDir "$INSTDIR\versions"
  RMDir "$INSTDIR"
SectionEnd
