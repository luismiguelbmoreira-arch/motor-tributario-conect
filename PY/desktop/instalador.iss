; desktop/instalador.iss — Instalador Windows do Motor Tributário Conect (Inno Setup 6).
;
; Empacota PY\dist\MotorTributario\ (saída do PyInstaller onedir) num único
; MotorTributario-Setup-<versão>.exe. Sem assinatura de código (fora do escopo):
; o SmartScreen avisa na 1ª execução.
;
; Gerar: powershell -ExecutionPolicy Bypass -File PY\desktop\build_instalador.ps1
;
; Instala por usuário, sem admin ({autopf} = %LOCALAPPDATA%\Programs com
; PrivilegesRequired=lowest). Os dados (banco, jwt_secret, senha inicial, PDFs
; cifrados, logs) ficam em %APPDATA%\MotorTributario e NÃO são apagados na
; desinstalação: perder o banco inutiliza o dossiê de auditoria (CTN 173).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\MotorTributario"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\instalador"
#endif

#define AppName "Motor Tributário Conect"
#define AppExe "MotorTributario.exe"

[Setup]
; AppId fixo: identifica o app entre versões (atualização por cima). Não trocar.
AppId={{6F1C2B9E-4D3A-4E8B-9A57-2C0F8D4B7E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Conect
DefaultDirName={autopf}\MotorTributario
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=MotorTributario-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Defesa extra: nada de segredo ou banco entra no pacote mesmo que apareça no dist.
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "*.db,*.db-wal,*.db-shm,.env,*.env,master.key,jwt_secret,senha_inicial_admin.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Sem [UninstallDelete]: o desinstalador remove só os arquivos que instalou.
; "filesandordirs {app}" apagaria a pasta inteira, e o usuário pode ter escolhido
; uma pasta que já existia com outros arquivos. %APPDATA%\MotorTributario fica.
