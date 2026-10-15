#ifndef AppDist
  #define AppDist "dist\SpireLens"
#endif

[Setup]
AppId={{EAF7EC43-2A71-48E6-B93F-79C8248D498D}
AppName=SpireLens
AppVersion=1.1.0
AppPublisher=SpireLens
AppComments=Локальный анализ забегов Slay the Spire 2
DefaultDirName={localappdata}\Programs\SpireLens
DefaultGroupName=SpireLens
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=release
OutputBaseFilename=SpireLens-1.1.0-Windows-x64-Setup
SetupIconFile=spirelens.ico
UninstallDisplayIcon={app}\SpireLens.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex=SpireLensDesktop
DisableWelcomePage=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
Source: "{#AppDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "WINDOWS-README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SpireLens"; Filename: "{app}\SpireLens.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\SpireLens"; Filename: "{app}\SpireLens.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\SpireLens.exe"; Description: "Запустить SpireLens"; Flags: nowait postinstall skipifsilent

; User settings and all game saves are intentionally retained on uninstall.
