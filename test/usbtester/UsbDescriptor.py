#
#
#
#
#
#
#
#
# SPDX-FileCopyrightText: Copyright 2023 Darryl Miles
# SPDX-License-Identifier: Apache2.0
#
#



# bLength = 18
# bDescriptorType = 1
def encode_device(
        bLength: int = 0,
        bDescriptorType: int = 0,
        bcdUSB: int = 0,
        bDeviceClass: int = 0,
        bDeviceSubClass: int = 0,
        bDeviceProtocol: int = 0,
        bMaxPacketSize: int = 0,
        idVendor: int = 0,
        idProduct: int = 0,
        bcdDevice: int = 0,
        iManufacturer: int = 0,
        iProduct: int = 0,
        iSerialNumber: int = 0,
        bNumConfigurations: int = 0
    ) -> bytearray:

    return None

# bLength = 9
# bDescriptorType = 2
def encode_configuration(
        bLength: int = 0,
        bDescriptorType: int = 0,
        wTotallength: int = 0,
        bNumInterfaces: int = 0,
        bConfigurationValue: int = 0,
        iConfiguration: int = 0,
        bmAttributes: int = 0,
        bMaxPower: int = 0
    ) -> bytearray:

    return None

# bLength = 9
# bDescriptorType = 4
def encode_interface(
        bLength = 0,
        bDescriptorType = 4,
        bInterfaceNumber: int = 0,
        bAlternateSetting: int = 0,
        bNumEndpoints: int = 0,
        bInterfaceClass: int = 0,
        bInterfaceSubClass: int = 0,
        bInterfaceProtocol: int = 0,
        iInterface: int = 0
    ) -> bytearray:

    return None
