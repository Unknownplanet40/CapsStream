' ============================================================
'  CapsStream — uTorrent State Change Hook (Silent Launcher)
'  Executes on any torrent state change.
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

args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & """" & WScript.Arguments(i) & """ "
Next

' Run hidden (0 = no console window), don't wait (False)
shell.Run """" & pythonw & """ """ & script & """ " & args, 0, False
