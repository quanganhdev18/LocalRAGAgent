; Inno Setup. CHƯA được build/kiểm thử. Chưa ký số: hướng dẫn người dùng bỏ qua cảnh báo SmartScreen.
[Setup]
AppName=Kho tài liệu cục bộ
AppVersion=0.1.0
DefaultDirName={autopf}\LocalRAG
OutputBaseFilename=LocalRAG-setup
[Files]
Source: "..\dist\LocalRAG\*"; DestDir: "{app}"; Flags: recursesubdirs
