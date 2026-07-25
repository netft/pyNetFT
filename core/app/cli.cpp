#include "cli.hpp"

#include <fcntl.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <limits>
#include <locale>
#include <optional>
#include <sstream>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

#include "netft/client.hpp"
#include "netft/discovery.hpp"
#include "netft/status.hpp"

namespace netft::cli {
namespace {

struct Summary {
  SensorConfiguration configuration;
  HealthSnapshot health;
  Sample sample;
  double elapsed_s{};
  std::optional<double> requested_duration_s;
  bool bias_applied{};
};

double parse_positive_double(std::string_view name, const std::string &text) {
  std::size_t consumed{};
  double value{};
  try {
    value = std::stod(text, &consumed);
  } catch (const std::exception &) {
    throw UsageError(std::string{name} + " must be a positive number");
  }
  if (consumed != text.size() || !std::isfinite(value) || value <= 0.0) {
    throw UsageError(std::string{name} + " must be a positive number");
  }
  return value;
}

int parse_port(std::string_view name, const std::string &text) {
  std::size_t consumed{};
  long value{};
  try {
    value = std::stol(text, &consumed);
  } catch (const std::exception &) {
    throw UsageError(std::string{name} + " must be in the range 1..65535");
  }
  if (consumed != text.size() || value < 1 || value > 65535) {
    throw UsageError(std::string{name} + " must be in the range 1..65535");
  }
  return static_cast<int>(value);
}

std::string take_value(const std::vector<std::string> &arguments, std::size_t &index) {
  if (++index >= arguments.size()) {
    throw UsageError(arguments[index - 1] + " requires a value");
  }
  return arguments[index];
}

void validate_utf8(std::string_view value) {
  const auto byte_at = [&value](const std::size_t index) {
    return static_cast<unsigned char>(value[index]);
  };
  const auto is_continuation = [&byte_at](const std::size_t index) {
    return (byte_at(index) & 0xc0U) == 0x80U;
  };
  const auto invalid = [] { throw std::runtime_error("cannot serialize invalid UTF-8 string"); };

  for (std::size_t index = 0; index < value.size();) {
    const auto first = byte_at(index);
    if (first <= 0x7fU) {
      ++index;
      continue;
    }
    if (first >= 0xc2U && first <= 0xdfU) {
      if (index + 1 >= value.size() || !is_continuation(index + 1)) {
        invalid();
      }
      index += 2;
      continue;
    }
    if (first >= 0xe0U && first <= 0xefU) {
      if (index + 2 >= value.size() || !is_continuation(index + 1) || !is_continuation(index + 2)) {
        invalid();
      }
      const auto second = byte_at(index + 1);
      if ((first == 0xe0U && second < 0xa0U) || (first == 0xedU && second > 0x9fU)) {
        invalid();
      }
      index += 3;
      continue;
    }
    if (first >= 0xf0U && first <= 0xf4U) {
      if (index + 3 >= value.size() || !is_continuation(index + 1) || !is_continuation(index + 2) ||
          !is_continuation(index + 3)) {
        invalid();
      }
      const auto second = byte_at(index + 1);
      if ((first == 0xf0U && second < 0x90U) || (first == 0xf4U && second > 0x8fU)) {
        invalid();
      }
      index += 4;
      continue;
    }
    invalid();
  }
}

std::string json_escape(std::string_view value) {
  validate_utf8(value);
  std::ostringstream escaped;
  for (const unsigned char character : value) {
    switch (character) {
    case '"':
      escaped << "\\\"";
      break;
    case '\\':
      escaped << "\\\\";
      break;
    case '\b':
      escaped << "\\b";
      break;
    case '\f':
      escaped << "\\f";
      break;
    case '\n':
      escaped << "\\n";
      break;
    case '\r':
      escaped << "\\r";
      break;
    case '\t':
      escaped << "\\t";
      break;
    default:
      if (character < 0x20U) {
        escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                << static_cast<unsigned>(character) << std::dec;
      } else {
        escaped << static_cast<char>(character);
      }
    }
  }
  return escaped.str();
}

std::string source_name(const CalibrationSource source) {
  return source == CalibrationSource::Sensor ? "sensor" : "override";
}

void use_json_locale(std::ostringstream &output) { output.imbue(std::locale::classic()); }

void append_json_number(std::ostringstream &output, const double value) {
  if (!std::isfinite(value)) {
    throw std::runtime_error("cannot serialize non-finite JSON number");
  }
  use_json_locale(output);
  output << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
}

void append_configuration_json(std::ostringstream &output, const SensorConfiguration &configuration,
                               const Config &config) {
  output << R"("product":")" << json_escape(configuration.product_name) << R"(","endpoint":")"
         << json_escape(config.sensor_host) << ':' << config.rdt_port
         << R"(","configuration_source":")" << source_name(configuration.source)
         << R"(","force_unit":")" << to_string(configuration.calibration.force_unit)
         << R"(","torque_unit":")" << to_string(configuration.calibration.torque_unit)
         << R"(","counts_per_force_unit":)";
  append_json_number(output, configuration.calibration.counts_per_force_unit);
  output << ",\"counts_per_torque_unit\":";
  append_json_number(output, configuration.calibration.counts_per_torque_unit);
  output << ",\"configuration_revision\":" << configuration.revision;
}

