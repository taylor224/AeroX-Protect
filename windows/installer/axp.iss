; AeroXProtect Windows installer (Inno Setup 6).
; Build (from a machine/CI where the payload dirs exist):
;   iscc /DAppVersion=1.3.0 /DPayloadDir=..\..\build\payload axp.iss
;
; PayloadDir layout (produced by CI from fetch-runtime.ps1 + assemble-bundle.ps1):
;   runtime\{python,ffmpeg,go2rtc,caddy,redis,mariadb,fonts}\...
;   winsw\WinSW-x64.exe
;   app\   = extracted aeroxprotect-windows-x64-app-v<version>.zip
;
; Deliberately thin: all real post-install logic lives in postinstall.py, run with
; the bundled CPython (easier to test and shared with dev installs).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\build\payload"
#endif

[Setup]
AppId={{7E7C60D1-9F62-4D5B-A1D2-AXPNVR000001}
AppName=AeroXProtect
AppVersion={#AppVersion}
AppPublisher=AeroXProtect
DefaultDirName=C:\AeroXProtect
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputBaseFilename=AeroXProtect-Setup-v{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName=AeroXProtect NVR

[Languages]
; Korean.isl is not shipped with stock Inno Setup (unofficial translation) — add it
; to the repo and reference it here if a Korean installer UI is wanted.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; runtime tier — replaced only by the installer, never by web auto-update
Source: "{#PayloadDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs ignoreversion
; launcher (stdlib package) + WinSW + config templates
Source: "..\launcher\axp_launcher\*"; DestDir: "{app}\launcher\axp_launcher"; Flags: recursesubdirs ignoreversion
Source: "..\service\axp-service.xml"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "{#PayloadDir}\winsw\WinSW-x64.exe"; DestDir: "{app}\launcher"; DestName: "axp-service.exe"; Flags: ignoreversion
Source: "..\caddy\Caddyfile.tmpl"; DestDir: "{app}\launcher\templates"; Flags: ignoreversion
Source: "..\mariadb\my.ini.tmpl"; DestDir: "{app}\launcher\templates"; Flags: ignoreversion
Source: "..\redis\redis.windows.conf.tmpl"; DestDir: "{app}\launcher\templates"; Flags: ignoreversion
Source: "..\go2rtc\go2rtc.windows.yaml"; DestDir: "{app}\launcher\templates"; Flags: ignoreversion
Source: "postinstall.py"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "bootstrap_admin.py"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "open-ui.ps1"; DestDir: "{app}\launcher"; Flags: ignoreversion
; versioned app payload
Source: "{#PayloadDir}\app\*"; DestDir: "{app}\versions\v{#AppVersion}"; Flags: recursesubdirs ignoreversion

[Code]
var
  ConfigPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  ConfigPage := CreateInputQueryPage(wpSelectDir,
    'AeroXProtect 설정', '웹 포트와 관리자 계정',
    '기본값을 그대로 사용해도 됩니다. 관리자 비밀번호는 첫 로그인에 사용됩니다.');
  ConfigPage.Add('웹 포트 (HTTP)', False);
  ConfigPage.Add('관리자 아이디', False);
  ConfigPage.Add('관리자 비밀번호', True);
  ConfigPage.Values[0] := '3000';
  ConfigPage.Values[1] := 'admin';
  ConfigPage.Values[2] := '';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = ConfigPage.ID) and (ConfigPage.Values[2] = '') then
  begin
    MsgBox('관리자 비밀번호를 입력하세요.', mbError, MB_OK);
    Result := False;
  end;
end;

function PyExe(Param: String): String;
begin
  Result := ExpandConstant('{app}\runtime\python\python.exe');
end;

function GetHttpPort(Param: String): String;
begin Result := ConfigPage.Values[0]; end;

function GetAdminId(Param: String): String;
begin Result := ConfigPage.Values[1]; end;

function GetAdminPw(Param: String): String;
begin Result := ConfigPage.Values[2]; end;

[Run]
Filename: "{code:PyExe}"; \
  Parameters: "-u ""{app}\launcher\postinstall.py"" --home ""{app}"" --version ""{#AppVersion}"" --http-port ""{code:GetHttpPort}"""; \
  StatusMsg: "구성 요소를 설정하는 중..."; Flags: runhidden waituntilterminated
Filename: "{app}\launcher\axp-service.exe"; Parameters: "start"; \
  StatusMsg: "AeroXProtect 서비스를 시작하는 중..."; Flags: runhidden waituntilterminated
; admin account: the wizard password is handed to seed-admin IN MEMORY only —
; never written to axp.env or any file. Waits for the stack's first boot.
Filename: "{code:PyExe}"; \
  Parameters: "-u ""{app}\launcher\bootstrap_admin.py"" --home ""{app}"" --admin-id ""{code:GetAdminId}"" --admin-pw ""{code:GetAdminPw}"""; \
  StatusMsg: "관리자 계정을 생성하는 중... (첫 부팅 대기, 최대 수 분)"; Flags: runhidden waituntilterminated
; finish page: open the web UI (checked by default). open-ui.ps1 waits for the
; stack to come up first; runasoriginaluser so the browser is not elevated.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\launcher\open-ui.ps1"" -Port {code:GetHttpPort}"; \
  Description: "웹 브라우저에서 AeroXProtect 열기"; \
  Flags: postinstall runasoriginaluser runhidden nowait

[UninstallRun]
Filename: "{app}\launcher\axp-service.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "svcstop"
Filename: "{app}\launcher\axp-service.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "svcuninst"

[UninstallDelete]
; binaries + versions only. data\ (recordings DB), config\ (secrets) and storage\
; are preserved — deleting footage must be a deliberate human act.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\versions"
Type: filesandordirs; Name: "{app}\launcher"
Type: files; Name: "{app}\current"
