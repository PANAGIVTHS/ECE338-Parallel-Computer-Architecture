/* The ZedBoard's ADV7511 HDMI transmitter, set up over PS I2C0 (EMIO) for
 * the video of the adv7511_video IP: 16-bit YCbCr 4:2:2 with separate syncs
 * (input ID 1), input style 1, 8 bits per component, right-justified. The
 * chip's colour space converter turns it back into RGB (BT.709, limited
 * range in, full range out), sent as DVI, which every HDMI sink accepts.
 *
 * Register values follow the ADV7511 Programming Guide as Linux's adv7511
 * driver applies them, with the input settings of Analog Devices' ZedBoard
 * device tree. */
#include "hdmi_encoder.h"

#include "xiicps.h"
#include "xparameters.h"
#include "xil_printf.h"
#include "xil_types.h"
#include "sleep.h"

#ifndef XPAR_XIICPS_0_BASEADDR
#error "XPAR_XIICPS_0_BASEADDR is not defined: the hardware has no PS I2C0 for the ADV7511"
#endif

#define ADV7511_ADDRESS      0x39U    /* main register map, 7-bit */
#define ADV7511_I2C_HZ       100000U
#define ADV7511_BUS_WAIT_US  10000U   /* one transfer takes well under 1 ms */

/* Main register map (ADV7511 Programming Guide). */
#define REG_I2C_FREQ_ID_CFG  0x15U    /* [3:0] video input ID */
#define REG_VIDEO_INPUT_CFG1 0x16U    /* [7] 4:2:2 out, [5:4] depth, [3:2] style, [0] YCbCr out */
#define REG_VIDEO_INPUT_CFG3 0x17U    /* [6:5] sync polarity, [1] 16:9 aspect */
#define REG_CSC_UPPER(n)     (0x18U + 2U * (n))
#define REG_CSC_LOWER(n)     (0x19U + 2U * (n))
#define REG_POWER            0x41U    /* [6] power down */
#define REG_STATUS           0x42U    /* [6] HPD, [5] monitor sense */
#define REG_VIDEO_INPUT_CFG2 0x48U    /* [4:3] justification */
#define REG_HDMI_CFG         0xAFU    /* [1] HDMI (1) or DVI (0) */
#define REG_CLOCK_DELAY      0xBAU    /* [7:5] input clock delay */
#define REG_TIMING_GEN_SEQ   0xD0U    /* [3:2] sync pulse */
#define REG_POWER2           0xD6U    /* [7:6] HPD source */

#define POWER_DOWN           0x40U
#define CSC_ENABLE           0x80U
#define CSC_UPDATE_MODE      0x20U
#define CSC_SCALING_4        (2U << 5)
#define HDMI_CFG_MODE_MASK   0x02U
#define HDMI_CFG_MODE_DVI    0x00U
#define HPD_SOURCE_MASK      0xC0U
#define HPD_SOURCE_NONE      0xC0U    /* HPD always high */

/* Registers that must hold these values after every power up. */
static const u8 fixed_registers[][2] = {
    { 0x98U, 0x03U }, { 0x9AU, 0xE0U }, { 0x9CU, 0x30U }, { 0x9DU, 0x61U },
    { 0xA2U, 0xA4U }, { 0xA3U, 0xA4U }, { 0xE0U, 0xD0U }, { 0xF9U, 0x00U },
    { 0x55U, 0x02U },
};

/* The video input format. */
static const u8 input_registers[][2] = {
    { REG_I2C_FREQ_ID_CFG,  0x01U },          /* ID 1: YCbCr 4:2:2, separate syncs */
    { REG_VIDEO_INPUT_CFG1, (3U << 4) | (2U << 2) },  /* RGB 4:4:4 out, 8 bits, style 1 */
    { REG_VIDEO_INPUT_CFG2, 1U << 3 },        /* right-justified */
    { REG_VIDEO_INPUT_CFG3, 0x02U },          /* active-high syncs, 16:9 (720p) */
    { REG_TIMING_GEN_SEQ,   3U << 2 },        /* no sync pulse: separate syncs */
    { REG_CLOCK_DELAY,      3U << 5 },        /* 0 ps clock delay */
};

/* YCbCr (BT.709, limited range) to RGB coefficients, 13-bit, with the
 * converter's x4 scaling. */
