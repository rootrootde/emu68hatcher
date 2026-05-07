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

call HLogOpen "WifiConfig"
call HLogWrite "starting WiFi config dialog"

/* load rexxreqtools.library; fall back with RequestChoice if missing */
if ~show('l', 'rexxreqtools.library') then do
    if ~addlib('rexxreqtools.library', 0, -30, 0) then do
        call HLogSay "rexxreqtools.library is missing - cannot show requester."
        address command ,
            'RequestChoice >NIL: TITLE "Wifi Config"' ,
            'BODY "rexxreqtools.library is missing.*nRebuild the SD card with the latest Hatcher."' ,
            'GADGETS "OK"'
        call HLogClose
        exit 20
    end
end

/* read existing SSID to offer as the default */
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
if hOldSsid ~= '' then call HLogWrite "previous SSID found: " || hOldSsid

/* prompt for SSID */
hSsid = rtgetstring(hOldSsid, 'Enter WiFi SSID:', 'Wifi Config')
if rtresult = 0 then do
    call HLogSay "user cancelled at SSID prompt"
    call HLogClose
    exit 5
end
hSsid = strip(hSsid)
if hSsid = '' then do
    call HLogSay "empty SSID - aborting"
    call HLogClose
    exit 5
end
call HLogWrite "user-entered SSID: " || hSsid

/* prompt for password */
hPsk = rtgetstring('', 'Enter WiFi password'||'0a'x||'(leave empty for open network):', 'Wifi Config')
if rtresult = 0 then do
    call HLogSay "user cancelled at password prompt"
    call HLogClose
    exit 5
end
hPsk = strip(hPsk)
if hPsk = '' then call HLogWrite "password: <empty> (open network)"
                else call HLogWrite "password: <set> (" || length(hPsk) || " chars)"

/* write wireless.prefs */
if ~open('w', hPrefsFile, 'W') then do
    call HLogSay "could not write " || hPrefsFile
    call rtezrequest('Could not write:'||'0a'x||hPrefsFile, 'OK', 'Wifi Config')
    call HLogClose
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

call HLogSay "WiFi settings saved to " || hPrefsFile

call rtezrequest('WiFi settings saved.'||'0a'x||'0a'x||'SSID: 'hSsid, 'OK', 'Wifi Config')
call HLogClose
exit 0

/* HLog* logging helpers - canonical copy at S:HatcherLog.rexx */

HLogOpen:
    parse arg HL_NAME
    if HL_NAME = '' then HL_NAME = 'hatcher'
    HL_STARTED  = TIME('S')
    HL_RAM_OK   = 0
    HL_BOOT_OK  = 0
    HL_LAST_RC  = 0
    HL_CC_SEQ   = 0
    HL_RAM_PATH = 'RAM:hatcher-' || HL_NAME || '.log'
    hHlT = TIME('N')
    HL_STAMP = DATE('S') || '-' || left(hHlT, 2) || substr(hHlT, 4, 2)
    HL_BOOT_PATH = 'EMU68BOOT:Logs/' || HL_NAME || '-' || HL_STAMP || '.log'

    if ~show('l', 'rexxsupport.library') then ,
        call addlib('rexxsupport.library', 0, -30, 0)

    HL_BANNER = '=== ' || HL_NAME || ' log @ ' || DATE('E') || ' ' || TIME('N') || ' ==='

    if open('HL_R', HL_RAM_PATH, 'W') then do
        call writeln 'HL_R', HL_BANNER
        call close  'HL_R'
        HL_RAM_OK = 1
    end

    if exists('EMU68BOOT:') then do
        address command 'MakeDir EMU68BOOT:Logs >NIL:'
        if open('HL_B', HL_BOOT_PATH, 'W') then do
            call writeln 'HL_B', HL_BANNER
            call close  'HL_B'
            HL_BOOT_OK = 1
        end
    end

    if HL_RAM_OK = 0 & HL_BOOT_OK = 0 then return 1
    return 0

HLogPut:
    parse arg HL_PUT_S
    if symbol('HL_RAM_OK') = 'VAR' & HL_RAM_OK = 1 then do
        if open('HL_R', HL_RAM_PATH, 'A') then do
            call writeln 'HL_R', HL_PUT_S
            call close  'HL_R'
        end
    end
    if symbol('HL_BOOT_OK') = 'VAR' & HL_BOOT_OK = 1 then do
        if open('HL_B', HL_BOOT_PATH, 'A') then do
            call writeln 'HL_B', HL_PUT_S
            call close  'HL_B'
        end
    end
    return

HLogSay:
    parse arg HL_SAY_S
    say HL_SAY_S
    call HLogPut TIME('N') || ' ' || HL_SAY_S
    return

HLogWrite:
    parse arg HL_WR_S
    call HLogPut TIME('N') || ' ' || HL_WR_S
    return

HLogSection:
    parse arg HL_SEC_S
    say ''
    say '--- ' || HL_SEC_S || ' ---'
    say ''
    call HLogPut ''
    call HLogPut '--- ' || HL_SEC_S || ' ---'
    call HLogPut ''
    return

HLogContains:
    parse arg HL_HC_HAY, HL_HC_NEED
    return pos(upper(HL_HC_NEED), upper(HL_HC_HAY)) > 0

HLogCaptureCmd:
    parse arg HL_CC_LBL, HL_CC_CMD
    HL_CC_SEQ = HL_CC_SEQ + 1
    HL_CC_TMP = 'T:hatcher-cap-' || HL_NAME || '-' || HL_CC_SEQ || '.txt'
    address command HL_CC_CMD || ' >' || HL_CC_TMP
    HL_LAST_RC = rc
    HL_CC_OUT = ''
    if open('HL_CC', HL_CC_TMP, 'R') then do
        do while ~eof('HL_CC')
            HL_CC_LINE = readln('HL_CC')
            HL_CC_OUT  = HL_CC_OUT || HL_CC_LINE || '0a'x
            call HLogPut '[' || HL_CC_LBL || '] ' || HL_CC_LINE
        end
        call close 'HL_CC'
    end
    address command 'Delete' HL_CC_TMP 'QUIET >NIL:'
    call HLogPut '[' || HL_CC_LBL || '] (rc=' || HL_LAST_RC || ')'
    return HL_CC_OUT

HLogClose:
    if symbol('HL_STARTED') ~= 'VAR' then return
    if HL_STARTED = '' then return
    HL_ELAPSED = TIME('S') - HL_STARTED
    call HLogPut '=== closed (' || HL_ELAPSED || 's elapsed) ==='
    HL_STARTED = ''
    return
