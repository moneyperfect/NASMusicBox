#define MyAppName "NAS音乐器"
#define MyAppPublisher "moneyperfect"
#define MyAppURL "https://music.nasbuild.dev"
#define RepoRoot ".."
#ifndef MyAppVersion
  #define MyAppVersion "1.7.0"
#endif

[Setup]
AppId={{C2F4ADAF-3E51-4C68-8D14-5F8117275A20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL=https://github.com/moneyperfect/NASMusicBox/issues
AppUpdatesURL=https://github.com/moneyperfect/NASMusicBox/releases
DefaultDirName={code:GetDefaultInstallDir}
DisableDirPage=no
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
MinVersion=10.0
DisableProgramGroupPage=yes
WizardStyle=modern
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#RepoRoot}\dist\release
OutputBaseFilename=NASMusicBox-Setup
SetupIconFile={#RepoRoot}\assets\app-icon.ico
UninstallDisplayIcon={app}\NASMusicBox.exe

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#RepoRoot}\tools\webview2\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
Source: "{#RepoRoot}\dist\versions\NASMusicBox-v{#MyAppVersion}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\NASMusicBox.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\NASMusicBox.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NASMusicBox.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function GetDriveType(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function GetDefaultInstallDir(Param: String): String;
begin
  if DirExists('D:\') and (GetDriveType('D:\') = 3) then
    Result := 'D:\Apps\NASMusicBox'
  else if DirExists('E:\') and (GetDriveType('E:\') = 3) then
    Result := 'E:\Apps\NASMusicBox'
  else
    Result := ExpandConstant('{localappdata}\Programs\NASMusicBox');
end;

function WebView2Installed: Boolean;
var
  Version: String;
  ClientKey: String;
begin
  ClientKey := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKLM32, ClientKey, 'pv', Version) or
             RegQueryStringValue(HKCU, ClientKey, 'pv', Version)) and
             (Version <> '') and (Version <> '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if not WebView2Installed then
  begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'),
                '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'Microsoft Edge WebView2 could not start. Please install it from https://developer.microsoft.com/microsoft-edge/webview2/ and retry.'
    else if not WebView2Installed then
      Result := 'Microsoft Edge WebView2 installation did not complete. Check your internet connection and retry. Exit code: ' + IntToStr(ExitCode);
  end;
end;
