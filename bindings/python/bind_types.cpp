#include "bind_types.hpp"

#include <chrono>
#include <cstdint>
#include <optional>

#include <pybind11/stl.h>

#include "netft/status.hpp"
#include "netft/types.hpp"

namespace pynetft::bindings {
namespace {

template <typename Owner>
auto duration_getter(std::chrono::duration<double> Owner::*member) {
  return [member](const Owner &owner) { return (owner.*member).count(); };
}

template <typename Owner>
auto duration_setter(std::chrono::duration<double> Owner::*member) {
  return [member](Owner &owner, const double seconds) {
    owner.*member = std::chrono::duration<double>{seconds};
  };
}

} // namespace

void bind_types(pybind11::module_ &module) {
  namespace py = pybind11;

  py::enum_<netft::ForceUnit>(module, "ForceUnit")
      .value("UNKNOWN", netft::ForceUnit::Unknown)
      .value("POUND_FORCE", netft::ForceUnit::PoundForce)
      .value("NEWTON", netft::ForceUnit::Newton)
      .value("KILO_POUND_FORCE", netft::ForceUnit::KiloPoundForce)
      .value("KILO_NEWTON", netft::ForceUnit::KiloNewton)
      .value("KILOGRAM_FORCE", netft::ForceUnit::KilogramForce);

  py::enum_<netft::TorqueUnit>(module, "TorqueUnit")
      .value("UNKNOWN", netft::TorqueUnit::Unknown)
      .value("POUND_FORCE_INCH", netft::TorqueUnit::PoundForceInch)
      .value("POUND_FORCE_FOOT", netft::TorqueUnit::PoundForceFoot)
      .value("NEWTON_METER", netft::TorqueUnit::NewtonMeter)
      .value("NEWTON_MILLIMETER", netft::TorqueUnit::NewtonMillimeter)
      .value("KILOGRAM_FORCE_CENTIMETER",
             netft::TorqueUnit::KilogramForceCentimeter)
      .value("KILO_NEWTON_METER", netft::TorqueUnit::KiloNewtonMeter);

  py::enum_<netft::CalibrationSource>(module, "CalibrationSource")
      .value("SENSOR", netft::CalibrationSource::Sensor)
      .value("OVERRIDE", netft::CalibrationSource::Override);

  py::enum_<netft::RecoveryPolicy>(module, "RecoveryPolicy")
      .value("RECONNECT", netft::RecoveryPolicy::Reconnect)
      .value("FAIL_STOP", netft::RecoveryPolicy::FailStop);

  py::enum_<netft::ClientState>(module, "ClientState")
      .value("STOPPED", netft::ClientState::Stopped)
      .value("CONNECTING", netft::ClientState::Connecting)
      .value("STREAMING", netft::ClientState::Streaming)
      .value("BACKOFF", netft::ClientState::Backoff)
      .value("FAULTED", netft::ClientState::Faulted);

  py::enum_<netft::FaultCode>(module, "FaultCode")
      .value("NONE", netft::FaultCode::None)
      .value("SENSOR_CONFIGURATION", netft::FaultCode::SensorConfiguration)
      .value("TIMEOUT", netft::FaultCode::Timeout)
      .value("SOCKET", netft::FaultCode::Socket)
      .value("SERIOUS_STATUS", netft::FaultCode::SeriousStatus)
      .value("FT_STALL", netft::FaultCode::FtStall)
      .value("FT_BACKWARD", netft::FaultCode::FtBackward)
      .value("MALFORMED_STORM", netft::FaultCode::MalformedStorm)
      .value("CALLBACK", netft::FaultCode::Callback);

  py::enum_<netft::StatusSeverity>(module, "StatusSeverity")
      .value("OK", netft::StatusSeverity::Ok)
      .value("WARN", netft::StatusSeverity::Warn)
      .value("ERROR", netft::StatusSeverity::Error);

  py::class_<netft::Calibration>(module, "Calibration")
      .def(py::init<>())
      .def_readwrite("counts_per_force_unit",
                     &netft::Calibration::counts_per_force_unit)
      .def_readwrite("counts_per_torque_unit",
                     &netft::Calibration::counts_per_torque_unit)
      .def_readwrite("force_unit", &netft::Calibration::force_unit)
      .def_readwrite("torque_unit", &netft::Calibration::torque_unit);

  py::class_<netft::SensorConfiguration>(module, "SensorConfiguration")
      .def(py::init<>())
      .def_readwrite("product_name", &netft::SensorConfiguration::product_name)
      .def_readwrite("calibration", &netft::SensorConfiguration::calibration)
      .def_readwrite("source", &netft::SensorConfiguration::source)
      .def_readwrite("revision", &netft::SensorConfiguration::revision);

  py::class_<netft::Config>(module, "Config")
      .def(py::init<>())
      .def_readwrite("sensor_host", &netft::Config::sensor_host)
      .def_readwrite("rdt_port", &netft::Config::rdt_port)
      .def_readwrite("http_port", &netft::Config::http_port)
      .def_property("receive_timeout",
                    duration_getter(&netft::Config::receive_timeout),
                    duration_setter(&netft::Config::receive_timeout))
      .def_property(
          "configuration_connect_timeout",
          duration_getter(&netft::Config::configuration_connect_timeout),
          duration_setter(&netft::Config::configuration_connect_timeout))
      .def_property("configuration_timeout",
                    duration_getter(&netft::Config::configuration_timeout),
                    duration_setter(&netft::Config::configuration_timeout))
      .def_property("reconnect_initial_delay",
                    duration_getter(&netft::Config::reconnect_initial_delay),
                    duration_setter(&netft::Config::reconnect_initial_delay))
      .def_property("reconnect_max_delay",
                    duration_getter(&netft::Config::reconnect_max_delay),
                    duration_setter(&netft::Config::reconnect_max_delay))
      .def_readwrite("sample_rate_limit_hz",
                     &netft::Config::sample_rate_limit_hz)
      .def_readwrite("deliver_samples_with_error_status",
                     &netft::Config::deliver_samples_with_error_status)
      .def_readwrite("recovery_policy", &netft::Config::recovery_policy)
      .def_readwrite("calibration_override",
                     &netft::Config::calibration_override);

  py::class_<netft::Sample>(module, "Sample")
      .def(py::init<>())
      .def_readonly("rdt_sequence", &netft::Sample::rdt_sequence)
      .def_readonly("ft_sequence", &netft::Sample::ft_sequence)
      .def_readonly("status", &netft::Sample::status)
      .def_readonly("raw_wrench", &netft::Sample::raw_wrench)
      .def_readonly("force", &netft::Sample::force)
      .def_readonly("torque", &netft::Sample::torque)
      .def_readonly("force_unit", &netft::Sample::force_unit)
      .def_readonly("torque_unit", &netft::Sample::torque_unit)
      .def_readonly("configuration_revision",
                    &netft::Sample::configuration_revision)
      .def_property_readonly("received_at_ns", [](const netft::Sample &sample) {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
                   sample.received_at.time_since_epoch())
            .count();
      });

