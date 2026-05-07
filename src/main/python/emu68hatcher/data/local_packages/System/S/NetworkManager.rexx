/* NetworkManager.rexx - Emu68 Hatcher network manager
 *
 * Presents a single RequestChoice dialog and, depending on the user's
 * pick, either brings up Roadshow over wifipi.device (WiFi) or
 * genet.device (Ethernet), or takes everything offline. Runs in a loop
 * so the user can perform multiple actions.
 *
 * Invoked by 'rx s:NetworkManager.rexx' - from the Tools menu or from
 * SYS:Utilities/Network Manager's double-click launcher.
 */

/* rexxsupport.library provides exists() - without it the function
 * falls through to host dispatch and returns garbage.
 */
if ~show('l', 'rexxsupport.library') then
    call addlib('rexxsupport.library', 0, -30, 0)

call HLogOpen "NetworkManager"

/* Paths and constants */
hWirelessPrefs = "SYS:Prefs/Env-Archive/sys/wireless.prefs"
hWifipiDevice  = "SYS:Devs/Networks/wifipi.device"
hGenetDevice   = "SYS:Devs/Networks/genet.device"
hTuningsFile   = "S:RoadshowSettings"
hWmLog         = "RAM:hatcher-wm.log"
hSntpLog       = "RAM:hatcher-sntp.log"
hChoiceFile    = "T:hatcher-choice"

address command

"RequestChoice >"hChoiceFile ,
    "TITLE ""Hatcher Network Manager""" ,
    "BODY ""Choose a network action:""" ,
    "GADGETS ""WiFi|Ethernet|Offline|Cancel"""

hChoice = ""
if open("c", hChoiceFile, "R") then do
    if ~eof("c") then hChoice = strip(readln("c"))
    call close("c")
end
"Delete" hChoiceFile "QUIET >NIL:"

call HLogWrite "user picked choice="hChoice

select
    when hChoice = "1" then call HatcherOnlineWifi
    when hChoice = "2" then call HatcherOnlineGenet
    when hChoice = "3" then call HatcherOffline
    otherwise nop
end

call HLogSay ""
call HLogSay "Click the close gadget to dismiss this window."
call HLogClose
exit 0

/* -----------------------------------------------------------------------
 * WiFi
 * --------------------------------------------------------------------- */
HatcherOnlineWifi:
    call HLogSection "Hatcher Network: Going Online (WiFi)"

    if ~exists("Libs:bsdsocket.library") then do
        call HLogSay "Roadshow's bsdsocket.library is not installed."
        return
    end

    if ~exists(hWifipiDevice) then do
        call HLogSay "Warning: " || hWifipiDevice || " is missing - WiFi driver not installed."
        return
    end
    call HLogCaptureCmd "wifipi-version", "Version FILE " || hWifipiDevice || " FULL"
    call HLogCaptureCmd "wifipi-config",  "Type SYS:Devs/NetInterfaces/wifipi"

    /* Pre-flight: wireless.prefs must exist and have an SSID. If not,
     * ask the user whether to launch Wifi Config, then re-read. */
    call ReadSsid
    if hSsid = "" then do
        call HLogSay "No SSID configured."
        "RequestChoice >"hChoiceFile ,
            "TITLE ""Hatcher Network Manager""" ,
            "BODY ""No WiFi configuration found.*nLaunch Wifi Config now?""" ,
            "GADGETS ""Yes|No"""
        hWantCfg = ""
        if open("c", hChoiceFile, "R") then do
            if ~eof("c") then hWantCfg = strip(readln("c"))
            call close("c")
        end
        "Delete" hChoiceFile "QUIET >NIL:"
        if hWantCfg ~= "1" then return
        address command 'SYS:Rexxc/rx s:WifiConfig.rexx'
        call ReadSsid
        if hSsid = "" then do
            call HLogSay "WiFi configuration cancelled or incomplete."
            return
        end
    end
    call HLogWrite "configured SSID=" || hSsid

    call HLogSay "Resetting network stack..."
    call HLogCaptureCmd "netshutdown", "C:Netshutdown"

    call HatcherKillWm

    call HLogSay "Starting WirelessManager..."
    "Run >NIL: C:WirelessManager DEVICE="hWifipiDevice ,
        "CONFIG="hWirelessPrefs "VERBOSE >"hWmLog

    call HLogSay "Waiting for WiFi link..."
    "C:WaitUntilConnected DEVICE="hWifipiDevice "Unit=0 DELAY=100"
    hWaitRc = rc

    if hWaitRc ~= 0 then do
        call HLogSay "Could not associate with the configured WiFi network."
        /* kill WirelessManager first - it holds an exclusive lock on hWmLog */
        call HatcherKillWm
        if exists(hWmLog) then ,
            call HLogCaptureCmd "wirelessmanager", "Type " || hWmLog
        call HLogSay "  see log file: " || HL_BOOT_PATH
        return
    end
    call HLogSay "WiFi link established."

    call HatcherApplyTunings "WIFIPI"
    call HatcherAttach "wifipi"
    call HatcherSyncTime

    call HLogSay ""
    call HLogSay "Connected via WiFi."
    call HLogCaptureCmd "shownetstatus", "ShowNetStatus"
    return

