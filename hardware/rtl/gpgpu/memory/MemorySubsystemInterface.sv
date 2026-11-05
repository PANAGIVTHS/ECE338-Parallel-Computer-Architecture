interface MemorySubsystemInterface;

    import MemorySubsystemPkg::*;

    // Requester handshake
    logic req_valid;
    logic req_ready;
    mem_req_t req;

    // Response handshake
    logic rsp_valid;
    logic rsp_ready;
    mem_rsp_t rsp;

    modport requester (
        output req_valid,
        output req,
        output rsp_ready,

        input req_ready,
        input rsp_valid,
        input rsp
    );

    modport responder (
        input req_valid,
        input req,
        input rsp_ready,

        output req_ready,
        output rsp_valid,
        output rsp
    );

endinterface