  py::class_<netft::HealthSnapshot>(module, "Health")
      .def(py::init<>())
      .def_readonly("state", &netft::HealthSnapshot::state)
      .def_readonly("fault_code", &netft::HealthSnapshot::fault_code)
      .def_readonly("sensor_host", &netft::HealthSnapshot::sensor_host)
      .def_readonly("rdt_port", &netft::HealthSnapshot::rdt_port)
      .def_readonly("sensor_configuration",
                    &netft::HealthSnapshot::sensor_configuration)
      .def_readonly("last_rdt_sequence",
                    &netft::HealthSnapshot::last_rdt_sequence)
      .def_readonly("last_ft_sequence",
                    &netft::HealthSnapshot::last_ft_sequence)
      .def_readonly("last_status", &netft::HealthSnapshot::last_status)
      .def_readonly("receive_rate_hz", &netft::HealthSnapshot::receive_rate_hz)
      .def_readonly("delivery_rate_hz",
                    &netft::HealthSnapshot::delivery_rate_hz)
      .def_readonly("received_count", &netft::HealthSnapshot::received_count)
      .def_readonly("delivered_count", &netft::HealthSnapshot::delivered_count)
      .def_readonly("rate_limited_count",
                    &netft::HealthSnapshot::rate_limited_count)
      .def_readonly("device_error_count",
                    &netft::HealthSnapshot::device_error_count)
      .def_readonly("warning_count", &netft::HealthSnapshot::warning_count)
      .def_readonly("lost_count", &netft::HealthSnapshot::lost_count)
      .def_readonly("duplicate_count", &netft::HealthSnapshot::duplicate_count)
      .def_readonly("out_of_order_count",
                    &netft::HealthSnapshot::out_of_order_count)
      .def_readonly("malformed_count", &netft::HealthSnapshot::malformed_count)
      .def_readonly("reconnect_count", &netft::HealthSnapshot::reconnect_count)
      .def_readonly("timeout_count", &netft::HealthSnapshot::timeout_count)
      .def_readonly("callback_error_count",
                    &netft::HealthSnapshot::callback_error_count)
      .def_readonly("ft_stall_count", &netft::HealthSnapshot::ft_stall_count)
      .def_readonly("ft_backward_count",
                    &netft::HealthSnapshot::ft_backward_count)
      .def_readonly("ft_restart_count",
                    &netft::HealthSnapshot::ft_restart_count)
      .def_readonly("calibration_change_count",
                    &netft::HealthSnapshot::calibration_change_count)
      .def_property_readonly(
          "last_record_age",
          [](const netft::HealthSnapshot &health) {
            return health.last_record_age
                       ? std::optional<double>{health.last_record_age->count()}
                       : std::nullopt;
          })
      .def_readonly("last_error", &netft::HealthSnapshot::last_error)
      .def_readonly("last_ft_progress",
                    &netft::HealthSnapshot::last_ft_progress);
}

} // namespace pynetft::bindings