static const u16 ycbcr_to_rgb[12] = {
    0x0734U, 0x04ADU, 0x0000U, 0x1C1BU,
    0x1DDCU, 0x04ADU, 0x1F24U, 0x0135U,
    0x0000U, 0x04ADU, 0x087CU, 0x1B77U,
};

static XIicPs iic;

static int bus_idle(void) {
    for (u32 waited = 0U; XIicPs_BusIsBusy(&iic); waited++) {
        if (waited == ADV7511_BUS_WAIT_US)
            return -1;
        usleep(1);
    }
    return 0;
}

static int adv_write(u8 reg, u8 value) {
    u8 message[2] = { reg, value };

    if (XIicPs_MasterSendPolled(&iic, message, 2, ADV7511_ADDRESS) != XST_SUCCESS || bus_idle() != 0) {
        xil_printf("ERROR: ADV7511 write 0x%02x = 0x%02x failed\r\n", reg, value);
        return -1;
    }
    return 0;
}

static int adv_read(u8 reg, u8 *value) {
    if (XIicPs_MasterSendPolled(&iic, &reg, 1, ADV7511_ADDRESS) != XST_SUCCESS || bus_idle() != 0 ||
        XIicPs_MasterRecvPolled(&iic, value, 1, ADV7511_ADDRESS) != XST_SUCCESS || bus_idle() != 0) {
        xil_printf("ERROR: ADV7511 read 0x%02x failed\r\n", reg);
        return -1;
    }
    return 0;
}

static int adv_update(u8 reg, u8 mask, u8 value) {
    u8 current;

    if (adv_read(reg, &current) != 0)
        return -1;
    return adv_write(reg, (u8)((current & ~mask) | (value & mask)));
}

static int write_table(const u8 (*table)[2], u32 count) {
    for (u32 i = 0U; i < count; i++) {
        if (adv_write(table[i][0], table[i][1]) != 0)
            return -1;
    }
    return 0;
}

/* Load the YCbCr-to-RGB matrix and enable the converter, as one update. */
static int load_csc(void) {
    if (adv_update(REG_CSC_UPPER(1), CSC_UPDATE_MODE, CSC_UPDATE_MODE) != 0)
        return -1;
    for (u32 i = 0U; i < 12U; i++) {
        if (adv_update((u8)REG_CSC_UPPER(i), 0x1FU, (u8)(ycbcr_to_rgb[i] >> 8)) != 0 ||
            adv_write((u8)REG_CSC_LOWER(i), (u8)(ycbcr_to_rgb[i] & 0xFFU)) != 0)
            return -1;
    }
    if (adv_update(REG_CSC_UPPER(0), 0xE0U, CSC_ENABLE | CSC_SCALING_4) != 0)
        return -1;
    return adv_update(REG_CSC_UPPER(1), CSC_UPDATE_MODE, 0U);
}

int hdmi_encoder_init(void) {
    XIicPs_Config *config = XIicPs_LookupConfig(XPAR_XIICPS_0_BASEADDR);
    u8 status;

    if (config == NULL || XIicPs_CfgInitialize(&iic, config, config->BaseAddress) != XST_SUCCESS ||
        XIicPs_SetSClk(&iic, ADV7511_I2C_HZ) != XST_SUCCESS) {
        xil_printf("ERROR: PS I2C0 for the ADV7511 did not initialize\r\n");
        return -1;
    }

    /* Power up first: the chip resets its fixed registers while powered
     * down. The ZedBoard does not wire HPD to the Zynq, and the chip powers
     * itself down while it sees HPD low, so it ignores HPD. */
    if (adv_update(REG_POWER, POWER_DOWN, 0U) != 0 ||
        adv_update(REG_POWER2, HPD_SOURCE_MASK, HPD_SOURCE_NONE) != 0 ||
        write_table(fixed_registers, sizeof(fixed_registers) / sizeof(fixed_registers[0])) != 0 ||
        write_table(input_registers, sizeof(input_registers) / sizeof(input_registers[0])) != 0 ||
        load_csc() != 0 ||
        adv_update(REG_HDMI_CFG, HDMI_CFG_MODE_MASK, HDMI_CFG_MODE_DVI) != 0 ||
        adv_read(REG_STATUS, &status) != 0)
        return -1;

    xil_printf("HDMI: ADV7511 set up (YCbCr 4:2:2 in, RGB DVI out); hot plug %s, monitor %s\r\n",
               (status & 0x40U) ? "high" : "low", (status & 0x20U) ? "sensed" : "not sensed");
    return 0;
}