template <std::size_t Size>
void append_array(std::ostringstream &output, const std::array<double, Size> &values) {
  output << '[';
  for (std::size_t index = 0; index < values.size(); ++index) {
    if (index != 0) {
      output << ',';
    }
    append_json_number(output, values[index]);
  }
  output << ']';
}

std::string serialize_json(const SensorConfiguration &configuration, const Config &config) {
  std::ostringstream output;
  use_json_locale(output);
  output << '{';
  append_configuration_json(output, configuration, config);
  output << "}\n";
  return output.str();
}

std::string serialize_json(const Summary &summary, const Config &config) {
  const auto &health = summary.health;
  std::ostringstream output;
  use_json_locale(output);
  output << '{';
  append_configuration_json(output, summary.configuration, config);
  if (summary.requested_duration_s) {
    output << ",\"requested_duration_s\":";
    append_json_number(output, *summary.requested_duration_s);
  }
  output << ",\"elapsed_s\":";
  append_json_number(output, summary.elapsed_s);
  output << ",\"sample_count\":" << health.delivered_count
         << ",\"received_count\":" << health.received_count
         << ",\"delivered_count\":" << health.delivered_count
         << ",\"rate_limited_count\":" << health.rate_limited_count << ",\"receive_rate_hz\":";
  append_json_number(output, health.receive_rate_hz);
  output << ",\"delivery_rate_hz\":";
  append_json_number(output, health.delivery_rate_hz);
  output << ",\"lost_count\":" << health.lost_count
         << ",\"duplicate_count\":" << health.duplicate_count
         << ",\"out_of_order_count\":" << health.out_of_order_count
         << ",\"malformed_count\":" << health.malformed_count
         << ",\"reconnect_count\":" << health.reconnect_count
         << ",\"timeout_count\":" << health.timeout_count
         << ",\"warning_count\":" << health.warning_count
         << ",\"device_error_count\":" << health.device_error_count
         << ",\"device_status\":" << summary.sample.status << R"(,"fault_code":")"
         << to_string(health.fault_code) << R"(","last_rdt_sequence":)"
         << summary.sample.rdt_sequence << ",\"last_ft_sequence\":" << summary.sample.ft_sequence
         << ",\"last_force\":";
  append_array(output, summary.sample.force);
  output << ",\"last_torque\":";
  append_array(output, summary.sample.torque);
  if (summary.bias_applied) {
    output << ",\"bias_applied\":true";
  }
  output << "}\n";
  return output.str();
}

std::string serialize_human(const SensorConfiguration &configuration, const Config &config) {
  std::ostringstream output;
  output << "Product: " << configuration.product_name << '\n'
         << "Endpoint: " << config.sensor_host << ':' << config.rdt_port << '\n'
         << "Calibration: " << source_name(configuration.source) << ", "
         << configuration.calibration.counts_per_force_unit << " counts/"
         << to_string(configuration.calibration.force_unit) << ", "
         << configuration.calibration.counts_per_torque_unit << " counts/"
         << to_string(configuration.calibration.torque_unit) << '\n';
  return output.str();
}

