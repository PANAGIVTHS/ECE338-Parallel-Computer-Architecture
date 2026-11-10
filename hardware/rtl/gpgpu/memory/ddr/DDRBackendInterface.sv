interface DDRBackendInterface;

    import gpu_pkg::*;
    import DDRBackendPkg::*;
    import AXI4FullPkg::*;

    logic cand;
    // A candidate as of last cycle, from registers only: what the backend may
    // pick now. It accepts only what is still a candidate (cand).
    logic pick;
    logic accept;
    ring_index_t idx;

    // Read
    logic rd_member; // is_rd_member
    logic rd_take; // rd_ready
    logic rd_sel; // rd_valid

    // Write
    logic wr_member; // is_wr_member
    logic wr_take; // wr_ready
    logic wr_bdone; // wr_valid
    axi_resp_t wr_bresp; // wr_status

    modport requester (
        output cand,
        output pick,
        output rd_member,
        output wr_member,
        output idx,
        output rd_take,
        output wr_take,

        input accept,
        input rd_sel,
        input wr_bdone,
        input wr_bresp
    );

    modport responder (
        input cand,
        input pick,
        input rd_member,
        input wr_member,
        input idx,
        input rd_take,
        input wr_take,

        output accept,
        output rd_sel,
        output wr_bdone,
        output wr_bresp
    );

endinterface
