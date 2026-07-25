# Security policy

## Supported versions

Security fixes are applied to the latest released version and the `main` branch. Older releases may not receive backports.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use [GitHub private vulnerability reporting](https://github.com/netft/pyNetFT/security/advisories/new) when it is enabled. If private reporting is unavailable, contact the maintainer at [hanxudong159@126.com](mailto:hanxudong159@126.com).

Include the affected version, deployment assumptions, a minimal reproduction or data-flow description, and the security impact. Remove sensor addresses, credentials, measurements, and private network details before submitting a report.

## Network security model

ATI Net F/T devices expose configuration through HTTP and stream RDT records through UDP. pyNetFT implements those device protocols and does not add transport encryption, peer authentication, or message integrity. Configuration discovery and RDT data must not be treated as authenticated solely because they came from the configured sensor address.

The supported deployment model assumes that the sensor and client run on a trusted, isolated network segment. Do not expose the sensor, its HTTP interface, or its RDT port directly to the Internet or an untrusted shared network. If traffic must cross an untrusted network, place the complete sensor connection inside an authenticated boundary such as a managed VPN or an equivalent industrial-network gateway.

Recommended controls include:

- isolate the sensor network with a dedicated interface or VLAN;
- restrict traffic with host and network firewalls to the expected client and sensor addresses;
- prevent untrusted devices from joining, routing to, or bridging the sensor segment; and
- monitor unexpected calibration, unit, sensor-address, and connection changes.

The native core disables HTTP redirects and proxy use and strictly validates the configuration response. Those controls reduce exposure but do not authenticate the response's origin.

## Configuration integrity and hardware safety

Automatic discovery reads calibration scales and units over unauthenticated HTTP. Verify discovered values against the intended sensor configuration before enabling a controller. If an application must use fixed, independently verified calibration values, configure a complete manual `Calibration` override. An override avoids HTTP discovery but does not authenticate the UDP measurement stream.

Force/torque data can affect motion and protective-limit decisions. Use fail-stop behavior where appropriate, reject stale or invalid data, and retain an independent safety-rated control path. pyNetFT is not a substitute for an emergency stop or other safety system.

`Client.bias()` changes the sensor's software bias. Invoke it only with explicit operator authorization and a verified unloaded sensor.

## Known protocol limitations

A report that depends only on the absence of HTTPS or authenticated UDP in the ATI device protocol may describe a known protocol limitation rather than a defect pyNetFT can correct independently. Reports remain valuable when they demonstrate an unexpected exposure, a bypass of the stated trusted-network model, unsafe handling of unauthenticated data, or a practical mitigation compatible with the device.
