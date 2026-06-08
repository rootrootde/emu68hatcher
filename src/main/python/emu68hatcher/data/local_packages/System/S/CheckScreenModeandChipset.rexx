/* CheckScreenModeandChipset.rexx - apply the WB screenmode that matches the
   detected chipset. mirrors the reference imager: on a chipset mismatch the
   shipped default screenmode is kept; otherwise the prepared RTG screenmode
   (screenmode.prefs.User) is applied and promoted to the active prefs. */

if ~show('l', 'rexxsupport.library') then
    call addlib('rexxsupport.library', 0, -30, 0)
if ~addlib('rexxidentify.library', 0, -30, 0) then do
    say "rexxidentify.library missing - keeping default screenmode."
    exit 0
end

hChipset = ID_Hardware("CHIPSET", NOLOCALE)

/* desired chipset for the prepared screenmode, written at build time */
hWant = ""
if open('c', 'ENV:ScreenModeChipset', 'R') then do
    hWant = upper(strip(readln('c')))
    call close('c')
end

hUserPrefs = "SYS:Prefs/Env-Archive/Sys/screenmode.prefs.User"
hPrefs     = "SYS:Prefs/Env-Archive/Sys/screenmode.prefs"

address command

hRevert = 0
select
    when hChipset = "OCS" then
        if hWant ~= "OCS" & hWant ~= "RTG" then hRevert = 1
    when hChipset = "ECS" then
        if hWant ~= "OCS" & hWant ~= "ECS" & hWant ~= "RTG" then hRevert = 1
    otherwise nop
end

if hRevert = 0 & exists(hUserPrefs) then do
    "Sys:Prefs/ScreenMode FROM" hUserPrefs "USE >NIL:"
    "Delete >NIL:" hPrefs
    "Rename >NIL:" hUserPrefs "TO" hPrefs
end

exit 0
