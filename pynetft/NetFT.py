#!/usr/bin/env python3

import socket
import struct
import time


class Response:
    """
    Response class.

    This class represents the response data structure from the NetFT device.

    Attributes:
        rdt_sequence (int): The RDT sequence number
        ft_sequence (int): The Force/Torque sequence number
        status (int): The status code
        FTData (list): The Force/Torque data (6 integers)
    """

    def __init__(self):
        """
        Initialize the Response object
        """

        self.rdt_sequence = 0
        self.ft_sequence = 0
        self.status = 0
        self.FTData = [0] * 6


class NetFT:
    """
    NetFT class.

    This class provides methods to connect to a NetFT device, send requests, receive and parse responses,
    and retrieve force/torque data.

    Attributes:
        host (str): The IP address of the NetFT device
        port (int): The port number
        num_samples (int): The number of samples to request
        sock (socket): The UDP socket
        is_connected (bool): Indicates if the socket is connected
        AXES (list): The names of the Force/Torque axes
        response (Response): The response data structure
        count_per_force (int): The count per force axis
        count_per_torque (int): The count per torque axis
    """

    def __init__(
        self,
        host,
        port: int = 49152,
        num_samples: int = 1,
        count_per_force: int = 1000000,
        count_per_torque: int = 999.999,
    ) -> None:
        """Initialize the NetFT object

        Args:
            host (str): The IP address of the NetFT device
            port (int): The port number
            num_samples (int): The number of samples to request
            count_per_force (int): The count per force axis
            count_per_torque (int): The count per torque axis
        """

        self.host = host
        self.port = port
        self.num_samples = num_samples
        self.sock = None
        self.is_connected = False
        self.AXES = ["Fx", "Fy", "Fz", "Tx", "Ty", "Tz"]
        self.response = Response()
        self.count_per_force = count_per_force
        self.count_per_torque = count_per_torque

    def connect(self) -> None:
        """
        Create and connect the UDP socket.

        The socket is created and the is_connected flag is set to True.
        """

        if self.is_connected:
            print("Already connected")
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_connected = True
        print(f"Connected to {self.host}:{self.port}")

    def disconnect(self) -> None:
        """
        Close the connection.

        The socket is closed and the is_connected flag is set to False.
        """

        if not self.is_connected:
            print("Not connected")
            return

        if self.sock:
            self.sock.close()
        self.is_connected = False

    def _send_request(self, command) -> None:
        """
        Construct and send the request

        The request is a 8-byte array with the following format:
        - 2 bytes: 0x1234
        - 2 bytes: command code
        - 4 bytes: number of samples
        
        Command | Code   | Purpose                         | Response
        ------- | ------ | ------------------------------- | --------
        Stop    | 0x0000 | Stop sending RDT packets        | None
        Start   | 0x0002 | Start sending RDT packets       | RDT record(s)
        Bias    | 0x0042 | Set software bias               | None
        """

        if not self.is_connected:
            raise ConnectionError("Not connected, please call connect() first")

        request = bytearray(8)
        struct.pack_into(">HHI", request, 0, 0x1234, command, self.num_samples)
        self.sock.sendto(request, (self.host, self.port))

    def _parse_response(self, response: bytes) -> Response:
        """
        Parse the response data

        The response is a 36-byte array with the following format:
        - 4 bytes: RDT sequence number
        - 4 bytes: FT sequence number
        - 4 bytes: status code
        - 24 bytes: Force/Torque data (6 integers)

        Args:
            response (bytes): The response data

        Returns:
            resp (Response): The parsed response data
        """

        resp = Response()
        resp.rdt_sequence, resp.ft_sequence, resp.status = struct.unpack(
            ">III", response[:12]
        )
        resp.FTData = struct.unpack(">6i", response[12:])
        return resp

    def _receive_data(self):
        """
        Receive and parse the data

        The response is received and parsed into a Response object stored in self.response

        Returns:
            Response (object): The parsed response data
        """

        if not self.is_connected:
            print("Not connected, please call connect() first")
            return None

        response = self.sock.recv(36)
        self.response = self._parse_response(response)
        return self.response

    def _print_data(self, resp: Response) -> None:
        """
        Print the received data

        The status and Force/Torque data are printed

        Args:
            resp (Response): The response data
        """

        print(f"Status: 0x{resp.status:08x}")
        for i, axis in enumerate(self.AXES):
            print(f"{axis}: {resp.FTData[i]}")

    def bias(self) -> None:
        """
        Set the software bias

        Sends a request to set the software bias, which is used to zero the sensor readings.
        """

        self._send_request(command=0x0042)
    
    def get_data(self) -> Response:
        """
        Get the data once

        Sends a request and receives the data once

        Returns:
            Response (object): The parsed response data
        """

        self._send_request(command=0x0002)
        return self._receive_data()

    def get_converted_data(self) -> Response:
        """
        Get the real data

        Converts the raw data to real values based on the provided counts

        Returns:
            list: The converted Force/Torque data
        """

        resp = self.get_data()

        raw_data = resp.FTData
        # Convert raw data to real values
        converted_data = [
            raw_data[0] / self.count_per_force,
            raw_data[1] / self.count_per_force,
            raw_data[2] / self.count_per_force,
            raw_data[3] / self.count_per_torque,
            raw_data[4] / self.count_per_torque,
            raw_data[5] / self.count_per_torque,
        ]

        resp.FTData = converted_data

        return resp

    def start_streaming(self, duration=10, delay=0.1, print_data=True) -> None:
        """
        Continuously read and print data until the specified time is reached

        Args:
            duration (float): The duration to stream data (in seconds)
            delay (float): The delay between requests (in seconds)
            print_data (bool): Whether to print the data
        """

        start_time = time.time()
        while time.time() - start_time < duration:
            resp = self.get_converted_data()
            if resp and print_data:
                self._print_data(resp)
            time.sleep(delay)
        print("Data streaming stopped")


# Example usage
if __name__ == "__main__":
    # Create NetFT object
    netft = NetFT(
        host="192.168.1.1", # Replace with your device's IP
        count_per_force=1000000,
        count_per_torque=999.999,
    )  

    # Connect to the device
    netft.connect()
    
    # Set the software bias
    netft.bias()

    # Start the data stream and continuously read for 10 seconds
    netft.start_streaming(duration=10)

    # Disconnect from the device
    netft.disconnect()
