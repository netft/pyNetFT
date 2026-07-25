#include <csignal>
#include <iostream>
#include <string>
#include <vector>

#include "cli.hpp"

namespace {

volatile std::sig_atomic_t interrupted = 0;

extern "C" void handle_sigint(int /*unused*/) { interrupted = 1; }

} // namespace

int main(int argc, char **argv) {
  std::signal(SIGINT, handle_sigint);

  std::vector<std::string> arguments;
  arguments.reserve(static_cast<std::size_t>(argc > 0 ? argc - 1 : 0));
  for (int index = 1; index < argc; ++index) {
    arguments.emplace_back(argv[index]);
  }

  try {
    const auto options = netft::cli::parse_options(arguments);
    if (options.help) {
      std::cout << netft::cli::usage();
      return 0;
    }
    return netft::cli::run(options, std::cout, std::cerr, &interrupted);
  } catch (const netft::cli::UsageError &error) {
    std::cerr << "netft: " << error.what() << "\n\n" << netft::cli::usage();
    return 2;
  } catch (const std::exception &error) {
    std::cerr << "netft: " << error.what() << '\n';
    return 2;
  }
}
