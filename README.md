# pyNetFT: Python interface for the ATI Force/Torque Sensor with Net F/T

[![PyPI version](https://img.shields.io/pypi/v/pynetft.svg?logo=pypi&logoColor=white)](https://pypi.org/project/pynetft/)
[![Python version](https://img.shields.io/pypi/pyversions/pynetft.svg?logo=python&logoColor=white)](https://pypi.org/project/pynetft/)
[![Github](https://img.shields.io/badge/Github-pyNetFT-purple?logo=github&logoColor=white)](https://github.com/han-xudong/pyNetFT)
[![License](https://img.shields.io/github/license/han-xudong/pyNetFT.svg?logo=open-source-initiative&logoColor=white)](LICENSE)

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

netft = NetFT(
    host='192.168.1.1', 
    tcp_port=49151,
    udp_port=49152,
    count_per_force=1000000,
    count_per_torque=999.999,
)
```

where `host` is the IP address of your Net F/T device, `port` is the port number (default is 49152), `count_per_force` is the conversion factor for force data, and `count_per_torque` is the conversion factor for torque data. `count_per_force` and `count_per_torque` can be found in the sensor's configuration page on `host`.

Several functions are provided to interact with the sensor:

- `connect()`: Connect to the sensor.

```python
netft.connect()
```

- `disconnect()`: Disconnect from the sensor.

```python
netft.disconnect()
```

- `bias()`: Set the software bias, which is used to zero the sensor readings.

```python
netft.bias()
```

- `get_data()`: Get the force and torque data once.

```python
data = netft.get_data()
print(data.FTData)  # Print the force and torque data
```

- `get_converted_data()`: Read and return the force and torque data from the sensor.

```python
data = netft.get_converted_data()
print(data.FTData)  # Print the force and torque data
```

- `start_streaming()`: Continuously read and print data from the sensor for a specified duration (in seconds).

```python
netft.start_streaming(duration=10, delay=0.1, print_data=True)
```

## License

This project is licensed under the [MIT LICENSE](LICENSE).

## Acknowledgements

This package is based on the C example provided by ATI. You can find the original code [here](https://www.ati-ia.com/Products/ft/software/net_ft_software.aspx).
