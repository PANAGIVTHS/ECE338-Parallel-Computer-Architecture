interface BRAMBackendInterface;

    import gpu_pkg::*;

    // Requester handshake
    logic cand;
    logic take;

    // Response handshake
    logic accept;
    word_t rdata;

    modport requester (
        output cand,
        output take,

        input accept,
        input rdata
    );

    modport responder (
        input cand,
        input take,

        output accept,
        output rdata
    );

endinterface
