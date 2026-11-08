Set sh = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
sh.Run """" & root & "\.venv\Scripts\pythonw.exe"" -m localrag.launcher", 0, False
