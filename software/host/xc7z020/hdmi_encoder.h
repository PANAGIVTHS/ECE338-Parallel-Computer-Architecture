#ifndef HDMI_ENCODER_H
#define HDMI_ENCODER_H

/* Set up the board's HDMI transmitter chip before scanout starts; 0 on
 * success. A board whose FPGA drives HDMI itself (rgb2dvi) has no chip to set
 * up: main.c's default does nothing. A board with one adds its source to
 * hardware.vitis.host_sources (adv7511.c for the ZedBoard), which replaces
 * the default. */
int hdmi_encoder_init(void);

#endif /* HDMI_ENCODER_H */
