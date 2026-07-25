#pragma once

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <optional>

#include "netft/types.hpp"

namespace pynetft::bindings {

#ifdef PYNETFT_SAMPLE_QUEUE_TESTING
struct SampleQueueTestAccess;
#endif

enum class ReadStatus : std::uint8_t { Sample, Timeout, Closed };

struct ReadResult {
  ReadStatus status{ReadStatus::Timeout};
  std::optional<netft::Sample> sample;
};

class SampleQueue {
public:
  using Generation = std::uint64_t;

  explicit SampleQueue(std::size_t capacity);

  void push(const netft::Sample &sample);
  ReadResult read_for(std::chrono::duration<double> timeout);
  ReadResult read_for(std::chrono::duration<double> timeout,
                      Generation generation);
  void close() noexcept;
  void reset();
  Generation generation() const noexcept;
  std::uint64_t dropped_count() const noexcept;

private:
#ifdef PYNETFT_SAMPLE_QUEUE_TESTING
  friend struct SampleQueueTestAccess;
#endif

  ReadResult read_for_locked(std::unique_lock<std::mutex> &lock,
                             std::chrono::duration<double> timeout,
                             Generation generation);

  const std::size_t capacity_;
  mutable std::mutex mutex_;
  std::condition_variable condition_;
  std::deque<netft::Sample> samples_;
  std::uint64_t dropped_count_{};
  Generation close_generation_{};
  bool closed_{};

#ifdef PYNETFT_SAMPLE_QUEUE_TESTING
  std::condition_variable waiter_observed_condition_;
  std::condition_variable woken_reader_condition_;
  std::condition_variable test_control_condition_;
  std::size_t waiting_reader_count_{};
  std::size_t woken_reader_count_{};
  bool pause_woken_readers_{};
#endif
};

} // namespace pynetft::bindings