std::string serialize_human(const Summary &summary, const Config &config) {
  std::ostringstream output;
  output << serialize_human(summary.configuration, config)
         << "Samples: " << summary.health.delivered_count << " delivered, "
         << summary.health.lost_count << " lost, " << summary.health.warning_count << " warnings, "
         << summary.health.device_error_count << " errors\n"
         << "Receive rate [Hz]: " << summary.health.receive_rate_hz << '\n'
         << "Lost records: " << summary.health.lost_count << '\n'
         << "Device status: " << summary.sample.status << '\n'
         << "Reconnects: " << summary.health.reconnect_count << '\n'
         << "Force [" << to_string(summary.sample.force_unit) << "]: " << summary.sample.force[0]
         << ' ' << summary.sample.force[1] << ' ' << summary.sample.force[2] << "\nTorque ["
         << to_string(summary.sample.torque_unit) << "]: " << summary.sample.torque[0] << ' '
         << summary.sample.torque[1] << ' ' << summary.sample.torque[2] << '\n';
  if (summary.bias_applied) {
    output << "Bias applied: yes\n";
  }
  return output.str();
}

void write_atomic(const std::string &path, const std::string &contents) {
  if (path.empty()) {
    throw std::invalid_argument("output path must not be empty");
  }
  std::string temporary = path + ".tmp.XXXXXX";
  std::vector<char> name(temporary.begin(), temporary.end());
  name.push_back('\0');
  const int descriptor = ::mkstemp(name.data());
  if (descriptor < 0) {
    throw std::runtime_error("cannot create temporary output file: " +
                             std::string{std::strerror(errno)});
  }
  const std::string temporary_path{name.data()};
  FILE *file = ::fdopen(descriptor, "wb");
  if (file == nullptr) {
    const auto message = std::string{std::strerror(errno)};
    ::close(descriptor);
    ::unlink(temporary_path.c_str());
    throw std::runtime_error("cannot open temporary output file: " + message);
  }

  bool success = std::fwrite(contents.data(), 1, contents.size(), file) == contents.size();
  success = std::fflush(file) == 0 && success;
  success = std::fclose(file) == 0 && success;
  if (!success) {
    ::unlink(temporary_path.c_str());
    throw std::runtime_error("cannot write output file");
  }
  if (std::rename(temporary_path.c_str(), path.c_str()) != 0) {
    const auto message = std::string{std::strerror(errno)};
    ::unlink(temporary_path.c_str());
    throw std::runtime_error("cannot replace output file: " + message);
  }
}

bool was_interrupted(const volatile std::sig_atomic_t *interrupted) {
  return interrupted != nullptr && *interrupted != 0;
}

void emit(const Options &options, std::ostream &output, const std::string &contents) {
  if (options.output_path.empty()) {
    output << contents;
  } else {
    write_atomic(options.output_path, contents);
  }
}

int result_code(const HealthSnapshot &health) {
  if (health.warning_count > 0 || health.device_error_count > 0) {
    return 1;
  }
  return health.fault_code == FaultCode::None ? 0 : 2;
}

int run_info(const Options &options, std::ostream &output,
             const volatile std::sig_atomic_t *interrupted) {
  DiscoveryOptions discovery;
  discovery.sensor_host = options.config.sensor_host;
  discovery.http_port = options.config.http_port;
  discovery.connect_timeout = options.config.configuration_connect_timeout;
  discovery.total_timeout = options.config.configuration_timeout;
  const auto configuration = discover_sensor(discovery);
  if (was_interrupted(interrupted)) {
    return 130;
  }
  emit(options, output,
       options.json ? serialize_json(configuration, options.config)
                    : serialize_human(configuration, options.config));
  return 0;
}

