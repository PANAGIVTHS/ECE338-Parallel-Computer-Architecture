interface BRAMBackendInterface;

    import gpu_pkg::*;

    // Requester handshake
    logic cand;
    // A candidate as of last cycle, from registers only: what the backend may
    // pick now. It accepts only what is still a candidate (cand).
    logic pick;
    logic take;

    // Response handshake
    logic accept;
    word_t rdata;

    modport requester (
        output cand,
        output pick,
        output take,

        input accept,
        input rdata
    );

    modport responder (
        input cand,
        input pick,
        input take,

        output accept,
        output rdata
    );

endinterface