/* -----------------------------------------------------------------------
 * Ethernet
 * --------------------------------------------------------------------- */
HatcherOnlineGenet:
    call HLogSection "Hatcher Network: Going Online (Ethernet)"

    if ~exists("Libs:bsdsocket.library") then do
        call HLogSay "Roadshow's bsdsocket.library is not installed."
        return
    end

    if ~exists(hGenetDevice) then do
        call HLogSay hGenetDevice || " is missing - Ethernet driver not installed."
        call HLogSay "  see log file: " || HL_BOOT_PATH
        return
    end
    call HLogCaptureCmd "genet-version", "Version FILE " || hGenetDevice || " FULL"
    call HLogCaptureCmd "genet-config",  "Type SYS:Devs/NetInterfaces/genet"

    call HLogSay "Resetting network stack..."
    call HLogCaptureCmd "netshutdown", "C:Netshutdown"

    call HatcherKillWm

    call HatcherApplyTunings "GENET"
    call HatcherAttach "genet"
    call HatcherSyncTime

    call HLogSay ""
    call HLogSay "Connected via Ethernet."
    call HLogCaptureCmd "shownetstatus", "ShowNetStatus"
    return

/* -----------------------------------------------------------------------
 * Offline
 * --------------------------------------------------------------------- */
HatcherOffline:
    call HLogSection "Hatcher Network: Going Offline"
    call HatcherKillWm
    call HLogSay "Shutting down TCP/IP stack..."
    call HLogCaptureCmd "netshutdown", "C:Netshutdown"
    call HLogSay "Disconnected."
    return

/* -----------------------------------------------------------------------
 * Helpers
 * --------------------------------------------------------------------- */

HatcherAttach:
    parse arg hDev
    call HLogSay "Adding " || hDev || " network interface..."
    hOut = HLogCaptureCmd("addnetif:" || hDev, "AddNetInterface " || hDev || " TIMEOUT=50")
    if HLogContains(hOut, "Could not add") | HL_LAST_RC ~= 0 then do
        call HLogSay "Error: could not add network interface (rc=" || HL_LAST_RC || ")."
        call HLogSay "  see log file: " || HL_BOOT_PATH
        if hDev = "wifipi" then call HatcherKillWm
        call HLogClose
        exit 10
    end
    return

HatcherKillWm:
    hStatusOut = HLogCaptureCmd("wm-status", "Status COM=C:WirelessManager")
    parse var hStatusOut hWmPid '0a'x .
    hWmPid = strip(hWmPid)
    if hWmPid ~= "" & datatype(hWmPid, "W") then do
        call HLogSay "Stopping WirelessManager (pid " || hWmPid || ")..."
        "Break "hWmPid
        "C:Wait 2"
    end
    return

HatcherApplyTunings:
    parse arg hTarget
    hTarget = upper(hTarget)
    if ~open("t", hTuningsFile, "R") then return
    do while ~eof("t")
        hRow = strip(readln("t"))
        if hRow = "" then iterate
        if left(hRow, 1) = ";" then iterate
        parse var hRow hDev ";" hKey ";" hVal
        if upper(strip(hDev)) ~= hTarget then iterate
        hKey = upper(strip(hKey))
        hVal = strip(hVal)
        select
            when hKey = "TCPRECEIVE" then "roadshowcontrol tcp.recvspace="hVal" >NIL:"
            when hKey = "UDPRECEIVE" then "roadshowcontrol udp.recvspace="hVal" >NIL:"
            when hKey = "TCPSEND"    then "roadshowcontrol tcp.sendspace="hVal" >NIL:"
            when hKey = "UDPSEND"    then "roadshowcontrol udp.sendspace="hVal" >NIL:"
            otherwise nop
        end
    end
    call close("t")
    return

ReadSsid:
    hSsid = ""
    if ~exists(hWirelessPrefs) then return
    if ~open("p", hWirelessPrefs, "R") then return
    do while ~eof("p")
        hLine = upper(strip(readln("p")))
        if pos("SSID=", hLine) > 0 then do
            parse var hLine . 'SSID="'hSsid'"'
            leave
        end
    end
    call close("p")
    return

HatcherSyncTime:
    call HLogSay "Syncing system time..."
    hSntpOut = HLogCaptureCmd("sntp-probe", "C:sntp pool.ntp.org")
    if HLogContains(hSntpOut, "Unknown host") | HL_LAST_RC ~= 0 then do
        call HLogSay "  (time sync skipped: could not reach pool.ntp.org)"
        return
    end
    call HLogCaptureCmd "setdst",    "C:SetDST NOASK NOREQ QUIET"
    call HLogCaptureCmd "sntp-sync", "C:sntp pool.ntp.org"
    return

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
