#define MyAppName "NAS音乐器"
#define MyAppPublisher "moneyperfect"
#define MyAppURL "https://github.com/moneyperfect/NASMusicBox"
#define RepoRoot ".."
#ifndef MyAppVersion
  #define MyAppVersion "1.5.1"
#endif

[Setup]
AppId={{C2F4ADAF-3E51-4C68-8D14-5F8117275A20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\NASMusicBox
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
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
Name: "english"; MessagesFile: "compiler:Default.isl"
#ifdef IncludeChineseLanguage
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#RepoRoot}\dist\versions\NASMusicBox-v{#MyAppVersion}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\NASMusicBox.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\NASMusicBox.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NASMusicBox.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
