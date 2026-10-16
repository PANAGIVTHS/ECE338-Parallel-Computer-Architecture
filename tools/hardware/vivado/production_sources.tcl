# Explicit dependency-ordered production manifest. No recursive source discovery.
# constants is an include; MemoryInterface must precede modules using modports.
set PRODUCTION_RTL_SOURCES {
    constants.svh
    memory/MemoryInterface.sv
    sp/ALU.sv
    sp/Decoder.sv
    sp/ForwardingUnit.sv
    sp/GUCounter.sv
    sp/HazardUnit.sv
    sp/Regfile.sv
    sp/StreamingProcessor.sv
    memory/MemoryCrossbarNx2.sv
    memory/MemoryDualPort.sv
    memory/MemorySinglePort.sv
    control/CSRBank.sv
    control/ExecutionController.sv
    control/MMIOController.sv
    StreamingMultiprocessor.sv
    GPGPU.sv
    interfaces/AXI4LiteSlave.sv
    interfaces/AXI4LiteTop.sv
}
proc production_source_paths {rtl_dir script_dir} {
    global PRODUCTION_RTL_SOURCES
    set result {}
    foreach relative $PRODUCTION_RTL_SOURCES {
        set path [file normalize [file join $rtl_dir $relative]]
        if {![file isfile $path]} {error "Required production source missing: $path"}
        lappend result $path
    }
    # Tracked zero initialization image: both memories are 2048 32-bit words.
    # Keep the basename empty.mem: RTL's default $readmemh names this file.
    set memory [file join $script_dir ip empty.mem]
    if {![file isfile $memory]} {error "Required memory initialization missing: $memory"}
    lappend result [file normalize $memory]
    return $result
}
