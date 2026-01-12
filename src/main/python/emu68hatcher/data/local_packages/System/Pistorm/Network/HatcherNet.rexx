/* HatcherNet.rexx
 *
 * Emu68 Hatcher network manager. Presents a single RequestChoice dialog
 * and, depending on the user's pick, either brings up Roadshow over
 * wifipi.device (WiFi) or genet.device (Ethernet), or takes everything
 * offline. Runs in a loop so the user can perform multiple actions.
 *
 * Invoked from the Tools menu via: rx sys:Pistorm/Network/HatcherNet.rexx
 */

/* Paths and constants */
hWirelessPrefs = "SYS:Prefs/Env-Archive/sys/wireless.prefs"
hWifipiDevice  = "SYS:Devs/Networks/wifipi.device"
hTuningsFile   = "SYS:Pistorm/HatcherTunings"
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

select
    when hChoice = "1" then call HatcherOnlineWifi
    when hChoice = "2" then call HatcherOnlineGenet
    when hChoice = "3" then call HatcherOffline
    otherwise nop
end

exit 0

/* -----------------------------------------------------------------------
 * WiFi
 * --------------------------------------------------------------------- */
HatcherOnlineWifi:
    say ""
    say "--- Hatcher Network: Going Online (WiFi) ---"
    say ""

    if ~exists("Libs:bsdsocket.library") then do
        say "Roadshow's bsdsocket.library is not installed."
        "C:Wait 4"
        return
    end

    if ~exists(hWirelessPrefs) then do
        say "No wireless.prefs found at:"
        say "  "hWirelessPrefs
        say "Please configure your WiFi settings first."
        "C:Wait 4"
        return
    end

    /* Pre-flight check: SSID must actually be set */
    hSsid = ""
    if open("p", hWirelessPrefs, "R") then do
        do while ~eof("p")
            hLine = upper(strip(readln("p")))
            if pos("SSID=", hLine) > 0 then do
                parse var hLine . 'SSID="'hSsid'"'
                leave
            end
        end
        call close("p")
    end
    if hSsid = "" then do
        say "wireless.prefs does not contain an SSID."
        "C:Wait 4"
        return
    end

    say "Resetting network stack..."
    "C:Netshutdown >NIL:"

    call HatcherKillWm

    say "Starting WirelessManager..."
    "Run >NIL: C:WirelessManager DEVICE="hWifipiDevice ,
        "CONFIG="hWirelessPrefs "VERBOSE >"hWmLog

    say "Waiting for WiFi link..."
    "C:WaitUntilConnected DEVICE="hWifipiDevice "Unit=0 DELAY=100"
    if rc ~= 0 then do
        say "Could not associate with the configured WiFi network."
        call HatcherKillWm
        "C:Wait 4"
        return
    end
    say "WiFi link established."

    call HatcherApplyTunings "WIFIPI"
    call HatcherAttach "wifipi"
    call HatcherSyncTime

    say ""
    say "Connected via WiFi."
    say ""
    "ShowNetStatus"
    "C:Wait 3"
    return

/* -----------------------------------------------------------------------
 * Ethernet
 * --------------------------------------------------------------------- */
HatcherOnlineGenet:
    say ""
    say "--- Hatcher Network: Going Online (Ethernet) ---"
    say ""

    if ~exists("Libs:bsdsocket.library") then do
        say "Roadshow's bsdsocket.library is not installed."
        "C:Wait 4"
        return
    end

    say "Resetting network stack..."
    "C:Netshutdown >NIL:"

    call HatcherKillWm

    call HatcherApplyTunings "GENET"
    call HatcherAttach "genet"
    call HatcherSyncTime

    say ""
    say "Connected via Ethernet."
    say ""
    "ShowNetStatus"
    "C:Wait 3"
    return

/* -----------------------------------------------------------------------
 * Offline
 * --------------------------------------------------------------------- */
HatcherOffline:
    say ""
    say "--- Hatcher Network: Going Offline ---"
    say ""
    call HatcherKillWm
    say "Shutting down TCP/IP stack..."
    "C:Netshutdown >NIL:"
    say "Disconnected."
    "C:Wait 2"
    return

/* -----------------------------------------------------------------------
 * Helpers
 * --------------------------------------------------------------------- */

HatcherAttach:
    parse arg hDev
    say "Adding "hDev" network interface..."
    "AddNetInterface" hDev "TIMEOUT=50 >T:hatcher-addif.txt"
    "Search T:hatcher-addif.txt ""Could not add"" >NIL:"
    if rc = 0 then do
        say "Error: could not add network interface!"
        "Delete T:hatcher-addif.txt QUIET >NIL:"
        if hDev = "wifipi" then call HatcherKillWm
        "C:Wait 4"
        exit 10
    end
    "Delete T:hatcher-addif.txt QUIET >NIL:"
    return

HatcherKillWm:
    "Status COM=C:WirelessManager >T:hatcher-wm-pid"
    if ~exists("T:hatcher-wm-pid") then return
    hWmPid = ""
    if open("q", "T:hatcher-wm-pid", "R") then do
        if ~eof("q") then hWmPid = strip(readln("q"))
        call close("q")
    end
    "Delete T:hatcher-wm-pid QUIET >NIL:"
    if hWmPid ~= "" & datatype(hWmPid, "W") then do
        say "Stopping WirelessManager (pid "hWmPid")..."
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

HatcherSyncTime:
    say "Syncing system time..."
    "C:sntp pool.ntp.org >"hSntpLog
    "Search "hSntpLog" ""Unknown host"" >NIL:"
    if rc = 0 then do
        say "  (Time sync skipped: could not reach pool.ntp.org)"
        "Delete "hSntpLog" QUIET >NIL:"
        return
    end
    "C:SetDST NOASK NOREQ QUIET >NIL:"
    "C:sntp pool.ntp.org >NIL:"
    "Delete "hSntpLog" QUIET >NIL:"
    return
