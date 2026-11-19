#!/usr/bin/env tclsh
# Batch check-in of a directory of artifacts through the devtrack CLI, the way EDA flows
# drive tools from Tcl.
#
#   tclsh scripts/devtrack_batch.tcl <dir> "<commit message>" ?--strict?
#
# Must be run from inside a DevTrack project. Exit code 1 if any file failed validation.

proc usage {} {
    puts stderr "usage: tclsh devtrack_batch.tcl <dir> \"<message>\" ?--strict?"
    exit 2
}

if {[llength $argv] < 2} { usage }
set dir     [lindex $argv 0]
set message [lindex $argv 1]
set strict  [expr {[lsearch -exact $argv --strict] >= 0}]

if {![file isdirectory $dir]} {
    puts stderr "not a directory: $dir"
    exit 2
}

# Prefer an installed `devtrack`; fall back to running the module.
if {[auto_execok devtrack] ne ""} {
    set cli [list devtrack]
} else {
    set cli [list python3 -m devtrack.cli]
}

# Recursively collect files, skipping hidden directories such as .devtrack and .git
proc collect {dir} {
    set out {}
    foreach f [lsort [glob -nocomplain -directory $dir -types f *]] { lappend out $f }
    foreach d [lsort [glob -nocomplain -directory $dir -types d *]] {
        if {[string index [file tail $d] 0] ne "."} {
            set out [concat $out [collect $d]]
        }
    }
    return $out
}

array set count {stored 0 unchanged 0 warned 0 rejected 0}
foreach f [collect $dir] {
    set cmd [concat $cli [list add $f -m $message]]
    if {$strict} { lappend cmd --strict }
    # catch: devtrack exits non-zero on validation failure, which Tcl treats as an error
    set rc [catch {exec {*}$cmd 2>@1} output]
    regsub {\n?child process exited abnormally$} $output "" output  ;# Tcl's own note
    puts $output
    if {[string match "*unchanged*" $output]}     { incr count(unchanged)
    } elseif {[string match "*rejected*" $output]} { incr count(rejected)
    } elseif {[string match "WARN*" $output]}      { incr count(warned)
    } elseif {$rc == 0}                             { incr count(stored) }
}

puts [format "\nsummary: %d stored, %d unchanged, %d with warnings, %d rejected" \
          $count(stored) $count(unchanged) $count(warned) $count(rejected)]
exit [expr {($count(warned) + $count(rejected)) > 0 ? 1 : 0}]
