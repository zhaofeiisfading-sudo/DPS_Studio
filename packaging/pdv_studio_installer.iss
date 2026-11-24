#ifndef MyAppVersion
  #define MyAppVersion "0.2.1"
#endif
#ifndef ProjectRoot
  #define ProjectRoot ".."
#endif
#ifndef OnedirSource
  #define OnedirSource ProjectRoot + "\build\windows_installer\dist\PDV_Studio_v" + MyAppVersion
#endif
#ifndef OutputDir
  #define OutputDir ProjectRoot + "\build\windows_installer\installer_staging"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "PDV-Studio-Setup-x64"
#endif

[Setup]
AppId={{8D6E4A72-5C39-4E91-9B1A-4D2F7A8C0200}
AppName=PDV Studio
AppVersion={#MyAppVersion}
AppVerName=PDV Studio {#MyAppVersion}
AppPublisher=DPS Studio
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName=PDV Studio
VersionInfoProductTextVersion={#MyAppVersion}
VersionInfoDescription=PDV Studio Setup (Windows x64)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DefaultDirName={code:GetPreferredInstallRoot}\PDV Studio
DefaultGroupName=PDV Studio
DisableProgramGroupPage=yes
DisableWelcomePage=no
SetupIconFile={#ProjectRoot}\src\dps_studio\gui\icons\pdv_studio.ico
UninstallDisplayIcon={app}\PDV Studio.exe
UninstallDisplayName=PDV Studio
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
UsePreviousAppDir=yes
DirExistsWarning=no

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "addtopath"; Description: "Add command-line tool (pdv) to current user &PATH"; GroupDescription: "Command-Line Interface:"; Flags: unchecked

[Dirs]
Name: "{app}\userdata"; Flags: uninsneveruninstall
Name: "{app}\userdata\config"; Flags: uninsneveruninstall
Name: "{app}\userdata\materials"; Flags: uninsneveruninstall
Name: "{app}\userdata\presets"; Flags: uninsneveruninstall
Name: "{app}\userdata\cache"; Flags: uninsneveruninstall
Name: "{app}\userdata\logs"; Flags: uninsneveruninstall
Name: "{app}\userdata\temp"; Flags: uninsneveruninstall
Name: "{app}\skills\pdv-studio"

[Files]
Source: "{#OnedirSource}\*"; DestDir: "{app}"; Excludes: "\userdata,\skills\pdv-studio\SKILL.md,\THIRD_PARTY_NOTICES.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\.agents\skills\pdv-studio\SKILL.md"; DestDir: "{app}\skills\pdv-studio"; Flags: ignoreversion
Source: "{#ProjectRoot}\packaging\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\PDV Studio"; Filename: "{app}\PDV Studio.exe"; WorkingDir: "{app}"; IconFilename: "{app}\PDV Studio.exe"
Name: "{autodesktop}\PDV Studio"; Filename: "{app}\PDV Studio.exe"; WorkingDir: "{app}"; IconFilename: "{app}\PDV Studio.exe"; Tasks: desktopicon

[Code]
const
  DRIVE_FIXED = 3;
  REG_SZ = 1;
  RRF_STRING_NOEXPAND = $10000006;
  ENVIRONMENT_KEY = 'Environment';
  WRITE_ERROR = 'The selected directory is not writable by the current user. ' +
    'PDV Studio stores userdata inside its installation directory.';

var
  PurgeUserdata: Boolean;

function GetDriveType(Root: String): LongWord;
  external 'GetDriveTypeW@kernel32.dll stdcall setuponly';

function RegGetValue(Key: LongWord; SubKey, ValueName: String; Flags: LongWord;
  var ValueType: LongWord; Data: LongWord; var DataSize: LongWord): Integer;
  external 'RegGetValueW@advapi32.dll stdcall';

function CanWriteToTargetDir(TargetDir: String): Boolean;
var
  Parent, ProbeDir: String;
begin
  Result := False;
  while not DirExists(TargetDir) do begin
    if FileExists(TargetDir) then
      Exit;
    Parent := ExtractFileDir(TargetDir);
    if (Parent = '') or (Parent = TargetDir) then
      Exit;
    TargetDir := Parent;
  end;
  ProbeDir := AddBackslash(TargetDir) + '.pdv-' + ExtractFileName(ExpandConstant('{tmp}'));
  if not CreateDir(ProbeDir) then
    Exit;
  try
    Result := SaveStringToFile(AddBackslash(ProbeDir) + 'probe', 'PDV Studio', False);
  finally
    DeleteFile(AddBackslash(ProbeDir) + 'probe');
    RemoveDir(ProbeDir);
  end;
end;

function GetPreferredInstallRoot(Param: String): String;
var
  Letter: Integer;
  Drive, Candidate: String;
begin
  for Letter := Ord('D') to Ord('Z') do begin
    Drive := Chr(Letter) + ':\';
    if (CompareText(Copy(Drive, 1, 2), Copy(ExpandConstant('{sd}'), 1, 2)) <> 0) and
        (GetDriveType(Drive) = DRIVE_FIXED) then begin
      Candidate := Drive + 'Programs';
      if CanWriteToTargetDir(Candidate) then begin
        Result := Candidate;
        Exit;
      end;
    end;
  end;
  Result := ExpandConstant('{autopf}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    if not CanWriteToTargetDir(WizardDirValue) then begin
      Log(WRITE_ERROR + ' ' + WizardDirValue);
      SuppressibleMsgBox(WRITE_ERROR, mbError, MB_OK, IDOK);
      Result := False;
    end;
end;

function NormalizedPath(Value: String): String;
begin
  Value := RemoveQuotes(Trim(Value));
  StringChangeEx(Value, '/', '\', True);
  while (Length(Value) > 3) and (Copy(Value, Length(Value), 1) = '\') do
    Delete(Value, Length(Value), 1);
  Result := Value;
end;

procedure WriteUserPath(Value: String);
var
  ValueType, Size: LongWord;
  Written: Boolean;
begin
  Size := 0;
  if (RegGetValue($80000001, ENVIRONMENT_KEY, 'Path', RRF_STRING_NOEXPAND,
                  ValueType, 0, Size) = 0) and (ValueType = REG_SZ) then
    Written := RegWriteStringValue(HKCU, ENVIRONMENT_KEY, 'Path', Value)
  else
    Written := RegWriteExpandStringValue(HKCU, ENVIRONMENT_KEY, 'Path', Value);
  if not Written then
    Log('Could not update HKCU\Environment\Path.');
end;

procedure UpdateUserPath(AddEntry: Boolean);
var
  Original, Remaining, Entry, Updated, AppDir: String;
  Found, Kept, Last: Boolean;
  Separator: Integer;
begin
  if not RegQueryStringValue(HKCU, ENVIRONMENT_KEY, 'Path', Original) then begin
    if (not AddEntry) or RegValueExists(HKCU, ENVIRONMENT_KEY, 'Path') then
      Exit;
    Original := '';
  end;
  AppDir := ExpandConstant('{app}');
  if Pos(';', AppDir) <> 0 then begin
    Log('Installation directory contains a PATH separator. PATH was left unchanged.');
    Exit;
  end;
  Remaining := Original;
  Updated := '';
  Found := False;
  Kept := False;
  repeat
    Separator := Pos(';', Remaining);
    Last := Separator = 0;
    if Last then
      Entry := Remaining
    else begin
      Entry := Copy(Remaining, 1, Separator - 1);
      Delete(Remaining, 1, Separator);
    end;
    if CompareText(NormalizedPath(Entry), NormalizedPath(AppDir)) = 0 then
      Found := True
    else begin
      if Kept then
        Updated := Updated + ';';
      Updated := Updated + Entry;
      Kept := True;
    end;
  until Last;
  if AddEntry and (not Found) then begin
    if Original <> '' then
      Original := Original + ';';
    WriteUserPath(Original + AppDir);
  end
  else if (not AddEntry) and Found then
    WriteUserPath(Updated);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and WizardSilent() then
    if not CanWriteToTargetDir(WizardDirValue) then begin
      Log(WRITE_ERROR + ' ' + WizardDirValue);
      Abort;
    end;
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    UpdateUserPath(True);
end;

function PurgeRequested(): Boolean;
var
  Index: Integer;
  Argument: String;
begin
  Result := False;
  if GetCmdTail() = '' then
    Exit;
  for Index := 1 to ParamCount() do begin
    Argument := ParamStr(Index);
    if (CompareText(Argument, '/PURGEUSERDATA') = 0) or
       (CompareText(Argument, '/PURGEUSERDATA=1') = 0) then begin
      Result := True;
      Exit;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir, Userdata: String;
begin
  AppDir := ExpandConstant('{app}');
  Userdata := AddBackslash(AppDir) + 'userdata';
  if CurUninstallStep = usUninstall then begin
    UpdateUserPath(False);
    DelTree(AddBackslash(Userdata) + 'cache', True, True, True);
    DelTree(AddBackslash(Userdata) + 'temp', True, True, True);
    PurgeUserdata := PurgeRequested();
    if (not PurgeUserdata) and (not UninstallSilent()) then
      PurgeUserdata := MsgBox('Keep PDV Studio userdata, including settings and custom materials?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDNO;
    if PurgeUserdata then
      DelTree(Userdata, True, True, True);
  end;
  if (CurUninstallStep = usPostUninstall) and PurgeUserdata then
    RemoveDir(AppDir);
end;
