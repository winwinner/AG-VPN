@echo off
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  "http://192.168.146.1/cgi-bin/luci/admin/status/overview" ^
  "http://192.168.155.1/cgi-bin/luci/admin/status/overview" ^
  "http://192.168.159.1/cgi-bin/luci/admin/status/overview"
