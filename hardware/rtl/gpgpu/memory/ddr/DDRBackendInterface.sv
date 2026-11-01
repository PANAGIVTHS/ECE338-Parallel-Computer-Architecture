interface DDRBackendInterface;

    import gpu_pkg::*;
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;
    import AXI4FullPkg::*;

    logic cand;
    logic accept;
    ring_index_t idx;

    // Read
    logic is_rd_member;
    logic rd_ready;
    logic rd_valid;
    beat_rdata_t rd_beat;
    axi_resp_t rd_status;
    ring_index_t alloc_rd; // read ring ptr

    // Write
    logic is_wr_member;
    logic wr_ready;
    logic wr_valid;
    axi_resp_t wr_status; 
    ring_index_t alloc_wr; // write ring ptr

    modport requester (
        output cand,
        output is_rd_member,
        output is_wr_member,
        output idx,
        output rd_ready,
        output wr_ready,

        input accept,
        input alloc_rd,
        input alloc_wr,
        input rd_valid,
        input rd_beat,
        input rd_status,
        input wr_valid,
        input wr_status
    );

    modport responder (
        input cand,
        input is_rd_member,
        input is_wr_member,
        input idx,
        input rd_ready,
        input wr_ready,

        output accept,
        output alloc_rd,
        output alloc_wr,
        output rd_valid,
        output rd_beat,
        output rd_status,
        output wr_valid,
        output wr_status
    );

endinterface
