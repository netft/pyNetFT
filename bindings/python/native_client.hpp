#pragma once

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <optional>

#include "netft/client.hpp"
#include "sample_queue.hpp"

namespace pynetft::bindings {

#ifdef PYNETFT_NATIVE_CLIENT_TESTING
struct NativeClientTestAccess;
#endif

class NativeClient {
public:
  NativeClient(netft::Config config, std::size_t queue_size);
  ~NativeClient();

  void start();
  void stop() noexcept;
  void bias();
  bool wait_for_first_sample(double timeout_seconds);
  ReadResult read(std::optional<double> timeout_seconds);
  std::optional<netft::Sample> latest_sample() const;
  netft::HealthSnapshot health() const;
  bool faulted() const noexcept;
  netft::FaultCode fault_code() const noexcept;
  std::uint64_t queue_dropped_count() const noexcept;

private:
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
  friend struct NativeClientTestAccess;
#endif

  bool faulted_for_read() const noexcept;
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
  void pause_before_core_stop_for_testing();
  void pause_after_fault_for_testing();
  void pause_after_timeout_for_testing();
  void observe_first_sample_call_for_testing();
#endif

  mutable std::mutex lifecycle_mutex_;
  SampleQueue queue_;
  netft::Client client_;
  std::atomic<bool> running_{false};

#ifdef PYNETFT_NATIVE_CLIENT_TESTING
  std::atomic<bool> forced_fault_{false};
  std::mutex test_mutex_;
  std::condition_variable test_condition_;
  bool pause_after_fault_{false};
  bool fault_observed_{false};
  bool pause_after_timeout_{false};
  bool timeout_observed_{false};
  bool pause_before_core_stop_{false};
  bool core_stop_observed_{false};
  bool gate_first_sample_calls_{false};
  std::uint64_t first_sample_call_count_{};
  std::uint64_t first_sample_calls_allowed_{};
#endif
};

} // namespace pynetft::bindings
