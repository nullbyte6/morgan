#ifndef MorganSourceDir
  #define MorganSourceDir "C:\Morgan"
#endif
#ifndef MorganVersion
  #define MorganVersion GetStringFileInfo(MorganSourceDir + "\Morgan.exe", "ProductVersion")
#endif
#ifndef MorganRepositoryDir
  #define MorganRepositoryDir SourcePath
#endif

[Setup]
AppId={{EFC7E428-7C68-4FF5-A608-C737BD547853}
AppName=Morgan
AppVersion={#MorganVersion}
AppPublisher=XDG
DefaultDirName=C:\Morgan
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesEnvironment=yes
SetupLogging=yes
OutputDir=build\installer
OutputBaseFilename=MorganSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\morgan.ico
UninstallDisplayIcon={app}\Morgan.exe
LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "hotkey"; Description: "Launch with the Ctrl+Alt+M hotkey"

[Files]
Source: "{#MorganSourceDir}\Morgan.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MorganSourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "scripts\morgan-services.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "scripts\morgan-hotkey.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "src\__init__.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\init\__init__.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\attachments.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\config.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\identity.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\lang.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\speech_text.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\subtitle_timing.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\tts_server.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\voice_client.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\voice_ipc.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\voice_profiles.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\voice_service.py"; DestDir: "{app}\src\init"; Flags: ignoreversion
Source: "src\init\locales\*"; DestDir: "{app}\src\init\locales"; Flags: ignoreversion
Source: "src\platforms\__init__.py"; DestDir: "{app}\src\platforms"; Flags: ignoreversion
Source: "src\platforms\base.py"; DestDir: "{app}\src\platforms"; Flags: ignoreversion
Source: "src\platforms\winx64\*.py"; DestDir: "{app}\src\platforms\winx64"; Flags: ignoreversion
Source: "src\cosyvoice\*"; DestDir: "{app}\src\cosyvoice"; Excludes: "__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "src\third_party\Matcha-TTS\*"; DestDir: "{app}\src\third_party\Matcha-TTS"; Excludes: "__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "src\voices\*"; DestDir: "{app}\src\voices"; Flags: ignoreversion
Source: "scripts\setup-runtime.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "{code:GetEnvironmentPrefix}"; ValueData: "{app}"
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "ASSISTANT_NAME"; ValueData: "{code:GetAssistantName}"
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "{code:GetEnvironmentPrefix}_HOME"; ValueData: "{code:GetRepositoryScripts}"; Check: HasMorganRepository
Root: HKCU; Subkey: "Software\Morgan\Installer"; ValueType: string; ValueName: "AssistantName"; ValueData: "{code:GetAssistantName}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Morgan\Installer"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[InstallDelete]
Type: filesandordirs; Name: "{app}\tui"
Type: files; Name: "{app}\MorganTUI.exe"
Type: files; Name: "{autoprograms}\{code:GetAssistantName} Terminal.lnk"
Type: filesandordirs; Name: "{app}\src\init"
Type: filesandordirs; Name: "{app}\dev"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\src"

[Icons]
Name: "{autoprograms}\{code:GetAssistantName}"; Filename: "{app}\Morgan.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{code:GetAssistantName}"; Filename: "{app}\Morgan.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  AssistantPage: TInputQueryWizardPage;
  BashPath: String;
  PreviousAssistantName: String;
  PreviousInstallPath: String;
  UninstallPrefix: String;
  UninstallPath: String;

function GetAssistantName(Param: String): String;
begin
  Result := Trim(AssistantPage.Values[0]);
end;

function GetEnvironmentPrefix(Param: String): String;
begin
  Result := Uppercase(GetAssistantName(''));
end;

function IsCustomAssistantName: Boolean;
begin
  Result := CompareText(GetAssistantName(''), 'Morgan') <> 0;
end;

function AssistantNameError: String;
var
  Name: String;
  Prefix: String;
  Index: Integer;
  HasAlphanumeric: Boolean;
begin
  Result := '';
  Name := GetAssistantName('');
  HasAlphanumeric := False;
  if (Length(Name) < 1) or (Length(Name) > 80) then
    Result := 'The name must contain between 1 and 80 characters.'
  else begin
    for Index := 1 to Length(Name) do begin
      if ((Name[Index] >= 'A') and (Name[Index] <= 'Z')) or
         ((Name[Index] >= 'a') and (Name[Index] <= 'z')) or
         ((Name[Index] >= '0') and (Name[Index] <= '9')) then
        HasAlphanumeric := True;
      if not (((Name[Index] >= 'A') and (Name[Index] <= 'Z')) or
              ((Name[Index] >= 'a') and (Name[Index] <= 'z')) or
              (Name[Index] = '_') or
              ((Index > 1) and (Name[Index] >= '0') and (Name[Index] <= '9'))) then
        Result := 'Use ASCII letters, digits and underscores; start with a letter or an underscore.';
    end;
    if not HasAlphanumeric then
      Result := 'The name must include at least one letter or digit.';
    Prefix := GetEnvironmentPrefix('');
    if Pos('|' + Prefix + '|',
      '|ALLUSERSPROFILE|APPDATA|BASH_ENV|COMMONPROGRAMFILES|COMPUTERNAME|COMSPEC|ENV|GIT_INSTALL_ROOT|HOME|HOMEDRIVE|HOMEPATH|LOCALAPPDATA|LOGONSERVER|NUMBER_OF_PROCESSORS|OS|PATH|PATHEXT|PROCESSOR_ARCHITECTURE|PROCESSOR_IDENTIFIER|PROGRAMDATA|PROGRAMFILES|PSMODULEPATH|PYTHONHOME|PYTHONPATH|SHELL|SYSTEMDRIVE|SYSTEMROOT|TEMP|TMP|USERDOMAIN|USERNAME|USERPROFILE|WINDIR|') > 0 then
      Result := 'That name is reserved for a system environment variable. Choose another name.';
  end;
end;

procedure InitializeWizard;
begin
  RegQueryStringValue(HKCU, 'Software\Morgan\Installer', 'AssistantName', PreviousAssistantName);
  RegQueryStringValue(HKCU, 'Software\Morgan\Installer', 'InstallPath', PreviousInstallPath);
  AssistantPage := CreateInputQueryPage(wpSelectDir,
    'Assistant name', 'Customize the assistant and its environment variables.',
    'This name will be saved in the application settings and names the data folder (.name in your user profile). Morgan creates MORGAN and MORGAN_HOME; Luna creates LUNA and LUNA_HOME. The first variable points to the installation folder. The second is only created when a cloned Morgan repository is found and points to its scripts folder.');
  AssistantPage.Add('Assistant name:', False);
  AssistantPage.Values[0] := ExpandConstant('{param:ASSISTANTNAME|' + GetPreviousData('AssistantName', 'Morgan') + '}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if CurPageID = AssistantPage.ID then begin
    Error := AssistantNameError;
    Result := Error = '';
    if not Result then
      MsgBox(Error, mbError, MB_OK);
  end;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'AssistantName', GetAssistantName(''));
end;

function BashUnder(GitDirectory: String): String;
begin
  Result := '';
  if FileExists(AddBackslash(GitDirectory) + 'cmd\git.exe') and
     FileExists(AddBackslash(GitDirectory) + 'bin\bash.exe') then
    Result := AddBackslash(GitDirectory) + 'bin\bash.exe';
end;

function FindGitBash: String;
var
  Directory: String;
  GitPath: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Software\GitForWindows', 'InstallPath', Directory) then
    Result := BashUnder(Directory);
  if (Result = '') and RegQueryStringValue(HKLM64, 'Software\GitForWindows', 'InstallPath', Directory) then
    Result := BashUnder(Directory);
  if (Result = '') and RegQueryStringValue(HKLM32, 'Software\GitForWindows', 'InstallPath', Directory) then
    Result := BashUnder(Directory);
  if Result = '' then
    Result := BashUnder(ExpandConstant('{localappdata}\Programs\Git'));
  if Result = '' then
    Result := BashUnder(ExpandConstant('{commonpf64}\Git'));
  if Result = '' then
    Result := BashUnder(ExpandConstant('{commonpf32}\Git'));
  if Result = '' then begin
    GitPath := FileSearch('git.exe', GetEnv('PATH'));
    if GitPath <> '' then
      Result := BashUnder(ExtractFileDir(ExtractFileDir(GitPath)));
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Winget: String;
  ResultCode: Integer;
begin
  Result := AssistantNameError;
  if Result <> '' then
    Exit;
  BashPath := FindGitBash;
  if BashPath <> '' then
    Exit;
  Winget := FileSearch('winget.exe', GetEnv('PATH'));
  if Winget = '' then
    Winget := ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe');
  if not FileExists(Winget) then begin
    Result := 'Install Git for Windows (including Git Bash) or WinGet, then run this installer again.';
    Exit;
  end;
  WizardForm.StatusLabel.Caption := 'Installing Git for Windows to run install.sh...';
  if not Exec(Winget,
    'install --id Git.Git --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity',
    '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then begin
    Result := 'Could not run WinGet: ' + SysErrorMessage(ResultCode);
    Exit;
  end;
  if ResultCode <> 0 then begin
    Result := 'Git installation failed with exit code ' + IntToStr(ResultCode) + '.';
    Exit;
  end;
  BashPath := FindGitBash;
  if BashPath = '' then
    Result := 'Git Bash could not be found after installing Git for Windows.';
end;

procedure DependencyOutput(const Line: String; const Error, FirstLine: Boolean);
begin
  Log(Line);
  if (not Error) and (Trim(Line) <> '') then
    WizardForm.StatusLabel.Caption := Copy(Line, 1, 180);
end;

procedure DeleteEnvironmentIfMatching(Name, ExpectedValue: String);
var
  Value: String;
begin
  if RegQueryStringValue(HKCU, 'Environment', Name, Value) and
     (CompareText(Value, ExpectedValue) = 0) then
    RegDeleteValue(HKCU, 'Environment', Name);
end;

function IsMorganRepository(Directory: String): Boolean;
begin
  Directory := RemoveBackslashUnlessRoot(Trim(Directory));
  Result := (Directory <> '') and
    (DirExists(Directory + '\.git') or FileExists(Directory + '\.git')) and
    FileExists(Directory + '\scripts\morgan-services.ps1') and
    FileExists(Directory + '\src\init\core.py');
end;

function RepositoryFromHome(Name: String): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Environment', Name, Value) then begin
    Value := RemoveBackslashUnlessRoot(Trim(Value));
    if (CompareText(ExtractFileName(Value), 'scripts') = 0) and
       IsMorganRepository(ExtractFileDir(Value)) then
      Result := ExtractFileDir(Value);
  end;
end;

function FindMorganRepository: String;
begin
  Result := RepositoryFromHome(GetEnvironmentPrefix('') + '_HOME');
  if Result = '' then
    Result := RepositoryFromHome('MORGAN_HOME');
  if (Result = '') and IsMorganRepository('{#MorganRepositoryDir}') then
    Result := RemoveBackslashUnlessRoot('{#MorganRepositoryDir}');
end;

function HasMorganRepository: Boolean;
begin
  Result := FindMorganRepository <> '';
end;

function GetRepositoryScripts(Param: String): String;
begin
  Result := AddBackslash(FindMorganRepository) + 'scripts';
end;

function GetRuntimeSwitches(Param: String): String;
begin
  if HasMorganRepository then
    Result := ' -SkipVoiceRuntime'
  else
    Result := '';
end;

procedure PrepareRuntime;
var
  Parameters: String;
  ResultCode: Integer;
begin
  WizardForm.StatusLabel.Caption := 'Preparing ' + GetAssistantName('') + ' runtime...';
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\setup-runtime.ps1') +
    '" -InstallDir "' + ExpandConstant('{app}') + '" -AssistantName "' + GetAssistantName('') + '"' +
    GetRuntimeSwitches('');
  if not Exec('powershell.exe', Parameters, '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then begin
    Log('Could not start the runtime setup: ' + SysErrorMessage(ResultCode));
    MsgBox('The ' + GetAssistantName('') + ' runtime could not be prepared: ' + SysErrorMessage(ResultCode) + #13#10#13#10 +
      'Run this installer again to retry.', mbError, MB_OK);
  end else if ResultCode <> 0 then begin
    Log('The runtime setup failed with exit code ' + IntToStr(ResultCode) + '.');
    MsgBox('The ' + GetAssistantName('') + ' runtime setup did not finish (exit code ' + IntToStr(ResultCode) + ').' + #13#10#13#10 +
      GetAssistantName('') + ' will not start its local services until it completes. ' +
      'Check your internet connection and run this installer again to resume.', mbError, MB_OK);
  end;
end;

procedure BindHotkey;
var
  Parameters: String;
  ResultCode: Integer;
begin
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\morgan-hotkey.ps1') +
    '" -InstallDir "' + ExpandConstant('{app}') + '" -AssistantName "' + GetAssistantName('') + '"';
  if (not Exec('powershell.exe', Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    Log('The hotkey could not be bound (exit code ' + IntToStr(ResultCode) + ').');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('hotkey') then
    BindHotkey;
  if CurStep = ssPostInstall then begin
    if HasMorganRepository then
      Log('Morgan repository found: ' + GetRepositoryScripts(''))
    else begin
      Log('No cloned Morgan repository found; ' + GetEnvironmentPrefix('') + '_HOME is not configured.');
      DeleteEnvironmentIfMatching(GetEnvironmentPrefix('') + '_HOME', ExpandConstant('{app}\scripts'));
    end;
  end;
  if (CurStep = ssPostInstall) and (PreviousAssistantName <> '') and
     (PreviousInstallPath <> '') and
     (CompareText(PreviousAssistantName, GetAssistantName('')) <> 0) then begin
    DeleteEnvironmentIfMatching(Uppercase(PreviousAssistantName), PreviousInstallPath);
    DeleteEnvironmentIfMatching(Uppercase(PreviousAssistantName) + '_HOME', AddBackslash(PreviousInstallPath) + 'scripts');
  end;
  if CurStep = ssPostInstall then
    PrepareRuntime;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Name: String;
begin
  if CurUninstallStep = usUninstall then begin
    if RegQueryStringValue(HKCU, 'Software\Morgan\Installer', 'AssistantName', Name) then
      UninstallPrefix := Uppercase(Name);
    RegQueryStringValue(HKCU, 'Software\Morgan\Installer', 'InstallPath', UninstallPath);
  end;
  if (CurUninstallStep = usPostUninstall) and
     (UninstallPrefix <> '') and (UninstallPath <> '') then begin
    DeleteEnvironmentIfMatching(UninstallPrefix, UninstallPath);
    DeleteEnvironmentIfMatching('ASSISTANT_NAME', UninstallPrefix);
    DeleteEnvironmentIfMatching(UninstallPrefix + '_HOME', AddBackslash(UninstallPath) + 'scripts');
  end;
end;
