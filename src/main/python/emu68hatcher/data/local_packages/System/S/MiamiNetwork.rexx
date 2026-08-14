/* MiamiDX network control */

if ~show('l', 'rexxsupport.library') then
    call addlib('rexxsupport.library', 0, -30, 0)
if ~show('l', 'rexxreqtools.library') then do
    if ~addlib('rexxreqtools.library', 0, -30, 0) then do
        say "rexxreqtools.library is missing."
        exit 20
    end
end

hMiamiDir      = "SYS:Programs/Miami"
hMiamiExe      = hMiamiDir || "/MiamiDX"
hWirelessPrefs = "SYS:Prefs/Env-Archive/Sys/wireless.prefs"
hWifipiDevice  = "SYS:Devs/Networks/wifipi.device"
hGenetDevice   = "SYS:Devs/Networks/genet.device"
hChoiceFile    = "T:hatcher-choice"
hWmLog         = "RAM:hatcher-wm.log"

address command
parse arg hCmd hIface .
hCmd = upper(strip(hCmd))

if hCmd = "ONLINE" then do
    call MiamiOnline upper(strip(hIface))
    if result = 0 then do
        "C:Wait 3"
        exit 10
    end
    exit 0
end
if hCmd = "OFFLINE" then do
    call MiamiOffline
    exit 0
end
if hCmd = "CONFIG" then do
    call MiamiConfig
    exit 0
end

do forever
    "RequestChoice >"hChoiceFile ,
        "TITLE ""Hatcher Network""" ,
        "BODY ""Choose an action:""" ,
        "GADGETS ""WiFi|Ethernet|Offline|MiamiDX|Exit"""
    hChoice = ReadChoice()
    select
        when hChoice = "1" then call MiamiOnline "WIFIPI"
        when hChoice = "2" then call MiamiOnline "GENET"
        when hChoice = "3" then call MiamiOffline
        when hChoice = "4" then call MiamiConfig
        otherwise leave
    end
end
exit 0

ReadChoice:
    hResult = ""
    if open("c", hChoiceFile, "R") then do
        if ~eof("c") then hResult = strip(readln("c"))
        call close("c")
    end
    "Delete " || hChoiceFile || " QUIET >NIL:"
    return hResult

MiamiReady:
    if ~exists(hMiamiExe) then do
        say "MiamiDX is not installed."
        return 0
    end
    if exists("LIBS:bsdsocket.library") then do
        say "A disk-based bsdsocket.library conflicts with MiamiDX."
        return 0
    end
    "Assign Miami: " || hMiamiDir || " >NIL:"
    return 1

MiamiOnline:
    parse arg hDevice
    if ~MiamiReady() then return 0

    select
        when hDevice = "GENET" then do
            hDevicePath = hGenetDevice
            hProfile = "Miami:Genet.default"
        end
        when hDevice = "WIFIPI" then do
            hDevicePath = hWifipiDevice
            hProfile = "Miami:Wifipi.default"
        end
        otherwise do
            say "Unknown interface: " || hDevice
            return 0
        end
    end

    if ~exists(hDevicePath) then do
        say "Network driver missing: " || hDevicePath
        return 0
    end
    if ~exists(hProfile) then do
        say "MiamiDX profile missing: " || hProfile
        return 0
    end

    call MiamiOffline
    if hDevice = "WIFIPI" then do
        if ~exists(hWirelessPrefs) then do
            "RequestChoice >"hChoiceFile ,
                "TITLE ""Hatcher Network""" ,
                "BODY ""No WiFi config.*nOpen WiFi credentials?""" ,
                "GADGETS ""Yes|No"""
            if ReadChoice() ~= "1" then return -1
            call WifiCredsScreen
            hCredResult = result
            if hCredResult ~= 1 then return hCredResult
        end
        call KillWirelessManager
        "Run >NIL: C:WirelessManager DEVICE="hWifipiDevice ,
            "CONFIG="hWirelessPrefs "VERBOSE >"hWmLog
        "C:WaitUntilConnected DEVICE=" || hWifipiDevice || " Unit=0 DELAY=100"
        if rc ~= 0 then do
            say "Could not connect to the WiFi network."
            call KillWirelessManager
            return 0
        end
    end

    "Run >NIL: Miami:MiamiDX " || hProfile
    do hWait = 1 to 30 while ~show('p', 'MIAMI.1')
        "C:Wait 1"
    end
    if ~show('p', 'MIAMI.1') then do
        say "MiamiDX did not open its ARexx port."
        if hDevice = "WIFIPI" then call KillWirelessManager
        return 0
    end

    hOnline = 0
    address 'MIAMI.1'
    do hTry = 1 to 3
        ONLINE
        ISONLINE
        if rc ~= 0 then do
            hOnline = 1
            leave
        end
        address command
        "C:Wait 1"
        address 'MIAMI.1'
    end
    if hOnline = 1 then HIDE
    address command

    if hOnline = 0 then do
        say "MiamiDX could not bring the interface online."
        call MiamiOffline
        return 0
    end
    say "Connected via " || hDevice || "."
    return 1

MiamiOffline:
    if show('p', 'MIAMI.1') then do
        address 'MIAMI.1'
        OFFLINE
        QUIT
        address command
        "C:Wait 2"
    end
    call KillWirelessManager
    return 1

MiamiConfig:
    if ~MiamiReady() then return 0
    if show('p', 'MIAMI.1') then do
        address 'MIAMI.1'
        SHOW
        address command
    end
    else
        "Run >NIL: Miami:MiamiDX Miami:Genet.default"
    return 1

WifiCredsScreen:
    hSsid = rtgetstring("", "Enter WiFi SSID:", "WiFi credentials")
    if rtresult = 0 then return -1
    hSsid = strip(hSsid)
    if hSsid = "" then return -1

    hPwdPrompt = "Enter WiFi password" || '0a'x || "(empty = open network):"
    hPsk = rtgetstring("", hPwdPrompt, "WiFi credentials")
    if rtresult = 0 then return -1
    hPsk = strip(hPsk)

    if ~open("w", hWirelessPrefs, "W") then do
        hErrMsg = "Could not write:" || '0a'x || hWirelessPrefs
        call rtezrequest(hErrMsg, "OK", "WiFi credentials")
        return 0
    end
    call writeln("w", "network={")
    call writeln("w", '   ssid="' || hSsid || '"')
    if hPsk = "" then
        call writeln("w", "   key_mgmt=NONE")
    else
        call writeln("w", '   psk="' || hPsk || '"')
    call writeln("w", "   scan_ssid=1")
    call writeln("w", "}")
    call close("w")

    hSavedMsg = "WiFi credentials saved." || '0a'x || '0a'x || "SSID: " || hSsid
    call rtezrequest(hSavedMsg, "OK", "WiFi credentials")
    return 1

KillWirelessManager:
    "Status COM=C:WirelessManager >" || hChoiceFile
    hWmPid = ""
    if open("p", hChoiceFile, "R") then do
        if ~eof("p") then hWmPid = strip(readln("p"))
        call close("p")
    end
    "Delete " || hChoiceFile || " QUIET >NIL:"
    if hWmPid ~= "" & datatype(hWmPid, "W") then do
        "Break " || hWmPid
        "C:Wait 2"
    end
    return
