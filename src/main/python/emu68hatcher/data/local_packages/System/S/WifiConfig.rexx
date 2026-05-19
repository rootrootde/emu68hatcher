/* WifiConfig.rexx
 *
 * WiFi configuration tool for Emu68 Hatcher. Uses rexxreqtools.library
 * for GUI requesters (rtgetstring, rtezrequest). Writes SSID and password
 * to wireless.prefs in wpa_supplicant format for WirelessManager.
 *
 * Exit codes:
 *   0  - config saved
 *   5  - user cancelled at a prompt
 *   20 - rexxreqtools.library missing or prefs write failed
 */

hPrefsFile = 'SYS:Prefs/Env-Archive/Sys/wireless.prefs'

/* rexxsupport.library provides exists() - without it the function
 * falls through to host dispatch and returns garbage.
 */
if ~show('l', 'rexxsupport.library') then
    call addlib('rexxsupport.library', 0, -30, 0)

/* load rexxreqtools.library; fall back with RequestChoice if missing */
if ~show('l', 'rexxreqtools.library') then do
    if ~addlib('rexxreqtools.library', 0, -30, 0) then do
        address command ,
            'RequestChoice >NIL: TITLE "Wifi Config"' ,
            'BODY "rexxreqtools.library is missing.*nRebuild the SD card with the latest Hatcher."' ,
            'GADGETS "OK"'
        exit 20
    end
end

/* read existing SSID so we can offer it as the default */
hOldSsid = ''
if exists(hPrefsFile) then do
    if open('p', hPrefsFile, 'R') then do
        do while ~eof('p')
            hLine = strip(readln('p'))
            if pos('SSID=', upper(hLine)) > 0 then do
                parse var hLine . 'ssid="'hOldSsid'"'
                leave
            end
        end
        call close('p')
    end
end

/* prompt for SSID */
hSsid = rtgetstring(hOldSsid, 'Enter WiFi SSID:', 'Wifi Config')
if rtresult = 0 then exit 5
hSsid = strip(hSsid)
if hSsid = '' then exit 5

/* prompt for password */
hPsk = rtgetstring('', 'Enter WiFi password'||'0a'x||'(leave empty for open network):', 'Wifi Config')
if rtresult = 0 then exit 5
hPsk = strip(hPsk)

/* write wireless.prefs */
if ~open('w', hPrefsFile, 'W') then do
    call rtezrequest('Could not write:'||'0a'x||hPrefsFile, 'OK', 'Wifi Config')
    exit 20
end

call writeln('w', 'network={')
call writeln('w', '   ssid="'hSsid'"')
if hPsk = '' then
    call writeln('w', '   key_mgmt=NONE')
else
    call writeln('w', '   psk="'hPsk'"')
call writeln('w', '   scan_ssid=1')
call writeln('w', '}')
call close('w')

call rtezrequest('WiFi settings saved.'||'0a'x||'0a'x||'SSID: 'hSsid, 'OK', 'Wifi Config')
exit 0
