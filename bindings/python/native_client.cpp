#include "native_client.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <string>
#include <utility>

namespace pynetft::bindings {
namespace {

using Clock = std::chrono::steady_clock;
constexpr auto kReadSlice = std::chrono::milliseconds{50};

void require_representable_timeout(const double seconds, const char *name) {
  const auto maximum_seconds =
      std::chrono::duration<long double>{Clock::duration::max()}.count();
  if (!std::isfinite(seconds) || seconds < 0.0) {
    throw std::invalid_argument(std::string{name} +
                                " must be finite and non-negative");
  }
  if (static_cast<long double>(seconds) > maximum_seconds) {
    throw std::invalid_argument(std::string{name} +
                                " exceeds the native clock range");
  }
}

} // namespace

NativeClient::NativeClient(netft::Config config, const std::size_t queue_size)
    : queue_(queue_size), client_(std::move(config)) {}

NativeClient::~NativeClient() { stop(); }

void NativeClient::start() {
  std::lock_guard<std::mutex> lock(lifecycle_mutex_);
  if (running_.load(std::memory_order_acquire) && !client_.faulted()) {
    return;
  }

  running_.store(false, std::memory_order_release);
  queue_.close();
  queue_.reset();
  try {
    client_.start([this](const netft::Sample &sample) { queue_.push(sample); });
    running_.store(true, std::memory_order_release);
  } catch (...) {
    running_.store(false, std::memory_order_release);
    queue_.close();
    throw;
  }
}

void NativeClient::stop() noexcept {
  std::lock_guard<std::mutex> lock(lifecycle_mutex_);
  running_.store(false, std::memory_order_release);
  queue_.close();
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
  pause_before_core_stop_for_testing();
#endif
  client_.stop();
}

void NativeClient::bias() { client_.bias(); }

bool NativeClient::faulted_for_read() const noexcept {
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
  if (forced_fault_.load(std::memory_order_acquire)) {
    return true;
  }
#endif
  return client_.faulted();
}

#ifdef PYNETFT_NATIVE_CLIENT_TESTING
void NativeClient::pause_before_core_stop_for_testing() {
  std::unique_lock<std::mutex> lock(test_mutex_);
  core_stop_observed_ = true;
  test_condition_.notify_all();
  test_condition_.wait(lock, [this] { return !pause_before_core_stop_; });
}

void NativeClient::pause_after_fault_for_testing() {
  std::unique_lock<std::mutex> lock(test_mutex_);
  fault_observed_ = true;
  test_condition_.notify_all();
  test_condition_.wait(lock, [this] { return !pause_after_fault_; });
}

void NativeClient::pause_after_timeout_for_testing() {
  std::unique_lock<std::mutex> lock(test_mutex_);
  timeout_observed_ = true;
  test_condition_.notify_all();
  test_condition_.wait(lock, [this] { return !pause_after_timeout_; });
}

void NativeClient::observe_first_sample_call_for_testing() {
  std::unique_lock<std::mutex> lock(test_mutex_);
  ++first_sample_call_count_;
  test_condition_.notify_all();
  test_condition_.wait(lock, [this] {
    return !gate_first_sample_calls_ ||
           first_sample_call_count_ <= first_sample_calls_allowed_;
  });
}
#endif

bool NativeClient::wait_for_first_sample(const double timeout_seconds) {
  require_representable_timeout(timeout_seconds, "timeout");
  const auto queue_generation = queue_.generation();
  const auto started_at = Clock::now();

  for (;;) {
    if (!running_.load(std::memory_order_acquire) || faulted_for_read() ||
        queue_.generation() != queue_generation) {
      return false;
    }

    const auto elapsed =
        std::chrono::duration<double>{Clock::now() - started_at}.count();
    const auto wait_duration =
        std::min(std::chrono::duration<double>{kReadSlice},
                 std::chrono::duration<double>{
                     std::max(0.0, timeout_seconds - elapsed)});
    const auto received_sample = client_.wait_for_first_sample(wait_duration);
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
    observe_first_sample_call_for_testing();
#endif
    if (queue_.generation() != queue_generation) {
      return false;
    }
    if (received_sample) {
      return true;
    }
    if (std::chrono::duration<double>{Clock::now() - started_at}.count() >=
        timeout_seconds) {
      return false;
    }
  }
}

ReadResult NativeClient::read(const std::optional<double> timeout_seconds) {
  if (timeout_seconds) {
    require_representable_timeout(*timeout_seconds, "timeout");
  }
  const auto queue_generation = queue_.generation();
  const auto started_at = Clock::now();

  for (;;) {
    if (!running_.load(std::memory_order_acquire)) {
      return {ReadStatus::Closed, std::nullopt};
    }
    if (faulted_for_read()) {
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
      pause_after_fault_for_testing();
#endif
      return {ReadStatus::Closed, std::nullopt};
    }

    auto wait_duration = std::chrono::duration<double>{kReadSlice};
    if (timeout_seconds) {
      const auto elapsed =
          std::chrono::duration<double>{Clock::now() - started_at}.count();
      wait_duration = std::min(wait_duration,
                               std::chrono::duration<double>{
                                   std::max(0.0, *timeout_seconds - elapsed)});
    }

    auto result = queue_.read_for(wait_duration, queue_generation);
    if (result.status != ReadStatus::Timeout) {
      return result;
    }
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
    pause_after_timeout_for_testing();
#endif
    if (!running_.load(std::memory_order_acquire)) {
      return {ReadStatus::Closed, std::nullopt};
    }
    if (faulted_for_read()) {
#ifdef PYNETFT_NATIVE_CLIENT_TESTING
      pause_after_fault_for_testing();
#endif
      return {ReadStatus::Closed, std::nullopt};
    }
    if (timeout_seconds &&
        std::chrono::duration<double>{Clock::now() - started_at}.count() >=
            *timeout_seconds) {
      return result;
    }
  }
}

std::optional<netft::Sample> NativeClient::latest_sample() const {
  return client_.latest_sample();
}

netft::HealthSnapshot NativeClient::health() const { return client_.health(); }

bool NativeClient::faulted() const noexcept { return client_.faulted(); }

netft::FaultCode NativeClient::fault_code() const noexcept {
  return client_.fault_code();
}

std::uint64_t NativeClient::queue_dropped_count() const noexcept {
  return queue_.dropped_count();
}

} // namespace pynetft::bindings