int run_monitor(const Options &options, std::ostream &output, std::ostream &errors,
                const volatile std::sig_atomic_t *interrupted) {
  auto config = options.config;
  config.deliver_samples_with_error_status = true;
  Client client{config};
  const auto start = std::chrono::steady_clock::now();
  client.start([](const Sample &) {});
  const auto deadline = start + options.duration;
  while (std::chrono::steady_clock::now() < deadline && !client.faulted() &&
         !was_interrupted(interrupted)) {
    std::this_thread::sleep_for(std::chrono::milliseconds{2});
  }
  const bool signal_received = was_interrupted(interrupted);
  client.stop();
  if (signal_received) {
    return 130;
  }

  const auto sample = client.latest_sample();
  const auto health = client.health();
  if (!sample || !health.sensor_configuration || health.delivered_count == 0) {
    errors << "netft: no sample received";
    if (!health.last_error.empty()) {
      errors << ": " << health.last_error;
    }
    errors << '\n';
    return 2;
  }
  Summary summary{*health.sensor_configuration,
                  health,
                  *sample,
                  std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(),
                  options.duration.count(),
                  false};
  emit(options, output,
       options.json ? serialize_json(summary, options.config)
                    : serialize_human(summary, options.config));
  return result_code(health);
}

int run_bias(const Options &options, std::ostream &output, std::ostream &errors,
             const volatile std::sig_atomic_t *interrupted) {
  Client client{options.config};
  const auto start = std::chrono::steady_clock::now();
  client.start([](const Sample &) {});
  while (!client.wait_for_first_sample(std::chrono::milliseconds{20}) && !client.faulted() &&
         !was_interrupted(interrupted) &&
         std::chrono::steady_clock::now() - start < std::chrono::seconds{2}) {
  }
  if (was_interrupted(interrupted)) {
    client.stop();
    return 130;
  }
  auto before = client.latest_sample();
  auto before_health = client.health();
  if (!before || before_health.delivered_count == 0 || client.faulted()) {
    client.stop();
    errors << "netft: no sample received before bias\n";
    return 2;
  }

  try {
    client.bias();
  } catch (const std::exception &error) {
    client.stop();
    errors << "netft: bias failed: " << error.what() << '\n';
    return 2;
  }

  std::optional<Sample> after;
  HealthSnapshot after_health;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds{2};
  while (std::chrono::steady_clock::now() < deadline && !client.faulted() &&
         !was_interrupted(interrupted)) {
    after = client.latest_sample();
    after_health = client.health();
    if (after && after->rdt_sequence != before->rdt_sequence &&
        after_health.delivered_count > before_health.delivered_count) {
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds{2});
  }
  const bool signal_received = was_interrupted(interrupted);
  client.stop();
  if (signal_received) {
    return 130;
  }
  if (!after || !after_health.sensor_configuration || after->rdt_sequence == before->rdt_sequence ||
      after_health.delivered_count <= before_health.delivered_count) {
    errors << "netft: no post-bias sample received\n";
    return 2;
  }

  Summary summary{*after_health.sensor_configuration,
                  after_health,
                  *after,
                  std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(),
                  std::nullopt,
                  true};
  emit(options, output,
       options.json ? serialize_json(summary, options.config)
                    : serialize_human(summary, options.config));
  return result_code(after_health);
}

} // namespace

