#include <cstddef>
#include <memory>
#include <stdexcept>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "bind_types.hpp"
#include "native_client.hpp"
#include "netft/discovery.hpp"

namespace py = pybind11;

namespace {

struct NativeClientDeleter {
  // pybind11's initialized GIL guard does not throw; its generic cast paths
  // confuse clang-tidy's exception call graph for this noexcept deleter.
  // NOLINTNEXTLINE(bugprone-exception-escape)
  void operator()(pynetft::bindings::NativeClient *client) const noexcept {
    py::gil_scoped_release release;
    delete client;
  }
};

using NativeClientHolder =
    std::unique_ptr<pynetft::bindings::NativeClient, NativeClientDeleter>;

} // namespace

PYBIND11_MODULE(_native, module) {
  module.attr("__version__") = PYNETFT_VERSION;

  py::register_local_exception<std::invalid_argument>(module, "ValidationError",
                                                      PyExc_ValueError);
  py::register_local_exception<netft::NotConnectedError>(
      module, "NotConnectedError", PyExc_ConnectionError);
  py::register_local_exception<netft::DiscoveryError>(module, "DiscoveryError",
                                                      PyExc_ConnectionError);

  pynetft::bindings::bind_types(module);

  py::enum_<pynetft::bindings::ReadStatus>(module, "ReadStatus")
      .value("SAMPLE", pynetft::bindings::ReadStatus::Sample)
      .value("TIMEOUT", pynetft::bindings::ReadStatus::Timeout)
      .value("CLOSED", pynetft::bindings::ReadStatus::Closed);

  py::class_<pynetft::bindings::ReadResult>(module, "ReadResult")
      .def(py::init<>())
      .def_readonly("status", &pynetft::bindings::ReadResult::status)
      .def_readonly("sample", &pynetft::bindings::ReadResult::sample);

  py::class_<pynetft::bindings::NativeClient, NativeClientHolder>(
      module, "NativeClient")
      .def(py::init<netft::Config, std::size_t>(), py::arg("config"),
           py::arg("queue_size"))
      .def("start", &pynetft::bindings::NativeClient::start,
           py::call_guard<py::gil_scoped_release>())
      .def("stop", &pynetft::bindings::NativeClient::stop,
           py::call_guard<py::gil_scoped_release>())
      .def("bias", &pynetft::bindings::NativeClient::bias,
           py::call_guard<py::gil_scoped_release>())
      .def("wait_for_first_sample",
           &pynetft::bindings::NativeClient::wait_for_first_sample,
           py::arg("timeout"), py::call_guard<py::gil_scoped_release>())
      .def("read", &pynetft::bindings::NativeClient::read,
           py::arg("timeout") = py::none(),
           py::call_guard<py::gil_scoped_release>())
      .def("latest_sample", &pynetft::bindings::NativeClient::latest_sample)
      .def("health", &pynetft::bindings::NativeClient::health)
      .def("faulted", &pynetft::bindings::NativeClient::faulted)
      .def("fault_code", &pynetft::bindings::NativeClient::fault_code)
      .def("queue_dropped_count",
           &pynetft::bindings::NativeClient::queue_dropped_count);
}
