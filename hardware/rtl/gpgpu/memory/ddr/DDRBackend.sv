import DDRBackendPkg::*;

module DDRBackend #(
    parameter int unsigned NUM_REQ = 32
) (
    
);


    initial begin
        assert(XLEN > 0 && AXI_DATA_W >= XLEN && (AXI_DATA_W % XLEN == 0))
            else $fatal(1, "Invalid AXI_DATA_W/XLEN configuration");
    end


endmodule