# convo watcher — polls conversation.md every 15s, infinite until DONE
# Usage: powershell -ExecutionPolicy Bypass -File tools/watch_convo.ps1
# Preferred cross-platform parallel agent: python tools/convo_watcher.py (10s poll + state json)
$root = Split-Path $PSScriptRoot -Parent
$convo = Join-Path $root "conversation.md"
$log = Join-Path $root "out/watch.log"
$done = Join-Path $root ".watch_done"
$last = ""
if (!(Test-Path (Split-Path $log -Parent))) { New-Item -ItemType Directory -Force -Path (Split-Path $log -Parent) | Out-Null }
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watch] started, polling $convo every 15s" | Tee-Object -FilePath $log -Append
while ($true) {
  if (Test-Path $done) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watch] DONE flag found, exiting" | Tee-Object -FilePath $log -Append; break }
  try {
    $h = (Get-FileHash $convo -Algorithm SHA256).Hash
    if ($last -ne "" -and $h -ne $last) {
      "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watch] CHANGE detected in conversation.md (hash $h)" | Tee-Object -FilePath $log -Append
      # print last 30 lines so async terminal shows what changed
      Get-Content $convo -Tail 30 | Out-String | Tee-Object -FilePath $log -Append
    }
    $last = $h
  } catch { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watch] error: $_" | Tee-Object -FilePath $log -Append }
  Start-Sleep -Seconds 15
}
