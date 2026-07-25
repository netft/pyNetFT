#include <stdexcept>

#include <pybind11/pybind11.h>

#include "netft/client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_exception_probe, module) {
  py::register_exception<std::invalid_argument>(module, "ProbeError",
                                                PyExc_RuntimeError);
  py::register_exception<netft::NotConnectedError>(
      module, "ProbeNotConnectedError", PyExc_RuntimeError);
  module.def("throw_invalid_argument",
             [] { throw std::invalid_argument("exception probe"); });
}
