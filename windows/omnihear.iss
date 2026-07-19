; Inno Setup script for Omnihear on Windows.
; Build with: iscc /DVersion=1.2.1 windows\omnihear.iss
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppName=Omnihear
AppVersion={#Version}
DefaultDirName={localappdata}\Programs\Omnihear
DefaultGroupName=Omnihear
PrivilegesRequired=lowest
SetupIconFile=omnihear.ico
OutputDir=..\dist-installer
OutputBaseFilename=omnihear-setup-{#Version}
Compression=lzma2
SolidCompression=yes

[Files]
Source: "..\dist\omnihear\*"; DestDir: "{app}"; Flags: recursesubdirs

[Tasks]
Name: "autostart"; Description: "Start Omnihear automatically when Windows starts"; Flags: checkedonce

[Icons]
Name: "{userprograms}\Omnihear"; Filename: "{app}\omnihear.exe"
Name: "{userstartup}\Omnihear"; Filename: "{app}\omnihear.exe"; Tasks: autostart

[Run]
Filename: "{app}\omnihear.exe"; Description: "Launch Omnihear"; Flags: nowait postinstall skipifsilent
