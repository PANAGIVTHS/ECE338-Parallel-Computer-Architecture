`timescale 1 ns / 1 ps

	module gpgpu_axi #
	(
		// Users to add parameters here
        parameter integer SP_PER_SM = 32,
        // Set by IP packaging (CLOCK_KHZ by the block design) from the
        // configuration; the CSR bank rejects the 0 defaults of the first two.
        parameter integer INTERFACE_VERSION = 0,
        parameter integer CLOCK_KHZ = 0,
        parameter integer BUILD_HASH = 0,
        parameter integer BUILD_DIRTY = 0,
        parameter integer DDR_ENABLE = 0,
		// User parameters ends
		// Do not modify the parameters beyond this line


		// Parameters of Axi Slave Bus Interface S00_AXI
		parameter integer C_S00_AXI_DATA_WIDTH	= 32,
		parameter integer C_S00_AXI_ADDR_WIDTH	= 32,

		// Parameters of Axi Master Bus Interface M00_AXI (DDR). They must
		// equal AXI_ID_W, AXI_ADDR_W and AXI_DATA_W of the RTL's AXI package.
		parameter integer C_M00_AXI_ID_WIDTH	= 1,
		parameter integer C_M00_AXI_ADDR_WIDTH	= 32,
		parameter integer C_M00_AXI_DATA_WIDTH	= 64
	)
	(
		// Users to add ports here
        output wire irq,
        output wire o_core_idle,
        output wire o_core_running,
		// User ports ends
		// Do not modify the ports beyond this line


		// Clock and active-low reset of both bus interfaces and the GPGPU
		input wire  aclk,
		input wire  aresetn,

		// Ports of Axi Slave Bus Interface S00_AXI
		input wire [C_S00_AXI_ADDR_WIDTH-1 : 0] s00_axi_awaddr,
		input wire [2 : 0] s00_axi_awprot,
		input wire  s00_axi_awvalid,
		output wire  s00_axi_awready,
		input wire [C_S00_AXI_DATA_WIDTH-1 : 0] s00_axi_wdata,
		input wire [(C_S00_AXI_DATA_WIDTH/8)-1 : 0] s00_axi_wstrb,
		input wire  s00_axi_wvalid,
		output wire  s00_axi_wready,
		output wire [1 : 0] s00_axi_bresp,
		output wire  s00_axi_bvalid,
		input wire  s00_axi_bready,
		input wire [C_S00_AXI_ADDR_WIDTH-1 : 0] s00_axi_araddr,
		input wire [2 : 0] s00_axi_arprot,
		input wire  s00_axi_arvalid,
		output wire  s00_axi_arready,
		output wire [C_S00_AXI_DATA_WIDTH-1 : 0] s00_axi_rdata,
		output wire [1 : 0] s00_axi_rresp,
		output wire  s00_axi_rvalid,
		input wire  s00_axi_rready,

		// Ports of Axi Master Bus Interface M00_AXI (DDR, clocked by aclk)
		output wire [C_M00_AXI_ID_WIDTH-1 : 0] m00_axi_awid,
		output wire [C_M00_AXI_ADDR_WIDTH-1 : 0] m00_axi_awaddr,
		output wire [7 : 0] m00_axi_awlen,
		output wire [2 : 0] m00_axi_awsize,
		output wire [1 : 0] m00_axi_awburst,
		output wire  m00_axi_awlock,
		output wire [3 : 0] m00_axi_awcache,
		output wire [2 : 0] m00_axi_awprot,
		output wire [3 : 0] m00_axi_awqos,
		output wire  m00_axi_awvalid,
		input wire  m00_axi_awready,
		output wire [C_M00_AXI_DATA_WIDTH-1 : 0] m00_axi_wdata,
		output wire [(C_M00_AXI_DATA_WIDTH/8)-1 : 0] m00_axi_wstrb,
		output wire  m00_axi_wlast,
		output wire  m00_axi_wvalid,
		input wire  m00_axi_wready,
		input wire [C_M00_AXI_ID_WIDTH-1 : 0] m00_axi_bid,
		input wire [1 : 0] m00_axi_bresp,
		input wire  m00_axi_bvalid,
		output wire  m00_axi_bready,
		output wire [C_M00_AXI_ID_WIDTH-1 : 0] m00_axi_arid,
		output wire [C_M00_AXI_ADDR_WIDTH-1 : 0] m00_axi_araddr,
		output wire [7 : 0] m00_axi_arlen,
		output wire [2 : 0] m00_axi_arsize,
		output wire [1 : 0] m00_axi_arburst,
		output wire  m00_axi_arlock,
		output wire [3 : 0] m00_axi_arcache,
		output wire [2 : 0] m00_axi_arprot,
		output wire [3 : 0] m00_axi_arqos,
		output wire  m00_axi_arvalid,
		input wire  m00_axi_arready,
		input wire [C_M00_AXI_ID_WIDTH-1 : 0] m00_axi_rid,
		input wire [C_M00_AXI_DATA_WIDTH-1 : 0] m00_axi_rdata,
		input wire [1 : 0] m00_axi_rresp,
		input wire  m00_axi_rlast,
		input wire  m00_axi_rvalid,
		output wire  m00_axi_rready
	);
	
	// ============================================================================
    // GPU Request Interface
    // ============================================================================
    
    wire        req_valid;
    wire        req_ready;
    wire        req_write;
    wire [31:0] req_addr;
    wire [31:0] req_wdata;
    wire [3:0]  req_wstrb;
    
    // ============================================================================
    // GPU Response Interface
    // ============================================================================
    
    wire        rsp_valid;
    wire        rsp_ready;
    wire [31:0] rsp_rdata;
    wire [2:0]  rsp_status;
	
// Instantiation of Axi Bus Interface S00_AXI
	gpgpu_axi_slave_lite_v1_0_S00_AXI # ( 
		.C_S_AXI_DATA_WIDTH(C_S00_AXI_DATA_WIDTH),
		.C_S_AXI_ADDR_WIDTH(C_S00_AXI_ADDR_WIDTH)
	) gpgpu_axi_slave_lite_v1_0_S00_AXI_inst (
		.S_AXI_ACLK(aclk),
		.S_AXI_ARESETN(aresetn),
		.S_AXI_AWADDR(s00_axi_awaddr),
		.S_AXI_AWPROT(s00_axi_awprot),
		.S_AXI_AWVALID(s00_axi_awvalid),
		.S_AXI_AWREADY(s00_axi_awready),
		.S_AXI_WDATA(s00_axi_wdata),
		.S_AXI_WSTRB(s00_axi_wstrb),
		.S_AXI_WVALID(s00_axi_wvalid),
		.S_AXI_WREADY(s00_axi_wready),
		.S_AXI_BRESP(s00_axi_bresp),
		.S_AXI_BVALID(s00_axi_bvalid),
		.S_AXI_BREADY(s00_axi_bready),
		.S_AXI_ARADDR(s00_axi_araddr),
		.S_AXI_ARPROT(s00_axi_arprot),
		.S_AXI_ARVALID(s00_axi_arvalid),
		.S_AXI_ARREADY(s00_axi_arready),
		.S_AXI_RDATA(s00_axi_rdata),
		.S_AXI_RRESP(s00_axi_rresp),
		.S_AXI_RVALID(s00_axi_rvalid),
		.S_AXI_RREADY(s00_axi_rready),
        // GPU request
        .o_req_valid(req_valid),
        .i_req_ready(req_ready),
        .o_req_write(req_write),
        .o_req_addr(req_addr),
        .o_req_wdata(req_wdata),
        .o_req_wstrb(req_wstrb),
    
        // GPU response
        .i_rsp_valid(rsp_valid),
        .o_rsp_ready(rsp_ready),
        .i_rsp_rdata(rsp_rdata),
        .i_rsp_status(rsp_status)
	);

	// Add user logic here

    GPGPU #(
        .SP_PER_SM(SP_PER_SM),
        .INTERFACE_VERSION(INTERFACE_VERSION),
        .CLOCK_KHZ(CLOCK_KHZ),
        .BUILD_HASH(BUILD_HASH),
        .BUILD_DIRTY(BUILD_DIRTY != 0),
        .DDR_ENABLE(DDR_ENABLE != 0)
    ) gpu (
        .clk(aclk),
        .rst_n(aresetn),
        
        .o_core_idle(o_core_idle),
        .o_core_running(o_core_running),
    
        // Request
        .i_req_valid(req_valid),
        .o_req_ready(req_ready),
        .i_req_write(req_write),
        .i_req_addr(req_addr),
        .i_req_wdata(req_wdata),
        .i_req_wstrb(req_wstrb),
    
        // Response
        .o_rsp_valid(rsp_valid),
        .i_rsp_ready(rsp_ready),
        .o_rsp_rdata(rsp_rdata),
        .o_rsp_status(rsp_status),
    
        // Interrupt
        .o_irq(irq),

        // DDR AXI4 master
        .m_axi_awid(m00_axi_awid),
        .m_axi_awaddr(m00_axi_awaddr),
        .m_axi_awlen(m00_axi_awlen),
        .m_axi_awsize(m00_axi_awsize),
        .m_axi_awburst(m00_axi_awburst),
        .m_axi_awlock(m00_axi_awlock),
        .m_axi_awcache(m00_axi_awcache),
        .m_axi_awprot(m00_axi_awprot),
        .m_axi_awqos(m00_axi_awqos),
        .m_axi_awvalid(m00_axi_awvalid),
        .m_axi_awready(m00_axi_awready),

        .m_axi_wdata(m00_axi_wdata),
        .m_axi_wstrb(m00_axi_wstrb),
        .m_axi_wlast(m00_axi_wlast),
        .m_axi_wvalid(m00_axi_wvalid),
        .m_axi_wready(m00_axi_wready),

        .m_axi_bid(m00_axi_bid),
        .m_axi_bresp(m00_axi_bresp),
        .m_axi_bvalid(m00_axi_bvalid),
        .m_axi_bready(m00_axi_bready),

        .m_axi_arid(m00_axi_arid),
        .m_axi_araddr(m00_axi_araddr),
        .m_axi_arlen(m00_axi_arlen),
        .m_axi_arsize(m00_axi_arsize),
        .m_axi_arburst(m00_axi_arburst),
        .m_axi_arlock(m00_axi_arlock),
        .m_axi_arcache(m00_axi_arcache),
        .m_axi_arprot(m00_axi_arprot),
        .m_axi_arqos(m00_axi_arqos),
        .m_axi_arvalid(m00_axi_arvalid),
        .m_axi_arready(m00_axi_arready),

        .m_axi_rid(m00_axi_rid),
        .m_axi_rdata(m00_axi_rdata),
        .m_axi_rresp(m00_axi_rresp),
        .m_axi_rlast(m00_axi_rlast),
        .m_axi_rvalid(m00_axi_rvalid),
        .m_axi_rready(m00_axi_rready)
    );
    
    // User logic ends

	endmodule