Options parse_options(const std::vector<std::string> &arguments) {
  Options options;
  if (arguments.size() == 1 && arguments.front() == "--help") {
    options.help = true;
    return options;
  }
  if (arguments.empty()) {
    throw UsageError("missing command");
  }
  if (arguments.front() == "info") {
    options.command = Command::Info;
  } else if (arguments.front() == "monitor") {
    options.command = Command::Monitor;
  } else if (arguments.front() == "bias") {
    options.command = Command::Bias;
  } else {
    throw UsageError("unknown command: " + arguments.front());
  }

  std::optional<double> counts_per_force;
  std::optional<double> counts_per_torque;
  std::optional<ForceUnit> force_unit;
  std::optional<TorqueUnit> torque_unit;
  bool duration_supplied = false;
  for (std::size_t index = 1; index < arguments.size(); ++index) {
    const auto &argument = arguments[index];
    if (argument == "--help") {
      options.help = true;
    } else if (argument == "--json") {
      options.json = true;
    } else if (argument == "--host") {
      options.config.sensor_host = take_value(arguments, index);
    } else if (argument == "--rdt-port") {
      options.config.rdt_port = parse_port("--rdt-port", take_value(arguments, index));
    } else if (argument == "--http-port") {
      options.config.http_port = parse_port("--http-port", take_value(arguments, index));
    } else if (argument == "--duration") {
      duration_supplied = true;
      options.duration = std::chrono::duration<double>{
          parse_positive_double("--duration", take_value(arguments, index))};
    } else if (argument == "--output") {
      options.output_path = take_value(arguments, index);
      if (options.output_path.empty()) {
        throw UsageError("--output must not be empty");
      }
    } else if (argument == "--counts-per-force-unit") {
      counts_per_force =
          parse_positive_double("--counts-per-force-unit", take_value(arguments, index));
    } else if (argument == "--counts-per-torque-unit") {
      counts_per_torque =
          parse_positive_double("--counts-per-torque-unit", take_value(arguments, index));
    } else if (argument == "--force-unit") {
      force_unit = force_unit_from_string(take_value(arguments, index));
      if (!force_unit || *force_unit == ForceUnit::Unknown) {
        throw UsageError("--force-unit is not supported");
      }
    } else if (argument == "--torque-unit") {
      torque_unit = torque_unit_from_string(take_value(arguments, index));
      if (!torque_unit || *torque_unit == TorqueUnit::Unknown) {
        throw UsageError("--torque-unit is not supported");
      }
    } else {
      throw UsageError("unknown option: " + argument);
    }
  }

  const unsigned override_count = static_cast<unsigned>(counts_per_force.has_value()) +
                                  static_cast<unsigned>(counts_per_torque.has_value()) +
                                  static_cast<unsigned>(force_unit.has_value()) +
                                  static_cast<unsigned>(torque_unit.has_value());
  if (override_count != 0 && override_count != 4) {
    throw UsageError("manual calibration requires all four calibration options");
  }
  if (override_count == 4) {
    if (options.command == Command::Info) {
      throw UsageError("manual calibration is not valid for info");
    }
    options.config.calibration_override =
        Calibration{*counts_per_force, *counts_per_torque, *force_unit, *torque_unit};
  }
  if (duration_supplied && options.command != Command::Monitor) {
    throw UsageError("--duration is only valid for monitor");
  }
  try {
    validate(options.config);
  } catch (const std::exception &error) {
    throw UsageError(error.what());
  }
  return options;
}

std::string usage() {
  return "Usage: netft <info|monitor|bias> [options]\n"
         "\n"
         "Commands:\n"
         "  info       Discover and print sensor calibration\n"
         "  monitor    Monitor the latest sample (default: 5 seconds)\n"
         "  bias       Apply software bias after receiving a sample\n"
         "\n"
         "Options:\n"
         "  --host HOST                     Sensor host\n"
         "  --rdt-port PORT                 RDT UDP port\n"
         "  --http-port PORT                Configuration HTTP port\n"
         "  --duration SECONDS              Monitor duration\n"
         "  --json                          Emit JSON\n"
         "  --output PATH                   Atomically write output to PATH\n"
         "  --counts-per-force-unit VALUE   Manual force scale\n"
         "  --counts-per-torque-unit VALUE  Manual torque scale\n"
         "  --force-unit UNIT               Manual force unit\n"
         "  --torque-unit UNIT              Manual torque unit\n"
         "  --help                          Show this help\n";
}

int run(const Options &options, std::ostream &output, std::ostream &errors,
        const volatile std::sig_atomic_t *interrupted) {
  try {
    switch (options.command) {
    case Command::Info:
      return run_info(options, output, interrupted);
    case Command::Monitor:
      return run_monitor(options, output, errors, interrupted);
    case Command::Bias:
      return run_bias(options, output, errors, interrupted);
    }
  } catch (const std::exception &error) {
    if (was_interrupted(interrupted)) {
      return 130;
    }
    errors << "netft: " << error.what() << '\n';
    return 2;
  }
  errors << "netft: invalid command\n";
  return 2;
}

} // namespace netft::cli
