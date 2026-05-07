/* HatcherLog.rexx - one-shot log line writer + canonical copy of the HLog*
 * subroutines used by NetworkManager.rexx and WifiConfig.rexx.
 *
 * Usage from shell:
 *   rx S:HatcherLog.rexx <name> <message>
 *
 * This appends <message> to RAM:hatcher-<name>.log AND
 * EMU68BOOT:Logs/<name>-<stamp>.log on the FAT32 boot partition (so the
 * user can pull the SD card and read it from a host PC).
 *
 * For in-script logging, copy the HLog* subroutines below into your own
 * Rexx script. ARexx does NOT preserve labels from INTERPRETed strings,
 * so a "load via interpret" pattern doesn't work - you have to inline.
 */

parse arg hSlug hMsg
if hSlug = '' then do
    say 'usage: rx S:HatcherLog.rexx <name> <message>'
    say '       appends one line to RAM:hatcher-<name>.log and'
    say '       EMU68BOOT:Logs/<name>-<stamp>.log'
    exit 5
end

if ~show('l', 'rexxsupport.library') then
    call addlib('rexxsupport.library', 0, -30, 0)

call HLogOpen hSlug
if hMsg ~= '' then call HLogWrite hMsg
call HLogClose
exit 0

/* -----------------------------------------------------------------------
 * HLog* subroutines - canonical source. Copy-paste into any script that
 * needs persistent, dual-sink logging. Calling convention:
 *   call HLogOpen "scriptname"        ; once at start
 *   call HLogSay "user-visible msg"   ; say + log
 *   call HLogWrite "log-only msg"     ; log without say
 *   call HLogSection "title"          ; visual separator
 *   x = HLogCaptureCmd("label", "cmd"); ; run cmd, log output, return text
 *   if HLogContains(x, "needle") then ...
 *   call HLogClose                    ; once before each exit
 * --------------------------------------------------------------------- */

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
