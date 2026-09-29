' ============================================================
'  CapsStream — uTorrent Finish Hook (Silent Launcher)
'  Executes when a torrent finishes downloading.
'  Automatically forces --finish so media request is marked completed.
'  Runs 100% silently with ZERO console window or terminal flashing.
' ============================================================
Option Explicit

Dim shell, fso, scriptDir, rootDir, pythonw, script, args, i

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootDir = fso.GetAbsolutePathName(scriptDir & "\..")
pythonw = rootDir & "\winpython\python\pythonw.exe"
script = rootDir & "\backend\utorrent_hook.py"

If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

' Always prepend --finish so the hook unconditionally treats this as a finished event
args = "--finish "
For i = 0 To WScript.Arguments.Count - 1
    args = args & """" & WScript.Arguments(i) & """ "
Next

' Run hidden (0 = no console window), don't wait (False)
shell.Run """" & pythonw & """ """ & script & """ " & args, 0, False
