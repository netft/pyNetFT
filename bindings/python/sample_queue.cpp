#include "sample_queue.hpp"

#include <stdexcept>

namespace pynetft::bindings {

SampleQueue::SampleQueue(const std::size_t capacity) : capacity_(capacity) {
  if (capacity_ == 0) {
    throw std::invalid_argument(
        "sample queue capacity must be greater than zero");
  }
}

void SampleQueue::push(const netft::Sample &sample) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (samples_.size() == capacity_) {
      samples_.pop_front();
      ++dropped_count_;
    }
    samples_.push_back(sample);
  }
  condition_.notify_one();
}

ReadResult SampleQueue::read_for(const std::chrono::duration<double> timeout) {
  std::unique_lock<std::mutex> lock(mutex_);
  return read_for_locked(lock, timeout, close_generation_);
}

ReadResult SampleQueue::read_for(const std::chrono::duration<double> timeout,
                                 const Generation generation) {
  std::unique_lock<std::mutex> lock(mutex_);
  return read_for_locked(lock, timeout, generation);
}

ReadResult
SampleQueue::read_for_locked(std::unique_lock<std::mutex> &lock,
                             const std::chrono::duration<double> timeout,
                             const Generation generation) {
#ifdef PYNETFT_SAMPLE_QUEUE_TESTING
  ++waiting_reader_count_;
  waiter_observed_condition_.notify_all();
#endif
  const auto ready = condition_.wait_for(lock, timeout, [this, generation] {
    return closed_ || close_generation_ != generation || !samples_.empty();
  });
#ifdef PYNETFT_SAMPLE_QUEUE_TESTING
  --waiting_reader_count_;
  ++woken_reader_count_;
  woken_reader_condition_.notify_all();
  test_control_condition_.wait(lock, [this] { return !pause_woken_readers_; });
  --woken_reader_count_;
#endif
  if (!ready) {
    return {ReadStatus::Timeout, std::nullopt};
  }
  if (closed_ || close_generation_ != generation) {
    return {ReadStatus::Closed, std::nullopt};
  }

  const auto sample = samples_.front();
  samples_.pop_front();
  return {ReadStatus::Sample, sample};
}

SampleQueue::Generation SampleQueue::generation() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  return close_generation_;
}

void SampleQueue::close() noexcept {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    closed_ = true;
    ++close_generation_;
  }
  condition_.notify_all();
}

void SampleQueue::reset() {
  std::lock_guard<std::mutex> lock(mutex_);
  samples_.clear();
  dropped_count_ = 0;
  closed_ = false;
}

std::uint64_t SampleQueue::dropped_count() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  return dropped_count_;
}

} // namespace pynetft::bindings
