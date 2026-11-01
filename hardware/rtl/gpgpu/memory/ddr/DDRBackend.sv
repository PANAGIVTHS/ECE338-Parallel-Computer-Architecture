import AXI4FullPkg::*;

module DDRBackend
    import MemorySubsystemPkg::*;
#(
    parameter int unsigned NUM_REQ = 32
) (
    input logic clk,
    input logic rst_n,

    input mem_req_t [NUM_REQ-1:0] req,

    AXI4FullInterface.master axi_if,
    DDRBackendInterface.responder ddr_if [NUM_REQ],

    output logic o_busy,
    output logic o_fatal,
    output mem_fatal_t o_fatal_code
);

    

    initial begin
        assert(XLEN > 0 && AXI_DATA_W >= XLEN && (AXI_DATA_W % XLEN == 0))
            else $fatal(1, "Invalid AXI_DATA_W/XLEN configuration");
    end

endmodule
