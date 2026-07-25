#pragma once

#include <chrono>
#include <csignal>
#include <iosfwd>
#include <stdexcept>
#include <string>
#include <vector>

#include "netft/types.hpp"

namespace netft::cli {

enum class Command { Info, Monitor, Bias };

class UsageError : public std::invalid_argument {
public:
  using std::invalid_argument::invalid_argument;
};

struct Options {
  Command command{Command::Info};
  Config config;
  std::chrono::duration<double> duration{5.0};
  bool json{false};
  bool help{false};
  std::string output_path;
};

Options parse_options(const std::vector<std::string> &arguments);
std::string usage();

int run(const Options &options, std::ostream &output, std::ostream &errors,
        const volatile std::sig_atomic_t *interrupted = nullptr);

} // namespace netft::cli
