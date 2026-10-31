interface DDRBackendInterface;

    import gpu_pkg::*;
    import DDRBackendPkg::*;
    import MemorySubsystemPkg::*;

    logic cand;
    logic accept;
    ring_index_t idx;

    // Read
    logic rd_member;
    logic rd_take;
    logic rd_sel;
    beat_rdata_t rd_beat;
    ddr_resp_t rd_resp;
    ring_index_t alloc_rd; // read ring ptr

    // Write
    logic wr_member;
    logic wr_take;
    logic wr_bdone;
    ddr_resp_t wr_bresp;
    ring_index_t alloc_wr; // write ring ptr

    modport requester (
        output cand,
        output rd_member,
        output wr_member,
        output idx,
        output rd_take,
        output wr_take,

        input accept,
        input alloc_rd,
        input alloc_wr,
        input rd_sel,
        input rd_beat,
        input rd_resp,
        input wr_bdone,
        input wr_bresp
    );

    modport responder (
        input cand,
        input rd_member,
        input wr_member,
        input idx,
        input rd_take,
        input wr_take,

        output accept,
        output alloc_rd,
        output alloc_wr,
        output rd_sel,
        output rd_beat,
        output rd_resp,
        output wr_bdone,
        output wr_bresp
    );

endinterface
