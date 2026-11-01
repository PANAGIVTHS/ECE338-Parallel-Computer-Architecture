import AXI4FullPkg::*;

module DDRBackend #(
    parameter int unsigned NUM_REQ = 32
) (
    AXI4FullInterface.master axi_if
);

    initial begin
        assert(XLEN > 0 && AXI_DATA_W >= XLEN && (AXI_DATA_W % XLEN == 0))
            else $fatal(1, "Invalid AXI_DATA_W/XLEN configuration");
    end

endmodule
