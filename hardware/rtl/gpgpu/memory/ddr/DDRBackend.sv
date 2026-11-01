module DDRBackend 
    import gpu_pkg::*;
    import AXI4FullPkg::*;
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

    // word_t seed_addr, seed_write;
    // assign ddr_accept = <ring has free slot>;
    // assign ddr_if[0].accept = ddr_accept & (ddr_if[0].cand & (req[0].addr[31:7] == seed_addr) & (req[0].write == seed_write));

    // always_ff @(posedge clk) begin
    //     if (~rst_n) begin
    //         ddr_if.alloc_rd
    //     end else if () begin
            
    //     end
    // end

endmodule
