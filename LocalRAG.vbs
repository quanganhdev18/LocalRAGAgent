' Kho tai lieu cuc bo - launcher (khong can terminal).
' Lan dau tren may moi: tu tao moi truong Python (.venv) va cai thu vien (can Internet, vai phut).
' Yeu cau: Python 3.11 hoac 3.12 da cai (python.org, tick "Add python.exe to PATH").
Option Explicit
Dim sh, fso, root, venvDir, pyw, py, rc, cmd, ans

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root

' Mot .venv copy tu may khac se hong (tro toi Python cua may cu) -> dung .venv-local rieng cho may nay.
venvDir = root & "\.venv"
If Not VenvOk(venvDir) Then venvDir = root & "\.venv-local"
pyw = venvDir & "\Scripts\pythonw.exe"

If Not (VenvOk(venvDir) And fso.FileExists(pyw)) Then
    ' Tim Python he thong
    py = ""
    If RunHidden("py -3 --version") = 0 Then
        py = "py -3"
    ElseIf RunHidden("python --version") = 0 Then
        py = "python"
    End If
    If py = "" Then
        MsgBox "Chua tim thay Python tren may nay." & vbCrLf & vbCrLf & _
               "Hay cai Python 3.12 (python.org/downloads), nho tick 'Add python.exe to PATH', roi mo lai LocalRAG.vbs.", _
               vbExclamation, "Kho tai lieu cuc bo"
        sh.Run "https://www.python.org/downloads/windows/"
        WScript.Quit 1
    End If
    ans = MsgBox("Lan dau chay tren may nay: can cai dat thu vien (can Internet, khoang vai phut)." & vbCrLf & _
                 "Mot cua so den se hien ra trong luc cai dat. Tiep tuc?", vbOKCancel + vbQuestion, "Kho tai lieu cuc bo")
    If ans <> vbOK Then WScript.Quit 0
    cmd = "cmd /c ""cd /d """ & root & """ && " & py & " -m venv """ & venvDir & """ && """ & venvDir & _
          "\Scripts\python.exe"" -m pip install --upgrade pip && """ & venvDir & _
          "\Scripts\python.exe"" -m pip install -r requirements.txt"""
    rc = sh.Run(cmd, 1, True)
    If rc <> 0 Or Not fso.FileExists(pyw) Then
        MsgBox "Cai dat that bai (ma " & rc & "). Kiem tra ket noi Internet roi chay lai.", vbCritical, "Kho tai lieu cuc bo"
        WScript.Quit 1
    End If
End If

sh.Run """" & pyw & """ -m localrag.launcher", 0, False

Function RunHidden(c)
    On Error Resume Next
    RunHidden = sh.Run("cmd /c " & c & " >nul 2>nul", 0, True)
    If Err.Number <> 0 Then RunHidden = 1
End Function

' Venv hop le: co pythonw.exe VA thu muc "home" trong pyvenv.cfg con ton tai tren may nay.
Function VenvOk(d)
    Dim cfg, f, line, home
    VenvOk = False
    If Not fso.FileExists(d & "\Scripts\pythonw.exe") Then Exit Function
    cfg = d & "\pyvenv.cfg"
    If Not fso.FileExists(cfg) Then Exit Function
    Set f = fso.OpenTextFile(cfg, 1)
    Do While Not f.AtEndOfStream
        line = f.ReadLine
        If LCase(Left(line, 4)) = "home" Then
            home = Trim(Mid(line, InStr(line, "=") + 1))
            VenvOk = fso.FolderExists(home)
            Exit Do
        End If
    Loop
    f.Close
End Function
