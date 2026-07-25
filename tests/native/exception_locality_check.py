import _exception_probe
import _native

try:
    _native.NativeClient(_native.Config(), 0)
except _native.ValidationError:
    pass
else:
    raise AssertionError("native validation did not use its module-local translator")

client = _native.NativeClient(_native.Config(), 1)
try:
    client.bias()
except _native.NotConnectedError:
    pass
else:
    raise AssertionError("native connection error did not use its module-local translator")

try:
    _exception_probe.throw_invalid_argument()
except _exception_probe.ProbeError:
    pass
else:
    raise AssertionError("probe did not use its own global translator")
