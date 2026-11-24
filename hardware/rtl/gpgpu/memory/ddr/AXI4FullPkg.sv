package AXI4FullPkg;

    import gpu_pkg::*;

    // AXI burst geometry: a window is the longest HP burst, so a burst never
    // crosses a window and every DDR region must be window-aligned.
    localparam int unsigned AXI_ADDR_W = 32;
    (* host *) localparam int unsigned AXI_DATA_W = 64;
    localparam int unsigned AXI_STRB_W = AXI_DATA_W / 8;
    localparam int unsigned AXI_ID_W   = 1;
    localparam int unsigned AXI_MAX_BEATS_PER_BURST = 16;
    localparam int unsigned AXI_MAX_OUTSTANDING_READS = 16;
    localparam int unsigned AXI_MAX_OUTSTANDING_WRITES = 8;

    typedef logic [AXI_ADDR_W-1:0] axi_addr_t;
    typedef logic [AXI_DATA_W-1:0] axi_data_t;
    typedef logic [AXI_STRB_W-1:0] axi_strb_t;
    typedef logic [AXI_ID_W-1:0] axi_id_t;
    typedef logic [7:0] axi_len_t;

    // The one transaction ID: responses return in issue order.
    localparam axi_id_t AXI_ID = '0;
    // AxCACHE: bufferable, modifiable
    localparam logic [3:0] AXI_CACHE = 4'b0011;

    typedef enum logic [1:0] {
        AXI_BURST_FIXED = 2'b00,
        AXI_BURST_INCR  = 2'b01,
        AXI_BURST_WRAP  = 2'b10
    } axi_burst_t;

    typedef enum logic [1:0] {
        AXI_RESP_OKAY   = 2'b00,
        AXI_RESP_EXOKAY = 2'b01,
        AXI_RESP_SLVERR = 2'b10,
        AXI_RESP_DECERR = 2'b11
    } axi_resp_t;

    // AW and AR carry the same fields
    typedef struct packed {
        axi_id_t    id;
        axi_addr_t  addr;
        axi_len_t   len;    // beats - 1
        logic [2:0] size;   // log2(bytes per beat)
        axi_burst_t burst;
        logic       lock;
        logic [3:0] cache;
        logic [2:0] prot;
        logic [3:0] qos;
    } axi_ax_t;

    typedef axi_ax_t axi_aw_t;
    typedef axi_ax_t axi_ar_t;

    typedef struct packed {
        axi_data_t data;
        axi_strb_t strb;
        logic      last;
    } axi_w_t;

    typedef struct packed {
        axi_id_t   id;
        axi_resp_t resp;
    } axi_b_t;

    typedef struct packed {
        axi_id_t   id;
        axi_data_t data;
        axi_resp_t resp;
        logic      last;
    } axi_r_t;

    typedef struct packed {
        logic       valid;
        axi_addr_t  addr;
        axi_len_t   len;
    } cmd_t;
    
endpackage
