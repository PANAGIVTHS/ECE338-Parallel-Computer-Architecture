# Production inputs are resolved from configuration (hardware.sources minus
# hardware.vivado.exclude_sources) by the Python flow and written to the
# -sources-manifest file as `<kind>\t<path>` lines, kind being memory (one),
# source (compile order) or header. This file only reads and validates them;
# it names no sources.
proc read_source_manifest {manifest} {
    if {![file isfile $manifest]} {error "Production source manifest missing: $manifest"}
    set channel [open $manifest r]
    set lines [split [read $channel] "\n"]
    close $channel
    set memory {}
    set sources {}
    set headers {}
    foreach line $lines {
        if {$line eq ""} {continue}
        set tab [string first "\t" $line]
        if {$tab < 1} {error "Invalid production source manifest line: $line"}
        set kind [string range $line 0 [expr {$tab - 1}]]
        set path [file normalize [string range $line [expr {$tab + 1}] end]]
        switch -- $kind {
            memory {lappend memory $path}
            source {lappend sources $path}
            header {lappend headers $path}
            default {error "Unknown production source kind: $kind"}
        }
    }
    if {[llength $memory] != 1} {error "Production source manifest needs exactly one memory entry"}
    return [list [lindex $memory 0] $sources $headers]
}

proc production_source_paths {memory_init rtl_sources header_sources} {
    # Put initialization data before HDL, so filesets end in an HDL source.
    set result {}
    foreach path [list $memory_init {*}$rtl_sources] {
        set path [file normalize $path]
        if {![file isfile $path]} {error "Required production source missing: $path"}
        lappend result $path
    }
    # Everything is staged flat into one src/ directory.
    set names [lmap path $result {file tail $path}]
    if {[llength [lsort -unique $names]] != [llength $names]} {
        error "Production sources must have unique file names: $names"
    }
    foreach header $header_sources {
        if {[file normalize $header] ni $result} {error "Header is not a production source: $header"}
    }
    return $result
}
