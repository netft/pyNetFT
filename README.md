# pyNetFT: Python interface for the ATI Force/Torque Sensor with Net F/T

This is a Python interface for the ATI force/torque sensor with Net F/T. It allows you to read the force and torque data from the sensor in real-time.

## Installation

To install the package, run the following command:

```bash
pip install pynetft
```

Or you can install it from the source code:

```bash
git clone https://github.com/han-xudong/pyNetFT.git
cd pyNetFT
pip install .
```

## Usage

Here is an example of how to use the package:

```python
from pynetft import NetFT

netft = NetFT(host='192.168.1.1', port=49152) # Change the host and port to the IP address and port of your sensor
netft.connect() # Connect to the sensor
netft.start_streaming(duration=10) # Start streaming data from the sensor for 10 seconds
netft.disconnect() # Disconnect from the sensor
```

And here are some functions provided to interact with the sensor:

- `connect()`: Connect to the sensor.

```python
netft.connect()
```

- `disconnect()`: Disconnect from the sensor.

```python
netft.disconnect()
```

- `get_data()`: Read and return the force and torque data from the sensor.

```python
data = netft.get_data()
print(data)
```

- `start_streaming()`: Continuously read and print data from the sensor for a specified duration (in seconds).

```python
netft.start_streaming(duration=10, delay=0.1, print_data=True)
```

## License

This project is licensed under the [MIT LICENSE](LICENSE).

## Acknowledgements

This package is based on the C example provided by ATI. You can find the original code [here](https://www.ati-ia.com/Products/ft/software/net_ft_software.aspx).
